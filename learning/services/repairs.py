"""Verificacion factual y reparaciones del .mini (coherencia, opciones, transcripcion) con trazas de cambios."""
from __future__ import annotations

import difflib
import re


from .backends import (
    call_ai,
    resolve_backend,
)
from .evidence import (
    build_verification_context,
)
from .generation import (
    count_mini_items,
    clean_plain_text_output,
    extract_mini_lines,
)
from .prompts import (
    build_coherence_prompt,
    build_transcript_repair_prompt,
    build_verification_prompt,
)


def verify_items(mini_content: str, backend: str = "auto", verification_mode: str = "web") -> tuple[str, str, str, dict]:
    backend = resolve_backend(backend)
    source_context, trace = build_verification_context(mini_content, verification_mode=verification_mode)
    prompt = build_verification_prompt(mini_content, source_context=source_context)
    # /no_think solo para backend local
    call_prompt = prompt + "\n/no_think" if backend == "local" else prompt
    # El reporte v|/e| es corto: ~60 tokens por item mas cabecera.
    output = call_ai(call_prompt, backend=backend, role="verification", max_tokens=600 + 60 * max(1, count_mini_items(mini_content)))
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

    from ..parse_mini import parse_mini

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

    from ..parse_mini import parse_mini

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

    from ..parse_mini import parse_mini

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
    from ..parse_mini import parse_mini

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
