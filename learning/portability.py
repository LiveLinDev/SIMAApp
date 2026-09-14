"""
Exportar e importar un curso como JSON: clases (con transcripcion y .mini
verificado), resumenes y flashcards. Sirve para mover datos de validacion
entre maquinas, repetir experimentos y armar demostraciones sin volver a
pagar la generacion. El banco de preguntas se reconstruye al importar desde
el .mini; el historial de practica no viaja (es del estudiante, no del curso).
"""
from __future__ import annotations

import json
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from .models import Course, Flashcard, LessonJob, Summary

FORMAT = "sima-course/1"
LESSON_FIELDS = ("title", "tags", "mode", "status", "source_text", "transcript", "toon_output", "corrected_output",
                 "verification_output", "ai_backend", "verification_mode", "visibility")
COURSE_FIELDS = ("name", "academic_period", "description", "instructor", "main_topics", "vocabulary", "level", "student_goal")


def _iso(value):
    return value.isoformat() if value else None


def export_course(course: Course) -> dict:
    lessons = []
    for job in LessonJob.objects.filter(course=course).order_by("created_at"):
        row = {f: getattr(job, f) for f in LESSON_FIELDS}
        row["created_at"] = _iso(job.created_at)
        lessons.append(row)
    summaries = [
        {"kind": s.kind, "title": s.title, "content": s.content, "key_concepts": s.key_concepts,
         "lesson_index": _lesson_index(course, s.class_session_id)}
        for s in Summary.objects.filter(course=course).order_by("created_at")
    ]
    flashcards = [
        {"question": c.question, "answer": c.answer, "topic": c.topic, "difficulty": c.difficulty,
         "source_excerpt": c.source_excerpt, "source_timestamp_seconds": c.source_timestamp_seconds,
         "ease_factor": c.ease_factor, "interval_days": c.interval_days, "repetitions": c.repetitions,
         "lesson_index": _lesson_index(course, c.class_session_id)}
        for c in Flashcard.objects.filter(course=course).order_by("created_at")
    ]
    return {
        "format": FORMAT,
        "exported_at": timezone.now().isoformat(),
        "course": {f: getattr(course, f) for f in COURSE_FIELDS} | {"exam_date": _iso(course.exam_date)},
        "lessons": lessons,
        "summaries": summaries,
        "flashcards": flashcards,
    }


def _lesson_index(course: Course, class_session_id) -> int | None:
    if not class_session_id:
        return None
    ids = list(LessonJob.objects.filter(course=course).order_by("created_at").values_list("class_session__id", flat=True))
    return ids.index(class_session_id) if class_session_id in ids else None


@transaction.atomic
def import_course(user, payload: dict, name: str | None = None, sync_bank: bool = True) -> Course:
    if payload.get("format") != FORMAT:
        raise ValueError(f"Formato no reconocido: {payload.get('format')!r} (se esperaba {FORMAT}).")
    from .pipeline import _sync_class_session_status  # import perezoso

    data = dict(payload["course"])
    exam_date = data.pop("exam_date", None)
    if name:
        data["name"] = name
    course = Course.objects.create(user=user, **data)
    if exam_date:
        course.exam_date = datetime.fromisoformat(exam_date).date()
        course.save(update_fields=["exam_date"])

    sessions = []
    for row in payload.get("lessons", []):
        fields = {f: row.get(f, "") for f in LESSON_FIELDS if row.get(f) is not None}
        fields.pop("visibility", None)  # una clase importada es privada hasta que se comparta de nuevo
        job = LessonJob.objects.create(user=user, course=course, **fields)
        sessions.append(_sync_class_session_status(job))
        if sync_bank and (job.corrected_output or job.toon_output):
            from .adaptive import sync_question_bank  # import perezoso

            sync_question_bank(job)

    def _session(index):
        return sessions[index] if index is not None and 0 <= index < len(sessions) else None

    for s in payload.get("summaries", []):
        Summary.objects.create(course=course, class_session=_session(s.get("lesson_index")), kind=s["kind"],
                               title=s.get("title", ""), content=s["content"], key_concepts=s.get("key_concepts") or [])
    for c in payload.get("flashcards", []):
        Flashcard.objects.create(
            course=course, class_session=_session(c.get("lesson_index")), question=c["question"], answer=c["answer"],
            topic=c.get("topic", ""), difficulty=c.get("difficulty") or "medium", source_excerpt=c.get("source_excerpt", ""),
            source_timestamp_seconds=c.get("source_timestamp_seconds"), ease_factor=c.get("ease_factor", 2.5),
            interval_days=c.get("interval_days", 0), repetitions=c.get("repetitions", 0),
        )
    return course


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
