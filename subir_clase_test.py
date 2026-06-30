import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
django.setup()

from django.contrib.auth import get_user_model
from learning.models import Course, LessonJob, ClassSession, Plan, Profile
from learning.job_queue import enqueue_lesson_job
from learning.views import _sync_class_session_for_job

User = get_user_model()

username = "test_agente_sima"
email = "test_agente@sima.local"
password = "Test1234!"

user, created = User.objects.get_or_create(username=username, defaults={"email": email})
if created:
    user.set_password(password)
    user.save()
    print(f"Usuario creado: {username}")
else:
    print(f"Usuario existente: {username}")

profile, _ = Profile.objects.get_or_create(user=user)
profile.plan = Plan.UNLIMITED
profile.credit_balance = 9999
profile.api_classes_used = 0
profile.save()
print(f"Perfil actualizado: plan={profile.plan}, creditos={profile.credit_balance}")

course, created = Course.objects.get_or_create(
    user=user,
    name="Biologia General - Fotosintesis",
    defaults={
        "academic_period": "2026-1",
        "description": "Curso de prueba para evaluar generacion de preguntas MINI sobre fotosintesis.",
        "level": "introductory",
    }
)
print(f"Curso {'creado' if created else 'existente'}: {course.name} (id={course.pk})")

text_path = "f:/SIMA/SIMAApp/clase_fotosintesis_3000.txt"
with open(text_path, "r", encoding="utf-8") as f:
    source_text = f.read()

word_count = len(source_text.split())
print(f"Texto cargado: {word_count} palabras")

job, created = LessonJob.objects.get_or_create(
    user=user,
    title="Clase de Fotosintesis - 3000 palabras",
    defaults={
        "course": course,
        "mode": LessonJob.Mode.API,
        "status": LessonJob.Status.QUEUED,
        "source_text": source_text,
        "tags": "fotosintesis, biologia, plantas, clorofila, ecologia",
        "ai_backend": "local",
        "verification_mode": "web",
        "processing_stage": "En cola",
        "processing_log": "En cola - Esperando turno en el procesador local.",
    }
)
if not created:
    job.course = course
    job.status = LessonJob.Status.QUEUED
    job.source_text = source_text
    job.ai_backend = "local"
    job.error = ""
    job.save()
    print(f"Job actualizado: id={job.pk}")
else:
    print(f"Job creado: id={job.pk}")

session = _sync_class_session_for_job(job)
print(f"ClassSession sincronizada: id={session.pk if session else None}")

try:
    enqueue_lesson_job(job.pk, backend="local")
    print(f"Job {job.pk} encolado correctamente.")
except Exception as exc:
    print(f"Error al encolar: {exc}")

print(f"\nURL del detalle: http://127.0.0.1:8002/clase/{job.pk}/")
print(f"URL publica: http://127.0.0.1:25564/clase/{job.pk}/")
