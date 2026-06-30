import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
django.setup()

from django.contrib.auth import get_user_model
from learning.models import Course, LessonJob, ClassSession, Plan, Profile
from learning.views import _sync_class_session_for_job
from learning.parse_mini import parse_mini, assessment_to_dict
import json

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
profile.save()

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

mini_path = "f:/SIMA/SIMAApp/mini_fotosintesis_manual.txt"
with open(mini_path, "r", encoding="utf-8") as f:
    mini_text = f.read()

print(f"Texto cargado: {len(source_text.split())} palabras")
print(f"MINI cargado: {len(mini_text.splitlines())} lineas")

job, created = LessonJob.objects.get_or_create(
    user=user,
    title="Clase de Fotosintesis - MINI manual",
    defaults={
        "course": course,
        "mode": LessonJob.Mode.FREE_MANUAL,
        "status": LessonJob.Status.CORRECTED,
        "source_text": source_text,
        "tags": "fotosintesis, biologia, plantas, clorofila, ecologia",
        "ai_backend": "local",
        "toon_output": mini_text,
        "corrected_output": mini_text,
        "processing_stage": "Listo",
        "processing_log": "MINI cargado manualmente para revision de coherencia.",
    }
)
if not created:
    job.course = course
    job.status = LessonJob.Status.CORRECTED
    job.source_text = source_text
    job.toon_output = mini_text
    job.corrected_output = mini_text
    job.processing_stage = "Listo"
    job.error = ""
    job.save()

session = _sync_class_session_for_job(job)
print(f"ClassSession sincronizada: id={session.pk if session else None}")

# Parsear a JSON y guardar
assessment = parse_mini(mini_text)
data = assessment_to_dict(assessment)
json_path = "f:/SIMA/SIMAApp/mini_fotosintesis_manual.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"JSON guardado en: {json_path}")
print(f"Items parseados: {len(assessment.items)}")

print(f"\nURL del detalle: http://127.0.0.1:8002/clase/{job.pk}/")
print(f"URL publica: http://127.0.0.1:25564/clase/{job.pk}/")
print(f"URL descarga JSON: http://127.0.0.1:8002/clase/{job.pk}/descargar/")
