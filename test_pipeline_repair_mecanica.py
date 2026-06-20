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

    path = "docs/mecanica_3000_palabras.txt"
    with open(path, "r", encoding="utf-8") as f:
        transcript = f.read()

    words = len(transcript.split())
    log("=" * 60)
    log("PRUEBA: _auto_repair_transcript con texto de mecanica")
    log(f"Archivo: {path}")
    log(f"Palabras en transcripcion: {words}")
    log("=" * 60)

    job = LessonJob.objects.create(
        user=user,
        title="Introduccion a la Mecanica Clasica",
        tags="mecanica, cinematica, dinamica, energia, fuerzas",
        transcript=transcript,
        source_text="",
        status=LessonJob.Status.PROCESSING,
        processing_stage="Preparando contenido",
    )

    log(f"LessonJob creado: id={job.pk}")
    log("Iniciando _auto_repair_transcript...")
    start = time.time()
    try:
        _auto_repair_transcript(job)
        elapsed = time.time() - start
        job.refresh_from_db()
        log(f"\nCompletado en {elapsed:.2f} segundos")
        log(f"Estado: {job.status}")
        log(f"Etapa: {job.processing_stage}")
        log(f"Transcripcion cambio: {job.transcript.strip() != transcript.strip()}")
        log("Ultimas lineas del log:")
        for line in (job.processing_log or "").splitlines()[-10:]:
            log(f"  {line}")
        with open("test_pipeline_repair_mecanica_log.txt", "w", encoding="utf-8") as f:
            f.write(job.processing_log or "")
        with open("test_pipeline_repair_mecanica_result.txt", "w", encoding="utf-8") as f:
            f.write(job.transcript)
        log("Guardados: test_pipeline_repair_mecanica_log.txt y test_pipeline_repair_mecanica_result.txt")
    except Exception as exc:
        elapsed = time.time() - start
        log(f"\nERROR tras {elapsed:.2f} segundos: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
