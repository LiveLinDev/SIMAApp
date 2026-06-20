import os
import sys
import time
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.contrib.auth import get_user_model
from learning.models import LessonJob
from learning.job_queue import _auto_repair_transcript


def log(msg):
    print(msg, flush=True)


def main():
    User = get_user_model()
    user, _ = User.objects.get_or_create(username="test_mecanica", defaults={"email": "test@local"})
    if not user.pk:
        user.set_password("test")
        user.save()

    with open("docs/mecanica_3000_palabras.txt", encoding="utf-8") as f:
        text = f.read()
    transcript = " ".join(text.split()[:1200])
    words = len(transcript.split())

    log("=" * 60)
    log("PRUEBA: _auto_repair_transcript con 1200 palabras de mecanica")
    log(f"Palabras: {words}")
    log("=" * 60)

    job = LessonJob.objects.create(
        user=user,
        title="Mecanica Clasica - fragmento",
        tags="mecanica",
        transcript=transcript,
        source_text="",
        status=LessonJob.Status.PROCESSING,
        processing_stage="Preparando contenido",
    )

    start = time.time()
    try:
        _auto_repair_transcript(job)
        elapsed = time.time() - start
        job.refresh_from_db()
        log(f"\nCompletado en {elapsed:.2f} segundos")
        log(f"Estado: {job.status}")
        log(f"Etapa: {job.processing_stage}")
        log("Log:")
        for line in (job.processing_log or "").splitlines():
            log(f"  {line}")
    except Exception as exc:
        elapsed = time.time() - start
        log(f"\nERROR tras {elapsed:.2f} segundos: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
