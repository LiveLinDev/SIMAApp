import os
import sys
import time
import django
import traceback

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
django.setup()

from learning.job_queue import process_lesson_job
from learning.models import LessonJob

job_id = 65
print(f"[{time.strftime('%H:%M:%S')}] Reset job {job_id}...")
job = LessonJob.objects.get(pk=job_id)
job.status = LessonJob.Status.QUEUED
job.error = ""
job.processing_stage = "En cola"
job.processing_log = "Debug - reintentando con qwen2.5:7b."
job.ai_backend = "local"
job.save()

print(f"[{time.strftime('%H:%M:%S')}] Iniciando procesamiento...")
try:
    process_lesson_job(job_id, backend="local")
    print(f"[{time.strftime('%H:%M:%S')}] Procesamiento finalizado.")
except Exception as exc:
    print(f"[{time.strftime('%H:%M:%S')}] ERROR: {exc}")
    traceback.print_exc()
    sys.exit(1)
