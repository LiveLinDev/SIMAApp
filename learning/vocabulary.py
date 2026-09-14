"""Vocabulario del curso y correccion de terminos mal transcritos.

Whisper escribe mal los terminos tecnicos que no conoce (p. ej. "hemoglovina", "taqui cardia") y repite el
mismo error cada vez que aparece la palabra. Este modulo ataca el problema en dos puntos:

1. Antes de transcribir: `whisper_prompt()` arma un contexto corto con el curso y sus terminos para que
   Whisper los escriba bien desde el inicio.
2. Despues de transcribir: `correct_transcript_vocabulary()` pide a un modelo, por partes, SOLO la lista de
   palabras mal transcritas y su forma correcta (no reescribe la clase). Las correcciones se validan (deben
   aparecer en el texto y parecerse a la palabra original), se aplican en TODA la transcripcion y los terminos
   corregidos se suman al vocabulario del curso para las clases siguientes.
"""
from __future__ import annotations

import difflib
import logging
import re
import unicodedata

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_TERMS = 120
MAX_VOCABULARY_CHARS = 3000
MAX_PAIR_WORDS = 6
MIN_SIMILARITY = 0.6


# ------------------------------------------------------------------------------------------ terminos
def split_terms(text: str) -> list[str]:
    terms, seen = [], set()
    for raw in re.split(r"[,;\n]+", text or ""):
        term = " ".join(raw.split()).strip(" .:-")
        key = term.lower()
        if term and len(term) <= 60 and key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def course_terms(course) -> list[str]:
    if course is None:
        return []
    terms = split_terms(getattr(course, "vocabulary", "") or "")
    seen = {t.lower() for t in terms}
    for topic in course.main_topics or []:
        topic = " ".join(str(topic).split())
        if topic and topic.lower() not in seen:
            seen.add(topic.lower())
            terms.append(topic)
    return terms[:MAX_TERMS]


def whisper_prompt(job) -> str:
    """Contexto para Whisper: curso, clase y terminos. Whisper imita la ortografia de este texto."""
    course = getattr(job, "course", None)
    parts = []
    if course is not None:
        parts.append(f"Clase universitaria de {course.name}.")
    if getattr(job, "title", ""):
        parts.append(f"Tema: {job.title}.")
    terms = course_terms(course)
    if terms:
        parts.append("Términos: " + ", ".join(terms) + ".")
    return " ".join(parts)


def learn_terms(course, terms: list[str]) -> list[str]:
    """Agrega al vocabulario del curso los terminos nuevos. Devuelve los que se agregaron."""
    if course is None or not terms:
        return []
    current = split_terms(course.vocabulary or "")
    known = {t.lower() for t in current}
    added = []
    for term in terms:
        term = " ".join(term.split())
        if term and term.lower() not in known and len(term) <= 60:
            known.add(term.lower())
            current.append(term)
            added.append(term)
    if not added:
        return []
    text = ", ".join(current)
    while len(text) > MAX_VOCABULARY_CHARS and len(current) > 1:
        current.pop(0)  # se descartan los mas antiguos
        text = ", ".join(current)
    course.vocabulary = text
    course.save(update_fields=["vocabulary", "updated_at"])
    return added


# ------------------------------------------------------------------------------------------ correccion
def build_vocabulary_prompt(chunk: str, course_name: str, title: str, terms: list[str], part: str = "") -> str:
    vocabulary = ", ".join(terms) if terms else "(sin vocabulario registrado)"
    return (
        "Revisas la transcripcion automatica de una clase universitaria en espanol. Whisper escribe mal "
        "terminos tecnicos (anatomia, farmacos, enfermedades, formulas, nombres propios, siglas) y repite el error.\n"
        "Devuelve SOLO la lista de palabras o frases mal transcritas con su forma correcta, una por linea:\n"
        "x|<texto exactamente como aparece en la transcripcion>|<forma correcta>|<t si es un termino tecnico del area, g si es una palabra general>\n\n"
        "Reglas:\n"
        "- Corrige solo errores de transcripcion u ortografia de terminos del area (incluidas tildes y palabras partidas).\n"
        "- No cambies estilo, puntuacion, muletillas ni gramatica, y no pongas sinonimos.\n"
        "- El texto de la izquierda debe copiarse tal cual aparece, de 1 a 6 palabras.\n"
        "- Si no estas seguro, no lo incluyas. Si no hay errores responde solo: ok\n\n"
        f"CURSO: {course_name or '(sin curso)'}\n"
        f"CLASE: {title}\n"
        f"VOCABULARIO DEL CURSO (ortografia correcta): {vocabulary}\n\n"
        f"TRANSCRIPCION{(' ' + part) if part else ''}:\n{chunk}\n"
    )


def parse_corrections(raw: str, with_kind: bool = False) -> list[tuple]:
    """Lee pares mal|bien. Tolera variantes frecuentes de los modelos: lineas numeradas ("1|a|b", "1. a|b"),
    vinetas y flechas ("a -> b", "a → b")."""
    pairs = []
    for line in (raw or "").splitlines():
        line = line.strip().strip("`").strip()
        if not line or line.lower() in {"ok", "ok."}:
            continue
        line = re.sub(r"^(?:[-*•]\s*|\d+[.)]\s+)", "", line)
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if parts and (parts[0].lower() == "x" or parts[0].isdigit()):
                parts = parts[1:]
        else:
            parts = [p.strip() for p in re.split(r"\s*(?:->|→|=>)\s*", line)]
        parts = [p.strip("\"'“”«»") for p in parts if p.strip()]
        kind = ""
        if len(parts) == 3 and parts[2].lower() in {"t", "g"}:
            kind = parts.pop().lower()
        if len(parts) != 2:
            continue
        wrong, right = parts
        if wrong and right:
            pairs.append((wrong, right, kind) if with_kind else (wrong, right))
    return pairs


def _letters(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if ch.isalnum())


def _pattern(wrong: str) -> re.Pattern:
    words = [re.escape(w) for w in wrong.split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)", re.IGNORECASE)


def valid_pair(wrong: str, right: str, text: str) -> bool:
    wrong_words, right_words = wrong.split(), right.split()
    if not (1 <= len(wrong_words) <= MAX_PAIR_WORDS and 1 <= len(right_words) <= MAX_PAIR_WORDS):
        return False
    if wrong == right:
        return False
    a, b = _letters(wrong), _letters(right)
    if not a or not b:
        return False
    if len(b) < 0.75 * len(a):
        return False  # una correccion no borra buena parte de lo dicho
    if a != b:
        # se acepta un error de transcripcion (sonido parecido), no un cambio de palabra
        if difflib.SequenceMatcher(None, a, b).ratio() < MIN_SIMILARITY:
            return False
    elif wrong.lower() == right.lower():
        return False  # solo mayusculas: no se toca
    return bool(_pattern(wrong).search(text))


def _match_case(original: str, replacement: str) -> str:
    if original[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply_corrections(text: str, pairs: list[tuple[str, str]]) -> tuple[str, list[dict]]:
    """Aplica cada correccion en todo el texto (las frases largas primero). Devuelve texto y detalle."""
    applied = []
    for wrong, right in sorted(pairs, key=lambda p: -len(p[0])):
        pattern = _pattern(wrong)
        text, count = pattern.subn(lambda m, r=right: _match_case(m.group(0), r), text)
        if count:
            applied.append({"before": wrong, "after": right, "count": count})
    return text, applied


def merge_pairs(pairs: list[tuple], text: str) -> list[tuple[str, str]]:
    merged, seen = [], {}
    for pair in pairs:
        wrong, right = pair[0], pair[1]
        key = wrong.lower()
        if key in seen:
            continue  # la primera propuesta gana; propuestas en conflicto no se mezclan
        if valid_pair(wrong, right, text):
            seen[key] = right
            merged.append((wrong, right))
    return merged


def split_spans(text: str, max_words: int) -> list[tuple[int, int]]:
    """Parte el texto en tramos contiguos de ~max_words palabras, cortando al final de una oracion cuando se
    puede. Los tramos cubren todo el texto, asi al unirlos se conserva el formato original."""
    words = list(re.finditer(r"\S+", text))
    if len(words) <= max_words:
        return [(0, len(text))]
    spans, start, index = [], 0, 0
    while index < len(words):
        cut = min(index + max_words, len(words))
        if cut < len(words):
            window_start = max(index + int(max_words * 0.8), index + 1)
            for j in range(cut - 1, window_start - 1, -1):
                if words[j].group().endswith((".", "?", "!", "…")):
                    cut = j + 1
                    break
        end = len(text) if cut >= len(words) else words[cut].start()
        spans.append((start, end))
        start, index = end, cut
    return spans


def correct_transcript_vocabulary(transcript: str, course=None, title: str = "", backend: str = "cloud",
                                  on_progress=None) -> dict:
    """Corrige terminos mal transcritos. Devuelve {"text", "applied", "chunks", "errors", "learned_terms"}.

    Cada parte se revisa por separado y sus correcciones se aplican solo en esa parte: un error repetido se
    corrige en todas sus apariciones de esa parte, sin arriesgar cambios en otras partes donde la misma
    palabra puede estar bien usada. Solo los terminos marcados como tecnicos pasan al vocabulario del curso.
    """
    from .services import call_ai

    text = transcript or ""
    result = {"text": text, "applied": [], "chunks": 0, "errors": 0, "learned_terms": []}
    if not text.strip():
        return result
    chunk_words = max(300, int(getattr(settings, "TRANSCRIPT_VOCABULARY_CHUNK_WORDS", 1800)))
    spans = split_spans(text, chunk_words)
    terms = course_terms(course)
    pieces, totals, technical = [], {}, []
    for index, (start, end) in enumerate(spans, start=1):
        chunk = text[start:end]
        if on_progress:
            on_progress(index, len(spans))
        part = f"(parte {index} de {len(spans)})" if len(spans) > 1 else ""
        prompt = build_vocabulary_prompt(chunk, getattr(course, "name", ""), title, terms, part)
        try:
            raw = call_ai(prompt, backend=backend, role="transcript", max_tokens=1200)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Revision de vocabulario parte %s/%s fallo: %s", index, len(spans), exc)
            result["errors"] += 1
            pieces.append(chunk)
            continue
        proposals = parse_corrections(raw, with_kind=True)
        kinds = {wrong.lower(): kind for wrong, _right, kind in proposals}
        pairs = merge_pairs(proposals, chunk)
        fixed, applied = apply_corrections(chunk, pairs)
        pieces.append(fixed)
        for item in applied:
            key = (item["before"], item["after"])
            totals[key] = totals.get(key, 0) + item["count"]
            if kinds.get(item["before"].lower()) == "t" and item["after"] not in technical:
                technical.append(item["after"])
    result["chunks"] = len(spans)
    result["text"] = "".join(pieces)
    result["applied"] = [{"before": b, "after": a, "count": c} for (b, a), c in totals.items()]
    result["learned_terms"] = technical
    return result


def correct_segments(segments: list[dict] | None, applied: list[dict]) -> list[dict] | None:
    """Aplica a los segmentos con tiempo las mismas correcciones que al texto completo."""
    if not segments or not applied:
        return segments
    pairs = [(item["before"], item["after"]) for item in applied]
    fixed = []
    for segment in segments:
        segment = dict(segment)
        segment["text"], _ = apply_corrections(segment.get("text") or "", pairs)
        fixed.append(segment)
    return fixed
