import os
import sys
import time
import django

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
job.processing_log = "Reintentando con qwen2.5:7b."
job.ai_backend = "local"
job.save()

print(f"[{time.strftime('%H:%M:%S')}] Iniciando procesamiento del job {job_id} con modelo local...")
try:
    process_lesson_job(job_id, backend="local")
    print(f"[{time.strftime('%H:%M:%S')}] Procesamiento finalizado.")
except Exception as exc:
    print(f"[{time.strftime('%H:%M:%S')}] ERROR: {exc}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

job = LessonJob.objects.get(pk=job_id)
print(f"Status final: {job.status}")
print(f"Stage final: {job.processing_stage}")
print(f"Error: {job.error[:1000] if job.error else 'Ninguno'}")
items = job.corrected_output.count('i|') if job.corrected_output else 0
print(f"Items generados: {items}")
if job.corrected_output:
    print("\n--- PRIMERAS 2000 chars de corrected_output ---")
    print(job.corrected_output[:2000])
