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
from django.utils import timezone

from .models import ClassSession, Course, CreditLedgerEntry, LessonJob, Profile, Summary, SummaryJob

logger = logging.getLogger(__name__)

# Una clase que entra en CLASS_SOURCE_CHARS se resume en una sola llamada. Una clase mas larga se divide en
# partes de ~CLASS_PART_WORDS palabras: de cada parte salen notas y el resumen final se escribe con las notas
# de TODAS las partes, asi cubre la clase completa y no solo el inicio.
CLASS_SOURCE_CHARS = 9000
CLASS_PART_WORDS = 1300
MAX_CLASS_PARTS = 12
COURSE_SOURCE_CHARS = 12000
MAX_COURSE_CLASSES = 8

CONCEPT_RULES = (
    "Cada c| es un termino o concepto tecnico de la clase (1 a 5 palabras), escrito con la ortografia "
    "correcta del area, como aparece en un libro de texto. No uses frases, preguntas, verbos sueltos ni "
    "palabras genericas como 'importancia', 'ejemplo' o 'tema'."
)


class SummaryUnavailable(RuntimeError):
    """No hay material suficiente o creditos para generar el resumen."""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def _vocabulary_line(vocabulary: list[str] | None) -> str:
    if not vocabulary:
        return ""
    return "VOCABULARIO DEL CURSO (usa esta ortografia): " + ", ".join(vocabulary[:80]) + "\n\n"


def build_class_summary_prompt(title: str, transcript: str, mini_text: str, vocabulary: list[str] | None = None) -> str:
    source = (transcript or "").strip()[:CLASS_SOURCE_CHARS]
    items = _mini_stems(mini_text)
    items_block = "\n".join(f"- {s}" for s in items[:25]) if items else "(sin preguntas generadas)"
    return (
        "Eres un asistente de estudio universitario. Resume la siguiente clase en espanol, "
        "de forma fiel al contenido (no inventes datos que no esten en la transcripcion). "
        "La transcripcion es automatica: si un termino tecnico esta mal escrito, escribelo correctamente.\n\n"
        "Responde SOLO con lineas en este formato, sin texto adicional:\n"
        "t|<titulo breve de la clase>\n"
        "c|<concepto clave> (entre 4 y 10 lineas c|)\n"
        "p|<parrafo del resumen> (entre 3 y 6 lineas p|, cada una un parrafo de 2 a 4 oraciones)\n"
        "r|<que conviene repasar primero y por que> (1 a 3 lineas r|)\n\n"
        f"{CONCEPT_RULES}\n\n"
        f"CLASE: {title}\n\n"
        f"{_vocabulary_line(vocabulary)}"
        f"TRANSCRIPCION:\n{source}\n\n"
        f"PREGUNTAS QUE SE EVALUAN SOBRE ESTA CLASE:\n{items_block}\n"
    )


def build_class_part_notes_prompt(title: str, part: str, index: int, total: int, vocabulary: list[str] | None = None) -> str:
    return (
        "Eres un asistente de estudio universitario. Esta es una parte de la transcripcion automatica de una clase. "
        "Toma notas fieles de TODO lo que se explica en esta parte, en espanol, sin inventar datos. "
        "Si un termino tecnico esta mal escrito, escribelo correctamente.\n\n"
        "Responde SOLO con lineas en este formato:\n"
        "n|<idea explicada, con los datos concretos: definiciones, valores, causas, ejemplos> (entre 4 y 10 lineas n|)\n"
        "c|<concepto clave de esta parte> (entre 2 y 6 lineas c|)\n\n"
        f"{CONCEPT_RULES}\n\n"
        f"CLASE: {title}\n"
        f"PARTE {index} DE {total}\n\n"
        f"{_vocabulary_line(vocabulary)}"
        f"TRANSCRIPCION:\n{part}\n"
    )


def build_class_summary_from_notes_prompt(title: str, notes: list[tuple[int, list[str], list[str]]], mini_text: str,
                                         vocabulary: list[str] | None = None) -> str:
    total = len(notes)
    blocks = []
    for index, ideas, concepts in notes:
        lines = "\n".join(f"- {idea}" for idea in ideas) or "- (sin notas)"
        blocks.append(f"[Parte {index} de {total}]\n{lines}" + (f"\nConceptos: {', '.join(concepts)}" if concepts else ""))
    items = _mini_stems(mini_text)
    items_block = "\n".join(f"- {s}" for s in items[:25]) if items else "(sin preguntas generadas)"
    return (
        "Eres un asistente de estudio universitario. Con las notas de TODAS las partes de una clase, escribe su "
        "resumen en espanol. Debe cubrir la clase completa en orden, de la primera a la ultima parte, sin inventar datos.\n\n"
        "Responde SOLO con lineas en este formato, sin texto adicional:\n"
        "t|<titulo breve de la clase>\n"
        "c|<concepto clave> (entre 6 y 12 lineas c|, repartidos entre todas las partes)\n"
        f"p|<parrafo del resumen> (entre {min(max(total, 3), 8)} y {min(max(total + 2, 5), 10)} lineas p|, "
        "cada una un parrafo de 2 a 4 oraciones; ninguna parte puede quedar fuera)\n"
        "r|<que conviene repasar primero y por que> (1 a 3 lineas r|)\n\n"
        f"{CONCEPT_RULES}\n\n"
        f"CLASE: {title}\n\n"
        f"{_vocabulary_line(vocabulary)}"
        f"NOTAS POR PARTE:\n" + "\n\n".join(blocks) + "\n\n"
        f"PREGUNTAS QUE SE EVALUAN SOBRE ESTA CLASE:\n{items_block}\n"
    )


def parse_part_notes(raw: str) -> tuple[list[str], list[str]]:
    ideas, concepts = [], []
    for line in (raw or "").splitlines():
        line = line.strip().strip("`").lstrip("-* ").strip()
        if len(line) < 3 or line[1] != "|":
            continue
        tag, value = line[0].lower(), line[2:].strip()
        if not value:
            continue
        if tag == "n":
            ideas.append(value)
        elif tag == "c":
            concepts.append(value)
    return ideas, concepts


def split_class_parts(source: str) -> list[str]:
    from .services.generation import chunk_content

    words = source.split()
    part_words = CLASS_PART_WORDS
    if len(words) > part_words * MAX_CLASS_PARTS:
        part_words = -(-len(words) // MAX_CLASS_PARTS)  # techo: nunca mas de MAX_CLASS_PARTS llamadas
    return chunk_content(source, max_words=part_words)


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
def clean_concepts(concepts: list[str], limit: int = 12) -> list[str]:
    """Descarta conceptos que son frases largas, preguntas o duplicados."""
    cleaned, seen = [], set()
    for concept in concepts:
        value = " ".join(str(concept).split()).strip(" .;:-\"'")
        value = re.sub(r"^\d+[.)]\s*", "", value)
        if not value or "?" in value or len(value.split()) > 6 or len(value) > 70:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value[:1].upper() + value[1:])
    return cleaned[:limit]


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
    return {"title": title or fallback_title, "key_concepts": clean_concepts(concepts), "content": content.strip(), "review": review}


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
        from .pipeline import _sync_class_session_status  # import perezoso

        session = _sync_class_session_status(job)
    return session


def _class_source(job: LessonJob) -> str:
    return (job.transcript or job.source_text or "").strip()


def check_class_summary(job: LessonJob):
    if len(_class_source(job)) < 200:
        raise SummaryUnavailable("La clase no tiene transcripcion suficiente para resumir.")
    if not job.course_id:
        raise SummaryUnavailable("La clase debe pertenecer a un curso para generar su resumen.")


def build_class_summary(job: LessonJob, backend: str, on_progress=None) -> dict:
    """Llama al modelo y devuelve el resumen parseado (sin cobrar ni guardar).

    on_progress(texto): avisa el avance cuando la clase es larga y se resume por partes.
    """
    from .services import call_ai  # import perezoso: services carga dependencias pesadas
    from .vocabulary import course_terms

    source = _class_source(job)
    mini_text = job.corrected_output or job.toon_output
    vocabulary = course_terms(job.course) if job.course_id else []
    if len(source) <= CLASS_SOURCE_CHARS:
        raw = call_ai(build_class_summary_prompt(job.title, source, mini_text, vocabulary), backend=backend, role="generation")
    else:
        parts = split_class_parts(source)
        notes = []
        for index, part in enumerate(parts, start=1):
            if on_progress:
                on_progress(f"Leyendo la parte {index} de {len(parts)}.")
            part_raw = call_ai(build_class_part_notes_prompt(job.title, part, index, len(parts), vocabulary),
                               backend=backend, role="generation", max_tokens=1500)
            ideas, concepts = parse_part_notes(part_raw)
            if not ideas:
                raise RuntimeError(f"El modelo no devolvio notas para la parte {index} de {len(parts)}.")
            notes.append((index, ideas, concepts))
        if on_progress:
            on_progress(f"Escribiendo el resumen con las {len(parts)} partes.")
        raw = call_ai(build_class_summary_from_notes_prompt(job.title, notes, mini_text, vocabulary), backend=backend, role="generation")
    parsed = parse_summary_response(raw, fallback_title=f"Resumen de {job.title}")
    if not parsed["content"]:
        raise RuntimeError("El modelo no devolvio contenido para el resumen.")
    return parsed


def store_class_summary(job: LessonJob, session: ClassSession | None, parsed: dict) -> Summary:
    with transaction.atomic():
        summary, _ = Summary.objects.update_or_create(
            course=job.course, class_session=session, kind=Summary.Kind.STRUCTURED,
            defaults={"title": parsed["title"], "content": parsed["content"], "key_concepts": parsed["key_concepts"]},
        )
    return summary


def generate_class_summary(user, job: LessonJob, backend: str = "auto") -> Summary:
    """Version sincrona: cobra, genera y guarda (reembolsa si falla). La cola usa run_summary_job."""
    from .services import resolve_backend

    check_class_summary(job)
    session = _class_session_for(job, create=True)
    resolved = resolve_backend(backend or "auto")
    profile, amount = _charge(user, job.course, session, resolved, f"clase {job.title}")
    try:
        parsed = build_class_summary(job, resolved)
    except Exception as exc:
        refund_credits(profile, amount, course=job.course, class_session=session, description="Reembolso: resumen fallido")
        logger.warning("Resumen de clase %s fallo: %s", job.pk, exc)
        raise SummaryUnavailable(f"No se pudo generar el resumen: {exc}") from exc
    return store_class_summary(job, session, parsed)


def class_summary_for(job: LessonJob) -> Summary | None:
    session = _class_session_for(job)
    if session is None or not job.course_id:
        return None
    return Summary.objects.filter(course=job.course, class_session=session, kind=Summary.Kind.STRUCTURED).first()


def course_summary_for(course: Course) -> Summary | None:
    return Summary.objects.filter(course=course, kind=Summary.Kind.COURSE_ACCUMULATED).first()


def _course_sections(course: Course) -> list[tuple[str, str]]:
    """Una seccion por clase: su resumen si existe; si no, un extracto repartido de toda su transcripcion."""
    summaries_by_session = {
        s.class_session_id: s
        for s in Summary.objects.filter(course=course, kind=Summary.Kind.STRUCTURED).exclude(class_session=None)
    }
    jobs = list(LessonJob.objects.filter(course=course).exclude(transcript="", source_text="").order_by("created_at"))
    jobs = jobs[-MAX_COURSE_CLASSES:]
    sessions = {
        s.legacy_lesson_job_id: s.pk
        for s in ClassSession.objects.filter(legacy_lesson_job__in=jobs)
    }
    pending = [job for job in jobs if sessions.get(job.pk) not in summaries_by_session]
    per_class = max(COURSE_SOURCE_CHARS // max(len(pending), 1), 1500) if pending else 0
    sections = []
    for job in jobs:
        summary = summaries_by_session.get(sessions.get(job.pk))
        if summary is not None:
            concepts = ", ".join(summary.key_concepts or [])
            sections.append((job.title, (f"Conceptos: {concepts}\n" if concepts else "") + summary.content))
            continue
        text = (job.transcript or job.source_text).strip()
        if text:
            sections.append((job.title, _spread_excerpt(text, per_class)))
    if not sections:
        for s in Summary.objects.filter(course=course, kind=Summary.Kind.STRUCTURED).order_by("created_at")[:MAX_COURSE_CLASSES]:
            sections.append((s.title, s.content))
    return sections


def _spread_excerpt(text: str, max_chars: int) -> str:
    """Extracto de inicio, medio y final (no solo el inicio) cuando la clase no tiene resumen propio."""
    if len(text) <= max_chars:
        return text
    third = max_chars // 3
    middle = len(text) // 2
    return " […] ".join([text[:third], text[middle - third // 2: middle + third // 2], text[-third:]])


def check_course_summary(course: Course) -> list[tuple[str, str]]:
    sections = _course_sections(course)
    if not sections:
        raise SummaryUnavailable("El curso no tiene clases con contenido para resumir.")
    return sections


def build_course_summary(user, course: Course, backend: str, sections=None) -> dict:
    from .adaptive import get_profile  # import perezoso (adaptive importa summaries)
    from .services import call_ai

    sections = sections or check_course_summary(course)
    profile_adaptive = get_profile(user, course)
    weak = list(profile_adaptive.weak_topics) if profile_adaptive else []
    raw = call_ai(build_course_summary_prompt(course, sections, weak), backend=backend, role="generation")
    parsed = parse_summary_response(raw, fallback_title=f"Resumen de {course.name}")
    if not parsed["content"]:
        raise RuntimeError("El modelo no devolvio contenido para el resumen.")
    return parsed


def store_course_summary(course: Course, parsed: dict) -> Summary:
    with transaction.atomic():
        summary, _ = Summary.objects.update_or_create(
            course=course, class_session=None, kind=Summary.Kind.COURSE_ACCUMULATED,
            defaults={"title": parsed["title"], "content": parsed["content"], "key_concepts": parsed["key_concepts"]},
        )
    return summary


def generate_course_summary(user, course: Course, backend: str = "auto") -> Summary:
    """Version sincrona del resumen acumulado; la cola usa run_summary_job."""
    from .services import resolve_backend

    sections = check_course_summary(course)
    resolved = resolve_backend(backend or "auto")
    profile, amount = _charge(user, course, None, resolved, f"curso {course.name}")
    try:
        parsed = build_course_summary(user, course, resolved, sections)
    except Exception as exc:
        refund_credits(profile, amount, course=course, description="Reembolso: resumen de curso fallido")
        logger.warning("Resumen de curso %s fallo: %s", course.pk, exc)
        raise SummaryUnavailable(f"No se pudo generar el resumen: {exc}") from exc
    return store_course_summary(course, parsed)


# ---------------------------------------------------------------------------
# Trabajos en cola (SummaryJob): la vista encola y el worker genera
# ---------------------------------------------------------------------------
def _job_log(current: str, stage: str, detail: str = "") -> str:
    stamp = timezone.localtime().strftime("%H:%M:%S")
    line = f"[{stamp}] {stage}" + (f" - {detail}" if detail else "")
    return f"{current}\n{line}".strip()


def pending_summary_job(course: Course, lesson: LessonJob | None = None) -> SummaryJob | None:
    qs = SummaryJob.objects.filter(course=course, status__in=[SummaryJob.Status.QUEUED, SummaryJob.Status.PROCESSING])
    qs = qs.filter(lesson=lesson) if lesson is not None else qs.filter(kind=SummaryJob.Kind.COURSE)
    return qs.first()


def latest_summary_job(course: Course, lesson: LessonJob | None = None) -> SummaryJob | None:
    qs = SummaryJob.objects.filter(course=course)
    qs = qs.filter(lesson=lesson) if lesson is not None else qs.filter(kind=SummaryJob.Kind.COURSE)
    return qs.first()


def summary_job_progress(job: SummaryJob | None) -> dict | None:
    """Estado legible de un resumen en curso: titulo, paso actual y cuantos trabajos de estudio van antes."""
    if job is None:
        return None
    from .models import ReinforcementJob

    if job.status == SummaryJob.Status.QUEUED:
        ahead = sum(
            model.objects.filter(status__in=[status.QUEUED, status.PROCESSING], created_at__lt=job.created_at).count()
            for model, status in ((SummaryJob, SummaryJob.Status), (ReinforcementJob, ReinforcementJob.Status))
        )
        step = (f"{ahead} resumen{'es' if ahead != 1 else ''} o refuerzo{'s' if ahead != 1 else ''} antes que el tuyo."
                if ahead else "Empieza en unos segundos.")
        return {"title": "En cola", "step": step, "percent": 10}
    detail = ""
    for line in reversed((job.processing_log or "").splitlines()):
        match = re.match(r"^\[[\d:]+\]\s+Procesando(?:\s+-\s+(.*))?$", line.strip())
        if match:
            detail = (match.group(1) or "").strip()
            break
    percent = 35
    part = re.search(r"parte (\d+) de (\d+)", detail)
    if part:
        done, total = int(part.group(1)), max(int(part.group(2)), 1)
        percent = 20 + int(65 * (done - 1) / total)
    elif detail.startswith("Escribiendo"):
        percent = 90
    return {"title": "Preparando tu resumen", "step": detail or "Leyendo la clase.", "percent": percent}


def create_summary_job(user, course: Course, lesson: LessonJob | None = None, backend: str = "auto") -> SummaryJob:
    """Valida, cobra los creditos y deja el trabajo en la cola. Si ya hay uno pendiente, lo devuelve sin cobrar."""
    from .services import resolve_backend

    pending = pending_summary_job(course, lesson)
    if pending is not None:
        return pending
    from .job_queue import TooManyPendingJobs, assert_user_can_enqueue  # import perezoso

    try:
        assert_user_can_enqueue(user)
    except TooManyPendingJobs as exc:
        raise SummaryUnavailable(str(exc)) from exc
    if lesson is not None:
        check_class_summary(lesson)
        session = _class_session_for(lesson, create=True)
        label = f"clase {lesson.title}"
    else:
        check_course_summary(course)
        session = None
        label = f"curso {course.name}"
    resolved = resolve_backend(backend or "auto")
    _profile, amount = _charge(user, course, session, resolved, label)
    job = SummaryJob.objects.create(
        user=user, course=course, lesson=lesson,
        kind=SummaryJob.Kind.CLASS if lesson is not None else SummaryJob.Kind.COURSE,
        backend=resolved, credits_charged=amount,
        processing_log=_job_log("", "En cola", f"{label} · backend {resolved} · {amount} creditos"),
    )
    from .job_queue import enqueue_summary_job  # import perezoso: job_queue importa este modulo

    try:
        enqueue_summary_job(job.pk)
    except RuntimeError as exc:  # cola llena
        job.status = SummaryJob.Status.ERROR
        job.error = str(exc)
        job.save(update_fields=["status", "error", "updated_at"])
        _refund_job(job)
        raise SummaryUnavailable(str(exc)) from exc
    return job


def run_summary_job(job: SummaryJob) -> SummaryJob:
    """La ejecuta el worker: genera, guarda y marca listo; ante error reembolsa."""
    job.status = SummaryJob.Status.PROCESSING
    job.processing_log = _job_log(job.processing_log, "Procesando", "Reuniendo el material.")
    job.save(update_fields=["status", "processing_log", "updated_at"])
    try:
        if job.kind == SummaryJob.Kind.CLASS:
            check_class_summary(job.lesson)
            session = _class_session_for(job.lesson, create=True)
            def progress(detail):
                job.processing_log = _job_log(job.processing_log, "Procesando", detail)
                job.save(update_fields=["processing_log", "updated_at"])

            parsed = build_class_summary(job.lesson, job.backend, on_progress=progress)
            summary = store_class_summary(job.lesson, session, parsed)
        else:
            parsed = build_course_summary(job.user, job.course, job.backend)
            summary = store_course_summary(job.course, parsed)
        job.summary = summary
        job.status = SummaryJob.Status.DONE
        job.error = ""
        job.completed_at = timezone.now()
        job.processing_log = _job_log(job.processing_log, "Listo", f"{len(parsed['key_concepts'])} conceptos clave.")
        job.save()
    except Exception as exc:  # noqa: BLE001 - queda en el trabajo y se reembolsa
        from .services import clean_ai_error

        logger.exception("Resumen %s fallo", job.pk)
        job.status = SummaryJob.Status.ERROR
        job.error = clean_ai_error(exc)
        job.processing_log = _job_log(job.processing_log, "Error", job.error)
        job.save(update_fields=["status", "error", "processing_log", "updated_at"])
        _refund_job(job)
    return job


def _refund_job(job: SummaryJob):
    if job.credits_charged <= 0 or job.credits_refunded:
        return
    profile, _ = Profile.objects.get_or_create(user=job.user)
    refund_credits(profile, job.credits_charged, course=job.course, description="Reembolso: el resumen fallo", metadata={"summary_job": job.pk})
    job.credits_refunded = True
    job.save(update_fields=["credits_refunded", "updated_at"])
