"""
Generacion adaptativa: refuerzo dirigido al perfil del estudiante.

A diferencia de la generacion inicial (que cubre toda la clase), el refuerzo
produce material nuevo a la medida de lo que el perfil dice que falla:

- items MINI sobre los temas debiles, en los niveles Bloom donde el estudiante
  falla y con dificultad IRT calibrada alrededor de su theta;
- una explicacion breve por concepto fallado, basada en la transcripcion de la
  clase (no en el enunciado del item);
- una flashcard por concepto, derivada de esa explicacion.

Todo sale de UNA llamada al modelo, en el mismo formato compacto: un bloque
MINI y un bloque de lineas `e<N>|tema|concepto|explicacion|pregunta|respuesta`.
Los items pasan por los mismos filtros deterministas del pipeline y se guardan
como Quiz de tipo "reinforcement" en el banco del curso.
"""
from __future__ import annotations

import logging
import re

from django.db import transaction
from django.utils import timezone

from .adaptive import get_profile, persist_items
from .credits import consume_credits, estimate_reinforcement_cost, has_enough_credits, refund_credits
from .models import (
    ClassSession,
    Difficulty,
    Flashcard,
    LessonJob,
    Profile,
    Quiz,
    Recommendation,
    ReinforcementJob,
    Summary,
)
from .parse_mini import filter_incoherent_items, filter_nonuniform_items, parse_mini
from .services import (
    _extract_keywords,
    _select_relevant_text,
    call_ai,
    clean_ai_error,
    extract_mini_lines,
    indent_content,
    read_prompt,
    resolve_backend,
)

logger = logging.getLogger(__name__)

DEFAULT_ITEMS = 8
MAX_ITEMS = 15
MAX_CONCEPTS = 6
MAX_SOURCE_CLASSES = 3
SOURCE_CONTEXT_CHARS = 7000
WEAK_BLOOM_THRESHOLD = 0.6
EXPLANATION_LINE = re.compile(r"^e\d+\|")


class ReinforcementUnavailable(RuntimeError):
    """No se puede generar refuerzo (sin temas debiles, sin creditos, sin fuentes)."""


# ---------------------------------------------------------------------------
# 1. Creacion del trabajo (cobra creditos y encola)
# ---------------------------------------------------------------------------
def create_reinforcement_job(user, course, practice_session=None, topics=None, requested_items: int = DEFAULT_ITEMS) -> ReinforcementJob:
    profile = get_profile(user, course)
    topics = [t for t in (topics or []) if t] or list(profile.weak_topics[:2])
    if not topics:
        raise ReinforcementUnavailable("Todavia no hay temas debiles identificados en este curso: practica primero.")
    if not _has_sources(course):
        raise ReinforcementUnavailable("El curso no tiene transcripciones ni texto de clase para generar refuerzo.")

    credit_profile, _ = Profile.objects.get_or_create(user=user)
    estimate = estimate_reinforcement_cost("auto")
    if not has_enough_credits(credit_profile, estimate.amount):
        raise ReinforcementUnavailable(f"Necesitas {estimate.amount} creditos para generar refuerzo.")

    try:
        requested = max(3, min(int(requested_items), MAX_ITEMS))
    except (TypeError, ValueError):
        requested = DEFAULT_ITEMS

    with transaction.atomic():
        entry = consume_credits(
            credit_profile,
            estimate.amount,
            action=estimate.action,
            course=course,
            description=f"Refuerzo adaptativo: {', '.join(topics)}",
            metadata={"topics": topics},
        )
        job = ReinforcementJob.objects.create(
            user=user,
            course=course,
            practice_session=practice_session,
            topics=topics,
            theta=profile.theta,
            requested_items=requested,
            credits_charged=entry.amount * -1 if entry else 0,
            processing_log=_log("", "En cola", f"Temas: {', '.join(topics)}. Habilidad estimada: {profile.theta:.2f}."),
        )
    from .job_queue import enqueue_reinforcement_job  # import perezoso: job_queue importa este modulo

    enqueue_reinforcement_job(job.pk)
    return job


def _has_sources(course) -> bool:
    return LessonJob.objects.filter(course=course).exclude(transcript="", source_text="").exists()


# ---------------------------------------------------------------------------
# 2. Contexto: fragmentos de las clases del curso relevantes a los temas
# ---------------------------------------------------------------------------
def _topic_keywords(topics: list[str], extra: list[str]) -> list[str]:
    words: list[str] = []
    for topic in topics:
        words.extend(w for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", topic.lower()))
    words.extend(_extract_keywords(" ".join(extra))[:12])
    seen: set[str] = set()
    return [w for w in words if not (w in seen or seen.add(w))]


def collect_source_context(course, topics: list[str], extra_terms: list[str], limit_chars: int = SOURCE_CONTEXT_CHARS) -> tuple[str, ClassSession | None]:
    keywords = _topic_keywords(topics, extra_terms)
    scored = []
    for job in LessonJob.objects.filter(course=course).exclude(transcript="", source_text="").order_by("-updated_at"):
        text = job.transcript or job.source_text
        lowered = text.lower()
        score = sum(lowered.count(k) for k in keywords)
        scored.append((score, job, text))
    if not scored:
        return "", None
    scored.sort(key=lambda row: row[0], reverse=True)
    chosen = [row for row in scored if row[0] > 0][:MAX_SOURCE_CLASSES] or scored[:1]
    per_class = max(limit_chars // len(chosen), 1200)
    chunks = []
    for _score, job, text in chosen:
        excerpt = _select_relevant_text(text, keywords, limit=per_class)
        if excerpt:
            chunks.append(f"[Clase: {job.title}]\n{excerpt}")
    session = None
    try:
        session = chosen[0][1].class_session
    except ClassSession.DoesNotExist:
        session = None
    return "\n\n".join(chunks), session


# ---------------------------------------------------------------------------
# 3. Prompt y parseo de la respuesta
# ---------------------------------------------------------------------------
def build_reinforcement_prompt(topics: list[str], bloom_focus: list[str], theta: float, n_items: int, context: str, avoid: list[str], concepts: list[str]) -> str:
    template = read_prompt("PROMPT.md")
    b_lo, b_hi = round(theta - 0.6, 1), round(theta + 0.6, 1)
    avoid_lines = "\n".join(f"  - {s}" for s in avoid[:8]) or "  - (ninguno)"
    concept_lines = "\n".join(f"  - {c}" for c in concepts) or "\n".join(f"  - {t}" for t in topics)
    blooms = ", ".join(bloom_focus) if bloom_focus else "L1, L2, L3"
    return (
        f"{template}\n\n"
        "MODO_REFUERZO_ADAPTATIVO:\n"
        f"- El estudiante falla en estos temas: {', '.join(topics)}. Genera items SOLO sobre esos temas.\n"
        f"- Prioriza los niveles Bloom {blooms}, donde su dominio es mas bajo.\n"
        f"- Su habilidad estimada es theta={theta:.2f}: calibra el parametro b de cada item entre {b_lo} y {b_hi}, "
        "para que sea desafiante pero alcanzable.\n"
        "- No repitas ni parafrasees estos enunciados ya evaluados:\n"
        f"{avoid_lines}\n"
        f"- Genera exactamente {n_items} items y declara n={n_items} en la cabecera.\n\n"
        "INPUT:\n"
        "  language: es\n"
        f"  items_requested: {n_items}\n"
        "  content: |\n"
        f"{indent_content(context)}\n\n"
        "Despues del bloque MINI agrega un bloque EXPLICACIONES: una linea por concepto, en este formato exacto, "
        "sin texto adicional antes ni despues:\n"
        "e<N>|<tema>|<concepto>|<explicacion de 2 a 4 oraciones basada en el contenido>|<pregunta breve para flashcard>|<respuesta breve>\n"
        "Conceptos a explicar:\n"
        f"{concept_lines}\n"
    )


def parse_explanations(raw: str) -> list[dict]:
    rows = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not EXPLANATION_LINE.match(line):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        topic, concept, explanation = parts[1], parts[2], parts[3]
        question = parts[4] if len(parts) > 4 and parts[4] else f"¿Que es {concept}?"
        answer = parts[5] if len(parts) > 5 and parts[5] else explanation.split(".")[0]
        if not (concept and explanation):
            continue
        rows.append({"topic": topic[:180], "concept": concept[:180], "explanation": explanation, "question": question, "answer": answer})
    return rows[:MAX_CONCEPTS]


def _ensure_mini_header(mini_text: str, topic: str) -> str:
    assessment = parse_mini(mini_text)
    lines = [item.raw for item in assessment.items]
    if not lines:
        return mini_text
    count = len(lines)
    header = assessment.header
    if not header or not header.startswith("a|"):
        header = f"a|m=IRT3PL|d={timezone.localdate():%Y%m%d}|n={count}|l=es|t={topic}|bd=0,0,0,0,0,0|cat=0,-3,3,0.3,10,SH"
    else:
        header = re.sub(r"\|n=\d+", f"|n={count}", header) if "|n=" in header else f"{header}|n={count}"
    return "\n".join([header, *lines])


def _log(current: str, stage: str, detail: str = "") -> str:
    stamp = timezone.localtime().strftime("%H:%M:%S")
    line = f"[{stamp}] {stage}" + (f" - {detail}" if detail else "")
    return f"{current}\n{line}".strip()


# ---------------------------------------------------------------------------
# 4. Ejecucion (la corre el worker de job_queue)
# ---------------------------------------------------------------------------
def run_reinforcement(job: ReinforcementJob) -> ReinforcementJob:
    job.status = ReinforcementJob.Status.PROCESSING
    job.processing_log = _log(job.processing_log, "Procesando", "Reuniendo fragmentos de las clases del curso.")
    job.save(update_fields=["status", "processing_log", "updated_at"])
    try:
        profile = get_profile(job.user, job.course)
        topics = list(job.topics or profile.weak_topics[:2])
        if not topics:
            raise ReinforcementUnavailable("No hay temas debiles identificados; practica primero.")

        bloom_focus = [
            level for level, info in sorted((profile.bloom_mastery or {}).items(), key=lambda kv: kv[1]["mastery"])
            if info.get("mastery", 1.0) < WEAK_BLOOM_THRESHOLD
        ][:2]
        failed = []
        if job.practice_session_id:
            failed = [row for row in (job.practice_session.feedback or {}).get("failed", []) if row.get("topic") in topics]
        avoid = [row["prompt"] for row in failed]
        concepts = [f"{row['topic']}: {row['prompt']}" for row in failed][:MAX_CONCEPTS] or topics

        context, session = collect_source_context(job.course, topics, avoid)
        if not context:
            raise ReinforcementUnavailable("El curso no tiene transcripciones para generar refuerzo.")

        prompt = build_reinforcement_prompt(topics, bloom_focus, job.theta, job.requested_items, context, avoid, concepts)
        backend = resolve_backend("auto")
        job.processing_log = _log(job.processing_log, "Generando", f"Backend {backend}, {job.requested_items} items sobre {', '.join(topics)}.")
        job.save(update_fields=["processing_log", "updated_at"])

        raw = call_ai(prompt, backend=backend, role="generation")
        mini_text = extract_mini_lines(raw) or raw
        mini_text = _ensure_mini_header(mini_text, topics[0])
        coherent, _dropped, _ = filter_incoherent_items(mini_text)
        uniform, _bad, _ = filter_nonuniform_items(coherent)
        assessment = parse_mini(uniform)
        if not assessment.items:
            raise RuntimeError("La IA no devolvio items validos de refuerzo.")

        with transaction.atomic():
            quiz = Quiz.objects.create(
                course=job.course,
                class_session=session,
                title=f"Refuerzo · {', '.join(topics)}"[:180],
                topic=topics[0][:180],
                quiz_type=Quiz.QuizType.REINFORCEMENT,
                mini_source=uniform,
                cat_config={"source": "reinforcement", "theta": job.theta, "topics": topics, "bloom_focus": bloom_focus},
            )
            kept = persist_items(quiz, assessment.items, default_topic=topics[0])
            summaries, cards = [], []
            for row in parse_explanations(raw):
                summary = Summary.objects.create(
                    course=job.course,
                    class_session=session,
                    kind=Summary.Kind.CONCEPT,
                    title=row["concept"],
                    content=row["explanation"],
                    key_concepts=[row["topic"]],
                )
                card = Flashcard.objects.create(
                    course=job.course,
                    class_session=session,
                    question=row["question"],
                    answer=row["answer"],
                    topic=row["topic"],
                    difficulty=Difficulty.MEDIUM,
                )
                summaries.append(summary.pk)
                cards.append(card.pk)
            job.quiz = quiz
            job.summary_ids = summaries
            job.flashcard_ids = cards
            job.status = ReinforcementJob.Status.DONE
            job.completed_at = timezone.now()
            job.error = ""
            job.processing_log = _log(
                job.processing_log, "Listo",
                f"{kept} preguntas nuevas, {len(summaries)} explicaciones, {len(cards)} flashcards.",
            )
            job.save()
            Recommendation.objects.get_or_create(
                user=job.user,
                course=job.course,
                status=Recommendation.Status.PENDING,
                title=f"Practica el refuerzo de «{topics[0]}»",
                defaults={
                    "message": f"Se generaron {kept} preguntas nuevas y {len(summaries)} explicaciones sobre {', '.join(topics)}. Lee las explicaciones y practica en modo refuerzo.",
                    "reason": "refuerzo generado",
                    "priority": 1,
                },
            )
    except Exception as exc:  # noqa: BLE001 - se registra en el job y se reembolsa
        logger.exception("Refuerzo %s fallo", job.pk)
        job.status = ReinforcementJob.Status.ERROR
        job.error = clean_ai_error(exc)
        job.processing_log = _log(job.processing_log, "Error", job.error)
        job.save(update_fields=["status", "error", "processing_log", "updated_at"])
        _refund(job)
    return job


def _refund(job: ReinforcementJob):
    if job.credits_charged <= 0 or job.credits_refunded:
        return
    profile, _ = Profile.objects.get_or_create(user=job.user)
    refund_credits(
        profile,
        job.credits_charged,
        course=job.course,
        description="Reembolso: el refuerzo adaptativo fallo",
        metadata={"reinforcement_job": job.pk},
    )
    job.credits_refunded = True
    job.save(update_fields=["credits_refunded", "updated_at"])
