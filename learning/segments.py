"""
Segmentos de transcripcion y su enlace con las preguntas.

Whisper entrega la transcripcion en segmentos con marcas de tiempo; cuando la
clase entro como texto, se generan ventanas de ~45 palabras sin tiempo. Cada
pregunta del banco se enlaza con el segmento que mas palabras clave comparte,
para que la retroalimentacion pueda mostrar "de donde sale" cada respuesta.
"""
from __future__ import annotations

import re

from .models import ClassSession, LessonJob, Question, Quiz, Transcript, TranscriptSegment

WINDOW_WORDS = 45
MIN_OVERLAP = 2
EXCERPT_CHARS = 320
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}")
_STOP = {
    "sobre", "entre", "desde", "hasta", "donde", "cuando", "porque", "tiene", "tienen", "puede",
    "pueden", "hacia", "cual", "cuales", "como", "para", "pero", "este", "esta", "estos", "estas",
    "esos", "esas", "aquel", "cada", "todo", "todos", "toda", "todas", "muy", "mas", "menos",
    "tambien", "entonces", "ahora", "siempre", "nunca", "algo", "otro", "otra", "otros", "otras",
    "pregunta", "respuesta", "opcion", "opciones", "correcta", "siguiente", "siguientes",
}


def keywords(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "") if w.lower() not in _STOP}


def build_segments_from_text(text: str, window_words: int = WINDOW_WORDS) -> list[dict]:
    """Ventanas de texto sin marcas de tiempo, solapadas un tercio para no cortar ideas en el borde."""
    words = (text or "").split()
    step = max(1, window_words - window_words // 3)
    segments = []
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + window_words]).strip()
        if chunk:
            segments.append({"start": None, "end": None, "text": chunk, "order": len(segments)})
        if i + window_words >= len(words):
            break
    return segments


def normalize_whisper_result(result: dict) -> tuple[str, list[dict]]:
    """Texto completo y segmentos (start, end, text) a partir del dict de Whisper."""
    text = (result.get("text") or "").strip()
    segments = []
    for order, seg in enumerate(result.get("segments") or []):
        seg_text = (seg.get("text") or "").strip()
        if not seg_text:
            continue
        segments.append({
            "start": float(seg.get("start") or 0.0),
            "end": float(seg.get("end") or 0.0),
            "text": seg_text,
            "order": order,
        })
    return text, segments


def store_segments(transcript: Transcript, segments: list[dict]) -> int:
    """Reemplaza los segmentos guardados de una transcripcion."""
    transcript.segments.all().delete()
    rows = [
        TranscriptSegment(
            transcript=transcript,
            start_seconds=seg.get("start") or 0.0,
            end_seconds=seg.get("end") or 0.0,
            text=seg["text"],
            order=seg.get("order", i),
        )
        for i, seg in enumerate(segments)
    ]
    TranscriptSegment.objects.bulk_create(rows)
    return len(rows)


def segments_for_session(session: ClassSession | None, job: LessonJob | None = None) -> list[dict]:
    """Segmentos con tiempo si existen; si no, ventanas del texto de la clase."""
    if session is not None:
        try:
            transcript = session.transcript_record
        except Transcript.DoesNotExist:
            transcript = None
        if transcript is not None:
            stored = list(transcript.segments.all())
            if stored:
                return [{"start": s.start_seconds, "end": s.end_seconds, "text": s.text, "order": s.order} for s in stored]
            if transcript.full_text.strip():
                return build_segments_from_text(transcript.full_text)
    if job is not None:
        return build_segments_from_text(job.transcript or job.source_text or "")
    return []


def best_segment(question_text: str, segments: list[dict]) -> dict | None:
    """Segmento con mayor solapamiento de palabras clave; None si no hay senal suficiente."""
    wanted = keywords(question_text)
    if not wanted or not segments:
        return None
    best, best_score = None, 0
    for seg in segments:
        score = len(wanted & keywords(seg["text"]))
        if score > best_score:
            best, best_score = seg, score
    return best if best_score >= MIN_OVERLAP else None


def format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def attach_sources(quiz: Quiz, session: ClassSession | None, job: LessonJob | None = None, force: bool = False) -> int:
    """
    Enlaza cada pregunta del quiz con el fragmento de la clase que la respalda
    (extracto y, si existe, marca de tiempo). Devuelve cuantas se enlazaron.
    """
    segments = segments_for_session(session, job)
    if not segments:
        return 0
    linked = 0
    for question in quiz.questions.all():
        if question.source_excerpt and not force:
            continue
        correct = question.options.filter(is_correct=True).first()
        probe = f"{question.topic} {question.prompt} {correct.text if correct else ''}"
        seg = best_segment(probe, segments)
        if seg is None:
            continue
        question.source_excerpt = seg["text"][:EXCERPT_CHARS]
        question.source_timestamp_seconds = seg.get("start")
        question.save(update_fields=["source_excerpt", "source_timestamp_seconds"])
        linked += 1
    return linked
