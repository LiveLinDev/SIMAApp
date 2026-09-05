"""Ayudantes compartidos por las vistas (perfil, trabajo accesible, sincronizacion de ClassSession, trazas)."""
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
from ..job_queue import (
    _compile_mini_for_render,
    _job_content_for_generation,
    _normalize_verification_mode,
    _safe_trace_list,
    _sync_class_session_status,
    enqueue_lesson_job,
)
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


def _get_or_create_profile(user):
    """Garantiza que el usuario siempre tenga un perfil, incluso si fue creado antes del signal."""
    from ..models import Profile
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _get_or_create_preferences(user):
    preferences, _ = UserPreference.objects.get_or_create(user=user)
    return preferences


def _has_api_capacity(user, profile):
    info = profile.plan_info
    if not info["api"]:
        return False
    total = info["classes"]
    if total is None:
        return True
    in_flight = LessonJob.objects.filter(
        user=user,
        mode=LessonJob.Mode.API,
        status__in=[LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING],
        api_usage_counted=False,
    ).count()
    return profile.api_classes_used + in_flight < total


def _normalize_ai_backend_choice(backend: str | None, backends: dict) -> str:
    value = normalize_backend(backend)
    if value == "auto":
        return backends["default"]
    if value == "cloud" and not backends.get("cloud"):
        return "local"
    if value not in {"local", "cloud"}:
        return backends["default"]
    return value


def _get_accessible_job(user, pk):
    return get_object_or_404(
        LessonJob.objects.select_related("user", "course"),
        Q(pk=pk, user=user)
        | Q(pk=pk, visibility=LessonJob.Visibility.PUBLIC)
        | Q(pk=pk, visibility=LessonJob.Visibility.SHARED),
    )


def _normalize_tags(tags: str) -> str:
    values = []
    for raw in re_split_tags(tags or ""):
        tag = raw.strip().lower()
        if tag and tag not in values:
            values.append(tag[:32])
        if len(values) >= 12:
            break
    return ", ".join(values)


def re_split_tags(tags: str) -> list[str]:
    import re
    return re.split(r"[,#;\n]+", tags)


def _transcript_context(job: LessonJob) -> str:
    parts = [f"TITULO: {job.title}"]
    if job.tags:
        parts.append(f"ETIQUETAS: {job.tags}")
    if job.source_text.strip():
        parts.append(f"TEXTO_ORIGINAL:\n{job.source_text.strip()}")
    mini_text = (job.corrected_output or job.toon_output or "").strip()
    if mini_text:
        parts.append(
            "MINI_GENERADO_COMO_PISTA_NO_AUTORITATIVA:\n"
            "Puede contener errores heredados de la transcripcion; usalo solo para inferir el tema general.\n"
            f"{mini_text[:5000]}"
        )
    return "\n\n".join(parts)


def _reset_after_transcript_change(job: LessonJob, generation_backend: str) -> str:
    job.toon_output = ""
    job.verification_prompt = ""
    job.verification_output = ""
    job.verification_trace = {}
    job.corrected_output = ""
    job.correction_trace = []
    job.mini_coherence_prompt = ""
    job.mini_coherence_trace = []
    job.error = ""

    if job.mode == LessonJob.Mode.API:
        job.generation_prompt = ""
        job.status = LessonJob.Status.QUEUED
        job.processing_stage = "En cola"
        job.processing_log = _append_view_log(
            job.processing_log,
            "Pipeline reiniciado",
            f"La transcripcion cambio; se regenerara con backend {generation_backend}.",
        )
        return "pipeline API reiniciado"

    content = _job_content_for_generation(job)
    job.generation_prompt = build_generation_prompt(content) if content else ""
    job.status = LessonJob.Status.PROMPT_READY if job.generation_prompt else LessonJob.Status.DRAFT
    job.processing_stage = "Prompt manual regenerado"
    job.processing_log = _append_view_log(
        job.processing_log,
        "Pipeline invalidado",
        "La transcripcion cambio; se regenero el prompt manual y se limpiaron los items anteriores.",
    )
    return "prompt manual regenerado"


def _transcript_repair_entry(before: str, after: str, trace: dict, backend: str, downstream_action: str) -> dict:
    return {
        "created_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"),
        "backend": backend,
        "changed": bool(trace.get("changed")),
        "prompt_chars": trace.get("prompt_chars", 0),
        "output_chars": trace.get("output_chars", 0),
        "downstream_action": downstream_action,
        "before": before,
        "after": after,
        "changes": _transcript_word_changes(before, after),
    }


def _transcript_word_changes(before: str, after: str) -> list[dict]:
    return text_change_summary(before, after)


def _append_view_log(current: str, stage: str, detail: str = "") -> str:
    stamp = timezone.localtime().strftime("%H:%M:%S")
    line = f"[{stamp}] {stage}"
    if detail:
        line = f"{line} - {detail}"
    return "\n".join(part for part in [current.strip(), line] if part)


def _collect_public_tags() -> list[str]:
    tags = []
    for value in LessonJob.objects.filter(visibility=LessonJob.Visibility.PUBLIC).values_list("tags", flat=True):
        for tag in re_split_tags(value or ""):
            tag = tag.strip().lower()
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) >= 24:
                return tags
    return tags


def _safe_class_session(job: LessonJob) -> ClassSession | None:
    try:
        return job.class_session
    except ClassSession.DoesNotExist:
        return None


# Las vistas y el worker deben sincronizar ClassSession con la misma regla.
_sync_class_session_for_job = _sync_class_session_status
