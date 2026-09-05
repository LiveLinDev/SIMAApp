"""Inicio, registro, panel principal, planes y salud."""
from __future__ import annotations

import csv
import json
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.db import connection
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from .. import adaptive, adaptive_generation, progress, summaries
from .. import spaced_repetition
from ..cat import BLOOM_LABELS, build_bank, choose_next_item, estimate_theta, option_index, parse_cat_params, theta_to_level
from ..credits import (
    REGENERATION_COST,
    consume_credits,
    estimate_lesson_job_cost,
    grant_plan_credits,
    has_enough_credits,
)
from ..forms import ApiLessonForm, CourseForm, FreeLessonForm, ManualResultForm, PlanForm, RegisterForm, VerificationResultForm
from ..job_queue import enqueue_lesson_job
from ..models import ClassSession, Course, Difficulty, Flashcard, LessonJob, UserPreference, get_plan_details
from ..parse_mini import apply_corrections_with_trace, assessment_to_dict, filter_incoherent_items, normalize_mini_text, parse_mini, render_mini_html, validate_mini_parse
from ..services import (
    build_generation_prompt,
    build_verification_prompt,
    clean_ai_error,
    extract_mini_lines,
    get_available_backends,
    normalize_backend,
    repair_mini_coherence,
    repair_transcript_text,
    text_change_summary,
)
import random

from ._common import (
    _collect_public_tags,
    _get_or_create_preferences,
    _get_or_create_profile,
)


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "learning/home.html", {"plans": get_plan_details()})


def mini_landing(request):
    return render(request, "landing/mini.html")


def mini_benchmark(request):
    return render(request, "landing/benchmark_page.html")


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            profile = _get_or_create_profile(user)
            grant_plan_credits(profile, description="Creditos iniciales del plan gratis")
            login(request, user)
            messages.success(request, "Cuenta creada. Bienvenido a tu dojo de clases.")
            return redirect("dashboard")
    else:
        form = RegisterForm()
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    profile = _get_or_create_profile(request.user)
    preferences = _get_or_create_preferences(request.user)
    if request.method == "POST" and request.POST.get("dashboard_action") == "update_preferences":
        try:
            daily_goal = int(request.POST.get("daily_goal", preferences.daily_goal))
        except (TypeError, ValueError):
            daily_goal = preferences.daily_goal
        preferences.daily_goal = max(1, min(daily_goal, 200))
        preferences.email_reminders = bool(request.POST.get("email_reminders"))
        preferences.save(update_fields=["daily_goal", "email_reminders", "updated_at"])
        messages.success(request, "Preferencias actualizadas.")
        return redirect(f"{request.path}?tab=preferencias")

    courses = Course.objects.filter(user=request.user, is_archived=False).annotate(
        class_count=Count("legacy_lesson_jobs", filter=Q(legacy_lesson_jobs__user=request.user)),
    )
    all_jobs = LessonJob.objects.filter(user=request.user)
    jobs = all_jobs.select_related("course")[:8]
    ready_jobs = all_jobs.filter(Q(corrected_output__gt="") | Q(toon_output__gt="")).count()
    processing_jobs = all_jobs.filter(status__in=[LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING]).count()
    class_sessions = ClassSession.objects.filter(user=request.user).select_related("course")[:6]
    public_jobs = LessonJob.objects.select_related("user").filter(
        visibility=LessonJob.Visibility.PUBLIC,
    ).exclude(corrected_output="", toon_output="")
    query = request.GET.get("q", "").strip()
    tag = request.GET.get("tag", "").strip()
    if query:
        public_jobs = public_jobs.filter(
            Q(title__icontains=query)
            | Q(tags__icontains=query)
            | Q(transcript__icontains=query)
            | Q(source_text__icontains=query)
        )
    if tag:
        public_jobs = public_jobs.filter(tags__icontains=tag)
    public_jobs = public_jobs[:24]
    popular_tags = _collect_public_tags()
    requested_tab = request.GET.get("tab", "").strip()
    allowed_tabs = {"cursos", "mis-clases", "explorar", "horario", "preferencias", "guardadas"}
    active_tab = requested_tab if requested_tab in allowed_tabs else ("explorar" if query or tag else "cursos")
    return render(request, "learning/dashboard.html", {
        "profile": profile,
        "preferences": preferences,
        "courses": courses,
        "jobs": jobs,
        "class_sessions": class_sessions,
        "dashboard_stats": {
            "course_count": courses.count(),
            "lesson_count": all_jobs.count(),
            "ready_count": ready_jobs,
            "processing_count": processing_jobs,
        },
        "public_jobs": public_jobs,
        "popular_tags": popular_tags,
        "active_tab": active_tab,
        "explore_query": query,
        "explore_tag": tag,
        "plans": get_plan_details(),
        "today": adaptive.dashboard_today(request.user),
        "progress": progress.progress_panel(request.user),
        "archived_courses": Course.objects.filter(user=request.user, is_archived=True).order_by("name"),
    })


@login_required
def plans(request):
    profile = _get_or_create_profile(request.user)
    if request.method == "POST":
        form = PlanForm(request.POST)
        if form.is_valid():
            profile.plan = form.cleaned_data["plan"]
            profile.api_classes_used = 0
            profile.save()
            grant_plan_credits(profile)
            messages.success(request, "Plan actualizado para este mes.")
            return redirect("dashboard")
    else:
        form = PlanForm(initial={"plan": profile.plan})
    return render(request, "learning/plans.html", {"form": form, "plans": get_plan_details(), "profile": profile})


def health(request):
    """Estado minimo para monitoreo: BD, cola y backend configurado. Sin datos sensibles."""
    from ..job_queue import queue_snapshot

    status = {"status": "ok"}
    try:
        connection.ensure_connection()
        status["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        status["status"] = "degraded"
        status["database"] = f"error: {exc.__class__.__name__}"
    try:
        status["queue"] = queue_snapshot()
    except Exception as exc:  # noqa: BLE001
        status["status"] = "degraded"
        status["queue"] = f"error: {exc.__class__.__name__}"
    status["cloud_backend"] = bool(getattr(settings, "CLOUD_API_KEY", ""))
    status["cloud_model"] = getattr(settings, "CLOUD_MODEL", "")
    status["whisper_model"] = getattr(settings, "WHISPER_MODEL", "")
    return JsonResponse(status, status=200 if status["status"] == "ok" else 503)
