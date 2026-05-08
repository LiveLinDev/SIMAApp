import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe

from .cat import BLOOM_LABELS, build_bank, choose_next_item, estimate_theta, option_index, parse_cat_params
from .credits import (
    REGENERATION_COST,
    consume_credits,
    estimate_lesson_job_cost,
    grant_plan_credits,
    has_enough_credits,
)
from .forms import ApiLessonForm, CourseForm, FreeLessonForm, ManualResultForm, PlanForm, RegisterForm, VerificationResultForm
from .job_queue import enqueue_lesson_job
from .models import ClassSession, Course, LessonJob, PLAN_DETAILS, Plan, QuizAttempt, QuizResponse
from .parse_mini import apply_corrections_with_trace, assessment_to_dict, normalize_mini_text, parse_mini, render_mini_html, validate_mini_parse
from .services import (
    build_generation_prompt,
    build_verification_prompt,
    clean_ai_error,
    extract_mini_lines,
    get_available_backends,
    repair_mini_coherence,
    repair_transcript_text,
    text_change_summary,
)


def _get_or_create_profile(user):
    """Garantiza que el usuario siempre tenga un perfil, incluso si fue creado antes del signal."""
    from .models import Profile
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


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
    return render(request, "learning/home.html", {"plans": PLAN_DETAILS})


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
    courses = Course.objects.filter(user=request.user, is_archived=False).annotate(
        class_count=Count("legacy_lesson_jobs", filter=Q(legacy_lesson_jobs__user=request.user)),
    )
    jobs = LessonJob.objects.filter(user=request.user)[:8]
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
    active_tab = "explorar" if query or tag else "cursos"
    return render(request, "learning/dashboard.html", {
        "profile": profile,
        "courses": courses,
        "jobs": jobs,
        "public_jobs": public_jobs,
        "popular_tags": popular_tags,
        "active_tab": active_tab,
        "explore_query": query,
        "explore_tag": tag,
        "plans": PLAN_DETAILS,
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
    return render(request, "learning/course_detail.html", {
        "course": course,
        "jobs": jobs[:24],
        "stats": stats,
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
    return render(request, "learning/plans.html", {"form": form, "plans": PLAN_DETAILS, "profile": profile})


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
        backend = request.POST.get("backend", "auto")
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
        "local_model": getattr(settings, "LOCAL_MODEL", None) or getattr(settings, "ANTHROPIC_MODEL", "local"),
        "verification_default_mode": getattr(settings, "VERIFICATION_DEFAULT_MODE", "web"),
        "credit_estimate": estimate_lesson_job_cost(has_audio=True, has_text=True),
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

    return render(request, "learning/lesson_detail.html", {
        "job": job,
        "items_html": items_html,
        "item_count": item_count,
        "cat_params": cat_params,
        "bloom_stats": bloom_stats,
        "quiz_attempts": job.quiz_attempts.filter(user=request.user)[:8],
        "pipeline_step": pipeline_step,
        "pipeline_total": pipeline_total,
        "is_owner": job.user_id == request.user.id,
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
    if request.method != "POST":
        raise Http404()
    job = _get_accessible_job(request.user, pk)
    mini_text = job.corrected_output or job.toon_output
    items, params = build_bank(mini_text)
    if not items:
        messages.warning(request, "Esta clase aún no tiene ítems válidos para iniciar un quiz.")
        return redirect("lesson_detail", pk=job.pk)

    requested = int(request.POST.get("target_count", params["max_items"]))
    target_count = max(1, min(requested, len(items), params["max_items"]))
    attempt = QuizAttempt.objects.create(
        user=request.user,
        lesson=job,
        target_count=target_count,
        theta=params["theta_init"],
    )
    next_item = choose_next_item(items, [], attempt.theta, [], target_count)
    attempt.current_item_id = next_item.id
    attempt.selected_item_ids = [next_item.id]
    attempt.save()
    return redirect("quiz_attempt", pk=job.pk, attempt_id=attempt.pk)


@login_required
def quiz_attempt(request, pk, attempt_id):
    job = _get_accessible_job(request.user, pk)
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, lesson=job, user=request.user)
    mini_text = job.corrected_output or job.toon_output
    items, params = build_bank(mini_text)
    items_by_id = {item.id: item for item in items}
    current_item = items_by_id.get(attempt.current_item_id)
    responses = list(attempt.responses.all())
    progress_pct = min(100, round((len(responses) / max(attempt.target_count, 1)) * 100))
    bloom_counts = {}
    for response in responses:
        bloom_counts[response.item_bloom] = bloom_counts.get(response.item_bloom, 0) + 1
    bloom_progress = [
        {"level": level, "label": label, "count": bloom_counts.get(level, 0)}
        for level, label in BLOOM_LABELS.items()
        if bloom_counts.get(level, 0)
    ]

    return render(request, "learning/quiz_attempt.html", {
        "job": job,
        "attempt": attempt,
        "item": current_item,
        "item_bloom_label": BLOOM_LABELS.get(current_item.bloom, current_item.bloom) if current_item else "",
        "responses": responses,
        "progress_pct": progress_pct,
        "bloom_progress": bloom_progress,
        "bloom_labels": BLOOM_LABELS,
        "cat_params": params,
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

    backend = request.POST.get("backend", "auto")
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


def _compile_mini_for_render(mini_text: str, stage: str) -> tuple[str, int]:
    mini_block = extract_mini_lines(mini_text) or mini_text
    normalized = normalize_mini_text(mini_block, stage=stage)
    assessment = validate_mini_parse(normalized, stage=stage)
    return normalized, len(assessment.items)


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
