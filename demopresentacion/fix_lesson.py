import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from django.contrib.auth.models import User
from learning.models import LessonJob
from learning.views import _sync_class_session_for_job

username = sys.argv[1] if len(sys.argv) > 1 else "demouser"

try:
    user = User.objects.get(username=username)
except User.DoesNotExist:
    print(f"User {username} not found")
    sys.exit(1)

job = LessonJob.objects.filter(user=user).order_by("-created_at").first()
if not job:
    print("No lesson job found")
    sys.exit(1)

source = LessonJob.objects.get(pk=9)
job.toon_output = source.toon_output
job.corrected_output = source.corrected_output
job.transcript = source.transcript
job.source_text = source.source_text
job.status = LessonJob.Status.CORRECTED
job.processing_stage = "Completado"
job.processing_log = "Procesamiento completado para demo."
job.save()

_sync_class_session_for_job(job)
with open(os.path.join(os.path.dirname(__file__), 'job_id.txt'), 'w') as f:
    f.write(str(job.pk))
print(f"Fixed job {job.pk} for user {username}")
