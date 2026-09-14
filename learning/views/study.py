"""Estudio: flashcards, repaso SM-2 por curso, ejercicios y mapa de la clase."""
from __future__ import annotations

import csv
import json
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.db import connection
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from .. import adaptive, adaptive_generation, progress, summaries
from .. import spaced_repetition
from ..cat import BLOOM_LABELS, build_bank, choose_next_item, estimate_theta, option_index, parse_cat_params, theta_to_level
from ..credits import (
    REGENERATION_COST,
    consume_credits,
    estimate_lesson_job_cost,
    grant_plan_credits,
    has_enough_credits,
)
from ..forms import ApiLessonForm, CourseForm, FreeLessonForm, ManualResultForm, PlanForm, RegisterForm, VerificationResultForm
from ..job_queue import enqueue_lesson_job
from ..models import ClassSession, Course, Difficulty, Flashcard, LessonJob, UserPreference, get_plan_details
from ..parse_mini import apply_corrections_with_trace, assessment_to_dict, filter_incoherent_items, normalize_mini_text, parse_mini, render_mini_html, validate_mini_parse
from ..services import (
    build_generation_prompt,
    build_verification_prompt,
    clean_ai_error,
    extract_mini_lines,
    get_available_backends,
    normalize_backend,
    repair_mini_coherence,
    repair_transcript_text,
    text_change_summary,
)
import random

from ._common import (
    _get_accessible_job,
    _safe_class_session,
    _sync_class_session_for_job,
)


@login_required
def flashcards(request, pk):
    job = _get_accessible_job(request.user, pk)
    # obtener o generar flashcards desde el MINI
    session = _safe_class_session(job)
    if not session and job.course_id:
        session = _sync_class_session_for_job(job)
    cards = list(Flashcard.objects.filter(class_session=session).order_by("?") if session else [])
    if not cards and (job.corrected_output or job.toon_output):
        cards = _ensure_flashcards_from_mini(job, session)
    return render(request, "learning/flashcards.html", {
        "job": job,
        "cards": cards,
        "card_count": len(cards),
        "is_owner": job.user_id == request.user.id,
    })


@login_required
def review_flashcard(request, pk):
    if request.method != "POST":
        raise Http404()
    job = _get_accessible_job(request.user, pk)
    return _rate_flashcard(request, course=job.course, redirect_to=("flashcards", job.pk))


def _rate_flashcard(request, course, redirect_to):
    """Aplica SM-2 a una tarjeta del curso del usuario y registra la actividad."""
    try:
        flashcard_id = int(request.POST.get("flashcard_id", 0))
    except (TypeError, ValueError):
        raise Http404()
    flashcard = get_object_or_404(Flashcard, pk=flashcard_id, course__user=request.user)
    grade = request.POST.get("difficulty", "medium")
    spaced_repetition.sm2_update(flashcard, grade)
    adaptive.register_activity(
        request.user, flashcard.course, adaptive.StudyActivity.ActivityType.FLASHCARDS_REVIEWED,
        xp=2, metadata={"flashcard": flashcard.pk, "grade": grade, "interval_days": flashcard.interval_days},
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "mastery": flashcard.mastery_level,
            "interval_days": flashcard.interval_days,
            "next_review": flashcard.next_review_at.isoformat() if flashcard.next_review_at else None,
        })
    name, arg = redirect_to
    return redirect(name, arg)


@login_required
def matching_exercise(request, pk):
    import json
    job = _get_accessible_job(request.user, pk)
    session = _safe_class_session(job)
    if not session and job.course_id:
        session = _sync_class_session_for_job(job)
    cards = list(Flashcard.objects.filter(class_session=session).order_by("?")[:8])
    if not cards and (job.corrected_output or job.toon_output):
        cards = _ensure_flashcards_from_mini(job, session)
        cards = list(Flashcard.objects.filter(class_session=session).order_by("?")[:8])
    pairs = []
    for c in cards:
        pairs.append({"id": c.pk, "concept": c.question, "definition": c.answer})
    definitions = [p["definition"] for p in pairs]
    random.shuffle(definitions)
    return render(request, "learning/matching_exercise.html", {
        "job": job,
        "pairs": pairs,
        "definitions": definitions,
        "pairs_json": json.dumps(pairs, ensure_ascii=False),
        "definitions_json": json.dumps(definitions, ensure_ascii=False),
        "is_owner": job.user_id == request.user.id,
    })


@login_required
def cloze_exercise(request, pk):
    job = _get_accessible_job(request.user, pk)
    session = _safe_class_session(job)
    if not session and job.course_id:
        session = _sync_class_session_for_job(job)
    cards = list(Flashcard.objects.filter(class_session=session).order_by("?")[:8])
    if not cards and (job.corrected_output or job.toon_output):
        cards = _ensure_flashcards_from_mini(job, session)
        cards = list(Flashcard.objects.filter(class_session=session).order_by("?")[:8])
    items = []
    for c in cards:
        prompt = c.question
        if "____" in prompt or "___" in prompt or "__" in prompt:
            items.append({"id": c.pk, "prompt": prompt, "answer": c.answer})
        else:
            # Transformar definición en cloze simple si no tiene blank
            items.append({"id": c.pk, "prompt": f"{c.question} ____", "answer": c.answer})
    return render(request, "learning/cloze_exercise.html", {
        "job": job,
        "items": items,
        "is_owner": job.user_id == request.user.id,
    })


def _ensure_flashcards_from_mini(job: LessonJob, session: ClassSession | None) -> list[Flashcard]:
    """Genera flashcards básicas desde los ítems MINI si no existen."""
    mini_text = job.corrected_output or job.toon_output
    if not mini_text:
        return []
    from ..parse_mini import parse_mini as _parse
    assessment = _parse(mini_text)
    created = []
    for item in assessment.items:
        def _is_correct(opt):
            return opt.get("correct") if isinstance(opt, dict) else getattr(opt, "correct", False)
        def _opt_text(opt):
            return opt.get("text", "") if isinstance(opt, dict) else getattr(opt, "text", "")
        correct = [opt for opt in item.options if _is_correct(opt)]
        answer_text = _opt_text(correct[0]) if correct else (_opt_text(item.options[0]) if item.options else "")
        topic = item.topic or job.tags.split(",")[0].strip() if job.tags else ""
        card, _ = Flashcard.objects.get_or_create(
            class_session=session,
            question=item.statement,
            defaults={
                "course": job.course,
                "answer": answer_text,
                "topic": topic,
                "difficulty": Difficulty.MEDIUM,
            },
        )
        created.append(card)
    return created


@login_required
def class_map(request, pk):
    job = _get_accessible_job(request.user, pk)
    session = _safe_class_session(job)
    if not session and job.course_id:
        session = _sync_class_session_for_job(job)
    topics = []
    concepts = []
    # Conceptos: solo los del resumen de la clase, que salen de leer la clase completa. Sin resumen el mapa
    # muestra los temas de las preguntas; ya no se arman conceptos con respuestas o enunciados recortados.
    from ..summaries import class_summary_for

    class_summary = class_summary_for(job) if job.course_id else None
    for concept in (class_summary.key_concepts if class_summary else []) or []:
        _add_map_term(concepts, concept, max_words=6, max_chars=70)

    bloom_counts = {}
    if job.corrected_output or job.toon_output:
        from ..parse_mini import parse_mini as _parse
        assessment = _parse(job.corrected_output or job.toon_output)
        for item in assessment.items:
            _add_map_term(topics, item.topic)
            bloom_counts[item.bloom] = bloom_counts.get(item.bloom, 0) + 1
    cards = list(Flashcard.objects.filter(class_session=session) if session else [])
    for card in cards:
        _add_map_term(topics, card.topic)
    max_bloom = max(bloom_counts.values()) if bloom_counts else 1
    bloom_chart_data = [
        {"label": BLOOM_LABELS.get(level, level), "count": count, "pct": round((count / max_bloom) * 100) if max_bloom else 0}
        for level, count in sorted(bloom_counts.items())
    ]
    return render(request, "learning/class_map.html", {
        "job": job,
        "topics": sorted(topics, key=str.lower),
        "concepts": concepts[:24],
        "bloom_chart_data": bloom_chart_data,
        "card_count": len(concepts),
        "is_owner": job.user_id == request.user.id,
    })


_GENERIC_MAP_TERMS = {
    "recordar", "recuerda", "recordando", "remember", "recall",
    "comprender", "comprension", "comprensión", "understand", "understanding",
    "aplicar", "aplicacion", "aplicación", "apply", "applying",
    "analizar", "analisis", "análisis", "analyze", "analysing", "analysis",
    "evaluar", "evaluacion", "evaluación", "evaluate", "evaluation",
    "crear", "creacion", "creación", "create", "creating",
    "bloom", "nivel", "levels", "level", "pregunta", "respuesta", "opcion", "item",
}


_MAP_STOPWORDS = {
    "a", "al", "ante", "bajo", "con", "contra", "de", "del", "desde", "durante", "e", "el", "ella",
    "en", "entre", "es", "esa", "ese", "esta", "este", "esto", "estos", "la", "las", "lo", "los",
    "para", "por", "que", "se", "segun", "sin", "sobre", "su", "sus", "un", "una", "unas", "uno", "unos",
    "cual", "cuales", "cuando", "donde", "como", "porque", "siguiente", "siguientes", "principal",
    "indica", "identifica", "selecciona", "corresponde", "relaciona", "define", "explica", "verdadero",
    "falso", "correcta", "correcto", "incorrecta", "incorrecto", "mejor", "mayor", "menor",
    "what", "which", "when", "where", "how", "why", "the", "and", "or", "of", "to", "in", "for",
}


def _is_generic_term(term: str) -> bool:
    compact = re.sub(r"\s+", " ", str(term or "").strip(" -:;.,¿?¡!()[]{}\"'`")).strip()
    if not compact:
        return True
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", compact.lower())
    if not words:
        return True
    meaningful = [word for word in words if word not in _MAP_STOPWORDS]
    if not meaningful:
        return True
    normalized = " ".join(meaningful)
    return normalized in _GENERIC_MAP_TERMS or all(word in _GENERIC_MAP_TERMS for word in meaningful)


def _add_map_term(collection: list[str], term: str, max_words: int = 6, max_chars: int = 80):
    compact = re.sub(r"\s+", " ", str(term or "").replace("_", " ").strip()).strip(" -:;.,¿?¡!()[]{}\"'`")
    if not compact or _is_generic_term(compact):
        return
    words = compact.split()
    if len(words) > max_words or len(compact) > max_chars:
        compact = " ".join(words[:max_words]).strip(" -:;.,")
    if _is_generic_term(compact):
        return
    key = compact.lower()
    if key not in {value.lower() for value in collection}:
        collection.append(compact)


_MAP_STOPWORDS.update({
    "capta", "captar", "libera", "liberan", "liberado", "ocurre", "principalmente",
    "respuesta", "pregunta", "alternativa", "opciones",
})


def _extract_statement_terms(statement: str) -> list[str]:
    text = re.sub(r"[_|]", " ", str(statement or ""))
    text = re.sub(r"[¿?¡!]", " ", text)
    quoted = re.findall(r"['\"]([^'\"]{4,70})['\"]", text)
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text)
    candidates = [*quoted]
    for word in words:
        lowered = word.lower()
        if len(word) <= 3 or lowered in _MAP_STOPWORDS or lowered in _GENERIC_MAP_TERMS:
            continue
        candidates.append(word)
    unique = []
    for candidate in candidates:
        compact = re.sub(r"\s+", " ", candidate.strip()).strip(" -:;.,")
        if compact and not _is_generic_term(compact) and compact.lower() not in {value.lower() for value in unique}:
            unique.append(compact)
    return unique[:4]


@login_required
def course_review(request, pk):
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    cards = spaced_repetition.review_queue(course)
    return render(request, "learning/course_review.html", {
        "course": course,
        "cards": cards,
        "card_count": len(cards),
        "due_count": spaced_repetition.due_count(course),
    })


@login_required
def course_review_card(request, pk):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    return _rate_flashcard(request, course=course, redirect_to=("course_review", course.pk))
