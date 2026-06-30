from pathlib import Path
import csv
import difflib
import json
import math
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from django.conf import settings


BASE_DIR = Path(settings.BASE_DIR)
_EDUQG_CACHE = {}


class LocalAITimeoutError(RuntimeError):
    """El servidor de IA local no respondio dentro del timeout configurado."""

# import diferido para evitar circular imports
def _get_merge_fn():
    from .parse_mini import merge_mini_chunks
    return merge_mini_chunks


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


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip())

    def text(self):
        return re.sub(r"\s+", " ", unescape(" ".join(self.parts))).strip()


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


def chunk_content(text: str, max_words: int = 2000) -> list[str]:
    """
    Divide el texto en chunks de max_words palabras respetando párrafos.
    Un chunk de ~2000 palabras genera ~20-25 ítems de calidad.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = []
    current_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if para_words > max_words:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_words = 0
            words = para.split()
            for start in range(0, len(words), max_words):
                chunks.append(" ".join(words[start:start + max_words]))
            continue
        if current_words + para_words > max_words and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_words = para_words
        else:
            current.append(para)
            current_words += para_words

    if current:
        chunks.append("\n\n".join(current))

    return chunks if chunks else [text]


def parse_items_requested(items_requested) -> int | None:
    if items_requested is None:
        return None
    if isinstance(items_requested, int):
        return items_requested if items_requested > 0 else None
    value = str(items_requested).strip().lower()
    if not value or value == "auto":
        return None
    match = re.search(r"\d+", value)
    if not match:
        return None
    parsed = int(match.group(0))
    return parsed if parsed > 0 else None


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def estimate_adaptive_item_count(content_or_words, items_requested=None) -> int:
    """
    Calcula el tamano del banco IRT. Clases cortas quedan en 5-20 items;
    clases grandes crecen hasta 100-150 items sin pedir tokens sin contenido.
    """
    minimum = max(1, int(getattr(settings, "LOCAL_MIN_ITEMS", 5)))
    maximum = max(minimum, int(getattr(settings, "LOCAL_MAX_ITEMS", 150)))
    explicit = parse_items_requested(items_requested)
    if explicit:
        return clamp_int(explicit, minimum, maximum)

    if isinstance(content_or_words, int):
        word_count = max(0, content_or_words)
    else:
        word_count = len((content_or_words or "").split())

    if word_count <= 0:
        return minimum
    if word_count <= 80:
        target = minimum
    elif word_count <= 250:
        target = math.ceil(word_count / 35)
    elif word_count <= 600:
        target = math.ceil(word_count / 50)
    elif word_count <= 1200:
        target = math.ceil(word_count / 65)
    elif word_count <= 2500:
        target = math.ceil(word_count / 75)
    elif word_count <= 5000:
        target = math.ceil(word_count / 85)
    elif word_count <= 9000:
        target = math.ceil(word_count / 85)
    elif word_count <= 15000:
        target = math.ceil(word_count / 95)
    else:
        target = math.ceil(word_count / 110)
    # Garantizar ~100 items para clases largas (>5000 palabras ~30-40 min)
    if word_count >= 5000:
        target = max(target, 100)
    return clamp_int(target, minimum, maximum)


def generation_chunk_plan(content: str, backend: str, items_requested=None) -> tuple[list[str], list[int], int]:
    word_count = len((content or "").split())
    total_items = estimate_adaptive_item_count(word_count, items_requested=items_requested)

    # Chunks mas pequenos para el backend local: menos tokens por llamada,
    # menor probabilidad de timeout en textos largos.
    if backend == "anthropic":
        chunk_words = max(500, int(getattr(settings, "CLOUD_CHUNK_WORDS", 3000)))
        per_chunk_max = max(5, int(getattr(settings, "CLOUD_ITEMS_PER_CHUNK_MAX", 32)))
    else:
        chunk_words = max(250, int(getattr(settings, "LOCAL_CHUNK_WORDS", 1500)))
        per_chunk_max = max(5, int(getattr(settings, "LOCAL_ITEMS_PER_CHUNK_MAX", 15)))

    # Para textos muy largos con modelos locales, forzar chunks mas pequenos
    # y menos items por llamada, evitando timeouts por prompt excesivo.
    if backend != "anthropic" and word_count > 10000:
        chunk_words = min(chunk_words, 1500)
        per_chunk_max = min(per_chunk_max, 15)

    chunks = chunk_content(content, max_words=chunk_words)
    needed_by_items = max(1, math.ceil(total_items / per_chunk_max))
    if needed_by_items > len(chunks):
        adjusted_words = max(250, math.ceil(max(word_count, 1) / needed_by_items))
        chunks = chunk_content(content, max_words=min(chunk_words, adjusted_words))

    budgets = allocate_item_budget(chunks, total_items, per_chunk_max=per_chunk_max)
    return chunks, budgets, sum(budgets)


def allocate_item_budget(chunks: list[str], total_items: int, per_chunk_max: int) -> list[int]:
    if not chunks:
        return []
    if len(chunks) == 1:
        return [min(total_items, per_chunk_max)]

    min_per_chunk = 3 if total_items >= len(chunks) * 3 else 1
    word_counts = [max(1, len(chunk.split())) for chunk in chunks]
    total_words = sum(word_counts)
    capacity = per_chunk_max * len(chunks)
    target = min(total_items, capacity)
    raw = [target * (words / total_words) for words in word_counts]
    budgets = [
        min(per_chunk_max, max(min_per_chunk, math.floor(value)))
        for value in raw
    ]

    while sum(budgets) < target:
        candidates = sorted(
            range(len(budgets)),
            key=lambda idx: (
                budgets[idx] >= per_chunk_max,
                budgets[idx],
                -(raw[idx] - math.floor(raw[idx])),
                -word_counts[idx],
            ),
        )
        changed = False
        for idx in candidates:
            if budgets[idx] < per_chunk_max:
                budgets[idx] += 1
                changed = True
                break
        if not changed:
            break

    while sum(budgets) > target:
        candidates = sorted(
            range(len(budgets)),
            key=lambda idx: (budgets[idx] <= min_per_chunk, word_counts[idx], budgets[idx]),
        )
        changed = False
        for idx in candidates:
            if budgets[idx] > min_per_chunk:
                budgets[idx] -= 1
                changed = True
                break
        if not changed:
            break

    return budgets


def call_generation_prompt(prompt: str, backend: str) -> str:
    call_prompt = prompt + "\n/no_think" if backend == "local" else prompt
    return call_ai(call_prompt, backend=backend, role="generation")


def count_mini_items(raw_output: str) -> int:
    mini = extract_mini_lines(raw_output)
    return len(re.findall(r"^i\d+\|", mini, flags=re.M))


def _retry_if_few_items(prompt: str, mini: str, target_items: int, backend: str) -> tuple[str, str]:
    """Reintenta una llamada si devolvio muy pocos items MINI."""
    if count_mini_items(mini) >= max(3, math.floor(target_items * 0.75)):
        return prompt, mini
    retry_prompt = (
        f"{prompt}\n\n"
        f"REFUERZO: este chunk debe contener exactamente {target_items} lineas i<N>|. "
        "Cubre conceptos distintos del fragmento y evita repetir enunciados."
    )
    retry_mini = call_generation_prompt(retry_prompt, backend=backend)
    if count_mini_items(retry_mini) > count_mini_items(mini):
        return retry_prompt, retry_mini
    return prompt, mini


def _generate_chunk_safe(
    chunk: str,
    chunk_items: int,
    chunk_info: str,
    backend: str,
    language: str = "es",
    depth: int = 0,
) -> tuple[str, str]:
    """
    Genera items para un chunk. Si el modelo local hace timeout,
    divide el chunk en dos partes mas pequenas y reintenta.
    """
    if depth > 3:
        # Ultimo recurso: pide menos items para un fragmento mas corto.
        chunk_items = max(3, chunk_items // 2)

    prompt = build_generation_prompt(
        chunk,
        language=language,
        items_requested=chunk_items,
        chunk_info=chunk_info,
        cloud_optimized=(backend == "anthropic"),
    )
    try:
        mini = call_generation_prompt(prompt, backend=backend)
    except LocalAITimeoutError:
        words = chunk.split()
        if len(words) < 200 or depth > 3:
            raise
        mid = len(words) // 2
        first = " ".join(words[:mid])
        second = " ".join(words[mid:])
        half_items = max(3, chunk_items // 2)
        prompt1, mini1 = _generate_chunk_safe(
            first, half_items, chunk_info + " [parte A]", backend, language, depth + 1
        )
        prompt2, mini2 = _generate_chunk_safe(
            second, max(3, chunk_items - half_items), chunk_info + " [parte B]", backend, language, depth + 1
        )
        merged = _get_merge_fn()([mini1, mini2])
        combined_prompt = prompt1 + "\n\n--- division por timeout ---\n\n" + prompt2
        return combined_prompt, merged

    prompt, mini = _retry_if_few_items(prompt, mini, chunk_items, backend=backend)
    return prompt, mini


def generate_items(
    content: str,
    backend: str = "auto",
    language: str = "es",
    items_requested=None,
    progress_callback=None,
) -> tuple[str, str, str]:
    """
    Genera bancos MINI con un presupuesto adaptativo y llamadas stateless.
    Cada chunk recibe un objetivo numerico pequeno para evitar salidas truncadas.
    Si un chunk local hace timeout, se divide automaticamente.
    """
    backend = resolve_backend(backend)
    configured_items = items_requested or getattr(settings, "LOCAL_ITEMS_REQUESTED", "auto")
    chunks, budgets, total_items = generation_chunk_plan(content, backend, items_requested=configured_items)

    if len(chunks) == 1:
        prompt = build_generation_prompt(
            content,
            language=language,
            items_requested=budgets[0],
            cloud_optimized=(backend == "anthropic"),
        )
        result = call_generation_prompt(prompt, backend=backend)
        prompt, result = _retry_if_few_items(prompt, result, budgets[0], backend=backend)
        return prompt, result, backend

    all_prompts = []
    all_minis = []
    for i, (chunk, chunk_items) in enumerate(zip(chunks, budgets), 1):
        chunk_info = (
            f"{i} de {len(chunks)}; objetivo_global={total_items}; "
            f"objetivo_chunk={chunk_items}; generar exactamente {chunk_items} items unicos"
        )
        prompt, mini = _generate_chunk_safe(chunk, chunk_items, chunk_info, backend=backend, language=language)
        all_prompts.append(f"--- chunk {i}/{len(chunks)} ---\n{prompt}")
        all_minis.append(mini)
        if progress_callback:
            try:
                progress_callback(i, len(chunks), _get_merge_fn()(all_minis))
            except Exception:
                pass

    merged = _get_merge_fn()(all_minis)
    plan_header = (
        f"--- generation plan ---\n"
        f"backend={backend}\n"
        f"target_items={total_items}\n"
        f"chunks={len(chunks)}\n"
        f"chunk_item_budgets={','.join(str(value) for value in budgets)}"
    )
    combined_prompt = "\n\n".join([plan_header, *all_prompts])
    return combined_prompt, merged, backend


def get_available_backends() -> dict:
    """
    Devuelve que backends de IA estan disponibles.
    - anthropic: True si hay una API cloud configurada.
      El nombre se conserva porque la UI muestra "Claude" y el modelo usa ese valor.
    - local:     True siempre, asumiendo API compatible con OpenAI en LOCAL_API_BASE
    """
    anthropic_real = is_real_cloud_key(getattr(settings, "ANTHROPIC_API_KEY", ""))
    deepseek_real = is_real_cloud_key(getattr(settings, "DEEPSEEK_API_KEY", ""))
    cloud_provider = "deepseek" if deepseek_real else ("anthropic" if anthropic_real else "")
    return {
        "anthropic": bool(cloud_provider),
        "local": True,
        "default": "anthropic" if cloud_provider else "local",
        "cloud_provider": cloud_provider,
    }


def is_real_anthropic_key(key: str | None) -> bool:
    return is_real_cloud_key(key)


def is_real_cloud_key(key: str | None) -> bool:
    value = (key or "").strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered in {"local", "none", "null", "false", "0", "change-me", "changeme"}:
        return False
    placeholder_markers = ("tu_clave", "your_", "example", "placeholder")
    return not any(marker in lowered for marker in placeholder_markers)


def resolve_backend(backend: str = "auto") -> str:
    backends = get_available_backends()
    if backend == "auto":
        return backends["default"]
    return backend


def use_direct_cloud_mini(backend: str) -> bool:
    """
    DeepSeek usa el backend historico "anthropic" en la UI, pero puede generar
    MINI final en una pasada y dejar solo filtros deterministas posteriores.
    """
    if backend != "anthropic":
        return False
    if not getattr(settings, "DEEPSEEK_DIRECT_MINI", True):
        return False
    return get_available_backends().get("cloud_provider") == "deepseek"


def verify_items(mini_content: str, backend: str = "auto", verification_mode: str = "web") -> tuple[str, str, str, dict]:
    backend = resolve_backend(backend)
    source_context, trace = build_verification_context(mini_content, verification_mode=verification_mode)
    prompt = build_verification_prompt(mini_content, source_context=source_context)
    # /no_think solo para backend local
    call_prompt = prompt + "\n/no_think" if backend == "local" else prompt
    output = call_ai(call_prompt, backend=backend, role="verification")
    output = ensure_verification_report_format(output, mini_content, backend)
    trace["backend"] = backend
    trace["prompt_chars"] = len(prompt)
    trace["output_chars"] = len(output)
    return prompt, output, backend, trace


def ensure_verification_report_format(output: str, mini_content: str, backend: str) -> str:
    if _looks_like_verification_report(output):
        return output

    retry_prompt = (
        "Convierte el reporte informal siguiente al formato MINI de verificacion.\n"
        "No agregues explicaciones. La primera linea debe empezar con v|.\n"
        "Usa solo estos formatos:\n"
        "v|d=<YYYYMMDD>|n=<total_revisados>|e=<errores>|s=<VERIFICADO|CORREGIDO>\n"
        "e<N>|<item_id>|<error_type>|<field>|<original>|<fix>|<justificacion>\n\n"
        "Si el reporte informal menciona que una respuesta correcta debe cambiar, usa error_type=wrong_answer y field=options.\n"
        "Si menciona que el enunciado es ambiguo o meta sobre video/clase, usa error_type=ambiguous_statement y field=statement.\n"
        "Si no hay correcciones concretas, responde v| con e=0.\n\n"
        f"MINI_ORIGINAL:\n{mini_content}\n\n"
        f"REPORTE_INFORMAL:\n{output}"
    )
    call_prompt = retry_prompt + "\n/no_think" if backend == "local" else retry_prompt
    try:
        coerced = call_ai(call_prompt, backend=backend, role="verification")
    except Exception:
        return output
    return coerced if _looks_like_verification_report(coerced) else output


def _looks_like_verification_report(output: str) -> bool:
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        return line.startswith("v|")
    return False


def repair_mini_coherence(mini_content: str, source_context: str = "", backend: str = "local") -> tuple[str, str, str, dict]:
    """
    Relee el MINI contra la transcripcion/contexto y repara preguntas u opciones
    con sintaxis rota o sentido dudoso. Es deliberadamente stateless: cada llamada
    envia solo este prompt y no conserva historial de conversacion.
    """
    resolved_backend = "local" if backend in {"auto", "", None, "local"} else resolve_backend(backend)
    prompt = build_coherence_prompt(mini_content, source_context=source_context)
    call_prompt = prompt + "\n/no_think" if resolved_backend == "local" else prompt
    raw_output = call_ai(call_prompt, backend=resolved_backend, role="coherence")
    repaired = extract_mini_lines(raw_output)
    if not repaired:
        raise RuntimeError("La IA no devolvio un bloque MINI valido para reparar coherencia.")

    from .parse_mini import parse_mini

    assessment = parse_mini(repaired)
    if not assessment.header or not assessment.items:
        raise RuntimeError("La reparacion de coherencia no produjo items MINI parseables.")

    trace = {
        "backend": resolved_backend,
        "prompt_chars": len(prompt),
        "output_chars": len(raw_output),
        "changed": repaired.strip() != mini_content.strip(),
    }
    return prompt, repaired, resolved_backend, trace


def repair_incoherent_mini(incoherent_mini: str, source_context: str = "", backend: str = "local") -> tuple[str, str, str, dict]:
    """
    Repara especificamente items incoherentes (enunciados declarativos sin ? ni ____).
    Es mas rapido que repair_mini_coherence porque actua sobre un subset pequeno.
    """
    if not incoherent_mini.strip():
        return "", "", backend, {"changed": False, "note": "No hay items incoherentes"}

    resolved_backend = "local" if backend in {"auto", "", None, "local"} else resolve_backend(backend)
    prompt = (
        "Eres un editor de items de evaluacion. Los siguientes items tienen enunciados "
        "declarativos (sin ? ni ____) en lugar de preguntas o completaciones.\n\n"
        "REGLAS DE REPARACION:\n"
        "1. Convierte CADA enunciado en una PREGUNTA con ? al final, o una COMPLETACION con ____\n"
        "2. Conserva el contenido factual exacto (fechas, nombres, causas, consecuencias)\n"
        "3. Conserva las 4 opciones; si no tienen sentido con la nueva pregunta, ajustalas minimamente\n"
        "4. Conserva los parametros IRT (a,b,c), dificultad, area y nivel Bloom\n"
        "5. Marca la opcion correcta con * al final de su texto\n"
        "6. NO inventes items nuevos; solo repara los que te doy\n"
        "7. Responde UNICAMENTE con el bloque MINI, sin explicaciones\n\n"
        f"CONTEXTO_ORIGEN:\n{source_context.strip() or 'Sin contexto adicional.'}\n\n"
        f"MINI_INCOHERENTE_A_REPARAR:\n{incoherent_mini}"
    )
    call_prompt = prompt + "\n/no_think" if resolved_backend == "local" else prompt
    raw_output = call_ai(call_prompt, backend=resolved_backend, role="coherence")
    repaired = extract_mini_lines(raw_output)

    from .parse_mini import parse_mini

    trace = {
        "backend": resolved_backend,
        "prompt_chars": len(prompt),
        "output_chars": len(raw_output),
        "changed": bool(repaired and repaired.strip() != incoherent_mini.strip()),
    }

    if not repaired:
        return prompt, "", resolved_backend, {**trace, "note": "La IA no devolvio MINI valido"}

    assessment = parse_mini(repaired)
    if not assessment.header or not assessment.items:
        return prompt, "", resolved_backend, {**trace, "note": "Reparacion no produjo items parseables"}

    return prompt, repaired, resolved_backend, trace


def repair_option_uniformity(mini_content: str, source_context: str = "", backend: str = "local") -> tuple[str, str, str, dict]:
    """
    Repara items donde las opciones o el concepto evaluado estan malformados:
    - Opciones fusionadas por comas (3 en 1)
    - Distractores de longitud muy diferente a la correcta
    - Categorias semanticas inconsistentes entre opciones
    - Preguntas meta sobre el video/clase, publicidad o escalas genericas
    """
    if not mini_content.strip():
        return "", "", backend, {"changed": False, "note": "No hay items a reparar"}

    resolved_backend = "local" if backend in {"auto", "", None, "local"} else resolve_backend(backend)
    prompt = (
        "Eres un editor de items de evaluacion. Los siguientes items tienen opciones "
        "MAL FORMATEADAS, NO responden al enunciado, o evaluan ruido/meta del video. "
        "Debes corregir cada item usando un concepto academico claro del contexto.\n\n"
        "REGLAS DE REPARACION DE OPCIONES:\n"
        "1. Cada item DEBE tener exactamente 4 opciones separadas por comas\n"
        "2. Las 4 opciones deben ser de la MISMA categoria semantica y longitud similar\n"
        "3. Si una opcion tiene comas internas, usa comillas: \"texto con, comas\"\n"
        "4. La opcion correcta NO debe ser siempre la mas corta ni la mas larga\n"
        "5. Todas las opciones deben ser PLAUSIBLES pero inequivocamente incorrectas (excepto la correcta)\n"
        "6. Conserva el enunciado exacto si las opciones ya responden a ese enunciado\n"
        "7. Si el enunciado y la respuesta correcta NO corresponden (por ejemplo pregunta 'donde vive' pero la correcta es 'felino mas comun'), reescribe minimamente el enunciado para que pregunte por esa respuesta correcta\n"
        "8. Si el item pregunta por 'el video', 'la clase', 'el audio', el narrador, publicidad, likes, comentarios, canal o acciones al final, reemplazalo por una pregunta academica del tema central\n"
        "9. Si el item usa opciones genericas como importancia nula/moderada/mayor/menor, reemplazalo por opciones conceptuales y verificables\n"
        "10. Marca la opcion correcta con * al final de su texto\n"
        "11. Responde UNICAMENTE con el bloque MINI, sin explicaciones\n\n"
        "EJEMPLO DE OPCIONES MALAS (no hacer esto):\n"
        "ciudad de Lima,centro de Ica,valle de Cañete,costa del sur\n"
        "(aqui la primera 'opcion' en realidad son 3 distractores fusionados)\n\n"
        "EJEMPLO DE OPCIONES BUENAS:\n"
        "costa del sur,sierra central,selva alta,costa norte*\n\n"
        f"CONTEXTO_ORIGEN:\n{source_context.strip() or 'Sin contexto adicional.'}\n\n"
        f"MINI_CON_OPCIONES_MALAS:\n{mini_content}"
    )
    call_prompt = prompt + "\n/no_think" if resolved_backend == "local" else prompt
    raw_output = call_ai(call_prompt, backend=resolved_backend, role="coherence")
    repaired = extract_mini_lines(raw_output)

    from .parse_mini import parse_mini

    trace = {
        "backend": resolved_backend,
        "prompt_chars": len(prompt),
        "output_chars": len(raw_output),
        "changed": bool(repaired and repaired.strip() != mini_content.strip()),
    }

    if not repaired:
        return prompt, "", resolved_backend, {**trace, "note": "La IA no devolvio MINI valido"}

    assessment = parse_mini(repaired)
    if not assessment.header or not assessment.items:
        return prompt, "", resolved_backend, {**trace, "note": "Reparacion no produjo items parseables"}

    return prompt, repaired, resolved_backend, trace


def repair_transcript_text(transcript: str, source_context: str = "", backend: str = "local") -> tuple[str, str, str, dict]:
    """
    Corrige errores obvios de transcripcion usando contexto local de la clase.
    La llamada no conserva historial: solo se envia este prompt puntual.
    """
    resolved_backend = "local" if backend in {"auto", "", None, "local"} else resolve_backend(backend)
    prompt = build_transcript_repair_prompt(transcript, source_context=source_context)
    call_prompt = prompt + "\n/no_think" if resolved_backend == "local" else prompt
    raw_output = call_ai(call_prompt, backend=resolved_backend, role="transcript")
    repaired = clean_plain_text_output(raw_output)
    if not repaired:
        raise RuntimeError("La IA no devolvio una transcripcion corregida.")
    trace = {
        "backend": resolved_backend,
        "prompt_chars": len(prompt),
        "output_chars": len(raw_output),
        "changed": repaired.strip() != transcript.strip(),
    }
    return prompt, repaired, resolved_backend, trace


def extract_mini_lines(raw_output: str) -> str:
    lines = []
    for raw_line in (raw_output or "").splitlines():
        line = raw_line.strip().strip("`")
        if line.startswith("a|") or re.match(r"^i\d+\|", line):
            lines.append(line)
    return "\n".join(lines).strip()


def clean_plain_text_output(raw_output: str) -> str:
    text = (raw_output or "").strip()
    text = re.sub(r"^```(?:text|txt|markdown)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"^\s*TRANSCRIPCION_CORREGIDA\s*:\s*", "", text, flags=re.I)
    return text.strip()


def text_change_summary(before: str, after: str, max_changes: int = 80) -> list[dict]:
    before_words = (before or "").split()
    after_words = (after or "").split()
    matcher = difflib.SequenceMatcher(None, before_words, after_words)
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append({
            "type": tag,
            "before": compact_words(before_words[i1:i2]),
            "after": compact_words(after_words[j1:j2]),
        })
        if len(changes) >= max_changes:
            changes.append({
                "type": "truncated",
                "before": "",
                "after": "Hay mas cambios; revisa antes/despues completos.",
            })
            break
    return changes


def mini_item_change_summary(before: str, after: str, max_changes: int = 80) -> list[dict]:
    from .parse_mini import parse_mini

    before_items = {item.id: item for item in parse_mini(before).items}
    after_items = {item.id: item for item in parse_mini(after).items}
    changes = []
    for item_id in sorted(set(before_items) | set(after_items), key=_mini_id_sort_key):
        old = before_items.get(item_id)
        new = after_items.get(item_id)
        if old and not new:
            changes.append({"item": item_id, "field": "item", "before": old.raw, "after": ""})
        elif new and not old:
            changes.append({"item": item_id, "field": "item", "before": "", "after": new.raw})
        elif old and new:
            if old.topic != new.topic:
                changes.append({"item": item_id, "field": "topic", "before": old.topic, "after": new.topic})
            if old.statement != new.statement:
                changes.append({"item": item_id, "field": "enunciado", "before": old.statement, "after": new.statement})
            old_options = _option_signature(old.options)
            new_options = _option_signature(new.options)
            if old_options != new_options:
                changes.append({"item": item_id, "field": "opciones", "before": old_options, "after": new_options})
        if len(changes) >= max_changes:
            changes.append({
                "item": "-",
                "field": "truncated",
                "before": "",
                "after": "Hay mas cambios; revisa antes/despues completos.",
            })
            break
    return changes


def compact_words(words: list[str], limit: int = 220) -> str:
    text = " ".join(words).strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _option_signature(options: list[dict]) -> str:
    parts = []
    for option in options:
        suffix = "*" if option.get("correct") else ""
        parts.append(f"{option.get('text', '')}{suffix}")
    return ", ".join(parts)


def _mini_id_sort_key(item_id: str):
    match = re.match(r"i(\d+)$", item_id or "")
    return (0, int(match.group(1))) if match else (1, item_id or "")


def build_verification_source_context(mini_content: str, verification_mode: str = "web") -> str:
    source_context, _trace = build_verification_context(mini_content, verification_mode=verification_mode)
    return source_context


def build_verification_context(mini_content: str, verification_mode: str = "web") -> tuple[str, dict]:
    mode = normalize_verification_mode(verification_mode)
    parts = []
    trace = {
        "mode": mode,
        "web": {"enabled": False, "queries": [], "configured_sources": []},
        "eduqg": {"enabled": False, "matches": []},
    }

    if mode in {"eduqg", "hybrid"}:
        eduqg_context, eduqg_trace = build_eduqg_context(mini_content)
        parts.append(eduqg_context)
        trace["eduqg"] = eduqg_trace

    if mode in {"web", "hybrid"} and getattr(settings, "VERIFICATION_FETCH_SOURCES", True):
        web_context, web_trace = build_web_context(mini_content)
        parts.append(web_context)
        trace["web"] = web_trace

    trace["context_chars"] = sum(len(part) for part in parts if part)
    return "\n\n".join(part for part in parts if part.strip()), trace


def normalize_verification_mode(verification_mode: str) -> str:
    mode = (verification_mode or getattr(settings, "VERIFICATION_DEFAULT_MODE", "web") or "web").strip().lower()
    return mode if mode in {"web", "eduqg", "hybrid"} else "web"


def build_web_source_context(mini_content: str) -> str:
    context, _trace = build_web_context(mini_content)
    return context


def build_web_context(mini_content: str) -> tuple[str, dict]:
    urls = collect_verification_urls(read_prompt("verify_prompt.md"), mini_content)
    max_sources = max(0, int(getattr(settings, "VERIFICATION_MAX_SOURCES", 6)))
    timeout = max(1, int(getattr(settings, "VERIFICATION_SOURCE_TIMEOUT", 8)))
    chars = max(400, int(getattr(settings, "VERIFICATION_SOURCE_CHARS", 2200)))
    academic_enabled = bool(getattr(settings, "VERIFICATION_ACADEMIC_SEARCH", True))
    trace = {
        "enabled": True,
        "search_provider": "ddgs web search + academic targets",
        "academic_search": {
            "enabled": academic_enabled,
            "targets": ["arxiv.org", "scholar.google.com", "semanticscholar.org"],
        },
        "queries": [],
        "configured_sources": [],
        "query_generation": {},
        "evidence_summary": {"queries": 0, "results": 0, "usable_sources": 0},
    }
    snippets = []

    if getattr(settings, "VERIFICATION_DYNAMIC_WEB_SEARCH", True):
        query_entries = build_verification_query_entries(mini_content)
        trace["query_generation"] = {
            "source": query_entries[0].get("source", "") if query_entries else "",
            "count": len(query_entries),
            "error": query_entries[0].get("error", "") if query_entries else "",
        }
        query_entries = query_entries[: max(1, int(getattr(settings, "VERIFICATION_SEARCH_QUERIES", 3)))]
        result_limit = max(1, int(getattr(settings, "VERIFICATION_SEARCH_RESULTS", 3)))
        fetched_urls = set()
        for entry in query_entries:
            query = entry["query"]
            results = search_web(query, max_results=result_limit, timeout=timeout)
            academic_queries = _academic_search_queries(query) if academic_enabled else []
            for academic_query in academic_queries:
                academic_results = search_web(academic_query, max_results=1, timeout=timeout)
                for result in academic_results:
                    result["search_source"] = academic_query
                results.extend(academic_results)
            results = _dedupe_search_results(results)
            query_trace = {
                "query": query,
                "source": entry.get("source", "keyword"),
                "claim": entry.get("claim", ""),
                "academic_queries": academic_queries,
                "results": [],
            }
            for result in results:
                url = result["url"]
                if url in fetched_urls:
                    continue
                fetched_urls.add(url)
                document = fetch_source_document(url, timeout=timeout, max_chars=chars)
                result_trace = {**result, **document}
                query_trace["results"].append(result_trace)
                if document.get("ok"):
                    snippets.append(
                        f"BUSQUEDA_WEB: {query}\n"
                        f"FUENTE_BUSQUEDA: {result.get('search_source', 'web')}\n"
                        f"URL: {url}\n"
                        f"TITULO: {result.get('title', '')}\n"
                        f"CONTENIDO: {document.get('snippet', '')}"
                    )
            trace["queries"].append(query_trace)
        trace["evidence_summary"] = _web_evidence_summary(trace["queries"])

    for url in urls[:max_sources]:
        document = fetch_source_document(url, timeout=timeout, max_chars=chars)
        trace["configured_sources"].append(document)
        if document.get("ok"):
            snippets.append(f"URL: {url}\nCONTENIDO: {document.get('snippet', '')}")
        else:
            snippets.append(f"URL: {url}\nERROR_FETCH: {document.get('error', 'No se pudo leer la fuente.')}")

    return "\n\n".join(snippets), trace


def _academic_search_queries(query: str) -> list[str]:
    return [
        f"{query} site:arxiv.org",
        f"{query} site:scholar.google.com",
        f"{query} site:semanticscholar.org",
    ]


def _dedupe_search_results(results: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for result in results:
        url = result.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(result)
    return deduped


def _web_evidence_summary(queries: list[dict]) -> dict:
    total = sum(len(query.get("results", [])) for query in queries)
    ok = sum(1 for query in queries for result in query.get("results", []) if result.get("ok"))
    return {"queries": len(queries), "results": total, "usable_sources": ok}


def build_verification_queries(mini_content: str) -> list[str]:
    return [entry["query"] for entry in build_verification_query_entries(mini_content)]


def build_verification_query_entries(mini_content: str) -> list[dict]:
    prompt = _build_ai_query_prompt(mini_content)
    if prompt:
        try:
            raw_output = call_ai(prompt + "\n/no_think", backend="local", role="verification")
            queries = _parse_ai_queries(raw_output)
            if queries:
                return [
                    {"query": query, "source": "ai", "claim": query, "error": ""}
                    for query in queries
                ]
        except Exception as exc:
            fallback = _fallback_verification_query_entries(mini_content)
            return [{**entry, "error": str(exc)[:240]} for entry in fallback]

    return _fallback_verification_query_entries(mini_content)


def _build_ai_query_prompt(mini_content: str) -> str:
    try:
        from .parse_mini import parse_mini
    except Exception:
        return ""

    assessment = parse_mini(mini_content)
    rows = []
    for item in assessment.items[:8]:
        correct = next((opt.get("text", "") for opt in item.options if opt.get("correct")), "")
        if not correct:
            continue
        rows.append(
            f"- tema: {item.topic}\n"
            f"  enunciado: {item.statement}\n"
            f"  respuesta_correcta: {correct}"
        )

    if not rows:
        return ""

    return (
        "Eres un verificador academico. Extrae afirmaciones facticas comprobables "
        "desde estos items MINI y conviertelas en busquedas web precisas.\n\n"
        "Reglas:\n"
        "1. Devuelve solo texto plano: una busqueda por linea.\n"
        "2. Cada busqueda debe incluir el tema y la respuesta correcta que se quiere validar.\n"
        "3. Evita preguntas genericas; apunta a fuentes educativas, institucionales o enciclopedicas.\n"
        "4. Maximo 6 busquedas, 8 a 16 palabras por busqueda.\n\n"
        "ITEMS:\n"
        f"{chr(10).join(rows)}"
    )


def _parse_ai_queries(raw_output: str) -> list[str]:
    queries = []
    for raw_line in (raw_output or "").splitlines():
        line = raw_line.strip()
        line = re.sub(r"^\s*(?:[-*•]|\d+[\).\:-])\s*", "", line)
        line = line.strip().strip("\"'`")
        if not line or line.lower() in {"no_think", "/no_think"}:
            continue
        if "|" in line:
            line = line.split("|")[-1].strip()
        line = re.sub(r"\s+", " ", line)
        if len(line.split()) < 3:
            continue
        line = line[:180]
        if line not in queries:
            queries.append(line)
        if len(queries) >= 6:
            break
    return queries


def _fallback_verification_query_entries(mini_content: str) -> list[dict]:
    keywords = _extract_keywords(mini_content)
    joined = " ".join(keywords[:10])
    title = ""
    assessment_topic = re.search(r"\|t=([^|]+)", mini_content)
    if assessment_topic:
        title = assessment_topic.group(1).replace("_", " ")
    questions = []
    for line in mini_content.splitlines():
        if line.startswith("i") and "|" in line:
            parts = line.split("|")
            if len(parts) > 4:
                questions.append(f"{parts[2]} {parts[3]}")
        if len(questions) >= 2:
            break
    candidates = [
        f"{title} {joined} facts",
        f"{' '.join(questions)}",
        f"{title} historia verificacion",
    ]
    queries = []
    for candidate in candidates:
        compact = re.sub(r"\s+", " ", candidate).strip()
        if compact and compact not in queries:
            queries.append(compact[:180])
    fallback_queries = queries or [joined or "educational multiple choice verification"]
    return [
        {"query": query, "source": "keyword", "claim": "", "error": ""}
        for query in fallback_queries
    ]


def search_web(query: str, max_results: int = 3, timeout: int = 8) -> list[dict]:
    """Busca en DuckDuckGo usando la libreria ddgs (maneja bloqueos y rate limits)."""
    try:
        from ddgs import DDGS
    except Exception:
        return []

    try:
        with DDGS() as ddgs:
            raw_results = ddgs.text(query, max_results=max(max_results, 5))
    except Exception:
        return []

    results = []
    for result in raw_results:
        url = normalize_search_result_url(result.get("href", ""))
        title = strip_html(result.get("title", ""))
        if not url or "duckduckgo.com" in urlparse(url).netloc:
            continue
        if any(r["url"] == url for r in results):
            continue
        results.append({"url": url, "title": title})
        if len(results) >= max_results:
            break
    return results


def normalize_search_result_url(href: str) -> str:
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    if "uddg" in params:
        return unquote(params["uddg"][0])
    if href.startswith("//"):
        return "https:" + href
    return href


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<.*?>", "", unescape(value))).strip()


def build_eduqg_source_context(mini_content: str) -> str:
    context, _trace = build_eduqg_context(mini_content)
    return context

    raw_reference_path = (getattr(settings, "EDUQG_REFERENCE_PATH", "") or "").strip()
    if not raw_reference_path:
        return (
            "EDUQG_LOCAL:\n"
            "EDUQG_REFERENCE_PATH esta vacio. El verificador no usara EduQG hasta que "
            "apuntes esa variable a un archivo .json/.jsonl/.csv/.txt o a una carpeta con esos archivos."
        )
    reference_path = Path(raw_reference_path)
    max_chars = max(1000, int(getattr(settings, "EDUQG_SOURCE_CHARS", 6000)))

    if not reference_path.exists():
        return (
            "EDUQG_LOCAL:\n"
            "No se encontro EDUQG_REFERENCE_PATH. El verificador no usara EduQG hasta que "
            "apuntes esa variable a un archivo .json/.jsonl/.csv/.txt o a una carpeta con esos archivos."
        )

    files = []
    if reference_path.is_file():
        files = [reference_path]
    else:
        for pattern in ("*.jsonl", "*.json", "*.csv", "*.txt", "*.md"):
            files.extend(reference_path.rglob(pattern))

    if not files:
        return (
            f"EDUQG_LOCAL:\nNo se encontraron archivos EduQG legibles en {reference_path}. "
            "Se mantiene el prompt de verificacion sin contexto EduQG."
        )

    keywords = _extract_keywords(mini_content)
    snippets = []
    remaining = max_chars
    for path in files[:12]:
        if remaining <= 0:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            snippets.append(f"ARCHIVO: {path}\nERROR_EDUQG: {exc}")
            continue
        snippet = _select_relevant_text(text, keywords, limit=min(remaining, 1800))
        if snippet:
            snippets.append(f"ARCHIVO: {path}\nCONTENIDO_EDUQG: {snippet}")
            remaining -= len(snippet)

    if not snippets:
        return f"EDUQG_LOCAL:\nNo se pudo extraer texto util desde {reference_path}."
    return "EDUQG_LOCAL:\n" + "\n\n".join(snippets)


def build_eduqg_context(mini_content: str) -> tuple[str, dict]:
    raw_reference_path = (getattr(settings, "EDUQG_REFERENCE_PATH", "") or "").strip()
    trace = {
        "enabled": True,
        "path": raw_reference_path,
        "exists": False,
        "files": [],
        "records_loaded": 0,
        "matches": [],
        "error": "",
    }
    if not raw_reference_path:
        trace["error"] = "EDUQG_REFERENCE_PATH esta vacio."
        return (
            "EDUQG_LOCAL:\nEDUQG_REFERENCE_PATH esta vacio. Configura una carpeta o archivo EduQG.",
            trace,
        )

    reference_path = Path(raw_reference_path)
    trace["exists"] = reference_path.exists()
    if not reference_path.exists():
        trace["error"] = "No se encontro EDUQG_REFERENCE_PATH."
        return (
            "EDUQG_LOCAL:\nNo se encontro EDUQG_REFERENCE_PATH. Configura una carpeta o archivo EduQG.",
            trace,
        )

    try:
        records, files = load_eduqg_records(reference_path)
    except Exception as exc:
        trace["error"] = str(exc)
        return f"EDUQG_LOCAL:\nERROR_EDUQG: {exc}", trace

    trace["files"] = [str(path) for path in files]
    trace["records_loaded"] = len(records)
    if not records:
        trace["error"] = "No se encontraron registros EduQG legibles."
        return "EDUQG_LOCAL:\nNo se encontraron registros EduQG legibles.", trace

    keywords = set(_extract_keywords(mini_content))
    scored = []
    for record in records:
        score = score_record(record["text"], keywords)
        scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)

    top_k = max(1, int(getattr(settings, "EDUQG_TOP_K", 5)))
    matches = scored[:top_k]
    max_chars = max(1000, int(getattr(settings, "EDUQG_SOURCE_CHARS", 6000)))
    remaining = max_chars
    blocks = []
    for score, record in matches:
        excerpt = record["excerpt"][: min(remaining, 1400)]
        if not excerpt:
            continue
        match = {
            "score": round(score, 4),
            "file": record["file"],
            "title": record["title"],
            "question": record["question"],
            "answer": record["answer"],
            "excerpt": excerpt,
        }
        trace["matches"].append(match)
        blocks.append(
            "EDUQG_MATCH:\n"
            f"archivo: {record['file']}\n"
            f"titulo: {record['title']}\n"
            f"score: {round(score, 4)}\n"
            f"pregunta_ejemplo: {record['question']}\n"
            f"respuesta_ejemplo: {record['answer']}\n"
            f"contexto: {excerpt}"
        )
        remaining -= len(excerpt)
        if remaining <= 0:
            break

    if not blocks:
        trace["error"] = "No se pudo extraer contexto util."
        return "EDUQG_LOCAL:\nNo se pudo extraer contexto util.", trace
    return "EDUQG_LOCAL:\n" + "\n\n".join(blocks), trace


def load_eduqg_records(reference_path: Path) -> tuple[list[dict], list[Path]]:
    files = collect_eduqg_files(reference_path)
    cache_key = (
        str(reference_path),
        tuple((str(path), path.stat().st_mtime, path.stat().st_size) for path in files),
    )
    if cache_key in _EDUQG_CACHE:
        return _EDUQG_CACHE[cache_key], files

    max_records = max(1, int(getattr(settings, "EDUQG_MAX_RECORDS", 6000)))
    records = []
    for path in files:
        if len(records) >= max_records:
            break
        records.extend(read_eduqg_file(path, limit=max_records - len(records)))

    _EDUQG_CACHE.clear()
    _EDUQG_CACHE[cache_key] = records
    return records, files


def collect_eduqg_files(reference_path: Path) -> list[Path]:
    if reference_path.is_file():
        return [reference_path]
    files = []
    for pattern in ("*.json", "*.jsonl", "*.csv", "*.txt", "*.md"):
        files.extend(reference_path.rglob(pattern))
    return sorted(files, key=lambda path: str(path).lower())


def read_eduqg_file(path: Path, limit: int) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return records_from_json(data, path, limit=limit)
    if suffix == ".jsonl":
        records = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if len(records) >= limit:
                    break
                if line.strip():
                    records.extend(records_from_json(json.loads(line), path, limit=limit - len(records)))
        return records
    if suffix == ".csv":
        records = []
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                text = " ".join(str(value) for value in row.values() if value)
                records.append(generic_eduqg_record(path, "CSV", text))
                if len(records) >= limit:
                    break
        return records
    text = path.read_text(encoding="utf-8", errors="replace")
    return [generic_eduqg_record(path, path.stem, text[:8000])] if text.strip() else []


def records_from_json(data, path: Path, limit: int) -> list[dict]:
    records = []
    chapters = data if isinstance(data, list) else [data]
    for chapter in chapters:
        if len(records) >= limit:
            break
        if not isinstance(chapter, dict):
            text = json.dumps(chapter, ensure_ascii=False)
            records.append(generic_eduqg_record(path, "JSON", text))
            continue
        bname = str(chapter.get("bname", "EduQG"))
        chapter_id = chapter.get("chapter", "")
        summary = str(chapter.get("summary", ""))
        questions = chapter.get("questions") or []
        for question_entry in questions:
            if len(records) >= limit:
                break
            records.append(record_from_eduqg_question(path, bname, chapter_id, summary, question_entry))
        if not questions:
            text = " ".join(str(chapter.get(key, "")) for key in ("intro", "chapter_text", "summary", "keyterm"))
            records.append(generic_eduqg_record(path, f"{bname} capitulo {chapter_id}", text))
    return records


def record_from_eduqg_question(path: Path, bname: str, chapter_id, summary: str, entry: dict) -> dict:
    question = entry.get("question", {}) if isinstance(entry, dict) else {}
    answer = entry.get("answer", {}) if isinstance(entry, dict) else {}
    question_text = str(question.get("normal_format") or question.get("question_text") or question.get("cloze_format") or "")
    choices = str(question.get("question_choices", ""))
    answer_text = str(answer.get("ans_text", ""))
    context = " ".join([
        str(entry.get("hl_sentences", "")),
        str(entry.get("hl_context", "")),
        summary[:1600],
    ])
    text = " ".join([bname, str(chapter_id), question_text, choices, answer_text, context])
    return {
        "file": str(path),
        "title": f"{bname} capitulo {chapter_id}".strip(),
        "question": question_text,
        "answer": answer_text,
        "text": normalize_text_for_score(text),
        "excerpt": re.sub(r"\s+", " ", context or text).strip(),
    }


def generic_eduqg_record(path: Path, title: str, text: str) -> dict:
    compact = re.sub(r"\s+", " ", text).strip()
    return {
        "file": str(path),
        "title": title,
        "question": "",
        "answer": "",
        "text": normalize_text_for_score(compact),
        "excerpt": compact[:2400],
    }


def normalize_text_for_score(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def score_record(text: str, keywords: set[str]) -> float:
    if not keywords:
        return 0
    hits = sum(1 for keyword in keywords if keyword in text)
    return hits / max(len(keywords), 1)


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{5,}", text.lower())
    stop = {
        "pregunta", "respuesta", "opcion", "opciones", "correcta", "dificultad",
        "explicacion", "topic", "historia", "origen", "objetivo", "relacion",
    }
    ranked = []
    for word in words:
        if word not in stop and word not in ranked:
            ranked.append(word)
        if len(ranked) >= 20:
            break
    return ranked


def _select_relevant_text(text: str, keywords: list[str], limit: int = 1800) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    lowered = compact.lower()
    positions = [lowered.find(keyword) for keyword in keywords if lowered.find(keyword) >= 0]
    if not positions:
        return compact[:limit]
    start = max(min(positions) - 300, 0)
    return compact[start:start + limit]


def collect_verification_urls(*texts: str) -> list[str]:
    configured = getattr(settings, "VERIFICATION_SOURCE_URLS", "")
    candidates = re.split(r"[\s,]+", configured.strip()) if configured else []
    for text in texts:
        if not text:
            continue
        candidates.extend(re.findall(r"https?://[^\s<>'\"|,]+", text))
        candidates.extend(re.findall(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>'\"|,]*)?", text, flags=re.I))

    urls = []
    seen = set()
    for raw in candidates:
        url = raw.strip().rstrip(").,;")
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        key = url.rstrip("/")
        if key not in seen:
            seen.add(key)
            urls.append(key)
    return urls


def fetch_source_snippet(url: str, timeout: int = 8, max_chars: int = 2200) -> str:
    try:
        req = Request(url, headers={"User-Agent": "SIMA verifier/1.0"})
        with urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(350_000)
            charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        if "html" in content_type.lower() or "<html" in text[:500].lower():
            parser = _HTMLTextExtractor()
            parser.feed(text)
            text = parser.text()
        else:
            text = re.sub(r"\s+", " ", text).strip()
        if not text or "Request unsuccessful" in text or "Incapsula incident" in text:
            return f"URL: {url}\nERROR_FETCH: La fuente no devolvió texto verificable."
        return f"URL: {url}\nCONTENIDO: {text[:max_chars]}"
    except Exception as exc:
        return f"URL: {url}\nERROR_FETCH: {exc}"


def fetch_source_document(url: str, timeout: int = 8, max_chars: int = 2200) -> dict:
    last_error = ""
    min_chars = max(120, min(350, max_chars // 8))
    for attempt in range(2):
        try:
            retry_timeout = timeout + (attempt * 4)
            req = Request(url, headers={"User-Agent": "SIMA verifier/1.0 (+https://sima.local)"})
            with urlopen(req, timeout=retry_timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(500_000)
                charset = response.headers.get_content_charset() or "utf-8"

            text = raw.decode(charset, errors="replace")
            if "html" in content_type.lower() or "<html" in text[:500].lower():
                parser = _HTMLTextExtractor()
                parser.feed(text)
                text = parser.text()
            else:
                text = re.sub(r"\s+", " ", text).strip()

            blocked_markers = ("Request unsuccessful", "Incapsula incident", "Access Denied", "Just a moment")
            if not text or any(marker.lower() in text.lower() for marker in blocked_markers):
                return {
                    "url": url,
                    "ok": False,
                    "content_type": content_type,
                    "chars": len(text),
                    "snippet": "",
                    "error": "La fuente no devolvio texto verificable.",
                }
            if len(text) < min_chars:
                return {
                    "url": url,
                    "ok": False,
                    "content_type": content_type,
                    "chars": len(text),
                    "snippet": text[:max_chars],
                    "error": "La fuente devolvio muy poco texto util para verificar.",
                }
            return {
                "url": url,
                "ok": True,
                "content_type": content_type,
                "chars": len(text),
                "snippet": text[:max_chars],
                "error": "",
            }
        except Exception as exc:
            last_error = str(exc)

    return {
        "url": url,
        "ok": False,
        "content_type": "",
        "chars": 0,
        "snippet": "",
        "error": last_error,
    }


def call_ai(prompt: str, backend: str = "auto", role: str = "generation") -> str:
    backend = resolve_backend(backend)
    backends = get_available_backends()

    if backend == "anthropic":
        if not backends["anthropic"]:
            raise RuntimeError("Anthropic API no esta configurada. Usa el backend local.")
        return _call_cloud_model(prompt, role=role)
    if backend == "local":
        return _call_local(prompt, role=role)
    raise RuntimeError(f"Backend desconocido: {backend}")


def clean_ai_error(exc) -> str:
    err_str = str(exc)
    if "<!DOCTYPE" in err_str or "<html" in err_str.lower():
        return "No se pudo conectar al servidor de IA. Verifica que el modelo local esté corriendo y que LOCAL_API_BASE en .env sea correcto."
    return err_str


def _call_cloud_model(prompt: str, role: str = "generation") -> str:
    """
    Mantiene el backend historico "anthropic" para la UI, pero permite usar
    DeepSeek cloud como proveedor real cuando DEEPSEEK_API_KEY esta configurada.
    """
    if is_real_cloud_key(getattr(settings, "DEEPSEEK_API_KEY", "")):
        return _call_deepseek(prompt, role=role)
    return _call_anthropic(prompt)


def _call_anthropic(prompt: str) -> str:
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("Instala el paquete anthropic: pip install anthropic") from exc

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=6000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    return "\n".join(block.text for block in message.content if getattr(block, "type", "") == "text")


def _call_deepseek(prompt: str, role: str = "generation") -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Instala openai para usar DeepSeek: pip install openai") from exc

    base_url = (getattr(settings, "DEEPSEEK_API_BASE", "https://api.deepseek.com") or "").strip().rstrip("/")
    if not base_url:
        base_url = "https://api.deepseek.com"
    temperature = (
        getattr(settings, "DEEPSEEK_VERIFICATION_TEMPERATURE", 0.2)
        if role in {"verification", "coherence", "transcript"}
        else getattr(settings, "DEEPSEEK_GENERATION_TEMPERATURE", 0.3)
    )

    client = OpenAI(
        api_key=getattr(settings, "DEEPSEEK_API_KEY", ""),
        base_url=base_url,
        max_retries=0,
        timeout=getattr(settings, "DEEPSEEK_API_TIMEOUT", 120),
    )
    try:
        response = client.chat.completions.create(
            model=getattr(settings, "DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=getattr(settings, "DEEPSEEK_MAX_TOKENS", 6000),
            temperature=temperature,
            stream=False,
            timeout=getattr(settings, "DEEPSEEK_API_TIMEOUT", 120),
        )
    except Exception as exc:
        from openai import APIConnectionError, APITimeoutError, AuthenticationError
        if isinstance(exc, AuthenticationError):
            raise RuntimeError("DeepSeek rechazo la API key configurada. Revisa DEEPSEEK_API_KEY en .env.") from exc
        if isinstance(exc, APITimeoutError):
            raise RuntimeError(
                f"DeepSeek no respondio dentro del timeout de {getattr(settings, 'DEEPSEEK_API_TIMEOUT', 120)} segundos."
            ) from exc
        if isinstance(exc, APIConnectionError):
            raise RuntimeError(
                f"No se pudo conectar a DeepSeek en {base_url}. Revisa DEEPSEEK_API_BASE en .env."
            ) from exc
        raise RuntimeError(f"Error llamando a DeepSeek cloud: {exc}") from exc

    return _extract_chat_completion_text(response, "DeepSeek")


def _extract_chat_completion_text(response, model_label: str) -> str:
    choice = response.choices[0]
    msg = choice.message
    text = (msg.content or "").strip()
    if not text:
        text = (getattr(msg, "reasoning_content", None) or "").strip()
    if not text:
        raise RuntimeError(
            f"{model_label} devolvio una respuesta vacia (finish_reason={choice.finish_reason})."
        )

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return text.replace("\x00", "")


def _call_local(prompt: str, role: str = "generation") -> str:
    """
    Llama a un modelo local compatible con OpenAI Chat Completions.
    Maneja modelos con thinking (Qwen3) donde content puede venir vacío
    y el texto real está en reasoning_content o en el primer choice.
    """
    local_base = normalize_openai_base_url(getattr(settings, "LOCAL_API_BASE", "http://localhost:1234/v1"))
    model = getattr(settings, "LOCAL_MODEL", None) or settings.ANTHROPIC_MODEL
    temperature = (
        getattr(settings, "LOCAL_VERIFICATION_TEMPERATURE", 0.3)
        if role in {"verification", "coherence", "transcript"}
        else getattr(settings, "LOCAL_GENERATION_TEMPERATURE", 0.4)
    )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Instala openai para usar el backend local: pip install openai") from exc

    client = OpenAI(
        api_key=getattr(settings, "LOCAL_API_KEY", "local"),
        base_url=local_base,
        max_retries=0,
        timeout=getattr(settings, "LOCAL_API_TIMEOUT", 120),
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=getattr(settings, "LOCAL_MAX_TOKENS", 6000),
            temperature=temperature,
            stream=False,
            timeout=getattr(settings, "LOCAL_API_TIMEOUT", 120),
        )
    except Exception as exc:
        from openai import APIConnectionError, APITimeoutError
        if isinstance(exc, APITimeoutError):
            raise LocalAITimeoutError(
                f"El servidor de IA local en {local_base} no respondio dentro del timeout de "
                f"{getattr(settings, 'LOCAL_API_TIMEOUT', 120)} segundos. "
                "Reduce el tamano del texto, sube LOCAL_API_TIMEOUT en .env, o revisa que el modelo local tenga recursos suficientes."
            ) from exc
        if isinstance(exc, APIConnectionError):
            raise RuntimeError(
                f"No se pudo conectar al servidor de IA en {local_base}. "
                "Verifica que llama-server este corriendo y que LOCAL_API_BASE apunte al endpoint /v1."
            ) from exc
        raise RuntimeError(
            f"Error inesperado llamando al servidor de IA en {local_base}: {exc}"
        ) from exc

    choice = response.choices[0]
    msg = choice.message

    # Qwen3 y otros modelos con thinking devuelven el texto en content
    # pero a veces lo ponen en reasoning_content cuando thinking está activo.
    # Intentamos content primero, luego reasoning_content como fallback.
    text = (msg.content or "").strip()
    if not text:
        text = (getattr(msg, "reasoning_content", None) or "").strip()
    if not text:
        raise RuntimeError(
            f"El modelo devolvió una respuesta vacía (finish_reason={choice.finish_reason}). "
            f"Verifica que el servidor local esté corriendo en {local_base}."
        )

    # Qwen3 con --jinja incluye <think>...</think> antes del output real — lo removemos
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Algunos servidores locales (Ollama) pueden devolver bytes NUL que PostgreSQL rechaza
    text = text.replace("\x00", "")

    return text


def normalize_openai_base_url(base_url: str) -> str:
    """
    llama-server expone la API compatible con OpenAI bajo /v1.
    Permite configurar http://127.0.0.1:8001 o http://127.0.0.1:8001/v1.
    """
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        return "http://127.0.0.1:8001/v1"

    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


def call_claude(prompt: str, backend: str = "auto") -> str:
    return call_ai(prompt, backend=backend)


def transcribe_audio(audio_path):
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("Instala Whisper local para transcribir: pip install openai-whisper") from exc

    configure_local_ffmpeg(whisper)
    model = whisper.load_model(settings.WHISPER_MODEL)
    result = model.transcribe(str(audio_path))
    return result.get("text", "").strip()


def configure_local_ffmpeg(whisper_module=None):
    try:
        import imageio_ffmpeg
    except ImportError:
        return None

    ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if whisper_module is not None:
        patch_whisper_loader(whisper_module, ffmpeg_path)
    return ffmpeg_path


def patch_whisper_loader(whisper_module, ffmpeg_path):
    import numpy as np
    from subprocess import CalledProcessError, run

    def load_audio(file, sr=16000):
        cmd = [
            str(ffmpeg_path),
            "-nostdin",
            "-threads",
            "0",
            "-i",
            file,
            "-f",
            "s16le",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sr),
            "-",
        ]
        try:
            out = run(cmd, capture_output=True, check=True).stdout
        except CalledProcessError as exc:
            raise RuntimeError(f"Failed to load audio: {exc.stderr.decode(errors='ignore')}") from exc
        return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0

    whisper_module.audio.load_audio = load_audio
