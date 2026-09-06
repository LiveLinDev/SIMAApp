"""Prompts del pipeline (generacion, verificacion, coherencia, reparacion de transcripcion) y limpieza del contenido."""
from __future__ import annotations

from pathlib import Path
import re

from django.conf import settings



BASE_DIR = Path(settings.BASE_DIR)


def read_prompt(filename):
    path = BASE_DIR / filename
    return path.read_text(encoding="utf-8")


def indent_content(content):
    return "\n".join(f"    {line}" for line in content.splitlines())


def strip_non_academic_content_noise(content: str) -> str:
    """
    Elimina frases de publicidad, intro/outro y referencias al medio antes de
    generar MINI. Si el filtro se pasa de agresivo, conserva el texto original.
    """
    text = (content or "").strip()
    if not text:
        return ""

    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    kept = []
    for part in parts:
        sentence = part.strip()
        if not sentence:
            continue
        normalized = _normalize_noise_text(sentence)
        if any(marker in normalized for marker in _NON_ACADEMIC_CONTENT_MARKERS):
            continue
        kept.append(sentence)

    cleaned = "\n".join(kept).strip()
    original_words = len(text.split())
    cleaned_words = len(cleaned.split())
    if cleaned_words < 80 or cleaned_words < original_words * 0.35:
        return text
    return cleaned


def _normalize_noise_text(value: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.lower()).strip()


_NON_ACADEMIC_CONTENT_MARKERS = {
    "cabefai", "cabify", "universidad primada", "universidad privada",
    "san juan bautista", "admision", "520 soles", "estudianla sanjuan",
    "estudianlasanjuan", "este video llega gracias", "espero que este video",
    "video explicativo", "intentar hacer un video", "en el video", "del video",
    "si este video", "soy norlin", "soy merlin", "soy marlin", "detras de esa camara",
    "detras de camara", "detras de la camara", "dale like", "suscribete", "suscribirse", "comenta",
    "comentarios", "biblioteca de merlin", "biblioteca de marlin", "libreria solo para fumadores",
    "solo para fumadores", "visita sus redes", "redes sociales", "novedades editoriales",
    "auspiciador", "publicidad", "patreon", "instagram", "tiktok",
}


def build_generation_prompt(content, language="es", items_requested="auto", chunk_info=None, cloud_optimized=False):
    """
    Construye el prompt de generación.
    chunk_info solo se incluye cuando hay chunking (backend local con contenido largo).
    """
    template = read_prompt("PROMPT.md")
    chunk_line = f"  chunk: {chunk_info}\n" if chunk_info else ""
    prompt = (
        f"{template}\n\n"
        "INPUT:\n"
        f"  language: {language}\n"
        f"  items_requested: {items_requested}\n"
        f"{chunk_line}"
        "  content: |\n"
        f"{indent_content(content)}"
    )
    if cloud_optimized:
        prompt = f"{prompt}\n\n{cloud_generation_instructions()}"
    return prompt


def cloud_generation_instructions() -> str:
    return (
        "MODO_CLOUD_MINI_DIRECTO:\n"
        "- Usa la mayor capacidad del modelo cloud para entregar un MINI final ya auditado.\n"
        "- Antes de emitir, limpia mentalmente anuncios, sponsors, intro/outro, canal, narrador, likes, comentarios y referencias al video/clase.\n"
        "- Genera preguntas solo sobre conceptos academicos del tema central y hechos respaldados por la transcripcion.\n"
        "- No hagas preguntas sobre la importancia del video, sobre lo que critica el video, ni sobre acciones sugeridas al final.\n"
        "- Si detectas un candidato ambiguo, sustituyelo por otro concepto claro del contenido.\n"
        "- Verifica internamente que cada opcion correcta responde al enunciado y que los distractores son de la misma categoria.\n"
        "- Devuelve solo MINI: una cabecera a| y las lineas i<N>|. No incluyas razonamiento ni reporte de auditoria."
    )


def build_verification_prompt(mini_content, source_context=""):
    template = read_prompt("verify_prompt.md")
    source_block = ""
    if source_context:
        source_block = (
            "\n\nCONTEXTO_DE_VERIFICACION_FETCHED:\n"
            "Usa estas fuentes como contexto externo. Si una fuente no respalda una corrección, no la cites.\n"
            f"{source_context}"
        )
    return f"{template}{source_block}\n\nMINI_A_VERIFICAR:\n{mini_content}"


def build_coherence_prompt(mini_content: str, source_context: str = "") -> str:
    template = read_prompt("coherence_prompt.md")
    context = source_context.strip() or "Sin contexto adicional; usa solo el MINI actual."
    return (
        f"{template}\n\n"
        "CONTEXTO_ORIGEN:\n"
        f"{context}\n\n"
        "MINI_ACTUAL:\n"
        f"{mini_content}"
    )


def build_transcript_repair_prompt(transcript: str, source_context: str = "") -> str:
    template = read_prompt("transcript_prompt.md")
    context = source_context.strip() or "Sin contexto adicional; usa solo la transcripcion."
    return (
        f"{template}\n\n"
        "CONTEXTO:\n"
        f"{context}\n\n"
        "TRANSCRIPCION_A_CORREGIR:\n"
        f"{transcript}"
    )
