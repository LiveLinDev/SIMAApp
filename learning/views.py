from __future__ import annotations

import json
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from . import adaptive, adaptive_generation
from .cat import BLOOM_LABELS, build_bank, choose_next_item, estimate_theta, option_index, parse_cat_params, theta_to_level
from .credits import (
    REGENERATION_COST,
    consume_credits,
    estimate_lesson_job_cost,
    grant_plan_credits,
    has_enough_credits,
)
from .forms import ApiLessonForm, CourseForm, FreeLessonForm, ManualResultForm, PlanForm, RegisterForm, VerificationResultForm
from .job_queue import enqueue_lesson_job
from .models import ClassSession, Course, Difficulty, Flashcard, LessonJob, QuizAttempt, QuizResponse, UserPreference, get_plan_details
from .parse_mini import apply_corrections_with_trace, assessment_to_dict, filter_incoherent_items, normalize_mini_text, parse_mini, render_mini_html, validate_mini_parse
from .services import (
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


def _get_or_create_profile(user):
    """Garantiza que el usuario siempre tenga un perfil, incluso si fue creado antes del signal."""
    from .models import Profile
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
        preferences.save(update_fields=["daily_goal", "updated_at"])
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
    })


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
        "quizzes": sum(job.quiz_attempts.filter(user=request.user).count() for job in jobs[:100]),
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


@login_required
def free_lesson(request):
    if not Course.objects.filter(user=request.user, is_archived=False).exists():
        messages.info(request, "Primero crea un curso para que SIMA guarde tus clases con contexto.")
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
        messages.warning(request, "Tu plan actual no tiene clases API disponibles.")
        return redirect("plans")
    if not Course.objects.filter(user=request.user, is_archived=False).exists():
        messages.info(request, "Primero crea un curso para que SIMA guarde tus clases con contexto.")
        return redirect("course_create")
    if request.method == "POST":
        form = ApiLessonForm(request.POST, request.FILES, user=request.user)
        backend = _normalize_ai_backend_choice(request.POST.get("backend"), backends)
        if normalize_backend(request.POST.get("backend")) == "cloud" and backend != "cloud":
            messages.info(request, "La nube no esta configurada; se usara el modelo local.")
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
                    f"No tienes creditos suficientes. Esta clase requiere {estimate.amount} y tienes {profile.credits_label}.",
                )
                return redirect("plans")
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
                messages.warning(request, "No tienes creditos suficientes para procesar esta clase.")
                return redirect("plans")
            try:
                enqueue_lesson_job(job.pk, backend=backend)
                messages.success(request, "Clase agregada a la cola. Puedes dejar esta página abierta; se actualizará sola.")
            except Exception as exc:
                err_str = clean_ai_error(exc)
                job.error = err_str
                job.status = LessonJob.Status.ERROR
                job.save(update_fields=["error", "status", "updated_at"])
                messages.warning(request, f"No se pudo completar automaticamente: {err_str}")
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
        from .parse_mini import parse_mini as _parse
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
        "quiz_attempts": job.quiz_attempts.filter(user=request.user)[:8],
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
        messages.warning(request, "Asigna esta clase a un curso para practicarla con seguimiento.")
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
        messages.warning(request, "Esta clase aun no tiene items validos para practicar.")
        return redirect("lesson_detail", pk=job.pk)
    return redirect("practice_session", pk=job.course_id, session_id=session.pk)

@login_required
def quiz_attempt(request, pk, attempt_id):
    job = _get_accessible_job(request.user, pk)
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, lesson=job, user=request.user)
    mini_text = job.corrected_output or job.toon_output
    items, params = build_bank(mini_text)
    items_by_id = {item.id: item for item in items}
    current_item = items_by_id.get(attempt.current_item_id)
    responses = list(attempt.responses.all())
    if not current_item and not attempt.is_complete and items:
        answered_ids = {response.item_id for response in responses}
        next_item = choose_next_item(items, answered_ids, attempt.theta, responses, attempt.target_count)
        if next_item:
            current_item = next_item
            attempt.current_item_id = next_item.id
            if next_item.id not in attempt.selected_item_ids:
                attempt.selected_item_ids = [*attempt.selected_item_ids, next_item.id]
            attempt.save(update_fields=["current_item_id", "selected_item_ids", "updated_at"])
        else:
            attempt.completed_at = timezone.now()
            attempt.current_item_id = ""
            attempt.save(update_fields=["completed_at", "current_item_id", "updated_at"])
    progress_pct = min(100, round((len(responses) / max(attempt.target_count, 1)) * 100))
    bloom_counts = {}
    for response in responses:
        bloom_counts[response.item_bloom] = bloom_counts.get(response.item_bloom, 0) + 1
    bloom_progress = [
        {"level": level, "label": label, "count": bloom_counts.get(level, 0)}
        for level, label in BLOOM_LABELS.items()
        if bloom_counts.get(level, 0)
    ]

    bloom_chart_data = [
        {"label": BLOOM_LABELS.get(level, level), "count": bloom_counts.get(level, 0), "pct": round((bloom_counts.get(level, 0) / max(attempt.answered_count, 1)) * 100)}
        for level in ["L1", "L2", "L3", "L4", "L5", "L6"]
        if bloom_counts.get(level, 0) > 0
    ]
    level_value, level_label = theta_to_level(attempt.theta)
    return render(request, "learning/quiz_attempt.html", {
        "job": job,
        "attempt": attempt,
        "item": current_item,
        "item_bloom_label": BLOOM_LABELS.get(current_item.bloom, current_item.bloom) if current_item else "",
        "responses": responses,
        "progress_pct": progress_pct,
        "bloom_progress": bloom_progress,
        "bloom_chart_data": bloom_chart_data,
        "bloom_labels": BLOOM_LABELS,
        "cat_params": params,
        "level_value": level_value,
        "level_label": level_label,
    })


@login_required
def answer_quiz(request, pk, attempt_id):
    if request.method != "POST":
        raise Http404()
    job = _get_accessible_job(request.user, pk)
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, lesson=job, user=request.user)
    if attempt.is_complete:
        return redirect("quiz_attempt", pk=job.pk, attempt_id=attempt.pk)

    mini_text = job.corrected_output or job.toon_output
    items, params = build_bank(mini_text)
    items_by_id = {item.id: item for item in items}
    item = items_by_id.get(attempt.current_item_id)
    if not item:
        responses = list(attempt.responses.all())
        next_item = choose_next_item(items, {response.item_id for response in responses}, attempt.theta, responses, attempt.target_count)
        if next_item:
            attempt.current_item_id = next_item.id
            attempt.selected_item_ids = [*attempt.selected_item_ids, next_item.id]
            attempt.save(update_fields=["current_item_id", "selected_item_ids", "updated_at"])
            messages.info(request, "Se omitio una pregunta con alternativas incoherentes y se cargo la siguiente.")
            return redirect("quiz_attempt", pk=job.pk, attempt_id=attempt.pk)
        messages.warning(request, "No se encontró el ítem actual.")
        return redirect("lesson_detail", pk=job.pk)

    selected_index = int(request.POST.get("option", "-1"))
    correct_index = option_index(item)
    is_correct = selected_index == correct_index
    response = QuizResponse.objects.create(
        attempt=attempt,
        item_id=item.id,
        item_bloom=item.bloom,
        item_topic=item.topic,
        item_area=item.area,
        item_demand=item.demand,
        theta_before=attempt.theta,
        selected_index=selected_index,
        correct_index=correct_index,
        is_correct=is_correct,
    )

    responses = list(attempt.responses.all())
    theta, se = estimate_theta(items_by_id, responses, params["theta_min"], params["theta_max"])
    response.theta_after = theta
    response.save(update_fields=["theta_after"])
    attempt.theta = theta
    attempt.standard_error = se
    attempt.correct_count = sum(1 for r in responses if r.is_correct)

    should_stop = len(responses) >= attempt.target_count or se <= params["se_stop"] or len(responses) >= len(items)
    if should_stop:
        attempt.completed_at = timezone.now()
        attempt.current_item_id = ""
        attempt.save()
        profile = _get_or_create_profile(request.user)
        profile.total_xp += 5 + attempt.correct_count * 2
        profile.save()
    else:
        next_item = choose_next_item(items, set(attempt.selected_item_ids), theta, responses, attempt.target_count)
        if next_item:
            attempt.current_item_id = next_item.id
            attempt.selected_item_ids = [*attempt.selected_item_ids, next_item.id]
        else:
            attempt.completed_at = timezone.now()
            attempt.current_item_id = ""
        attempt.save()
    return redirect("quiz_attempt", pk=job.pk, attempt_id=attempt.pk)


@login_required
def retry_api_lesson(request, pk):
    if request.method != "POST":
        raise Http404()
    profile = _get_or_create_profile(request.user)
    job = get_object_or_404(LessonJob, pk=pk, user=request.user, mode=LessonJob.Mode.API)
    if not _has_api_capacity(request.user, profile):
        messages.warning(request, "Tu plan actual no tiene clases API disponibles.")
        return redirect("plans")

    backends = get_available_backends()
    backend = _normalize_ai_backend_choice(request.POST.get("backend"), backends)
    if normalize_backend(request.POST.get("backend")) == "cloud" and backend != "cloud":
        messages.info(request, "La nube no esta configurada; se reintentara con el modelo local.")
    verification_mode = request.POST.get("verification_mode") or job.verification_mode
    if not has_enough_credits(profile, REGENERATION_COST):
        messages.warning(request, f"Necesitas {REGENERATION_COST} creditos para regenerar esta clase.")
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
        messages.warning(request, "No tienes creditos suficientes para regenerar esta clase.")
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
        messages.success(request, "Reintento agregado a la cola.")
    except Exception as exc:
        err_str = clean_ai_error(exc)
        job.error = err_str
        job.status = LessonJob.Status.ERROR
        messages.warning(request, f"No se pudo completar automaticamente: {err_str}")
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
            messages.warning(request, f"No se guardo el MINI porque no parsea completo: {exc}")
            return redirect("lesson_detail", pk=job.pk)
        job.verification_prompt = build_verification_prompt(job.toon_output)
        job.status = LessonJob.Status.TOON_READY
        job.processing_log = _append_view_log(job.processing_log, "MINI manual parseado", f"{item_count} items renderizables.")
        job.save()
        messages.success(request, "Ítems guardados. Ya puedes verificarlos.")
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
            messages.warning(request, f"Las correcciones no se guardaron porque el MINI no parsea completo: {exc}")
            return redirect("lesson_detail", pk=job.pk)
        job.status = LessonJob.Status.CORRECTED
        job.processing_log = _append_view_log(job.processing_log, "MINI corregido parseado", f"{item_count} items renderizables.")
        job.save()
        messages.success(request, "Correcciones aplicadas automáticamente.")
    return redirect("lesson_detail", pk=job.pk)


@login_required
def repair_coherence(request, pk):
    if request.method != "POST":
        raise Http404()
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    mini_text = job.corrected_output or job.toon_output
    if not mini_text.strip():
        messages.warning(request, "Aun no hay items MINI para revisar.")
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
        messages.warning(request, f"No se pudo reparar coherencia con IA local: {clean_ai_error(exc)}")
        return redirect("lesson_detail", pk=job.pk)

    update_fields = ["ai_backend", "processing_log", "updated_at"]
    job.ai_backend = backend
    try:
        repaired_mini, item_count = _compile_mini_for_render(repaired_mini, "Coherencia MINI manual")
    except ValueError as exc:
        messages.warning(request, f"La reparacion no se guardo porque el MINI no parsea completo: {exc}")
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
        messages.success(request, "Coherencia reparada con IA local.")
    else:
        messages.info(request, "La IA local no encontro incoherencias que cambiar.")
    return redirect("lesson_detail", pk=job.pk)


@login_required
def repair_transcript(request, pk):
    if request.method != "POST":
        raise Http404()
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)
    if job.status in [LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING]:
        messages.warning(request, "Espera a que termine el procesamiento antes de corregir la transcripcion.")
        return redirect("lesson_detail", pk=job.pk)
    if not job.transcript.strip():
        messages.warning(request, "Esta clase aun no tiene transcripcion para corregir.")
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
        messages.warning(request, f"No se pudo corregir la transcripcion con IA local: {clean_ai_error(exc)}")
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
            messages.warning(request, f"Transcripcion corregida, pero no se pudo regenerar automaticamente: {err_str}")
            return redirect("lesson_detail", pk=job.pk)

    if changed and job.mode == LessonJob.Mode.API:
        messages.success(request, "Transcripcion corregida. Se reinicio todo el pipeline desde ese lienzo.")
    elif changed:
        messages.success(request, "Transcripcion corregida. El prompt manual fue regenerado y los items anteriores quedaron invalidados.")
    else:
        messages.info(request, "La IA local no encontro cambios necesarios en la transcripcion.")
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


def _normalize_ai_backend_choice(backend: str | None, backends: dict) -> str:
    value = normalize_backend(backend)
    if value == "auto":
        return backends["default"]
    if value == "cloud" and not backends.get("cloud"):
        return "local"
    if value not in {"local", "cloud"}:
        return backends["default"]
    return value


def _normalize_verification_mode(mode: str) -> str:
    return mode if mode in {"web", "eduqg", "hybrid"} else getattr(settings, "VERIFICATION_DEFAULT_MODE", "web")


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


def _job_content_for_generation(job: LessonJob) -> str:
    parts = []
    source_text = (job.source_text or "").strip()
    transcript = (job.transcript or "").strip()
    if source_text:
        parts.append(source_text)
    if transcript:
        parts.append(f"TRANSCRIPCION:\n{transcript}")
    return "\n\n".join(parts).strip()


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


def _safe_trace_list(value) -> list:
    return value if isinstance(value, list) else []


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


def _compile_mini_for_render(mini_text: str, stage: str) -> tuple[str, int, str]:
    mini_block = extract_mini_lines(mini_text) or mini_text
    filtered, dropped, incoherent_mini = filter_incoherent_items(mini_block)
    if dropped:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[%s] Items incoherentes detectados: %s", stage, dropped)
    normalized = normalize_mini_text(filtered, stage=stage)
    assessment = validate_mini_parse(normalized, stage=stage)
    return normalized, len(assessment.items), incoherent_mini


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


def _sync_class_session_for_job(job: LessonJob) -> ClassSession | None:
    if not job.course_id:
        return None
    status_map = {
        LessonJob.Status.DRAFT: ClassSession.ProcessingStatus.DRAFT,
        LessonJob.Status.QUEUED: ClassSession.ProcessingStatus.QUEUED,
        LessonJob.Status.PROCESSING: ClassSession.ProcessingStatus.PROCESSING,
        LessonJob.Status.ERROR: ClassSession.ProcessingStatus.ERROR,
    }
    ready_statuses = {
        LessonJob.Status.PROMPT_READY,
        LessonJob.Status.TOON_READY,
        LessonJob.Status.VERIFIED,
        LessonJob.Status.CORRECTED,
    }
    status = ClassSession.ProcessingStatus.READY if job.status in ready_statuses else status_map.get(
        job.status,
        ClassSession.ProcessingStatus.DRAFT,
    )
    session, _created = ClassSession.objects.update_or_create(
        legacy_lesson_job=job,
        defaults={
            "user": job.user,
            "course": job.course,
            "title": job.title,
            "status": status,
            "main_topic": job.tags.split(",")[0].strip() if job.tags else "",
            "requested_outputs": ["transcript", "quiz"],
            "processing_log": job.processing_log,
            "error": job.error,
        },
    )
    return session


def _safe_class_session(job: LessonJob) -> ClassSession | None:
    try:
        return job.class_session
    except ClassSession.DoesNotExist:
        return None


# ══════════════════════════════════════════════════════════════════
# FLASHCARDS
# ══════════════════════════════════════════════════════════════════

@login_required
def flashcards(request, pk):
    job = _get_accessible_job(request.user, pk)
    # obtener o generar flashcards desde el MINI
    session = _safe_class_session(job)
    if not session and job.course_id:
        session = _sync_class_session_for_job(job)
    cards = list(Flashcard.objects.filter(class_session=session).order_by("?") if session else [])
    if not cards and (job.corrected_output or job.toon_output):
        cards = _ensure_flashcards_from_mini(job, session)
    return render(request, "learning/flashcards.html", {
        "job": job,
        "cards": cards,
        "card_count": len(cards),
        "is_owner": job.user_id == request.user.id,
    })


@login_required
def review_flashcard(request, pk):
    if request.method != "POST":
        raise Http404()
    job = _get_accessible_job(request.user, pk)
    flashcard_id = int(request.POST.get("flashcard_id", 0))
    difficulty = request.POST.get("difficulty", "medium")  # again / hard / medium / easy
    flashcard = get_object_or_404(Flashcard, pk=flashcard_id)
    # spaced repetition básico
    if difficulty == "again":
        flashcard.mastery_level = max(0, flashcard.mastery_level - 1)
        flashcard.next_review_at = timezone.now() + timezone.timedelta(minutes=10)
    elif difficulty == "hard":
        flashcard.mastery_level = max(0, flashcard.mastery_level)
        flashcard.next_review_at = timezone.now() + timezone.timedelta(hours=4)
    elif difficulty == "easy":
        flashcard.mastery_level = min(5, flashcard.mastery_level + 1)
        flashcard.next_review_at = timezone.now() + timezone.timedelta(days=3)
    else:  # medium
        flashcard.mastery_level = min(5, flashcard.mastery_level + 1)
        flashcard.next_review_at = timezone.now() + timezone.timedelta(days=1)
    flashcard.save(update_fields=["mastery_level", "next_review_at"])
    # award XP
    profile = _get_or_create_profile(request.user)
    profile.total_xp += 2
    profile.save()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "mastery": flashcard.mastery_level, "next_review": flashcard.next_review_at.isoformat()})
    return redirect("flashcards", pk=job.pk)


# ══════════════════════════════════════════════════════════════════
# EJERCICIOS DE RELACIÓN Y COMPLETAR
# ══════════════════════════════════════════════════════════════════

import random

@login_required
def matching_exercise(request, pk):
    import json
    job = _get_accessible_job(request.user, pk)
    session = _safe_class_session(job)
    if not session and job.course_id:
        session = _sync_class_session_for_job(job)
    cards = list(Flashcard.objects.filter(class_session=session).order_by("?")[:8])
    if not cards and (job.corrected_output or job.toon_output):
        cards = _ensure_flashcards_from_mini(job, session)
        cards = list(Flashcard.objects.filter(class_session=session).order_by("?")[:8])
    pairs = []
    for c in cards:
        pairs.append({"id": c.pk, "concept": c.question, "definition": c.answer})
    definitions = [p["definition"] for p in pairs]
    random.shuffle(definitions)
    return render(request, "learning/matching_exercise.html", {
        "job": job,
        "pairs": pairs,
        "definitions": definitions,
        "pairs_json": json.dumps(pairs, ensure_ascii=False),
        "definitions_json": json.dumps(definitions, ensure_ascii=False),
        "is_owner": job.user_id == request.user.id,
    })


@login_required
def cloze_exercise(request, pk):
    job = _get_accessible_job(request.user, pk)
    session = _safe_class_session(job)
    if not session and job.course_id:
        session = _sync_class_session_for_job(job)
    cards = list(Flashcard.objects.filter(class_session=session).order_by("?")[:8])
    if not cards and (job.corrected_output or job.toon_output):
        cards = _ensure_flashcards_from_mini(job, session)
        cards = list(Flashcard.objects.filter(class_session=session).order_by("?")[:8])
    items = []
    for c in cards:
        prompt = c.question
        if "____" in prompt or "___" in prompt or "__" in prompt:
            items.append({"id": c.pk, "prompt": prompt, "answer": c.answer})
        else:
            # Transformar definición en cloze simple si no tiene blank
            items.append({"id": c.pk, "prompt": f"{c.question} ____", "answer": c.answer})
    return render(request, "learning/cloze_exercise.html", {
        "job": job,
        "items": items,
        "is_owner": job.user_id == request.user.id,
    })


def _ensure_flashcards_from_mini(job: LessonJob, session: ClassSession | None) -> list[Flashcard]:
    """Genera flashcards básicas desde los ítems MINI si no existen."""
    mini_text = job.corrected_output or job.toon_output
    if not mini_text:
        return []
    from .parse_mini import parse_mini as _parse
    assessment = _parse(mini_text)
    created = []
    for item in assessment.items:
        def _is_correct(opt):
            return opt.get("correct") if isinstance(opt, dict) else getattr(opt, "correct", False)
        def _opt_text(opt):
            return opt.get("text", "") if isinstance(opt, dict) else getattr(opt, "text", "")
        correct = [opt for opt in item.options if _is_correct(opt)]
        answer_text = _opt_text(correct[0]) if correct else (_opt_text(item.options[0]) if item.options else "")
        topic = item.topic or job.tags.split(",")[0].strip() if job.tags else ""
        card, _ = Flashcard.objects.get_or_create(
            class_session=session,
            question=item.statement,
            defaults={
                "course": job.course,
                "answer": answer_text,
                "topic": topic,
                "difficulty": Difficulty.MEDIUM,
            },
        )
        created.append(card)
    return created


# ══════════════════════════════════════════════════════════════════
# MAPA DE CLASE
# ══════════════════════════════════════════════════════════════════

@login_required
def class_map(request, pk):
    job = _get_accessible_job(request.user, pk)
    session = _safe_class_session(job)
    if not session and job.course_id:
        session = _sync_class_session_for_job(job)
    topics = []
    concepts = []
    if job.tags:
        for tag in job.tags.split(","):
            _add_map_term(topics, tag)
    if job.course and job.course.main_topics:
        for topic in job.course.main_topics:
            _add_map_term(topics, topic)

    bloom_counts = {}
    if job.corrected_output or job.toon_output:
        from .parse_mini import parse_mini as _parse
        assessment = _parse(job.corrected_output or job.toon_output)
        for item in assessment.items:
            _add_map_term(topics, item.topic)
            correct = next((opt.get("text", "") for opt in item.options if opt.get("correct")), "")
            _add_map_term(concepts, correct, max_words=7, max_chars=90)
            for term in _extract_statement_terms(item.statement):
                _add_map_term(concepts, term, max_words=4, max_chars=70)
            bloom_counts[item.bloom] = bloom_counts.get(item.bloom, 0) + 1
    cards = list(Flashcard.objects.filter(class_session=session) if session else [])
    for card in cards:
        _add_map_term(topics, card.topic)
        _add_map_term(concepts, card.answer, max_words=7, max_chars=90)
        for term in _extract_statement_terms(card.question):
            _add_map_term(concepts, term, max_words=4, max_chars=70)
    max_bloom = max(bloom_counts.values()) if bloom_counts else 1
    bloom_chart_data = [
        {"label": BLOOM_LABELS.get(level, level), "count": count, "pct": round((count / max_bloom) * 100) if max_bloom else 0}
        for level, count in sorted(bloom_counts.items())
    ]
    return render(request, "learning/class_map.html", {
        "job": job,
        "topics": sorted(topics, key=str.lower),
        "concepts": sorted(concepts, key=str.lower)[:24],
        "bloom_chart_data": bloom_chart_data,
        "card_count": len(concepts),
        "is_owner": job.user_id == request.user.id,
    })


_GENERIC_MAP_TERMS = {
    "recordar", "recuerda", "recordando", "remember", "recall",
    "comprender", "comprension", "comprensión", "understand", "understanding",
    "aplicar", "aplicacion", "aplicación", "apply", "applying",
    "analizar", "analisis", "análisis", "analyze", "analysing", "analysis",
    "evaluar", "evaluacion", "evaluación", "evaluate", "evaluation",
    "crear", "creacion", "creación", "create", "creating",
    "bloom", "nivel", "levels", "level", "pregunta", "respuesta", "opcion", "item",
}

_MAP_STOPWORDS = {
    "a", "al", "ante", "bajo", "con", "contra", "de", "del", "desde", "durante", "e", "el", "ella",
    "en", "entre", "es", "esa", "ese", "esta", "este", "esto", "estos", "la", "las", "lo", "los",
    "para", "por", "que", "se", "segun", "sin", "sobre", "su", "sus", "un", "una", "unas", "uno", "unos",
    "cual", "cuales", "cuando", "donde", "como", "porque", "siguiente", "siguientes", "principal",
    "indica", "identifica", "selecciona", "corresponde", "relaciona", "define", "explica", "verdadero",
    "falso", "correcta", "correcto", "incorrecta", "incorrecto", "mejor", "mayor", "menor",
    "what", "which", "when", "where", "how", "why", "the", "and", "or", "of", "to", "in", "for",
}


def _is_generic_term(term: str) -> bool:
    compact = re.sub(r"\s+", " ", str(term or "").strip(" -:;.,¿?¡!()[]{}\"'`")).strip()
    if not compact:
        return True
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", compact.lower())
    if not words:
        return True
    meaningful = [word for word in words if word not in _MAP_STOPWORDS]
    if not meaningful:
        return True
    normalized = " ".join(meaningful)
    return normalized in _GENERIC_MAP_TERMS or all(word in _GENERIC_MAP_TERMS for word in meaningful)


def _add_map_term(collection: list[str], term: str, max_words: int = 6, max_chars: int = 80):
    compact = re.sub(r"\s+", " ", str(term or "").replace("_", " ").strip()).strip(" -:;.,¿?¡!()[]{}\"'`")
    if not compact or _is_generic_term(compact):
        return
    words = compact.split()
    if len(words) > max_words or len(compact) > max_chars:
        compact = " ".join(words[:max_words]).strip(" -:;.,")
    if _is_generic_term(compact):
        return
    key = compact.lower()
    if key not in {value.lower() for value in collection}:
        collection.append(compact)


def _extract_statement_terms(statement: str) -> list[str]:
    text = re.sub(r"[_|]", " ", str(statement or ""))
    text = re.sub(r"[¿?¡!]", " ", text)
    quoted = re.findall(r"['\"]([^'\"]{4,70})['\"]", text)
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text)
    content = [
        word for word in words
        if len(word) > 3 and word.lower() not in _MAP_STOPWORDS and word.lower() not in _GENERIC_MAP_TERMS
    ]
    candidates = [*quoted]
    for size in (3, 2, 1):
        for index in range(0, max(0, len(content) - size + 1)):
            candidate = " ".join(content[index:index + size])
            if not _is_generic_term(candidate):
                candidates.append(candidate)
            if len(candidates) >= 4:
                break
        if len(candidates) >= 4:
            break
    unique = []
    for candidate in candidates:
        compact = re.sub(r"\s+", " ", candidate.strip()).strip(" -:;.,")
        if compact and compact.lower() not in {value.lower() for value in unique}:
            unique.append(compact)
    return unique[:3]


_MAP_STOPWORDS.update({
    "capta", "captar", "libera", "liberan", "liberado", "ocurre", "principalmente",
    "respuesta", "pregunta", "alternativa", "opciones",
})


def _extract_statement_terms(statement: str) -> list[str]:
    text = re.sub(r"[_|]", " ", str(statement or ""))
    text = re.sub(r"[¿?¡!]", " ", text)
    quoted = re.findall(r"['\"]([^'\"]{4,70})['\"]", text)
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text)
    candidates = [*quoted]
    for word in words:
        lowered = word.lower()
        if len(word) <= 3 or lowered in _MAP_STOPWORDS or lowered in _GENERIC_MAP_TERMS:
            continue
        candidates.append(word)
    unique = []
    for candidate in candidates:
        compact = re.sub(r"\s+", " ", candidate.strip()).strip(" -:;.,")
        if compact and not _is_generic_term(compact) and compact.lower() not in {value.lower() for value in unique}:
            unique.append(compact)
    return unique[:4]


@login_required
def pipeline_visualization(request, pk):
    """Visualizacion del pipeline de generacion como diagrama de flujo."""
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)

    # Parsear processing_log en etapas
    stages = _parse_pipeline_stages(job)

    # Extraer metricas clave
    metrics = _extract_pipeline_metrics(job)

    # Preparar datos de modal por etapa
    stage_details = _build_stage_details(job, stages)

    return render(request, "learning/pipeline_viz.html", {
        "job": job,
        "stages": stages,
        "metrics": metrics,
        "stage_details": stage_details,
    })


def _build_stage_details(job, stages):
    """Mapea cada etapa del pipeline a sus datos detallados (traces JSON)."""
    details = {}

    # Datos de reparacion de transcripcion
    transcript_traces = job.transcript_repair_trace or []
    for i, trace in enumerate(transcript_traces):
        key = f"transcript_repair_{i}"
        details[key] = {
            "title": "Corrección de transcripción",
            "body": _format_transcript_trace(trace),
        }

    # Datos de coherencia MINI
    coherence_traces = job.mini_coherence_trace or []
    for i, trace in enumerate(coherence_traces):
        key = f"coherence_{i}"
        details[key] = {
            "title": "Revisión de coherencia MINI",
            "body": _format_coherence_trace(trace),
        }

    # Datos de verificacion
    verif = job.verification_trace or {}
    if verif:
        details["verification"] = {
            "title": "Verificación con fuentes",
            "body": _format_verification_trace(verif),
        }

    # Datos de correcciones
    corr_traces = job.correction_trace or []
    if corr_traces:
        applied = [c for c in corr_traces if c.get("applied")]
        ignored = [c for c in corr_traces if not c.get("applied")]
        details["corrections"] = {
            "title": f"Correcciones aplicadas ({len(applied)})",
            "body": _format_corrections_trace(applied, ignored),
        }

    # Mapear stages a keys
    stage_keys = {}
    for stage in stages:
        name_lower = stage["name"].lower()
        if "transcripcion" in name_lower and ("corrigiendo" in name_lower or "revisada" in name_lower):
            stage_keys[id(stage)] = "transcript_repair_0"
        elif "coherencia" in name_lower:
            stage_keys[id(stage)] = "coherence_0"
        elif "verificacion" in name_lower and "recibida" in name_lower:
            stage_keys[id(stage)] = "verification"
        elif "aplicando correcciones" in name_lower:
            stage_keys[id(stage)] = "corrections"

    return {"details": details, "stage_keys": stage_keys}


def _format_transcript_trace(trace):
    lines = []
    changes = trace.get("changes", [])
    if changes:
        lines.append("<strong>Cambios detectados:</strong>")
        for ch in changes[:8]:
            lines.append(f"<code>{ch.get('before','')[:60]}...</code> → <code>{ch.get('after','')[:60]}...</code>")
    else:
        lines.append("No se detectaron cambios significativos.")
    return "<br>".join(lines)


def _format_coherence_trace(trace):
    lines = []
    changes = trace.get("changes", [])
    if changes:
        lines.append(f"<strong>Cambios:</strong> {len(changes)} items modificados")
        for ch in changes[:5]:
            lines.append(f"<code>{ch.get('before','')[:80]}...</code> → <code>{ch.get('after','')[:80]}...</code>")
    else:
        lines.append("No se requirieron cambios de coherencia.")
    return "<br>".join(lines)


def _format_verification_trace(verif):
    lines = []
    web = verif.get("web", {})
    queries = web.get("queries", [])
    if queries:
        lines.append(f"<strong>Queries web:</strong> {len(queries)}")
        for q in queries:
            results = q.get("results", [])
            lines.append(f"• <em>{q.get('query','')[:50]}...</em> → {len(results)} resultados")
    eduqg = verif.get("eduqg", {})
    matches = eduqg.get("matches", [])
    if matches:
        lines.append(f"<strong>Matches EduQG:</strong> {len(matches)}")
    return "<br>".join(lines)


def _format_corrections_trace(applied, ignored):
    lines = []
    if applied:
        lines.append(f"<strong>Aplicadas ({len(applied)}):</strong>")
        for c in applied[:10]:
            lines.append(f"• [{c.get('matched_item_id','?')}] {c.get('error_type','')} — {c.get('note','')}")
    if ignored:
        lines.append(f"<strong>Ignoradas ({len(ignored)}):</strong>")
        for c in ignored[:5]:
            lines.append(f"• [{c.get('report_item_id','?')}] {c.get('note','')}")
    return "<br>".join(lines)


def _build_stage_details(job, stages):
    """Construye dossiers estructurados para exponer prompts, MINI y evidencia."""
    details = {}
    source_content = job.source_text or job.transcript or ""

    if source_content:
        details["source"] = _stage_detail(
            "Entrada de la clase",
            "Texto base usado para transcripcion, generacion o reparacion.",
            [_text_section("Contenido de entrada", source_content)],
        )

    if job.transcript:
        details["transcript"] = _stage_detail(
            "Transcripcion local",
            "Texto obtenido o revisado antes de generar items.",
            [_text_section("Transcripcion", job.transcript)],
        )

    if job.generation_prompt or job.toon_output:
        details["generation"] = _stage_detail(
            "Generacion de microcontenidos MINI",
            "Prompt real enviado al backend y salida MINI inicial renderizable.",
            [
                _text_section("Prompt de generacion", job.generation_prompt, kind="prompt"),
                _text_section("Salida MINI generada", job.toon_output, kind="mini"),
            ],
        )

    for index, trace in enumerate(job.transcript_repair_trace or []):
        details[f"transcript_repair_{index}"] = _stage_detail(
            "Correccion de transcripcion",
            "El modelo revisa errores probables de audio antes de crear items.",
            [
                _text_section("Prompt de reparacion", job.transcript_repair_prompt, kind="prompt"),
                _diff_section("Antes / despues", trace.get("before", ""), trace.get("after", ""), trace.get("changes", [])),
                _json_section("Trace tecnico", trace),
            ],
        )

    for index, trace in enumerate(job.mini_coherence_trace or []):
        details[f"coherence_{index}"] = _stage_detail(
            "Revision de coherencia MINI",
            "Control local de sentido antes de verificar contra fuentes externas.",
            [
                _text_section("Prompt de coherencia", job.mini_coherence_prompt, kind="prompt"),
                _diff_section("MINI antes / despues", trace.get("before", ""), trace.get("after", ""), trace.get("changes", [])),
                _json_section("Trace tecnico", trace),
            ],
        )

    verif = job.verification_trace or {}
    if verif or job.verification_prompt or job.verification_output:
        details["verification"] = _stage_detail(
            "Verificacion con fuentes",
            "La IA valida afirmaciones MINI usando consultas generadas y documentos recuperados.",
            [
                _text_section("Prompt de verificacion", job.verification_prompt, kind="prompt"),
                _web_section("Evidencia web y EduQG", verif),
                _text_section("Reporte del verificador", job.verification_output, kind="code"),
            ],
        )

    corr_traces = job.correction_trace or []
    if corr_traces or job.corrected_output:
        applied = [entry for entry in corr_traces if entry.get("applied")]
        ignored = [entry for entry in corr_traces if not entry.get("applied")]
        details["corrections"] = _stage_detail(
            f"Correcciones aplicadas ({len(applied)})",
            f"{len(applied)} cambios aplicados, {len(ignored)} observaciones sin cambio.",
            [
                _diff_section("MINI generado / MINI final", job.toon_output, job.corrected_output, corr_traces),
                _json_section("Correcciones aplicadas", applied),
                _json_section("Observaciones ignoradas", ignored),
            ],
        )

    if job.corrected_output or job.toon_output:
        details["final"] = _stage_detail(
            "MINI final listo para estudiar",
            "Banco que alimenta quiz adaptativo, flashcards, mapa y ejercicios.",
            [_text_section("MINI final", job.corrected_output or job.toon_output, kind="mini")],
        )

    for stage in stages:
        stage["detail_key"] = _detail_key_for_stage(stage, details)

    return details


def _stage_detail(title: str, summary: str, sections: list[dict]) -> dict:
    return {
        "title": title,
        "summary": summary,
        "sections": [
            section for section in sections
            if section.get("content") or section.get("kind") in {"web", "diff", "json"}
        ],
    }


def _text_section(label: str, content: str, kind: str = "text") -> dict:
    content = content or ""
    return {
        "label": label,
        "kind": kind,
        "content": content,
        "stats": _content_stats(content, is_mini=kind == "mini"),
    }


def _json_section(label: str, value) -> dict:
    return {
        "label": label,
        "kind": "json",
        "content": json.dumps(value or [], ensure_ascii=False, indent=2),
        "stats": [{"label": "entradas", "value": len(value or []) if isinstance(value, list) else len(value or {})}],
    }


def _diff_section(label: str, before: str, after: str, changes) -> dict:
    return {
        "label": label,
        "kind": "diff",
        "content": after or before or "",
        "before": before or "",
        "after": after or "",
        "changes": changes or [],
        "stats": [
            {"label": "antes", "value": f"{len(before or '')} chars"},
            {"label": "despues", "value": f"{len(after or '')} chars"},
            {"label": "cambios", "value": len(changes or [])},
        ],
    }


def _web_section(label: str, trace: dict) -> dict:
    web = (trace or {}).get("web", {})
    eduqg = (trace or {}).get("eduqg", {})
    queries = web.get("queries", [])
    configured = web.get("configured_sources", [])
    matches = eduqg.get("matches", [])
    return {
        "label": label,
        "kind": "web",
        "content": "web",
        "mode": (trace or {}).get("mode", ""),
        "search_provider": web.get("search_provider", ""),
        "academic_search": web.get("academic_search", {}),
        "query_generation": web.get("query_generation", {}),
        "queries": queries,
        "configured_sources": configured,
        "eduqg_matches": matches,
        "stats": [
            {"label": "queries", "value": len(queries)},
            {"label": "fuentes", "value": len(configured) + sum(len(q.get("results", [])) for q in queries)},
            {"label": "EduQG", "value": len(matches)},
        ],
    }


def _content_stats(content: str, is_mini: bool = False) -> list[dict]:
    stats = [
        {"label": "chars", "value": len(content or "")},
        {"label": "lineas", "value": len((content or "").splitlines())},
    ]
    if is_mini:
        stats.append({"label": "items", "value": _count_view_mini_items(content)})
    return stats


def _count_view_mini_items(content: str) -> int:
    try:
        return len(parse_mini(content or "").items)
    except Exception:
        return 0


def _detail_key_for_stage(stage: dict, details: dict) -> str:
    name = (stage.get("name") or "").lower()
    if "preparando contenido" in name:
        return "source" if "source" in details else ""
    if "transcribiendo audio" in name:
        return "transcript" if "transcript" in details else ""
    if "transcripcion" in name and "transcript_repair_0" in details:
        return "transcript_repair_0"
    if "generando items" in name or "mini parseado" in name or "relleno mini" in name:
        return "generation" if "generation" in details else ""
    if "coherencia" in name:
        return "coherence_0" if "coherence_0" in details else ("generation" if "generation" in details else "")
    if "verificando" in name or "verificacion" in name:
        return "verification" if "verification" in details else ""
    if "aplicando correcciones" in name:
        return "corrections" if "corrections" in details else ""
    if "final" in name or "listo" in name:
        return "final" if "final" in details else ""
    return ""


def _parse_pipeline_stages(job):
    """Parsea processing_log en lista de etapas estructuradas."""
    import re
    log_text = (job.processing_log or "").strip()
    if not log_text:
        return []

    # Patron: [HH:MM:SS] Etapa - Detalle
    # O: Etapa - Detalle (sin timestamp)
    pattern = re.compile(r"^(?:\[(\d{2}:\d{2}:\d{2})\]\s+)?(.+?)(?:\s+-\s+(.*))?$", re.MULTILINE)

    stages = []
    stage_map = {
        "en cola": {"icon": "queue", "type": "queue", "color": "#6c757d"},
        "preparando contenido": {"icon": "doc", "type": "prep", "color": "#495057"},
        "transcribiendo audio": {"icon": "mic", "type": "whisper", "color": "#0d6efd"},
        "audio temporal eliminado": {"icon": "trash", "type": "cleanup", "color": "#6c757d"},
        "corrigiendo transcripcion": {"icon": "brain", "type": "ai", "color": "#6610f2"},
        "transcripcion local revisada": {"icon": "check", "type": "success", "color": "#198754"},
        "transcripcion revisada": {"icon": "check", "type": "success", "color": "#198754"},
        "generando items": {"icon": "brain", "type": "ai", "color": "#6610f2"},
        "mini parseado": {"icon": "code", "type": "parse", "color": "#0dcaf0"},
        "recuperando items incoherentes": {"icon": "wrench", "type": "recovery", "color": "#fd7e14"},
        "recuperacion mini": {"icon": "check-wrench", "type": "recovery", "color": "#fd7e14"},
        "opciones no uniformes detectadas": {"icon": "alert", "type": "warning", "color": "#ffc107"},
        "opciones reparadas": {"icon": "wrench", "type": "recovery", "color": "#fd7e14"},
        "reparacion de opciones fallida": {"icon": "alert", "type": "error", "color": "#dc3545"},
        "revisando coherencia": {"icon": "brain", "type": "ai", "color": "#6610f2"},
        "coherencia mini revisada": {"icon": "check", "type": "success", "color": "#198754"},
        "relleno mini": {"icon": "plus", "type": "fill", "color": "#20c997"},
        "generando items de relleno": {"icon": "plus", "type": "fill", "color": "#20c997"},
        "verificando con fuentes": {"icon": "globe", "type": "verify", "color": "#0d6efd"},
        "verificacion recibida": {"icon": "check-globe", "type": "verify", "color": "#0d6efd"},
        "aplicando correcciones": {"icon": "pencil", "type": "correct", "color": "#6f42c1"},
        "mini final parseado": {"icon": "flag", "type": "done", "color": "#198754"},
        "listo": {"icon": "flag", "type": "done", "color": "#198754"},
        "error": {"icon": "alert", "type": "error", "color": "#dc3545"},
        "pipeline reiniciado": {"icon": "refresh", "type": "warning", "color": "#ffc107"},
    }

    for line in log_text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            timestamp = match.group(1) or ""
            stage_name = (match.group(2) or "").strip()
            detail = (match.group(3) or "").strip()
        else:
            timestamp = ""
            stage_name = line
            detail = ""

        # Buscar en stage_map (case-insensitive partial match)
        meta = {"icon": "circle", "type": "generic", "color": "#6c757d"}
        stage_lower = stage_name.lower()
        for key, value in stage_map.items():
            if key in stage_lower:
                meta = value
                break

        stages.append({
            "timestamp": timestamp,
            "name": stage_name,
            "detail": detail,
            "icon": meta["icon"],
            "type": meta["type"],
            "color": meta["color"],
        })

    return stages


def _extract_pipeline_metrics(job):
    """Extrae metricas clave del pipeline para el panel lateral."""
    metrics = {
        "word_count": len((job.source_text or job.transcript or "").split()),
        "target_items": max(50, len((job.source_text or job.transcript or "").split()) // 50),
        "final_items": 0,
        "recovered_items": 0,
        "web_sources": 0,
        "eduqg_matches": 0,
        "corrections_applied": 0,
        "backend": job.ai_backend or "auto",
        "verification_mode": job.get_verification_mode_display(),
        "duration_seconds": 0,
    }

    # Contar items finales
    mini_text = job.corrected_output or job.toon_output
    if mini_text:
        try:
            assessment = parse_mini(mini_text)
            metrics["final_items"] = len(assessment.items)
        except Exception:
            pass

    # Contar fuentes web
    verif_trace = job.verification_trace or {}
    web = verif_trace.get("web", {})
    metrics["web_sources"] = len(web.get("configured_sources", [])) + sum(
        len(q.get("results", [])) for q in web.get("queries", [])
    )
    metrics["eduqg_matches"] = len((verif_trace.get("eduqg") or {}).get("matches", []))

    # Contar correcciones aplicadas
    corr_trace = job.correction_trace or []
    metrics["corrections_applied"] = sum(1 for c in corr_trace if c.get("applied"))

    # Contar items recuperados de incoherentes
    # Estimacion: contar cuantos items tenia toon_output vs corrected_output
    if job.toon_output and job.corrected_output:
        try:
            toon_assessment = parse_mini(job.toon_output)
            corrected_assessment = parse_mini(job.corrected_output)
            # Si corrected tiene mas items, asumimos recuperacion
            if len(corrected_assessment.items) > len(toon_assessment.items):
                metrics["recovered_items"] = len(corrected_assessment.items) - len(toon_assessment.items)
        except Exception:
            pass

    # Duracion estimada desde created_at hasta updated_at
    if job.created_at and job.updated_at:
        metrics["duration_seconds"] = int((job.updated_at - job.created_at).total_seconds())

    return metrics


# ══════════════════════════════════════════════════════════════════
# PRACTICA ADAPTATIVA POR CURSO
# ══════════════════════════════════════════════════════════════════

@login_required
def practice_start(request, pk):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    try:
        session = adaptive.start_practice(
            request.user,
            course,
            target_count=request.POST.get("target_count", 10),
            focus=request.POST.get("focus", "balanced"),
        )
    except adaptive.NoItemsError:
        messages.warning(request, "Este curso aun no tiene preguntas listas. Sube una clase y espera a que termine de procesarse.")
        return redirect("course_detail", pk=course.pk)
    return redirect("practice_session", pk=course.pk, session_id=session.pk)


@login_required
def practice_session(request, pk, session_id):
    course = get_object_or_404(Course, pk=pk, user=request.user)
    session = get_object_or_404(adaptive.PracticeSession, pk=session_id, course=course, user=request.user)
    return render(request, "learning/practice_session.html", adaptive.session_context(session))


@login_required
def practice_answer(request, pk, session_id):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user)
    session = get_object_or_404(adaptive.PracticeSession, pk=session_id, course=course, user=request.user)
    if not session.is_complete:
        try:
            adaptive.answer_question(session, int(request.POST.get("question_id", 0)), request.POST.get("option_id"))
        except (ValueError, adaptive.Question.DoesNotExist):
            messages.info(request, "Esa pregunta ya no esta activa; continua con la siguiente.")
    return redirect("practice_session", pk=course.pk, session_id=session.pk)


@login_required
def recommendation_update(request, pk, rec_id):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user)
    rec = get_object_or_404(adaptive.Recommendation, pk=rec_id, course=course, user=request.user)
    try:
        adaptive.complete_recommendation(rec, request.POST.get("status", "completed"))
    except ValueError:
        raise Http404()
    return redirect("course_detail", pk=course.pk)


# ══════════════════════════════════════════════════════════════════
# REFUERZO ADAPTATIVO (generacion dirigida al perfil)
# ══════════════════════════════════════════════════════════════════

@login_required
def reinforcement_start(request, pk):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    practice_session = None
    if request.POST.get("practice_session"):
        practice_session = adaptive.PracticeSession.objects.filter(
            pk=request.POST.get("practice_session"), user=request.user, course=course
        ).first()
    topics = [t.strip() for t in request.POST.getlist("topic") if t.strip()]
    try:
        job = adaptive_generation.create_reinforcement_job(
            request.user, course, practice_session=practice_session, topics=topics,
            requested_items=request.POST.get("items", adaptive_generation.DEFAULT_ITEMS),
        )
    except adaptive_generation.ReinforcementUnavailable as exc:
        messages.warning(request, str(exc))
        return redirect("course_detail", pk=course.pk)
    except RuntimeError as exc:  # cola llena
        messages.warning(request, str(exc))
        return redirect("course_detail", pk=course.pk)
    return redirect("reinforcement_detail", pk=course.pk, job_id=job.pk)


@login_required
def reinforcement_detail(request, pk, job_id):
    course = get_object_or_404(Course, pk=pk, user=request.user)
    job = get_object_or_404(adaptive.ReinforcementJob, pk=job_id, course=course, user=request.user)
    summaries = list(adaptive.Summary.objects.filter(pk__in=job.summary_ids or []))
    flashcards_url = ""
    if job.quiz_id and job.quiz.class_session_id and job.quiz.class_session.legacy_lesson_job_id:
        flashcards_url = reverse("flashcards", args=[job.quiz.class_session.legacy_lesson_job_id])
    return render(request, "learning/reinforcement_detail.html", {
        "course": course,
        "job": job,
        "summaries": summaries,
        "question_count": job.quiz.questions.count() if job.quiz_id else 0,
        "flashcards_url": flashcards_url,
    })
