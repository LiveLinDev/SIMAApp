"""Generacion de items .mini por chunks con presupuesto adaptativo y reintentos."""
from __future__ import annotations

import math
import re

from django.conf import settings

from .backends import (
    LocalAITimeoutError,
    call_ai,
    resolve_backend,
)
from .prompts import (
    build_generation_prompt,
)


def _leer_respuesta(raw: str, prompt: str, chunk_items: int, chunk_info: str, backend: str, informe) -> tuple[str, str]:
    """
    Lee la respuesta de un bloque segun SIMA_LECTOR.

    minifmt: valida contra el contrato de mini-format, repara solo las lineas invalidas y pide solo lo que falta.
    legado:  conserva el comportamiento anterior (reintento completo si llegan pocos items) y registra lo que
             el lector anterior hace con esa misma respuesta, para poder comparar.
    """
    from . import lectura_mini

    if lectura_mini.lector_activo() == "legado":
        bloque = lectura_mini.diagnostico_legado(raw, chunk_items, chunk_info)
        if count_mini_items(raw) < max(3, math.floor(chunk_items * 0.75)):
            # el lector anterior repite el bloque completo cuando llegan pocos items
            bloque.llamadas = 2
        nuevo_prompt, nuevo_raw = _retry_if_few_items(prompt, raw, chunk_items, backend=backend)
        bloque.finales = len(lectura_mini.parse_mini(nuevo_raw or "").items)
        if informe is not None:
            informe.append(bloque.a_dict())
        return nuevo_prompt, nuevo_raw

    def llamar(texto: str) -> str:
        return call_ai(texto, backend=backend, role="generation", max_tokens=output_budget(chunk_items))

    def pedir_faltantes(n: int, enunciados: list[str]) -> str:
        evitar = "\n".join(f"- {e}" for e in enunciados if e)
        extra = (
            f"{prompt}\n\n"
            f"COMPLEMENTO: genera exactamente {n} items nuevos para este mismo fragmento. "
            "No repitas ninguno de estos enunciados ya generados:\n" + evitar
        )
        return call_generation_prompt(extra, backend=backend, items=n)

    texto, bloque = lectura_mini.leer_bloque(raw, chunk_items, chunk_info, llamar, pedir_faltantes)
    if informe is not None:
        informe.append(bloque.a_dict())
    return prompt, texto


def _get_merge_fn():
    from ..parse_mini import merge_mini_chunks
    return merge_mini_chunks


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
    if backend == "cloud":
        chunk_words = max(500, int(getattr(settings, "CLOUD_CHUNK_WORDS", 3000)))
        per_chunk_max = max(5, int(getattr(settings, "CLOUD_ITEMS_PER_CHUNK_MAX", 32)))
    else:
        chunk_words = max(250, int(getattr(settings, "LOCAL_CHUNK_WORDS", 1500)))
        per_chunk_max = max(5, int(getattr(settings, "LOCAL_ITEMS_PER_CHUNK_MAX", 15)))

    # Para textos muy largos con modelos locales, forzar chunks mas pequenos
    # y menos items por llamada, evitando timeouts por prompt excesivo.
    if backend != "cloud" and word_count > 10000:
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


OUTPUT_TOKENS_BASE = 400        # cabecera a| + margen
OUTPUT_TOKENS_PER_ITEM = 170    # una linea i<N>| con 4 opciones y metadatos


def output_budget(items: int | None) -> int | None:
    """Tokens de salida que necesita una llamada que pide `items` items .mini."""
    if not items or items <= 0:
        return None
    return OUTPUT_TOKENS_BASE + OUTPUT_TOKENS_PER_ITEM * int(items)


def call_generation_prompt(prompt: str, backend: str, items: int | None = None) -> str:
    call_prompt = prompt + "\n/no_think" if backend == "local" else prompt
    return call_ai(call_prompt, backend=backend, role="generation", max_tokens=output_budget(items))


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
    retry_mini = call_generation_prompt(retry_prompt, backend=backend, items=target_items)
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
    informe: list | None = None,
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
        cloud_optimized=(backend == "cloud"),
    )
    try:
        mini = call_generation_prompt(prompt, backend=backend, items=chunk_items)
    except LocalAITimeoutError:
        words = chunk.split()
        if len(words) < 200 or depth > 3:
            raise
        mid = len(words) // 2
        first = " ".join(words[:mid])
        second = " ".join(words[mid:])
        half_items = max(3, chunk_items // 2)
        prompt1, mini1 = _generate_chunk_safe(
            first, half_items, chunk_info + " [parte A]", backend, language, depth + 1, informe
        )
        prompt2, mini2 = _generate_chunk_safe(
            second, max(3, chunk_items - half_items), chunk_info + " [parte B]", backend, language, depth + 1, informe
        )
        merged = _get_merge_fn()([mini1, mini2])
        combined_prompt = prompt1 + "\n\n--- division por timeout ---\n\n" + prompt2
        return combined_prompt, merged

    return _leer_respuesta(mini, prompt, chunk_items, chunk_info, backend, informe)


def generate_items(
    content: str,
    backend: str = "auto",
    language: str = "es",
    items_requested=None,
    progress_callback=None,
    informe: list | None = None,
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
            cloud_optimized=(backend == "cloud"),
        )
        result = call_generation_prompt(prompt, backend=backend, items=budgets[0])
        prompt, result = _leer_respuesta(result, prompt, budgets[0], "1 de 1", backend, informe)
        return prompt, result, backend

    all_prompts = []
    all_minis = []
    for i, (chunk, chunk_items) in enumerate(zip(chunks, budgets), 1):
        chunk_info = (
            f"{i} de {len(chunks)}; objetivo_global={total_items}; "
            f"objetivo_chunk={chunk_items}; generar exactamente {chunk_items} items unicos"
        )
        prompt, mini = _generate_chunk_safe(
            chunk, chunk_items, chunk_info, backend=backend, language=language, informe=informe
        )
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
