"""
Comparación real de formatos de salida en SIMA: el mismo fragmento de clase, con las mismas instrucciones de
generación, se pide al modelo una vez en .mini y otra en JSON. Se miden los tokens que reporta el proveedor, el
tiempo, el costo, las preguntas que cumplen el contrato y si la respuesta se cortó por el límite de salida.

Las dos llamadas usan el prompt real de SIMA (build_generation_prompt). Para JSON solo se reemplaza la sección de
formato por su equivalente JSON (mismos campos, mismo ejemplo); el resto de instrucciones y el contenido son
idénticos. Ninguna respuesta se repara: es la lectura de una sola llamada en cada formato.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

from django.conf import settings
from django.db import close_old_connections

from . import lectura_mini
from .backends import model_for_role, normalize_openai_base_url
from .prompts import build_generation_prompt

# ejemplo del prompt de SIMA (2 ítems) usado para escribir su equivalente en JSON
_EJEMPLO_MINI = (
    "a|m=IRT3PL|d=20260503|n=2|l=es|t=fotosintesis|bd=1,1,0,0,0,0|cat=0,-3,3,0.3,10,SH\n"
    "i1|L1|Organelo|La fotosíntesis ocurre en ____|raíces,cloroplastos*,flores,tallo|0.9,-1.2,0.25|1|Fund,0.2,low\n"
    "i2|L3|Presión|Al aumentar la presión atmosférica, el punto de ebullición del agua ____|aumenta*,disminuye,no cambia,desaparece|1.5,0.3,0.25|3|Física,0.2,medium"
)


def _ejemplo_json() -> str:
    from minifmt import parse
    doc = parse(_EJEMPLO_MINI, lectura_mini.contrato(), strict=False)
    cabecera = {k: v for k, v in doc.header.items() if k != "v"}
    # JSON compacto, un ítem por línea: la forma más económica de JSON, para no inflar la comparación
    compacto = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    return ('{"header":' + compacto(cabecera) + ',\n"items":[\n' + ",\n".join(compacto(r) for r in doc.records) + "\n]}")


def _seccion_json() -> str:
    return (
        "## FORMATO DE SALIDA — JSON\n\n"
        "El output es un unico objeto JSON valido, sin texto antes ni despues: una cabecera `header` y la lista `items`.\n\n"
        "### Cabecera `header`\n"
        '{"m": "<modelo>", "d": "<YYYYMMDD>", "n": <total>, "l": "<idioma>", "t": "<tema>", "bd": [L1, L2, L3, L4, L5, L6], '
        '"cat": {"theta_init": .., "theta_min": .., "theta_max": .., "se_stop": .., "max_items": .., "exposure_ctrl": ".."}}\n\n'
        "### Cada item de `items`\n"
        '{"id": "i<N>", "bloom": "<bloom>", "topic": "<topic>", "statement": "<enunciado>", "options": ["<opA>", "<opB>", "<opC>", "<opD>"], '
        '"correct": <indice 0-3 de la opcion correcta>, "irt": {"a": .., "b": .., "c": ..}, "difficulty": <difficulty_level>, '
        '"cat": {"area": "<content_area>", "exposure_cap": .., "demand": "<cognitive_demand>"}}\n\n'
        "- La opcion correcta se indica con su indice en `correct`\n"
        "- Sin comentarios ni comas finales\n\n"
        "### Ejemplo (2 items):\n```json\n" + _ejemplo_json() + "\n```\n"
    )


def prompt_json(prompt_mini: str) -> str:
    """El prompt de SIMA con la sección de formato y las menciones de salida cambiadas a JSON."""
    ini = prompt_mini.find("## FORMATO DE SALIDA")
    fin = prompt_mini.find("\n---\n", ini)
    if ini < 0 or fin < 0:
        raise ValueError("el prompt de generación no tiene la sección de formato esperada")
    p = prompt_mini[:ini] + _seccion_json() + prompt_mini[fin:]
    cambios = [
        ("genera items de evaluacion en formato MINI", "genera items de evaluacion en formato JSON"),
        ("genera EXACTAMENTE esa cantidad de lineas `i<N>|`", "genera EXACTAMENTE esa cantidad de elementos en `items`"),
        ("`a|n=` debe contar solo los items del chunk actual", "`header.n` debe contar solo los items del chunk actual"),
        ("Genera EXCLUSIVAMENTE las lineas MINI (una `a|` + N lineas `i`).", "Genera EXCLUSIVAMENTE el objeto JSON (`header` + `items`)."),
        ("- Texto explicativo fuera del bloque MINI", "- Texto explicativo fuera del objeto JSON"),
        ("- JSON, YAML, XML u otro formato", "- MINI, YAML, XML u otro formato"),
        ("- La opcion correcta marcada con `*` al final de su texto", "- La opcion correcta indicada por su indice en `correct`"),
        ("MODO_CLOUD_MINI_DIRECTO:", "MODO_CLOUD_DIRECTO:"),
        ("entregar un MINI final ya auditado", "entregar un JSON final ya auditado"),
        ("- Devuelve solo MINI: una cabecera a| y las lineas i<N>|.", "- Devuelve solo el objeto JSON."),
    ]
    for viejo, nuevo in cambios:
        p = p.replace(viejo, nuevo)
    return p


def _leer_json(texto: str) -> tuple[list, str]:
    """(items, error) como lo haría una integración con JSON: el objeto completo o nada."""
    t = (texto or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    ini, fin = t.find("{"), t.rfind("}")
    if ini < 0 or fin <= ini:
        return [], "no hay un objeto JSON en la respuesta"
    try:
        datos = json.loads(t[ini:fin + 1])
    except json.JSONDecodeError as exc:
        return [], f"JSON inválido: {exc.msg} (línea {exc.lineno})"
    items = datos.get("items") if isinstance(datos, dict) else None
    return (items if isinstance(items, list) else []), ("" if isinstance(items, list) else "el JSON no trae la lista items")


def _validas_json(items: list) -> int:
    """Cuántos ítems JSON cumplen el mismo contrato que la línea .mini."""
    from minifmt import dumps
    validas = 0
    for it in items:
        try:
            texto = dumps({"header": {}, "items": [it]}, lectura_mini.contrato())
        except Exception:  # noqa: BLE001 - un ítem que no se puede escribir no cumple el contrato
            continue
        if not lectura_mini.validar_item(texto, coherencia=False):
            validas += 1
    return validas


def _precio() -> tuple[float, float]:
    """USD por millón de tokens (entrada, salida); configurable, por defecto DeepSeek V4 Flash de septiembre de 2026."""
    try:
        return float(os.environ.get("DEMO_PRECIO_ENTRADA", "0.22")), float(os.environ.get("DEMO_PRECIO_SALIDA", "0.66"))
    except ValueError:
        return 0.22, 0.66


def _llamar(prompt: str, avance) -> dict:
    """Llamada en streaming al proveedor configurado en SIMA; informa el texto parcial y devuelve las métricas."""
    from openai import OpenAI

    modelo = model_for_role("generation")
    cliente = OpenAI(api_key=getattr(settings, "CLOUD_API_KEY", ""), max_retries=0,
                     base_url=normalize_openai_base_url(getattr(settings, "CLOUD_API_BASE", "") or "https://api.deepseek.com"),
                     timeout=getattr(settings, "CLOUD_API_TIMEOUT", 120))
    pedido = dict(model=modelo, messages=[{"role": "user", "content": prompt}], stream=True,
                  temperature=getattr(settings, "CLOUD_GENERATION_TEMPERATURE", 0.3),
                  stream_options={"include_usage": True})
    limite = int(getattr(settings, "CLOUD_MAX_TOKENS", 0) or 0)
    if limite > 0:
        pedido["max_tokens"] = limite
    if getattr(settings, "CLOUD_PROVIDER", "") == "qwen":
        pedido["extra_body"] = {"enable_thinking": False}
    inicio, texto, uso, fin_motivo, ultimo = time.monotonic(), [], None, "", 0.0
    for parte in cliente.chat.completions.create(**pedido):
        if getattr(parte, "usage", None):
            uso = parte.usage
        for opcion in getattr(parte, "choices", None) or []:
            delta = getattr(opcion.delta, "content", None) or ""
            if delta:
                texto.append(delta)
            if opcion.finish_reason:
                fin_motivo = opcion.finish_reason
        if time.monotonic() - ultimo > 0.8:
            ultimo = time.monotonic()
            avance("".join(texto), ultimo - inicio)
    return {"texto": "".join(texto), "segundos": round(time.monotonic() - inicio, 1), "corte": fin_motivo == "length",
            "tokens_entrada": getattr(uso, "prompt_tokens", 0) if uso else 0,
            "tokens_salida": getattr(uso, "completion_tokens", 0) if uso else 0}


def _medir(formato: str, prompt: str, guardar) -> None:
    def avance(parcial, segundos):
        guardar({"estado": "generando", "caracteres": len(parcial), "segundos": round(segundos, 1), "respuesta": parcial[-6000:]})

    guardar({"estado": "generando", "caracteres": 0, "segundos": 0})
    try:
        r = _llamar(prompt, avance)
    except Exception as exc:  # noqa: BLE001 - se informa en la página
        guardar({"estado": "error", "error": str(exc)[:300]})
        return
    if formato == "mini":
        doc, leido, _ = lectura_mini._leer(r["texto"])
        total = len(doc.splitlines()) - 1
        validas = len(leido.records) if leido is not None else 0
        error = "" if leido is not None else "no hay documento .mini"
        rechazadas = [(e.line, e.code) for e in (leido.errors if leido is not None else []) if e.line and e.line > 1][:20]
    else:
        items, error = _leer_json(r["texto"])
        total, validas, rechazadas = len(items), _validas_json(items), []
    entrada, salida = _precio()
    guardar({
        "estado": "listo", "caracteres": len(r["texto"]), "segundos": r["segundos"], "corte": r["corte"],
        "tokens_entrada": r["tokens_entrada"], "tokens_salida": r["tokens_salida"],
        "costo_usd": round((r["tokens_entrada"] * entrada + r["tokens_salida"] * salida) / 1_000_000, 6),
        "total": total, "validas": validas, "rechazadas": rechazadas, "error": error, "respuesta": r["texto"][-12000:],
    })


def iniciar(comparacion) -> None:
    """Lanza las dos llamadas en paralelo; cada una guarda su avance en su propio campo de la comparación."""
    from ..models import ComparacionFormato

    prompt_mini = build_generation_prompt(comparacion.fragmento, language="es", items_requested=comparacion.items,
                                          chunk_info=f"1 de 1; generar exactamente {comparacion.items} items unicos",
                                          cloud_optimized=True)
    prompts = {"mini": prompt_mini, "json": prompt_json(prompt_mini)}

    def trabajo(formato):
        def guardar(datos):
            ComparacionFormato.objects.filter(pk=comparacion.pk).update(**{formato: datos})
        try:
            _medir(formato, prompts[formato], guardar)
        finally:
            close_old_connections()

    def ambos():
        hilos = [threading.Thread(target=trabajo, args=(f,), daemon=True) for f in ("mini", "json")]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        ComparacionFormato.objects.filter(pk=comparacion.pk).update(estado="listo")
        close_old_connections()

    threading.Thread(target=ambos, name=f"sima-comparacion-{comparacion.pk}", daemon=True).start()
