"""
Repeticion espaciada (SM-2) para flashcards.

Cada tarjeta guarda factor de facilidad, intervalo en dias y repeticiones
consecutivas correctas. La calificacion del estudiante (again / hard / medium /
easy) se traduce a la escala 0-5 de SM-2 y decide cuando vuelve a aparecer.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Course, Flashcard

GRADE_QUALITY = {"again": 1, "hard": 3, "medium": 4, "easy": 5}
MIN_EASE = 1.3
DEFAULT_EASE = 2.5
AGAIN_DELAY_MINUTES = 10
MAX_INTERVAL_DAYS = 180
DEFAULT_QUEUE_SIZE = 20


def quality_from_grade(grade: str) -> int:
    return GRADE_QUALITY.get((grade or "").strip().lower(), 4)


def sm2_update(card: Flashcard, grade: str, now=None) -> Flashcard:
    """Aplica una revision a la tarjeta y programa la siguiente. Guarda la tarjeta."""
    now = now or timezone.now()
    quality = quality_from_grade(grade)
    ease = card.ease_factor or DEFAULT_EASE

    if quality < 3:
        # olvido: se reinicia la racha de la tarjeta y vuelve en minutos
        card.repetitions = 0
        card.interval_days = 0
        card.next_review_at = now + timedelta(minutes=AGAIN_DELAY_MINUTES)
    else:
        if card.repetitions == 0:
            interval = 1
        elif card.repetitions == 1:
            interval = 6
        else:
            interval = round(card.interval_days * ease)
        if quality == 3 and card.repetitions >= 2:
            interval = round(interval * 0.8)  # "dificil": acorta el salto
        card.interval_days = max(1, min(int(interval), MAX_INTERVAL_DAYS))
        card.repetitions += 1
        card.next_review_at = now + timedelta(days=card.interval_days)

    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    card.ease_factor = round(max(MIN_EASE, ease), 3)
    card.mastery_level = min(5, card.repetitions)
    card.last_reviewed_at = now
    card.save(update_fields=[
        "repetitions", "interval_days", "next_review_at", "ease_factor", "mastery_level", "last_reviewed_at", "updated_at",
    ])
    return card


def due_filter(now=None):
    now = now or timezone.now()
    return Q(next_review_at__isnull=True) | Q(next_review_at__lte=now)


def due_cards(course: Course, now=None):
    """Tarjetas del curso que tocan hoy: nunca vistas o con la revision vencida."""
    return Flashcard.objects.filter(course=course).filter(due_filter(now))


def due_count(course: Course, now=None) -> int:
    return due_cards(course, now).count()


def review_queue(course: Course, limit: int = DEFAULT_QUEUE_SIZE, now=None) -> list[Flashcard]:
    """
    Cola de repaso: primero lo vencido (lo mas atrasado antes), luego tarjetas
    nuevas. Nunca repite una tarjeta en la misma cola.
    """
    now = now or timezone.now()
    overdue = list(
        Flashcard.objects.filter(course=course, next_review_at__lte=now).order_by("next_review_at", "id")[:limit]
    )
    remaining = limit - len(overdue)
    fresh = []
    if remaining > 0:
        fresh = list(Flashcard.objects.filter(course=course, next_review_at__isnull=True).order_by("created_at", "id")[:remaining])
    return overdue + fresh
