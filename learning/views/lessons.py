"""Clases (LessonJob): carga, detalle, estado, reintentos, reparaciones, visibilidad y descarga."""
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
from ..job_queue import TooManyPendingJobs, assert_user_can_enqueue, enqueue_lesson_job
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
    _append_view_log,
    _compile_mini_for_render,
    _get_accessible_job,
    _get_or_create_profile,
    _has_api_capacity,
    _normalize_ai_backend_choice,
    _normalize_tags,
    _normalize_verification_mode,
    _reset_after_transcript_change,
    _safe_class_session,
    _safe_trace_list,
    _sync_class_session_for_job,
    _transcript_context,
    _transcript_repair_entry,
)


@login_required
def free_lesson(request):
    if not Course.objects.filter(user=request.user, is_archived=False).exists():
        messages.info(request, "Primero crea un curso para guardar tus clases.")
        return redirect("course_create")
    if request.method == "POST":
        form = FreeLessonForm(request.POST, user=request.user)
        if form.is_valid():
            job = form.save(commit=False)
            job.user = request.user
            job.mode = LessonJob.Mode.FREE_MANUAL
            job.tags = _normalize_tags(job.tags)
            job.generation_prompt = build_generation_prompt(job.source_text)
            job.status = LessonJob.Status.PROMPT_READY
            job.save()
            _sync_class_session_for_job(job)
            return redirect("lesson_detail", pk=job.pk)
    else:
        form = FreeLessonForm(user=request.user, initial={"course": request.GET.get("course")})
    return render(request, "learning/lesson_form.html", {"form": form, "mode": "free"})


@login_required
def api_lesson(request):
    profile = _get_or_create_profile(request.user)
    backends = get_available_backends()
    if not _has_api_capacity(request.user, profile):
        messages.warning(request, "Ya usaste las clases de tu plan. Cambia de plan para subir más.")
        return redirect("plans")
    if not Course.objects.filter(user=request.user, is_archived=False).exists():
        messages.info(request, "Primero crea un curso para guardar tus clases.")
        return redirect("course_create")
    if request.method == "POST":
        form = ApiLessonForm(request.POST, request.FILES, user=request.user)
        backend = _normalize_ai_backend_choice(request.POST.get("backend"), backends)
        if normalize_backend(request.POST.get("backend")) == "cloud" and backend != "cloud":
            messages.info(request, "Usaremos el procesamiento estándar.")
        verification_mode = request.POST.get("verification_mode") or getattr(settings, "VERIFICATION_DEFAULT_MODE", "web")
        if form.is_valid():
            job = form.save(commit=False)
            job.user = request.user
            job.mode = LessonJob.Mode.API
            job.status = LessonJob.Status.QUEUED
            job.ai_backend = backend
            job.verification_mode = _normalize_verification_mode(verification_mode)
            job.tags = _normalize_tags(job.tags)
            job.processing_stage = "En cola"
            job.processing_log = "En cola - Esperando turno en el procesador local."
            estimate = estimate_lesson_job_cost(
                has_audio=bool(request.FILES.get("audio")),
                has_text=bool(form.cleaned_data.get("source_text", "").strip()),
                backend=backend,
            )
            if not has_enough_credits(profile, estimate.amount):
                messages.warning(
                    request,
                    f"Te faltan créditos: esta clase necesita {estimate.amount} y tienes {profile.credits_label}.",
                )
                return redirect("plans")
            try:
                assert_user_can_enqueue(request.user)
            except TooManyPendingJobs as exc:
                messages.warning(request, str(exc))
                return redirect("dashboard")
            job.save()
            class_session = _sync_class_session_for_job(job)
            try:
                consume_credits(
                    profile,
                    estimate.amount,
                    action=estimate.action,
                    course=job.course,
                    class_session=class_session,
                    description=f"Procesamiento de clase: {job.title}",
                    metadata={"details": estimate.details, "lesson_job_id": job.pk},
                )
            except ValueError:
                job.delete()
                messages.warning(request, "No tienes créditos suficientes para esta clase.")
                return redirect("plans")
            try:
                enqueue_lesson_job(job.pk, backend=backend)
                messages.success(request, "Estamos procesando tu clase. Te avisaremos aquí cuando esté lista.")
            except Exception as exc:
                err_str = clean_ai_error(exc)
                job.error = err_str
                job.status = LessonJob.Status.ERROR
                job.save(update_fields=["error", "status", "updated_at"])
                messages.warning(request, f"No pudimos procesar tu clase: {err_str}")
            return redirect("lesson_detail", pk=job.pk)
    else:
        form = ApiLessonForm(user=request.user, initial={"course": request.GET.get("course")})
    return render(request, "learning/lesson_form.html", {
        "form": form, "mode": "api", "profile": profile, "backends": backends,
        "local_model": getattr(settings, "LOCAL_MODEL", None) or getattr(settings, "CLOUD_MODEL", "local"),
        "verification_default_mode": getattr(settings, "VERIFICATION_DEFAULT_MODE", "web"),
        "credit_estimate": estimate_lesson_job_cost(has_audio=True, has_text=True, backend=backends["default"]),
        "local_credit_estimate": estimate_lesson_job_cost(has_audio=True, has_text=True, backend="local"),
        "cloud_credit_estimate": estimate_lesson_job_cost(has_audio=True, has_text=True, backend="cloud"),
    })


@login_required
def lesson_detail(request, pk):
    job = _get_accessible_job(request.user, pk)
    if job.user_id == request.user.id and job.status in [LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING]:
        try:
            enqueue_lesson_job(job.pk, backend=job.ai_backend or "auto")
        except RuntimeError as exc:
            job.error = str(exc)
            job.status = LessonJob.Status.ERROR
            job.save(update_fields=["error", "status", "updated_at"])
    mini_text = job.corrected_output or job.toon_output
    items_html = None
    item_count = 0
    cat_params = None
    bloom_stats = []
    key_topics = set()
    if mini_text:
        from ..parse_mini import parse_mini as _parse
        assessment = _parse(mini_text)
        item_count = len(assessment.items)
        items_html = mark_safe(render_mini_html(mini_text))
        cat_params = parse_cat_params(assessment)
        for level in ["L1", "L2", "L3", "L4", "L5", "L6"]:
            count = sum(1 for item in assessment.items if item.bloom == level)
            if count:
                bloom_stats.append({"level": level, "label": BLOOM_LABELS[level], "count": count})
        for item in assessment.items:
            if item.topic:
                key_topics.add(item.topic)
    if job.tags:
        key_topics.update(t.strip() for t in job.tags.split(",") if t.strip())
    if job.course and job.course.main_topics:
        key_topics.update(job.course.main_topics)

    # calcular paso actual del pipeline
    pipeline_step = 0
    pipeline_total = 4
    if job.generation_prompt:
        pipeline_step = 1
    if job.toon_output:
        pipeline_step = 2
    if job.verification_prompt:
        pipeline_step = 3
    if job.verification_output or job.corrected_output:
        pipeline_step = 4

    profile = _get_or_create_profile(request.user)
    return render(request, "learning/lesson_detail.html", {
        "job": job,
        "items_html": items_html,
        "item_count": item_count,
        "cat_params": cat_params,
        "bloom_stats": bloom_stats,
        "key_topics": sorted(key_topics),
        "practice_sessions": adaptive.PracticeSession.objects.filter(user=request.user, lesson=job)[:8],
        "class_summary": summaries.class_summary_for(job),
        "pipeline_step": pipeline_step,
        "pipeline_total": pipeline_total,
        "is_owner": job.user_id == request.user.id,
        "profile": profile,
        "backends": get_available_backends(),
        "local_model": getattr(settings, "LOCAL_MODEL", None) or getattr(settings, "CLOUD_MODEL", "local"),
    })


@login_required
def shared_lesson_detail(request, token):
    job = get_object_or_404(LessonJob, share_token=token, visibility=LessonJob.Visibility.SHARED)
    return redirect("lesson_detail", pk=job.pk)


@login_required
def lesson_job_status(request, pk):
    job = _get_accessible_job(request.user, pk)
    return JsonResponse({
        "status": job.status,
        "status_display": job.get_status_display(),
        "processing_stage": job.processing_stage,
        "processing_log": job.processing_log,
        "verification_mode": job.verification_mode,
        "error": job.error,
        "has_items": bool(job.corrected_output or job.toon_output),
    })


@login_required
def start_quiz(request, pk):
    """
    Reemplazo del quiz por clase: abre una practica adaptativa del curso limitada
    al banco de esta clase, con la memoria del perfil del curso.
    """
    if request.method != "POST":
        raise Http404()
    job = _get_accessible_job(request.user, pk)
    if not job.course_id:
        messages.warning(request, "Agrega esta clase a un curso para practicarla.")
        return redirect("lesson_detail", pk=job.pk)
    try:
        session = adaptive.start_practice(
            request.user,
            job.course,
            target_count=request.POST.get("target_count", 10),
            focus=request.POST.get("focus", "balanced"),
            lesson=job,
        )
    except adaptive.NoItemsError:
        messages.warning(request, "Esta clase aún no tiene preguntas para practicar.")
        return redirect("lesson_detail", pk=job.pk)
    return redirect("practice_session", pk=job.course_id, session_id=session.pk)


@login_required
def retry_api_lesson(request, pk):
    if request.method != "POST":
        raise Http404()
    profile = _get_or_create_profile(request.user)
    job = get_object_or_404(LessonJob, pk=pk, user=request.user, mode=LessonJob.Mode.API)
    if not _has_api_capacity(request.user, profile):
        messages.warning(request, "Ya usaste las clases de tu plan. Cambia de plan para subir más.")
        return redirect("plans")

    backends = get_available_backends()
    backend = _normalize_ai_backend_choice(request.POST.get("backend"), backends)
    if normalize_backend(request.POST.get("backend")) == "cloud" and backend != "cloud":
        messages.info(request, "Reintentaremos con el procesamiento estándar.")
    verification_mode = request.POST.get("verification_mode") or job.verification_mode
    if not has_enough_credits(profile, REGENERATION_COST):
        messages.warning(request, f"Necesitas {REGENERATION_COST} créditos para reintentar.")
        return redirect("plans")
    try:
        consume_credits(
            profile,
            REGENERATION_COST,
            action="regeneration",
            course=job.course,
            class_session=_safe_class_session(job),
            description=f"Regeneracion de clase: {job.title}",
            metadata={"lesson_job_id": job.pk},
        )
    except ValueError:
        messages.warning(request, "No tienes créditos suficientes para reintentar.")
        return redirect("plans")
    job.status = LessonJob.Status.QUEUED
    job.ai_backend = backend
    job.verification_mode = _normalize_verification_mode(verification_mode)
    job.processing_stage = "En cola"
    job.processing_log = "En cola - Reintento esperando turno en el procesador local."
    job.error = ""
    job.verification_prompt = ""
    job.verification_output = ""
    job.verification_trace = {}
    job.corrected_output = ""
    job.correction_trace = []
    job.mini_coherence_prompt = ""
    job.mini_coherence_trace = []
    job.save(update_fields=[
        "status",
        "ai_backend",
        "verification_mode",
        "processing_stage",
        "processing_log",
        "error",
        "verification_prompt",
        "verification_output",
        "verification_trace",
        "corrected_output",
        "correction_trace",
        "mini_coherence_prompt",
        "mini_coherence_trace",
        "updated_at",
    ])
    try:
        enqueue_lesson_job(job.pk, backend=backend)
        messages.success(request, "Reintentando. Te avisaremos cuando esté lista.")
    except Exception as exc:
        err_str = clean_ai_error(exc)
        job.error = err_str
        job.status = LessonJob.Status.ERROR
        messages.warning(request, f"No pudimos procesar tu clase: {err_str}")
        job.save(update_fields=["error", "status", "updated_at"])
    return redirect("lesson_detail", pk=job.pk)


@login_required
def submit_toon(request, pk):
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    if request.method != "POST":
        raise Http404()
    form = ManualResultForm(request.POST)
    if form.is_valid():
        try:
            job.toon_output, item_count = _compile_mini_for_render(form.cleaned_data["toon_output"], "MINI manual")
        except ValueError as exc:
            messages.warning(request, "No pudimos leer las preguntas pegadas. Revisa el texto e inténtalo de nuevo.")
            return redirect("lesson_detail", pk=job.pk)
        job.verification_prompt = build_verification_prompt(job.toon_output)
        job.status = LessonJob.Status.TOON_READY
        job.processing_log = _append_view_log(job.processing_log, "MINI manual parseado", f"{item_count} items renderizables.")
        job.save()
        messages.success(request, "Preguntas guardadas.")
    return redirect("lesson_detail", pk=job.pk)


@login_required
def submit_verification(request, pk):
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    if request.method != "POST":
        raise Http404()
    form = VerificationResultForm(request.POST)
    if form.is_valid():
        job.verification_output = form.cleaned_data["verification_output"]
        job.corrected_output, job.correction_trace = apply_corrections_with_trace(job.toon_output, job.verification_output)
        try:
            job.corrected_output, item_count = _compile_mini_for_render(job.corrected_output, "MINI corregido manual")
        except ValueError as exc:
            messages.warning(request, "No pudimos aplicar las correcciones. Revisa el texto e inténtalo de nuevo.")
            return redirect("lesson_detail", pk=job.pk)
        job.status = LessonJob.Status.CORRECTED
        job.processing_log = _append_view_log(job.processing_log, "MINI corregido parseado", f"{item_count} items renderizables.")
        job.save()
        messages.success(request, "Correcciones aplicadas.")
    return redirect("lesson_detail", pk=job.pk)


@login_required
def repair_coherence(request, pk):
    if request.method != "POST":
        raise Http404()
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    mini_text = job.corrected_output or job.toon_output
    if not mini_text.strip():
        messages.warning(request, "Aún no hay preguntas para revisar.")
        return redirect("lesson_detail", pk=job.pk)

    source_context = "\n\n".join(
        part for part in [
            f"TITULO: {job.title}",
            f"ETIQUETAS: {job.tags}" if job.tags else "",
            f"TEXTO_ORIGINAL:\n{job.source_text.strip()}" if job.source_text.strip() else "",
            f"TRANSCRIPCION:\n{job.transcript.strip()}" if job.transcript.strip() else "",
        ]
        if part
    )
    try:
        _prompt, repaired_mini, backend, trace = repair_mini_coherence(
            mini_text,
            source_context=source_context,
            backend="local",
        )
    except Exception as exc:
        messages.warning(request, f"No pudimos revisar las preguntas: {clean_ai_error(exc)}")
        return redirect("lesson_detail", pk=job.pk)

    update_fields = ["ai_backend", "processing_log", "updated_at"]
    job.ai_backend = backend
    try:
        repaired_mini, item_count = _compile_mini_for_render(repaired_mini, "Coherencia MINI manual")
    except ValueError as exc:
        messages.warning(request, "No pudimos guardar la revisión. Inténtalo de nuevo.")
        return redirect("lesson_detail", pk=job.pk)
    if job.corrected_output:
        job.corrected_output = repaired_mini
        update_fields.append("corrected_output")
    else:
        job.toon_output = repaired_mini
        update_fields.append("toon_output")

    status = "con cambios" if trace.get("changed") else "sin cambios necesarios"
    job.processing_log = _append_view_log(
        job.processing_log,
        "Coherencia revisada con IA local",
        f"Resultado: {status}. {item_count} items renderizables. Prompt {trace.get('prompt_chars', 0)} chars.",
    )
    job.save(update_fields=update_fields)

    if trace.get("changed"):
        messages.success(request, "Preguntas corregidas.")
    else:
        messages.info(request, "Todo en orden: no hubo nada que corregir.")
    return redirect("lesson_detail", pk=job.pk)


@login_required
def repair_transcript(request, pk):
    if request.method != "POST":
        raise Http404()
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    if job.status in [LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING]:
        messages.warning(request, "Espera a que termine de procesarse para corregir la transcripción.")
        return redirect("lesson_detail", pk=job.pk)
    if not job.transcript.strip():
        messages.warning(request, "Esta clase aún no tiene transcripción.")
        return redirect("lesson_detail", pk=job.pk)

    original_transcript = job.transcript
    generation_backend = job.ai_backend or "auto"
    try:
        prompt, repaired_transcript, repair_backend, trace = repair_transcript_text(
            original_transcript,
            source_context=_transcript_context(job),
            backend="local",
        )
    except Exception as exc:
        messages.warning(request, f"No pudimos corregir la transcripción: {clean_ai_error(exc)}")
        return redirect("lesson_detail", pk=job.pk)

    changed = bool(trace.get("changed"))
    status = "con cambios" if trace.get("changed") else "sin cambios necesarios"
    downstream_action = "sin regeneracion"
    update_fields = [
        "transcript_repair_prompt",
        "transcript_repair_trace",
        "processing_log",
        "updated_at",
    ]

    job.transcript_repair_prompt = prompt

    if changed:
        job.transcript = repaired_transcript
        downstream_action = _reset_after_transcript_change(job, generation_backend)
        update_fields.extend([
            "transcript",
            "generation_prompt",
            "toon_output",
            "verification_prompt",
            "verification_output",
            "verification_trace",
            "corrected_output",
            "correction_trace",
            "mini_coherence_prompt",
            "mini_coherence_trace",
            "error",
            "status",
            "processing_stage",
        ])

    job.transcript_repair_trace = [
        *_safe_trace_list(job.transcript_repair_trace),
        _transcript_repair_entry(
            before=original_transcript,
            after=repaired_transcript,
            trace=trace,
            backend=repair_backend,
            downstream_action=downstream_action,
        ),
    ][-8:]
    job.processing_log = _append_view_log(
        job.processing_log,
        "Transcripcion revisada con IA local",
        f"Resultado: {status}. Accion posterior: {downstream_action}.",
    )
    job.save(update_fields=update_fields)

    if changed and job.mode == LessonJob.Mode.API:
        try:
            enqueue_lesson_job(job.pk, backend=generation_backend)
        except Exception as exc:
            err_str = clean_ai_error(exc)
            job.error = err_str
            job.status = LessonJob.Status.ERROR
            job.processing_stage = "Error"
            job.processing_log = _append_view_log(job.processing_log, "Error", err_str)
            job.save(update_fields=["error", "status", "processing_stage", "processing_log", "updated_at"])
            messages.warning(request, f"Transcripción corregida, pero no pudimos crear las preguntas: {err_str}")
            return redirect("lesson_detail", pk=job.pk)

    if changed and job.mode == LessonJob.Mode.API:
        messages.success(request, "Transcripción corregida. Estamos creando las preguntas de nuevo.")
    elif changed:
        messages.success(request, "Transcripción corregida. Copia las nuevas instrucciones para crear las preguntas.")
    else:
        messages.info(request, "La transcripción ya estaba bien.")
    return redirect("lesson_detail", pk=job.pk)


@login_required
def set_visibility(request, pk):
    """Cambia la visibilidad de una clase (privada / compartida / pública)."""
    if request.method != "POST":
        raise Http404()
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    visibility = request.POST.get("visibility", "private")
    if visibility not in [v for v, _ in LessonJob.Visibility.choices]:
        visibility = "private"

    job.visibility = visibility
    job.tags = _normalize_tags(request.POST.get("tags", job.tags))

    # generar token único si se comparte con link
    if visibility == LessonJob.Visibility.SHARED and not job.share_token:
        import secrets
        job.share_token = secrets.token_hex(16)
    elif visibility == LessonJob.Visibility.PRIVATE:
        job.share_token = None

    job.save(update_fields=["visibility", "share_token", "tags", "updated_at"])
    label = dict(LessonJob.Visibility.choices)[visibility]
    messages.success(request, f"Visibilidad actualizada: {label}.")
    return redirect("lesson_detail", pk=job.pk)


@login_required
def delete_lesson(request, pk):
    """Elimina una clase del usuario."""
    if request.method != "POST":
        raise Http404()
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    job.delete()
    messages.success(request, "Clase eliminada.")
    return redirect("dashboard")


@login_required
def rename_lesson(request, pk):
    """Renombra el título de una clase."""
    if request.method != "POST":
        raise Http404()
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    title = request.POST.get("title", "").strip()
    if title:
        job.title = title[:140]
        job.save()
        messages.success(request, "Nombre actualizado.")
    return redirect("lesson_detail", pk=job.pk)


@login_required
def download_json(request, pk):
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    mini_text = job.corrected_output or job.toon_output
    assessment = parse_mini(mini_text) if mini_text else None
    assessment_payload = assessment_to_dict(assessment)["assessment"] if assessment else {"meta": {}, "items": []}

    payload = {
        "title": job.title,
        "mode": job.mode,
        "assessment": assessment_payload,
        "transcript": job.transcript,
        "verification_report": job.verification_output,
    }
    response = HttpResponse(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
    response["Content-Disposition"] = f'attachment; filename="clase-{job.pk}.json"'
    return response
