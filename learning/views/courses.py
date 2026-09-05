"""Cursos: creacion, detalle, banco de preguntas y exportaciones."""
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
    _get_or_create_profile,
    _has_api_capacity,
)


@login_required
def course_create(request):
    if request.method == "POST":
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            course.user = request.user
            course.save()
            messages.success(request, "Curso creado. Ahora puedes subir clases dentro de este curso.")
            return redirect("course_detail", pk=course.pk)
    else:
        form = CourseForm()
    return render(request, "learning/course_form.html", {"form": form})


@login_required
def course_detail(request, pk):
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    jobs = LessonJob.objects.filter(user=request.user, course=course)
    class_sessions = ClassSession.objects.filter(user=request.user, course=course)
    stats = {
        "classes": jobs.count(),
        "sessions": class_sessions.count(),
        "ready": jobs.filter(Q(corrected_output__gt="") | Q(toon_output__gt="")).count(),
        "processing": jobs.filter(status__in=[LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING]).count(),
        "quizzes": adaptive.PracticeSession.objects.filter(user=request.user, course=course, completed_at__isnull=False).count(),
    }
    progress_pct = round((stats["ready"] / stats["classes"]) * 100) if stats["classes"] > 0 else 0
    profile = _get_or_create_profile(request.user)
    can_use_api = _has_api_capacity(request.user, profile)
    return render(request, "learning/course_detail.html", {
        "course": course,
        "jobs": jobs[:24],
        "stats": stats,
        "progress_pct": progress_pct,
        "profile": profile,
        "can_use_api": can_use_api,
        "overview": adaptive.course_overview(request.user, course),
    })


@login_required
def course_bank(request, pk):
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    report = adaptive.bank_report(course)
    return render(request, "learning/course_bank.html", {"course": course, "report": report, "calibration_min": adaptive.CALIBRATION_MIN})


def _csv_response(filename: str, header: list[str], rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # BOM para que Excel abra UTF-8 sin preguntar
    writer = csv.writer(response, delimiter=";")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return response


@login_required
def course_bank_csv(request, pk):
    course = get_object_or_404(Course, pk=pk, user=request.user)
    report = adaptive.bank_report(course)
    return _csv_response(
        f"banco_curso_{course.pk}.csv",
        ["id", "clase", "tema", "bloom", "enunciado", "b_generada", "b_calibrada", "desvio", "intentos", "acierto_pct", "bandera"],
        ((r["id"], r["source"], r["topic"], r["bloom"], r["prompt"], r["b"], r["b_calibrated"], r["drift"], r["attempts"], r["accuracy"], r["flag"]) for r in report["rows"]),
    )


@login_required
def course_answers_csv(request, pk):
    course = get_object_or_404(Course, pk=pk, user=request.user)
    answers = (
        adaptive.StudentAnswer.objects.filter(user=request.user, course=course)
        .select_related("question", "practice_session")
        .order_by("answered_at")
    )
    return _csv_response(
        f"respuestas_curso_{course.pk}.csv",
        ["fecha", "sesion", "modo", "pregunta_id", "tema", "bloom", "correcta", "theta_antes", "theta_despues"],
        ((timezone.localtime(a.answered_at).strftime("%Y-%m-%d %H:%M:%S"), a.practice_session_id,
          a.practice_session.focus if a.practice_session_id else "", a.question_id, a.question.topic, a.question.bloom_level,
          1 if a.is_correct else 0, a.theta_before, a.theta_after) for a in answers),
    )


@login_required
def course_edit(request, pk):
    course = get_object_or_404(Course, pk=pk, user=request.user)
    if request.method == "POST":
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, "Curso actualizado.")
            return redirect("course_detail", pk=course.pk)
    else:
        form = CourseForm(instance=course)
    return render(request, "learning/course_form.html", {"form": form, "course": course})


@login_required
def course_archive(request, pk):
    """Archivar oculta el curso del panel y de la barra lateral sin borrar nada; se puede restaurar."""
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user)
    course.is_archived = request.POST.get("action", "archive") != "restore"
    course.save(update_fields=["is_archived", "updated_at"] if hasattr(course, "updated_at") else ["is_archived"])
    if course.is_archived:
        messages.info(request, f"«{course.name}» quedo archivado. Puedes restaurarlo desde Inicio → Cursos.")
        return redirect("dashboard")
    messages.success(request, f"«{course.name}» esta activo de nuevo.")
    return redirect("course_detail", pk=course.pk)
