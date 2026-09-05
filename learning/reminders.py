"""
Recordatorios de estudio por correo.

Se envian a quienes activaron `email_reminders`, tienen correo y no han
estudiado hoy. El cuerpo prioriza tarjetas vencidas y el primer paso del plan
del dia del curso mas reciente. Se ejecuta con el comando
`send_study_reminders` (programable con el Programador de tareas o cron).
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import Course, Profile, UserPreference
from .spaced_repetition import due_count


@dataclass
class Reminder:
    user: User
    subject: str
    body: str


def _site_url(path: str) -> str:
    base = (getattr(settings, "SIMA_SITE_URL", "") or "").rstrip("/")
    return f"{base}{path}" if base else path


def build_reminder(user: User) -> Reminder | None:
    """Arma el recordatorio; None si no corresponde enviarlo hoy."""
    from .adaptive import daily_plan  # import perezoso

    prefs = UserPreference.objects.filter(user=user).first()
    if prefs is None or not prefs.email_reminders or not user.email:
        return None
    profile, _ = Profile.objects.get_or_create(user=user)
    if profile.last_study_date == timezone.localdate():
        return None

    courses = list(Course.objects.filter(user=user, is_archived=False).order_by("-pk")[:5])
    if not courses:
        return None
    due_total = sum(due_count(c) for c in courses)
    course = courses[0]
    plan = daily_plan(user, course)
    first_name = (user.first_name or user.username).strip()

    lines = [f"Hola {first_name},", ""]
    if profile.current_streak:
        lines.append(f"Llevas una racha de {profile.current_streak} dias. Hoy todavia no registras estudio.")
    else:
        lines.append("Hoy todavia no registras estudio en SIMA.")
    lines.append("")
    if due_total:
        lines.append(f"- Tienes {due_total} tarjetas vencidas para repasar.")
    if plan:
        step = plan[0]
        lines.append(f"- Siguiente paso en {course.name}: {step.get('title', '')}")
        if step.get("detail"):
            lines.append(f"  {step['detail']}")
    lines += ["", f"Abrir el curso: {_site_url(reverse('course_detail', args=[course.pk]))}", "",
              "Puedes desactivar estos recordatorios en Preferencias.", "SIMA"]
    subject = f"SIMA: {due_total} tarjetas por repasar" if due_total else f"SIMA: tu plan de hoy en {course.name}"
    return Reminder(user=user, subject=subject, body="\n".join(lines))


def send_reminders(dry_run: bool = False) -> list[Reminder]:
    """Envia los recordatorios pendientes y devuelve los construidos."""
    sent = []
    users = User.objects.filter(is_active=True, preferences__email_reminders=True).exclude(email="").select_related("preferences")
    for user in users:
        reminder = build_reminder(user)
        if reminder is None:
            continue
        if not dry_run:
            send_mail(
                reminder.subject, reminder.body, getattr(settings, "DEFAULT_FROM_EMAIL", None), [user.email], fail_silently=False,
            )
        sent.append(reminder)
    return sent
