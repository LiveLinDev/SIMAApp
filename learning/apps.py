import logging
import os
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class LearningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "learning"

    def ready(self):
        if not _should_requeue_on_start():
            return
        from django.db.utils import OperationalError, ProgrammingError

        from .job_queue import requeue_orphaned_jobs

        try:
            requeue_orphaned_jobs()
        except (OperationalError, ProgrammingError) as exc:
            # BD sin migrar o inaccesible: no bloquear el arranque por esto.
            logger.warning("No se pudieron reencolar trabajos pendientes: %s", exc)


def _should_requeue_on_start() -> bool:
    """
    Reencola solo cuando este proceso va a servir peticiones y tiene worker.

    - SIMA_REQUEUE_ON_START=1|0 fuerza el comportamiento (util con gunicorn).
    - Con runserver y autoreload, ready() corre en el padre y en el hijo;
      solo el hijo (RUN_MAIN=true) atiende peticiones y debe reencolar.
    - migrate, test, shell y demas comandos no reencolan nunca.
    """
    from django.conf import settings

    if str(getattr(settings, "SIMA_QUEUE_MODE", "thread")).strip().lower() == "db":
        return False  # el worker aparte (run_worker) se encarga de lo pendiente
    override = os.environ.get("SIMA_REQUEUE_ON_START", "").strip().lower()
    if override in {"1", "true", "yes"}:
        return True
    if override in {"0", "false", "no"}:
        return False
    if "runserver" not in sys.argv:
        return False
    return os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv
