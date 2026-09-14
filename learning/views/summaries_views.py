"""Resumenes por clase y acumulado del curso (trabajos en cola)."""
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


def _register_summary_review(user, course, class_session=None):
    """Una revision de resumen por dia y por objeto suma XP sin inflar la racha."""
    from ..models import StudyActivity

    today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    already = StudyActivity.objects.filter(
        user=user, course=course, class_session=class_session,
        activity_type=StudyActivity.ActivityType.SUMMARY_REVIEWED, occurred_at__gte=today_start,
    ).exists()
    if not already:
        adaptive.register_activity(user, course, StudyActivity.ActivityType.SUMMARY_REVIEWED, xp=5)


@login_required
def class_summary(request, pk):
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    if request.method == "POST":
        try:
            if not job.course_id:
                raise summaries.SummaryUnavailable("La clase debe pertenecer a un curso para generar su resumen.")
            summaries.create_summary_job(request.user, job.course, lesson=job, backend=request.POST.get("backend", "auto"))
            messages.info(request, "Estamos preparando tu resumen.")
        except summaries.SummaryUnavailable as exc:
            messages.warning(request, str(exc))
        return redirect("class_summary", pk=job.pk)
    summary = summaries.class_summary_for(job)
    pending_job = summaries.pending_summary_job(job.course, job) if job.course_id else None
    last_job = summaries.latest_summary_job(job.course, job) if job.course_id else None
    if summary is not None and job.course_id and pending_job is None:
        _register_summary_review(request.user, job.course, summary.class_session)
    return render(request, "learning/class_summary.html", {
        "job": job,
        "summary": summary,
        "pending_job": pending_job,
        "last_job": last_job,
        "can_generate": bool(job.course_id) and len((job.transcript or job.source_text or "").strip()) >= 200,
        "summary_cost": summaries.estimate_summary_cost("auto").amount,
    })


@login_required
def course_summary(request, pk):
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    if request.method == "POST":
        try:
            summaries.create_summary_job(request.user, course, backend=request.POST.get("backend", "auto"))
            messages.info(request, "Estamos preparando el resumen del curso.")
        except summaries.SummaryUnavailable as exc:
            messages.warning(request, str(exc))
        return redirect("course_summary", pk=course.pk)
    summary = summaries.course_summary_for(course)
    pending_job = summaries.pending_summary_job(course)
    last_job = summaries.latest_summary_job(course)
    if summary is not None and pending_job is None:
        _register_summary_review(request.user, course)
    class_summaries = list(
        adaptive.Summary.objects.filter(course=course, kind=adaptive.Summary.Kind.STRUCTURED).select_related("class_session")
    )
    profile = adaptive.get_profile(request.user, course)
    return render(request, "learning/course_summary.html", {
        "course": course,
        "summary": summary,
        "class_summaries": class_summaries,
        "class_summary_count": len(class_summaries),
        "weak_topics": list(profile.weak_topics) if profile else [],
        "pending_job": pending_job,
        "last_job": last_job,
        "can_generate": bool(class_summaries) or LessonJob.objects.filter(course=course).exclude(transcript="", source_text="").exists(),
        "summary_cost": summaries.estimate_summary_cost("auto").amount,
    })


@login_required
def class_summary_pdf(request, pk):
    from ..pdf_export import safe_filename, summary_pdf

    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    summary = summaries.class_summary_for(job)
    if summary is None:
        raise Http404("La clase aun no tiene resumen.")
    subtitle = " · ".join(filter(None, [job.course.name if job.course_id else "", job.title, "Resumen de la clase"]))
    response = HttpResponse(summary_pdf(job.title, subtitle, summary), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="resumen-{safe_filename(job.title, f"clase-{job.pk}")}.pdf"'
    return response


@login_required
def course_summary_pdf(request, pk):
    from ..pdf_export import safe_filename, summary_pdf

    course = get_object_or_404(Course, pk=pk, user=request.user)
    summary = summaries.course_summary_for(course)
    if summary is None:
        raise Http404("El curso aun no tiene resumen.")
    subtitle = " · ".join(filter(None, [course.name, course.academic_period, "Resumen del curso"]))
    response = HttpResponse(summary_pdf(course.name, subtitle, summary), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="resumen-{safe_filename(course.name, f"curso-{course.pk}")}.pdf"'
    return response
