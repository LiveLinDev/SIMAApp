from __future__ import annotations

import logging
import threading
from queue import Full, Queue

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .models import ClassSession, LessonJob, Profile, Transcript
from .parse_mini import (
    apply_corrections_with_trace,
    filter_incoherent_items,
    filter_nonuniform_items,
    merge_mini_chunks,
    normalize_mini_text,
    validate_mini_parse,
)
from .services import (
    LocalAITimeoutError,
    call_ai,
    chunk_content,
    clean_ai_error,
    count_mini_items,
    extract_mini_lines,
    generate_items,
    generation_chunk_plan,
    mini_item_change_summary,
    repair_incoherent_mini,
    repair_mini_coherence,
    repair_option_uniformity,
    repair_transcript_text,
    resolve_backend,
    strip_non_academic_content_noise,
    text_change_summary,
    transcribe_audio,
    use_direct_cloud_mini,
    verify_items,
)


logger = logging.getLogger(__name__)
_queue = Queue(maxsize=getattr(settings, "LOCAL_TASK_QUEUE_MAXSIZE", 20))
_lock = threading.Lock()
_queued_ids = set()
_workers_started = 0


def enqueue_lesson_job(job_id: int, backend: str = "auto"):
    ensure_worker()
    with _lock:
        if job_id in _queued_ids:
            return
        try:
            _queue.put_nowait((job_id, backend))
        except Full as exc:
            raise RuntimeError("La cola local esta llena. Espera a que termine una clase antes de agregar otra.") from exc
        _queued_ids.add(job_id)


def ensure_worker():
    global _workers_started
    with _lock:
        target_workers = max(1, int(getattr(settings, "LOCAL_TASK_WORKERS", 1)))
        while _workers_started < target_workers:
            worker = threading.Thread(
                target=_worker_loop,
                name=f"sima-local-ai-worker-{_workers_started + 1}",
                daemon=True,
            )
            worker.start()
            _workers_started += 1


def _worker_loop():
    while True:
        job_id, backend = _queue.get()
        try:
            close_old_connections()
            process_lesson_job(job_id, backend)
        except Exception:
            logger.exception("Error procesando LessonJob %s", job_id)
        finally:
            with _lock:
                _queued_ids.discard(job_id)
            close_old_connections()
            _queue.task_done()


def process_lesson_job(job_id: int, backend: str = "auto"):
    job = LessonJob.objects.select_related("user").get(pk=job_id)
    try:
        requested_backend = resolve_backend(backend)
        _set_stage(job, "Preparando contenido", "Leyendo texto, audio y configuracion del trabajo.")

        if job.audio:
            _set_stage(job, "Transcribiendo audio con Whisper", f"Archivo: {job.audio.name}. Whisper corre localmente.")
            if not job.transcript:
                job.transcript = transcribe_audio(job.audio.path)
                job.save(update_fields=["transcript", "updated_at"])
                _sync_transcript_record(job)
            _discard_processed_audio(job)

        if requested_backend == "local":
            _auto_repair_transcript(job)

        raw_content = _job_content_for_generation(job)
        content = strip_non_academic_content_noise(raw_content)
        if content != raw_content:
            job.processing_log = _append_log(
                job.processing_log,
                "Ruido no academico filtrado",
                f"{len(raw_content.split())} -> {len(content.split())} palabras antes de generar MINI.",
            )
            job.save(update_fields=["processing_log", "updated_at"])

        if not content:
            raise RuntimeError("Agrega texto o sube un audio para transcribir.")

        word_count = len(content.split())
        configured_items = getattr(settings, "LOCAL_ITEMS_REQUESTED", "auto")
        chunks, budgets, planned_items = generation_chunk_plan(
            content,
            requested_backend,
            items_requested=configured_items,
        )
        _set_stage(
            job,
            "Generando items con IA",
            (
                f"Backend: {requested_backend}. {word_count} palabras -> objetivo {planned_items} items "
                f"en {len(chunks)} llamadas ({', '.join(str(value) for value in budgets)})."
            ),
        )

        def _progress_callback(done_index: int, total_chunks: int, partial_mini: str):
            partial_count = count_mini_items(partial_mini)
            job.processing_log = _append_log(
                job.processing_log,
                f"Chunk {done_index}/{total_chunks} completado",
                f"{partial_count} items generados hasta ahora; reiniciando contexto para el siguiente chunk.",
            )
            job.save(update_fields=["processing_log", "updated_at"])

        generation_prompt, toon_output, resolved_backend = generate_items(
            content,
            backend=requested_backend,
            progress_callback=_progress_callback,
        )
        toon_output, item_count, incoherent_mini = _compile_mini_for_render(toon_output, "Generacion MINI")

        # Recuperar items incoherentes (enunciados sin ? ni ____)
        if incoherent_mini:
            toon_output = _recover_incoherent_items(job, toon_output, incoherent_mini, resolved_backend)
            toon_output, item_count, _ = _compile_mini_for_render(toon_output, "Recuperacion MINI")

        # Recuperar items con opciones malformadas (fusionadas por comas, sesgo de longitud)
        uniform_mini, bad_opts_log, bad_opts_mini = filter_nonuniform_items(toon_output)
        if bad_opts_mini:
            job.processing_log = _append_log(
                job.processing_log,
                "Opciones no uniformes detectadas",
                f"{len(bad_opts_log)} items con opciones malformadas.",
            )
            toon_output = _recover_nonuniform_items(job, uniform_mini, bad_opts_mini, resolved_backend)
            toon_output, item_count, _ = _compile_mini_for_render(toon_output, "Uniformidad MINI")

        job.generation_prompt = generation_prompt
        job.toon_output = toon_output
        job.ai_backend = resolved_backend
        job.processing_log = _append_log(job.processing_log, "MINI parseado", f"{item_count} items listos para renderizar.")
        job.save(update_fields=["generation_prompt", "toon_output", "ai_backend", "processing_log", "updated_at"])

        if resolved_backend == "local":
            _auto_repair_mini_coherence(job)

        # Generar items de relleno si el conteo es bajo para IRT
        toon_output = _fill_items_if_needed(job, toon_output, content, item_count, planned_items, resolved_backend)
        if toon_output != job.toon_output:
            job.toon_output = toon_output
            toon_output, item_count, _ = _compile_mini_for_render(toon_output, "Relleno MINI")
            job.processing_log = _append_log(job.processing_log, "Relleno MINI", f"{item_count} items tras generacion de relleno.")
            job.save(update_fields=["toon_output", "processing_log", "updated_at"])

        if use_direct_cloud_mini(resolved_backend):
            _set_stage(
                job,
                "Validando MINI cloud",
                "DeepSeek genera MINI directo; se aplican filtros deterministas finales.",
            )
            job.verification_prompt = ""
            job.verification_trace = {"backend": resolved_backend, "mode": "deepseek_direct_mini"}
            job.corrected_output, corrected_count = _finalize_mini_quality(job, job.toon_output, "MINI cloud final")
            job.verification_output = (
                f"v|d={timezone.localdate().strftime('%Y%m%d')}|n={corrected_count}|e=0|s=VERIFICADO"
            )
            job.correction_trace = []
        else:
            verification_mode = _normalize_verification_mode(job.verification_mode)
            _set_stage(job, _verification_stage_label(verification_mode), f"Modo de verificacion: {verification_mode}.")
            verification_prompt, verification_output, _backend, verification_trace = verify_items(
                job.toon_output,
                backend=resolved_backend,
                verification_mode=verification_mode,
            )
            job.verification_prompt = _strip_nul(verification_prompt)
            job.verification_output = _strip_nul(verification_output)
            job.verification_trace = _strip_nul(verification_trace)
            _set_stage(
                job,
                "Verificacion recibida",
                f"Fuentes web: {_count_web_sources(verification_trace)}. EduQG matches: {_count_eduqg_matches(verification_trace)}.",
            )
            _set_stage(job, "Aplicando correcciones", "Interpretando el reporte y generando la version final.")
            corrected_output, correction_trace = apply_corrections_with_trace(job.toon_output, verification_output)
            job.corrected_output = _strip_nul(corrected_output)
            job.correction_trace = _strip_nul(correction_trace)
            job.corrected_output, corrected_count = _finalize_mini_quality(job, job.corrected_output, "Correccion MINI")
        job.error = ""
        job.status = LessonJob.Status.CORRECTED
        job.processing_stage = "Listo"
        job.processing_log = _append_log(job.processing_log, "MINI final parseado", f"{corrected_count} items listos para estudiar.")
        job.processing_log = _append_log(job.processing_log, "Listo", "Clase verificada y corregida.")
        _count_api_usage(job)
        job.save(update_fields=[
            "verification_prompt",
            "verification_output",
            "verification_trace",
            "corrected_output",
            "correction_trace",
            "error",
            "status",
            "processing_stage",
            "processing_log",
            "api_usage_counted",
            "updated_at",
        ])
        _sync_class_session_status(job)
        _sync_transcript_record(job)
    except Exception as exc:
        job.error = clean_ai_error(exc)
        job.status = LessonJob.Status.ERROR
        job.processing_stage = "Error"
        job.processing_log = _append_log(job.processing_log, "Error", job.error)
        job.save(update_fields=["error", "status", "processing_stage", "processing_log", "updated_at"])
        _sync_class_session_status(job)


def _strip_nul(value):
    """Elimina caracteres NUL de strings, listas y dicts para evitar errores de PostgreSQL."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nul(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_nul(val) for key, val in value.items()}
    return value


def _set_stage(job: LessonJob, stage: str, detail: str = ""):
    job.status = LessonJob.Status.PROCESSING
    job.processing_stage = stage
    job.processing_log = _append_log(job.processing_log, stage, detail)
    job.error = ""
    job.save(update_fields=["status", "processing_stage", "processing_log", "error", "updated_at"])


def _append_log(current: str, stage: str, detail: str = "") -> str:
    stamp = timezone.localtime().strftime("%H:%M:%S")
    line = f"[{stamp}] {stage}"
    if detail:
        line = f"{line} - {detail}"
    return "\n".join(part for part in [current.strip(), line] if part)


def _compile_mini_for_render(mini_text: str, stage: str) -> tuple[str, int, str]:
    mini_block = extract_mini_lines(mini_text) or mini_text
    filtered, dropped, incoherent_mini = filter_incoherent_items(mini_block)
    if dropped:
        logger.info("[%s] Items incoherentes detectados: %s", stage, dropped)
    normalized = normalize_mini_text(filtered, stage=stage)
    assessment = validate_mini_parse(normalized, stage=stage)
    return normalized, len(assessment.items), incoherent_mini


def _finalize_mini_quality(job: LessonJob, mini_text: str, stage: str) -> tuple[str, int]:
    normalized, _count, _ = _compile_mini_for_render(mini_text, stage)
    uniform, dropped, _bad_mini = filter_nonuniform_items(normalized)
    if dropped:
        job.processing_log = _append_log(
            job.processing_log,
            "Filtro final de calidad MINI",
            f"Se descartaron {len(dropped)} items meta, publicitarios o semanticamente inconsistentes.",
        )
        job.save(update_fields=["processing_log", "updated_at"])
        normalized, _count, _ = _compile_mini_for_render(uniform, f"{stage} filtrado")
    return normalized, _count


def _discard_processed_audio(job: LessonJob):
    if not job.audio:
        return

    audio_name = job.audio.name
    try:
        storage = job.audio.storage
        if storage.exists(audio_name):
            storage.delete(audio_name)
        job.audio = ""
        job.processing_log = _append_log(
            job.processing_log,
            "Audio temporal eliminado",
            "La transcripcion ya quedo guardada; el archivo no se conserva en media.",
        )
        job.save(update_fields=["audio", "processing_log", "updated_at"])
    except Exception as exc:
        logger.warning("No se pudo eliminar el audio temporal de LessonJob %s: %s", job.pk, exc)
        job.processing_log = _append_log(
            job.processing_log,
            "Aviso",
            "No se pudo eliminar el audio temporal automaticamente.",
        )
        job.save(update_fields=["processing_log", "updated_at"])


def _job_content_for_generation(job: LessonJob) -> str:
    parts = []
    source_text = (job.source_text or "").strip()
    transcript = (job.transcript or "").strip()
    if source_text:
        parts.append(source_text)
    if transcript:
        parts.append(f"TRANSCRIPCION:\n{transcript}")
    return "\n\n".join(parts).strip()


def _job_context_for_ai(job: LessonJob, include_mini: bool = False, include_transcript: bool = True) -> str:
    parts = [f"TITULO: {job.title}"]
    if job.tags:
        parts.append(f"ETIQUETAS: {job.tags}")
    if job.source_text.strip():
        parts.append(f"TEXTO_ORIGINAL:\n{job.source_text.strip()}")
    if include_transcript and job.transcript.strip():
        parts.append(f"TRANSCRIPCION:\n{job.transcript.strip()}")
    if include_mini and job.toon_output.strip():
        parts.append(f"MINI_GENERADO:\n{job.toon_output.strip()}")
    return "\n\n".join(parts)


def _auto_repair_transcript(job: LessonJob):
    if not (job.transcript or "").strip():
        return

    before = job.transcript
    source_context = _job_context_for_ai(job, include_transcript=False)
    chunk_words = max(100, int(getattr(settings, "LOCAL_TRANSCRIPT_REPAIR_CHUNK_WORDS", 500)))
    words = len(before.split())
    chunks = [before] if words <= chunk_words else chunk_content(before, max_words=chunk_words)

    if len(chunks) == 1:
        _set_stage(
            job,
            "Corrigiendo transcripcion con IA local",
            "Qwen revisa errores tipo palabras mal oidas antes de generar items.",
        )
    else:
        _set_stage(
            job,
            "Corrigiendo transcripcion con IA local",
            f"Transcripcion de {words} palabras. Se corrige por partes de ~{chunk_words} palabras ({len(chunks)} partes).",
        )

    repaired_parts = []
    total_prompt_chars = 0
    total_output_chars = 0
    any_timeout = False
    for idx, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            _set_stage(
                job,
                "Corrigiendo transcripcion con IA local",
                f"Parte {idx}/{len(chunks)} - {len(chunk.split())} palabras.",
            )
        try:
            prompt, repaired_chunk, backend, trace = repair_transcript_text(
                chunk,
                source_context=source_context,
                backend="local",
            )
            repaired_parts.append(repaired_chunk)
            total_prompt_chars += trace.get("prompt_chars", 0)
            total_output_chars += trace.get("output_chars", 0)
        except LocalAITimeoutError:
            any_timeout = True
            logger.warning("Timeout corrigiendo chunk %s/%s de la transcripcion del job %s", idx, len(chunks), job.pk)
            repaired_parts.append(chunk)
            job.processing_log = _append_log(
                job.processing_log,
                f"Timeout en correccion parte {idx}/{len(chunks)}",
                "Se conserva el texto original de esta parte para continuar el pipeline.",
            )
            job.save(update_fields=["processing_log", "updated_at"])
        except Exception as exc:
            logger.warning("Error corrigiendo chunk %s/%s de la transcripcion del job %s: %s", idx, len(chunks), job.pk, exc)
            repaired_parts.append(chunk)
            job.processing_log = _append_log(
                job.processing_log,
                f"Error en correccion parte {idx}/{len(chunks)}",
                f"{clean_ai_error(exc)}. Se conserva el texto original de esta parte.",
            )
            job.save(update_fields=["processing_log", "updated_at"])

    repaired = "\n\n".join(repaired_parts)
    changed = repaired.strip() != before.strip()
    trace = {
        "backend": "local",
        "prompt_chars": total_prompt_chars,
        "output_chars": total_output_chars,
        "changed": changed,
        "chunks": len(chunks),
        "timeout": any_timeout,
    }
    job.transcript_repair_prompt = ""
    job.transcript_repair_trace = [
        *_safe_trace_list(job.transcript_repair_trace),
        _transcript_repair_entry(before, repaired, trace, "local", "pipeline local previo a generacion"),
    ][-8:]
    if changed:
        job.transcript = repaired
    detail = (
        f"Se aplicaron cambios antes de generar items. {len(chunks)} parte(s) procesada(s)."
        if changed else
        f"No se detectaron cambios necesarios. {len(chunks)} parte(s) procesada(s)."
    )
    if any_timeout:
        detail += " Algunas partes no se corrigieron por timeout."
    job.processing_log = _append_log(
        job.processing_log,
        "Transcripcion local revisada",
        detail,
    )
    job.save(update_fields=[
        "transcript",
        "transcript_repair_prompt",
        "transcript_repair_trace",
        "processing_log",
        "updated_at",
    ])


def _auto_repair_mini_coherence(job: LessonJob):
    if not (job.toon_output or "").strip():
        return

    before = job.toon_output
    item_count = count_mini_items(before)
    max_items = max(0, int(getattr(settings, "LOCAL_COHERENCE_MAX_ITEMS", 60)))
    if max_items and item_count > max_items:
        job.processing_log = _append_log(
            job.processing_log,
            "Coherencia MINI por lotes",
            (
                f"Banco grande ({item_count} items). Se evita una llamada monolitica local; "
                "la verificacion final revisara el banco completo."
            ),
        )
        job.save(update_fields=["processing_log", "updated_at"])
        return

    _set_stage(
        job,
        "Revisando coherencia de items con IA local",
        "Qwen revisa si cada pregunta tiene sentido antes de verificar y guardar.",
    )
    try:
        prompt, repaired, backend, trace = repair_mini_coherence(
            before,
            source_context=_job_context_for_ai(job),
            backend="local",
        )
    except Exception as exc:
        job.processing_log = _append_log(
            job.processing_log,
            "Coherencia MINI no aplicada",
            f"{clean_ai_error(exc)}. Se conserva el MINI parseable y filtrado.",
        )
        job.save(update_fields=["processing_log", "updated_at"])
        return
    repaired, item_count, _ = _compile_mini_for_render(repaired, "Coherencia MINI")
    changed = bool(trace.get("changed")) or repaired.strip() != before.strip()
    job.mini_coherence_prompt = prompt
    job.mini_coherence_trace = [
        *_safe_trace_list(job.mini_coherence_trace),
        _mini_coherence_entry(before, repaired, trace, backend),
    ][-8:]
    if changed:
        job.toon_output = repaired
    job.processing_log = _append_log(
        job.processing_log,
        "Coherencia MINI revisada",
        (
            f"Se repararon items incoherentes. {item_count} items renderizables."
            if changed else
            f"Todos los items pasaron la revision de sentido. {item_count} items renderizables."
        ),
    )
    job.save(update_fields=[
        "toon_output",
        "mini_coherence_prompt",
        "mini_coherence_trace",
        "processing_log",
        "updated_at",
    ])


def _safe_trace_list(value) -> list:
    return value if isinstance(value, list) else []


def _recover_nonuniform_items(job: LessonJob, uniform_mini: str, bad_opts_mini: str, backend: str) -> str:
    """
    Repara items con opciones malformadas y los mergea de vuelta al MINI principal.
    """
    try:
        _set_stage(job, "Reparando opciones malformadas", f"{count_mini_items(bad_opts_mini)} items a reparar.")
        prompt, repaired, _backend, trace = repair_option_uniformity(
            bad_opts_mini,
            source_context=_job_context_for_ai(job),
            backend=backend,
        )
        if repaired and repaired.strip():
            combined = merge_mini_chunks([uniform_mini, repaired])
            job.processing_log = _append_log(
                job.processing_log,
                "Opciones reparadas",
                f"Reparados {count_mini_items(repaired)} items con opciones malformadas. "
                f"Trace: {trace.get('note', 'OK')}.",
            )
            return combined
    except Exception as exc:
        job.processing_log = _append_log(
            job.processing_log,
            "Reparacion de opciones fallida",
            f"Error reparando opciones: {clean_ai_error(exc)}",
        )
    return uniform_mini


def _recover_incoherent_items(job: LessonJob, coherent_mini: str, incoherent_mini: str, backend: str) -> str:
    """
    Repara items incoherentes y los mergea de vuelta al MINI principal.
    Retorna el MINI combinado.
    """
    try:
        _set_stage(job, "Recuperando items incoherentes", f"{count_mini_items(incoherent_mini)} items a reparar.")
        prompt, repaired, _backend, trace = repair_incoherent_mini(
            incoherent_mini,
            source_context=_job_context_for_ai(job),
            backend=backend,
        )
        if repaired and repaired.strip():
            combined = merge_mini_chunks([coherent_mini, repaired])
            job.processing_log = _append_log(
                job.processing_log,
                "Recuperacion MINI",
                f"Reparados {count_mini_items(repaired)} items incoherentes. "
                f"Trace: {trace.get('note', 'OK')}.",
            )
            return combined
    except Exception as exc:
        job.processing_log = _append_log(
            job.processing_log,
            "Recuperacion MINI fallida",
            f"Error reparando items incoherentes: {clean_ai_error(exc)}",
        )
    return coherent_mini


def _fill_items_if_needed(
    job: LessonJob,
    current_mini: str,
    source_content: str,
    current_count: int,
    planned_count: int,
    backend: str,
) -> str:
    """
    Genera items de relleno si el conteo actual es significativamente menor al objetivo.
    Umbral: menos del 80% del objetivo planificado.
    """
    if current_count >= planned_count * 0.8:
        return current_mini

    needed = planned_count - current_count
    needed = min(needed, 15)  # max 15 items por llamada de relleno para evitar timeout
    if needed <= 0:
        return current_mini

    try:
        _set_stage(job, "Generando items de relleno", f"Objetivo: {planned_count}, actual: {current_count}, faltan: {needed}.")
        fill_prompt = (
            f"Genera exactamente {needed} items MINI adicionales sobre el siguiente contenido. "
            f"Cada item debe ser una pregunta con ? o una completacion con ____. "
            f"Ignora publicidad, sponsors, intro/outro, canal, narrador, likes, comentarios y referencias al video o la clase. "
            f"No preguntes por la importancia del video ni por acciones sugeridas al final. "
            f"Distribuye las respuestas correctas entre A, B, C, D. "
            f"Varia los niveles Bloom (L1-L6).\n\n"
            f"CONTENIDO:\n{source_content[:4000]}\n\n"
            f"Responde SOLO con el bloque MINI (cabecera a| + items iN|)."
        )
        raw_output = call_ai(fill_prompt, backend=backend, role="generation")
        fill_mini = extract_mini_lines(raw_output)
        if fill_mini:
            combined = merge_mini_chunks([current_mini, fill_mini])
            return combined
    except Exception as exc:
        job.processing_log = _append_log(
            job.processing_log,
            "Relleno MINI fallido",
            f"Error generando items de relleno: {clean_ai_error(exc)}",
        )
    return current_mini


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
        "changes": text_change_summary(before, after),
    }


def _mini_coherence_entry(before: str, after: str, trace: dict, backend: str) -> dict:
    return {
        "created_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"),
        "backend": backend,
        "changed": bool(trace.get("changed")),
        "prompt_chars": trace.get("prompt_chars", 0),
        "output_chars": trace.get("output_chars", 0),
        "before": before,
        "after": after,
        "changes": mini_item_change_summary(before, after),
    }


def _normalize_verification_mode(mode: str) -> str:
    if mode in {"web", "eduqg", "hybrid"}:
        return mode
    default = getattr(settings, "VERIFICATION_DEFAULT_MODE", "web")
    return default if default in {"web", "eduqg", "hybrid"} else "web"


def _verification_stage_label(mode: str) -> str:
    if mode == "eduqg":
        return "Verificando con EduQG local"
    if mode == "hybrid":
        return "Verificando con fuentes web y EduQG"
    return "Verificando con fuentes web"


def _count_web_sources(trace: dict) -> int:
    web = (trace or {}).get("web", {})
    configured = len(web.get("configured_sources", []))
    query_sources = sum(len(query.get("results", [])) for query in web.get("queries", []))
    return configured + query_sources


def _count_eduqg_matches(trace: dict) -> int:
    return len(((trace or {}).get("eduqg") or {}).get("matches", []))


def _count_api_usage(job: LessonJob):
    if job.api_usage_counted:
        return
    profile, _ = Profile.objects.get_or_create(user=job.user)
    profile.api_classes_used += 1
    profile.save(update_fields=["api_classes_used", "updated_at"])
    job.api_usage_counted = True


def _sync_class_session_status(job: LessonJob) -> ClassSession | None:
    if not job.course_id:
        return None
    ready_statuses = {
        LessonJob.Status.PROMPT_READY,
        LessonJob.Status.TOON_READY,
        LessonJob.Status.VERIFIED,
        LessonJob.Status.CORRECTED,
    }
    status_map = {
        LessonJob.Status.DRAFT: ClassSession.ProcessingStatus.DRAFT,
        LessonJob.Status.QUEUED: ClassSession.ProcessingStatus.QUEUED,
        LessonJob.Status.PROCESSING: ClassSession.ProcessingStatus.PROCESSING,
        LessonJob.Status.ERROR: ClassSession.ProcessingStatus.ERROR,
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


def _sync_transcript_record(job: LessonJob):
    if not (job.course_id and job.transcript.strip()):
        return
    session = _sync_class_session_status(job)
    if not session:
        return
    Transcript.objects.update_or_create(
        class_session=session,
        defaults={
            "full_text": job.transcript,
            "source": Transcript.Source.WHISPER if job.audio or job.mode == LessonJob.Mode.API else Transcript.Source.MANUAL,
            "language": "es",
        },
    )
