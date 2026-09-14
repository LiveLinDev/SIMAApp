"""
Cola de trabajos de SIMA: encolado (hilos o BD), worker, reclamo con bloqueo,
reencolado de huerfanos y limite de trabajos pendientes por usuario.
Las etapas del pipeline de una clase viven en learning/pipeline.py.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta
from queue import Full, Queue

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .models import LessonJob
from .pipeline import (  # noqa: F401 - reexportados por compatibilidad
    _append_log,
    _compile_mini_for_render,
    _job_content_for_generation,
    _normalize_verification_mode,
    _persist_question_bank,
    _safe_trace_list,
    _sync_class_session_status,
    _sync_transcript_record,
    process_lesson_job,
)


logger = logging.getLogger(__name__)


_queue = Queue(maxsize=getattr(settings, "LOCAL_TASK_QUEUE_MAXSIZE", 20))


_lock = threading.Lock()


_queued_ids = set()


_workers_started = 0


def queue_mode() -> str:
    """'thread': worker en hilos dentro del proceso web. 'db': un proceso aparte (manage.py run_worker) reclama en la BD."""
    mode = str(getattr(settings, "SIMA_QUEUE_MODE", "thread") or "thread").strip().lower()
    return "db" if mode == "db" else "thread"


def _enqueue(kind: str, job_id: int, backend: str = "auto"):
    if queue_mode() == "db":
        return  # el trabajo ya esta en la BD como QUEUED; lo reclama run_worker
    ensure_worker()
    key = (kind, job_id)
    with _lock:
        if key in _queued_ids:
            return
        try:
            _queue.put_nowait((kind, job_id, backend))
        except Full as exc:
            raise RuntimeError("La cola local esta llena. Espera a que termine un trabajo antes de agregar otro.") from exc
        _queued_ids.add(key)


def enqueue_lesson_job(job_id: int, backend: str = "auto"):
    _enqueue("lesson", job_id, backend)


def enqueue_reinforcement_job(job_id: int):
    _enqueue("reinforcement", job_id)


def enqueue_summary_job(job_id: int):
    _enqueue("summary", job_id)


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
        kind, job_id, backend = _queue.get()
        try:
            close_old_connections()
            _dispatch(kind, job_id, backend)
        except Exception:
            logger.exception("Error procesando trabajo %s %s", kind, job_id)
        finally:
            with _lock:
                _queued_ids.discard((kind, job_id))
            close_old_connections()
            _queue.task_done()


def _dispatch(kind: str, job_id: int, backend: str = "auto"):
    if kind == "reinforcement":
        _process_reinforcement_job(job_id)
    elif kind == "summary":
        _process_summary_job(job_id)
    else:
        process_lesson_job(job_id, backend)


def _process_reinforcement_job(job_id: int):
    from .adaptive_generation import run_reinforcement  # import perezoso
    from .models import ReinforcementJob

    job = ReinforcementJob.objects.select_related("user", "course", "practice_session").get(pk=job_id)
    run_reinforcement(job)


def _process_summary_job(job_id: int):
    from .models import SummaryJob
    from .summaries import run_summary_job  # import perezoso

    job = SummaryJob.objects.select_related("user", "course", "lesson").get(pk=job_id)
    run_summary_job(job)


def _job_tables():
    from .models import ReinforcementJob, SummaryJob

    return (
        ("lesson", LessonJob, LessonJob.Status),
        ("reinforcement", ReinforcementJob, ReinforcementJob.Status),
        ("summary", SummaryJob, SummaryJob.Status),
    )


JOB_KINDS = ("lesson", "reinforcement", "summary")


def parse_kinds(value) -> tuple[str, ...]:
    """'lesson' o 'summary,reinforcement' -> tupla validada. Vacio = todos los tipos."""
    if not value:
        return JOB_KINDS
    items = value.split(",") if isinstance(value, str) else list(value)
    kinds = tuple(dict.fromkeys(item.strip().lower() for item in items if item and item.strip()))
    unknown = [kind for kind in kinds if kind not in JOB_KINDS]
    if unknown or not kinds:
        raise ValueError(f"Tipos de trabajo no validos: {', '.join(unknown) or 'ninguno'} (usa {', '.join(JOB_KINDS)})")
    return kinds


def _tables_for(kinds=None):
    selected = parse_kinds(kinds)
    return [table for table in _job_tables() if table[0] in selected]


def claim_next_job(kinds=None):
    """
    Reclama el trabajo QUEUED mas antiguo entre las tablas de `kinds` (todas por defecto) y lo marca
    PROCESSING en la misma transaccion (select_for_update con skip_locked,
    asi varios workers no se pisan). Devuelve (kind, id, backend) o None.

    Con dos workers (uno para clases y otro para resumenes y refuerzos) una clase larga esperando su
    transcripcion no bloquea los resumenes ni los refuerzos.
    """
    with transaction.atomic():
        best = None
        for kind, model, status in _tables_for(kinds):
            row = model.objects.select_for_update(skip_locked=True).filter(status=status.QUEUED).order_by("created_at").first()
            if row is not None and (best is None or row.created_at < best[1].created_at):
                best = (kind, row, status)
        if best is None:
            return None
        kind, row, status = best
        row.status = status.PROCESSING
        fields = ["status", "updated_at"]
        if kind == "lesson":
            row.processing_stage = "Reclamado por el worker"
            row.processing_log = _append_log(row.processing_log, "Worker", "Trabajo reclamado por el proceso worker.")
            fields += ["processing_stage", "processing_log"]
        row.save(update_fields=fields)
        backend = getattr(row, "ai_backend", None) or getattr(row, "backend", None) or "auto"
        return kind, row.pk, backend


def process_claimed(kind: str, job_id: int, backend: str = "auto"):
    try:
        close_old_connections()
        _dispatch(kind, job_id, backend)
    except Exception:
        logger.exception("Error procesando trabajo %s %s", kind, job_id)
    finally:
        close_old_connections()


def reset_stale_processing(minutes: int = 120, kinds=None) -> int:
    """Trabajos PROCESSING sin actividad reciente (worker caido) vuelven a QUEUED.

    Solo toca los tipos del worker que arranca: asi reiniciar el worker de resumenes no devuelve a la cola una
    clase que el worker de clases sigue procesando.
    """
    cutoff = timezone.now() - timedelta(minutes=max(1, int(minutes)))
    total = 0
    for kind, model, status in _tables_for(kinds):
        for row in model.objects.filter(status=status.PROCESSING, updated_at__lt=cutoff):
            row.status = status.QUEUED
            fields = ["status", "updated_at"]
            if kind == "lesson":
                row.processing_stage = "En cola"
                row.processing_log = _append_log(row.processing_log, "Reencolado", "Sin actividad del worker; se retoma.")
                fields += ["processing_stage", "processing_log"]
            row.save(update_fields=fields)
            total += 1
    return total


class TooManyPendingJobs(RuntimeError):
    """El usuario ya tiene el maximo de trabajos en cola o procesando."""


def pending_jobs_for_user(user) -> int:
    total = 0
    for _kind, model, status in _job_tables():
        total += model.objects.filter(user=user, status__in=[status.QUEUED, status.PROCESSING]).count()
    return total


def assert_user_can_enqueue(user):
    """Corta antes de cobrar: un clic repetido o un bucle no debe vaciar los creditos ni la cola."""
    limit = int(getattr(settings, "SIMA_MAX_PENDING_JOBS", 3) or 0)
    if limit <= 0:
        return
    pending = pending_jobs_for_user(user)
    if pending >= limit:
        raise TooManyPendingJobs(
            f"Ya tienes {pending} trabajo{'s' if pending != 1 else ''} en proceso (maximo {limit}). Espera a que terminen antes de agregar otro."
        )


def queue_snapshot() -> dict:
    """Conteo de trabajos por tipo y estado, para /salud/ y para el panel."""
    out = {"mode": queue_mode()}
    for kind, model, status in _job_tables():
        out[kind] = {
            "queued": model.objects.filter(status=status.QUEUED).count(),
            "processing": model.objects.filter(status=status.PROCESSING).count(),
        }
    return out


def requeue_orphaned_jobs(reason: str = "reinicio del servidor") -> int:
    """
    Reencola los LessonJob que quedaron en QUEUED o PROCESSING sin worker.

    La cola vive en memoria dentro del proceso de Django, asi que un reinicio
    (o el autoreloader) deja esos trabajos huerfanos en la base de datos.
    Devuelve cuantos se volvieron a encolar.
    """
    orphans = LessonJob.objects.filter(
        status__in=[LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING]
    ).order_by("created_at")
    requeued = 0
    for job in orphans:
        job.status = LessonJob.Status.QUEUED
        job.processing_stage = "En cola"
        job.processing_log = _append_log(
            job.processing_log,
            "Reencolado",
            f"Trabajo pendiente detectado tras {reason}; se retoma automaticamente.",
        )
        job.save(update_fields=["status", "processing_stage", "processing_log", "updated_at"])
        try:
            enqueue_lesson_job(job.pk, job.ai_backend or "auto")
        except RuntimeError as exc:
            logger.warning("No se pudo reencolar LessonJob %s: %s", job.pk, exc)
            continue
        requeued += 1
    from .models import ReinforcementJob

    for job in ReinforcementJob.objects.filter(
        status__in=[ReinforcementJob.Status.QUEUED, ReinforcementJob.Status.PROCESSING]
    ).order_by("created_at"):
        job.status = ReinforcementJob.Status.QUEUED
        job.save(update_fields=["status", "updated_at"])
        try:
            enqueue_reinforcement_job(job.pk)
        except RuntimeError as exc:
            logger.warning("No se pudo reencolar el refuerzo %s: %s", job.pk, exc)
            continue
        requeued += 1
    from .models import SummaryJob

    for job in SummaryJob.objects.filter(
        status__in=[SummaryJob.Status.QUEUED, SummaryJob.Status.PROCESSING]
    ).order_by("created_at"):
        job.status = SummaryJob.Status.QUEUED
        job.save(update_fields=["status", "updated_at"])
        try:
            enqueue_summary_job(job.pk)
        except RuntimeError as exc:
            logger.warning("No se pudo reencolar el resumen %s: %s", job.pk, exc)
            continue
        requeued += 1
    if requeued:
        logger.info("Reencolados %s trabajo(s) pendiente(s) tras %s.", requeued, reason)
    return requeued
