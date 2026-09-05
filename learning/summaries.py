"""
Resumenes de estudio (US-050).

- Resumen por clase: se genera a partir de la transcripcion y del .mini de la
  clase; queda como Summary(kind=structured) ligado a la ClassSession.
- Resumen acumulado del curso: integra los resumenes de clase (o, si no hay,
  extractos de las transcripciones) en un unico documento por temas.

Formato compacto que se le pide al modelo (una linea por elemento):
    t|<titulo>
    c|<concepto clave>          (3 a 8 lineas)
    p|<parrafo del resumen>     (3 a 6 lineas)
    r|<que repasar primero>     (opcional, 1 a 3 lineas)
"""
from __future__ import annotations

import logging
import re

from django.db import transaction

from .credits import consume_credits, estimate_summary_cost, has_enough_credits, refund_credits
from .models import ClassSession, Course, CreditLedgerEntry, LessonJob, Profile, Summary

logger = logging.getLogger(__name__)

CLASS_SOURCE_CHARS = 9000
COURSE_SOURCE_CHARS = 12000
MAX_COURSE_CLASSES = 8


class SummaryUnavailable(RuntimeError):
    """No hay material suficiente o creditos para generar el resumen."""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def build_class_summary_prompt(title: str, transcript: str, mini_text: str) -> str:
    source = (transcript or "").strip()[:CLASS_SOURCE_CHARS]
    items = _mini_stems(mini_text)
    items_block = "\n".join(f"- {s}" for s in items[:25]) if items else "(sin preguntas generadas)"
    return (
        "Eres un asistente de estudio universitario. Resume la siguiente clase en espanol, "
        "de forma fiel al contenido (no inventes datos que no esten en la transcripcion).\n\n"
        "Responde SOLO con lineas en este formato, sin texto adicional:\n"
        "t|<titulo breve de la clase>\n"
        "c|<concepto clave> (entre 3 y 8 lineas c|, una idea por linea)\n"
        "p|<parrafo del resumen> (entre 3 y 6 lineas p|, cada una un parrafo de 2 a 4 oraciones)\n"
        "r|<que conviene repasar primero y por que> (1 a 3 lineas r|)\n\n"
        f"CLASE: {title}\n\n"
        f"TRANSCRIPCION:\n{source}\n\n"
        f"PREGUNTAS QUE SE EVALUAN SOBRE ESTA CLASE:\n{items_block}\n"
    )


def build_course_summary_prompt(course: Course, sections: list[tuple[str, str]], weak_topics: list[str]) -> str:
    body = "\n\n".join(f"[{title}]\n{text}" for title, text in sections)
    weak = ", ".join(weak_topics) if weak_topics else "(sin datos de practica aun)"
    return (
        "Eres un asistente de estudio universitario. Integra el material de varias clases de un curso en "
        "un resumen acumulado en espanol, organizado por temas y fiel al contenido.\n\n"
        "Responde SOLO con lineas en este formato, sin texto adicional:\n"
        "t|<titulo del resumen del curso>\n"
        "c|<concepto clave del curso> (entre 5 y 12 lineas c|)\n"
        "p|<parrafo por tema, indicando como se relaciona con los demas> (entre 4 y 8 lineas p|)\n"
        "r|<que repasar primero, priorizando los temas debiles del estudiante> (2 a 4 lineas r|)\n\n"
        f"CURSO: {course.name}\n"
        f"TEMAS DEBILES DEL ESTUDIANTE: {weak}\n\n"
        f"MATERIAL:\n{body[:COURSE_SOURCE_CHARS]}\n"
    )


def _mini_stems(mini_text: str) -> list[str]:
    stems = []
    for line in (mini_text or "").splitlines():
        parts = line.split("|")
        if len(parts) >= 4 and re.match(r"^i\d+$", parts[0].strip()):
            stems.append(parts[3].strip())
    return stems


# ---------------------------------------------------------------------------
# Parseo de la respuesta
# ---------------------------------------------------------------------------
def parse_summary_response(raw: str, fallback_title: str = "Resumen") -> dict:
    title, concepts, paragraphs, review = "", [], [], []
    for line in (raw or "").splitlines():
        line = line.strip().strip("`")
        if len(line) < 3 or line[1] != "|":
            continue
        tag, value = line[0].lower(), line[2:].strip()
        if not value:
            continue
        if tag == "t" and not title:
            title = value
        elif tag == "c":
            concepts.append(value)
        elif tag == "p":
            paragraphs.append(value)
        elif tag == "r":
            review.append(value)
    if not paragraphs:
        text = re.sub(r"^\s*[tcpr]\|", "", (raw or "").strip(), flags=re.M).strip()
        paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()][:6]
    content = "\n\n".join(paragraphs)
    if review:
        content += "\n\nQue repasar primero:\n" + "\n".join(f"- {r}" for r in review)
    return {"title": title or fallback_title, "key_concepts": concepts[:12], "content": content.strip(), "review": review}


# ---------------------------------------------------------------------------
# Generacion
# ---------------------------------------------------------------------------
def _charge(user, course, class_session, backend: str, label: str):
    profile, _ = Profile.objects.get_or_create(user=user)
    estimate = estimate_summary_cost(backend)
    if not has_enough_credits(profile, estimate.amount):
        raise SummaryUnavailable(f"Necesitas {estimate.amount} creditos para generar el {label}.")
    consume_credits(
        profile, estimate.amount, action=CreditLedgerEntry.Action.SUMMARY_GENERATION,
        course=course, class_session=class_session, description=f"Resumen: {label}",
        metadata={"details": list(estimate.details), "backend": backend},
    )
    return profile, estimate.amount


def _class_session_for(job: LessonJob, create: bool = False) -> ClassSession | None:
    session = ClassSession.objects.filter(legacy_lesson_job=job).first()
    if session is None and create and job.course_id:
        from .job_queue import _sync_class_session_status  # import perezoso

        session = _sync_class_session_status(job)
    return session


def generate_class_summary(user, job: LessonJob, backend: str = "auto") -> Summary:
    """Genera (o regenera) el resumen estructurado de una clase. Cobra creditos y reembolsa si falla."""
    from .services import call_ai, resolve_backend  # import perezoso: services carga dependencias pesadas

    transcript = (job.transcript or job.source_text or "").strip()
    if len(transcript) < 200:
        raise SummaryUnavailable("La clase no tiene transcripcion suficiente para resumir.")
    if not job.course_id:
        raise SummaryUnavailable("La clase debe pertenecer a un curso para generar su resumen.")
    session = _class_session_for(job, create=True)
    resolved = resolve_backend(backend or "auto")
    profile, amount = _charge(user, job.course, session, resolved, f"clase {job.title}")
    try:
        raw = call_ai(build_class_summary_prompt(job.title, transcript, job.corrected_output or job.toon_output), backend=resolved, role="generation")
        parsed = parse_summary_response(raw, fallback_title=f"Resumen de {job.title}")
        if not parsed["content"]:
            raise RuntimeError("El modelo no devolvio contenido para el resumen.")
    except Exception as exc:
        refund_credits(profile, amount, course=job.course, class_session=session, description="Reembolso: resumen fallido")
        logger.warning("Resumen de clase %s fallo: %s", job.pk, exc)
        raise SummaryUnavailable(f"No se pudo generar el resumen: {exc}") from exc
    with transaction.atomic():
        summary, _ = Summary.objects.update_or_create(
            course=job.course, class_session=session, kind=Summary.Kind.STRUCTURED,
            defaults={"title": parsed["title"], "content": parsed["content"], "key_concepts": parsed["key_concepts"]},
        )
    return summary


def class_summary_for(job: LessonJob) -> Summary | None:
    session = _class_session_for(job)
    if session is None or not job.course_id:
        return None
    return Summary.objects.filter(course=job.course, class_session=session, kind=Summary.Kind.STRUCTURED).first()


def course_summary_for(course: Course) -> Summary | None:
    return Summary.objects.filter(course=course, kind=Summary.Kind.COURSE_ACCUMULATED).first()


def _course_sections(course: Course) -> list[tuple[str, str]]:
    """Resumenes de clase si existen; si no, extractos de las transcripciones mas recientes."""
    sections = []
    class_summaries = Summary.objects.filter(course=course, kind=Summary.Kind.STRUCTURED).select_related("class_session").order_by("created_at")
    for s in class_summaries[:MAX_COURSE_CLASSES]:
        head = s.class_session.title if s.class_session_id else s.title
        concepts = ", ".join(s.key_concepts or [])
        sections.append((head, (f"Conceptos: {concepts}\n" if concepts else "") + s.content))
    if sections:
        return sections
    jobs = LessonJob.objects.filter(course=course).exclude(transcript="", source_text="").order_by("created_at")[:MAX_COURSE_CLASSES]
    per_class = max(COURSE_SOURCE_CHARS // max(len(jobs), 1), 1500)
    for job in jobs:
        text = (job.transcript or job.source_text).strip()
        if text:
            sections.append((job.title, text[:per_class]))
    return sections


def generate_course_summary(user, course: Course, backend: str = "auto") -> Summary:
    """Resumen acumulado del curso; prioriza los temas debiles del perfil adaptativo."""
    from .adaptive import get_profile  # import perezoso (adaptive importa summaries indirectamente)
    from .services import call_ai, resolve_backend

    sections = _course_sections(course)
    if not sections:
        raise SummaryUnavailable("El curso no tiene clases con contenido para resumir.")
    profile_adaptive = get_profile(user, course)
    weak = list(profile_adaptive.weak_topics) if profile_adaptive else []
    resolved = resolve_backend(backend or "auto")
    profile, amount = _charge(user, course, None, resolved, f"curso {course.name}")
    try:
        raw = call_ai(build_course_summary_prompt(course, sections, weak), backend=resolved, role="generation")
        parsed = parse_summary_response(raw, fallback_title=f"Resumen de {course.name}")
        if not parsed["content"]:
            raise RuntimeError("El modelo no devolvio contenido para el resumen.")
    except Exception as exc:
        refund_credits(profile, amount, course=course, description="Reembolso: resumen de curso fallido")
        logger.warning("Resumen de curso %s fallo: %s", course.pk, exc)
        raise SummaryUnavailable(f"No se pudo generar el resumen: {exc}") from exc
    with transaction.atomic():
        summary, _ = Summary.objects.update_or_create(
            course=course, class_session=None, kind=Summary.Kind.COURSE_ACCUMULATED,
            defaults={"title": parsed["title"], "content": parsed["content"], "key_concepts": parsed["key_concepts"]},
        )
    return summary
