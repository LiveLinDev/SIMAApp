"""
Lectura de las respuestas del modelo con mini-format (contrato de la familia `a`).

Reemplaza, en la generación de ítems, la lectura tolerante de parse_mini.py, que descarta en silencio las líneas
que no entiende y marca como correcta la primera opción cuando el modelo no marcó ninguna. Con el contrato de
mini-format cada bloque que devuelve el modelo se procesa así:

  1. se separan la cabecera y las líneas de ítem del resto del texto que escribió el modelo;
  2. se valida línea por línea contra el contrato;
  3. los ítems completos y válidos se conservan aunque la respuesta llegue cortada;
  4. solo las líneas inválidas se reenvían al modelo para corregirlas, y la corrección se valida antes de aceptarla;
  5. solo los ítems que faltan se piden en una llamada aparte.

El resultado es un bloque `a|` + `i<N>|` que el resto de SIMA sigue leyendo con parse_mini.py.
El lector se elige con la variable SIMA_LECTOR ("minifmt" por defecto, "legado" para comparar).
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field

from minifmt import MiniValidationError, Registry, dumps, parse
from minifmt.ai import extract_document, merge_repair, repair_request

from learning.parse_mini import parse_mini

_CONTRATO = None
# línea de ítem, también cuando el modelo la escribe como "i3: L1|..." o dentro de una lista o bloque de código
_REGISTRO = re.compile(r"^[`>*\s-]*(i\d+)\s*([|:])\s*(.*)$")


def contrato():
    """Contrato de la familia `a` (ítems de evaluación) incluido en mini-format."""
    global _CONTRATO
    if _CONTRATO is None:
        _CONTRATO = Registry.load().get("a")
    return _CONTRATO


def lector_activo() -> str:
    valor = os.environ.get("SIMA_LECTOR", "minifmt").strip().lower()
    return "legado" if valor in {"legado", "legacy", "parse_mini"} else "minifmt"


@dataclass
class Bloque:
    """Qué pasó con la respuesta del modelo para un bloque de la clase."""
    bloque: str
    lector: str
    pedidos: int
    recibidos: int = 0                 # ítems completos y válidos en la primera respuesta
    lineas_invalidas: list = field(default_factory=list)   # [(línea, código, campo)]
    truncado: bool = False
    normalizados: int = 0              # líneas escritas como "i3: L1|..." en lugar de "i3|L1|..."
    borradores: int = 0                # versiones anteriores de un mismo ítem (se conserva la última)
    prosa_descartada: int = 0          # líneas de texto del modelo que no son cabecera ni ítems
    sin_cabecera: bool = False
    reparados: list = field(default_factory=list)          # líneas corregidas y aceptadas
    rechazados: list = field(default_factory=list)         # correcciones que seguían siendo inválidas
    faltantes_pedidos: int = 0
    recuperados: int = 0               # ítems válidos obtenidos al pedir los que faltaban
    finales: int = 0
    llamadas: int = 1
    # lo que hace parse_mini.py con la misma primera respuesta (se registra con ambos lectores)
    legado_aceptados: int = 0
    legado_sin_correcta: int = 0       # ítems sin respuesta marcada a los que se les marcó la primera opción
    legado_descartados: int = 0        # líneas de ítem que el lector anterior omitió sin aviso
    legado_invalidos: int = 0          # ítems que no cumplen el contrato y el lector anterior aceptó igual

    def a_dict(self) -> dict:
        return asdict(self)


def _lineas_item(texto: str) -> tuple[str | None, list[str], dict]:
    """(cabecera o None, líneas de ítem normalizadas, ajustes contados)."""
    cabecera, registros = None, []
    ajustes = {"normalizados": 0, "prosa_descartada": 0}
    for linea in extract_document(texto or "", contrato()).splitlines():
        limpia = linea.strip().strip("`").strip()
        if not limpia:
            continue
        if cabecera is None and limpia.startswith(contrato().prefix + "|"):
            cabecera = limpia
            continue
        m = _REGISTRO.match(limpia)
        if m:
            if m.group(2) == ":":
                ajustes["normalizados"] += 1
            registros.append(f"{m.group(1)}|{m.group(3)}")
        else:
            ajustes["prosa_descartada"] += 1
    # el modelo a veces escribe un borrador y luego la versión final con los mismos ids: vale la última
    vistos, unicos = set(), []
    for registro in reversed(registros):
        clave = registro.split("|", 1)[0]
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(registro)
    ajustes["borradores"] = len(registros) - len(unicos)
    return cabecera, unicos[::-1], ajustes


def preparar(texto: str) -> tuple[str, dict]:
    """
    Separa el documento .mini del resto de la respuesta.

    Los modelos que escriben su razonamiento antes de responder mezclan el plan con los ítems, a veces sin
    cabecera y con "i3: L1|..." en lugar de "i3|L1|...". Se conservan solo la cabecera y las líneas de ítem, se
    normaliza ese separador y la cabecera declara n igual al número de líneas de ítem (si falta, se escribe una).
    Cada ajuste queda contado; el contenido de los ítems no se toca: su validez la decide el contrato.
    """
    cabecera, registros, ajustes = _lineas_item(texto)
    ajustes["sin_cabecera"] = cabecera is None
    prefijo = contrato().prefix
    if cabecera is None:
        cabecera = f"{prefijo}|n={len(registros)}"
    elif re.search(r"\|n=[^|]*", cabecera):
        cabecera = re.sub(r"\|n=[^|]*", f"|n={len(registros)}", cabecera, count=1)
    else:
        cabecera = f"{cabecera}|n={len(registros)}"
    return "\n".join([cabecera, *registros]), ajustes


def _leer(texto: str):
    """(documento preparado, Document o None, ajustes)."""
    doc, ajustes = preparar(texto)
    try:
        return doc, parse(doc, contrato(), strict=False), ajustes
    except MiniValidationError:
        return doc, None, ajustes


def _cortado(leido, doc: str) -> bool:
    """La última línea de ítem quedó incompleta: la respuesta se cortó por el límite de tokens."""
    ultima = len(doc.splitlines())
    return ultima > 1 and any(e.code == "E05" and e.line == ultima for e in leido.errors)


def _texto(cabecera: dict, registros: list) -> str:
    cab = {k: v for k, v in (cabecera or {}).items() if k != "n"}
    return dumps({"header": cab, "records": registros}, contrato())


def diagnostico_legado(texto: str, pedidos: int, bloque: str) -> Bloque:
    """Lo que el lector anterior hace con una respuesta, medido con el contrato para poder compararlo."""
    doc, leido, _ = _leer(texto)
    ev = Bloque(bloque=bloque, lector="legado", pedidos=pedidos)
    if leido is not None:
        ev.recibidos = len(leido.records)
        ev.lineas_invalidas = [(e.line, e.code, e.field or "") for e in leido.errors if e.line]
        ev.truncado = _cortado(leido, doc)
    legado = parse_mini(texto or "")
    _, lineas, _ = _lineas_item(texto)
    ev.legado_aceptados = len(legado.items)
    ev.legado_descartados = max(0, len(lineas) - len(legado.items))
    ev.legado_sin_correcta = sum(1 for it in legado.items if "*" not in (it.raw or "*"))
    ev.legado_invalidos = sum(1 for it in legado.items if validar_item(f"{contrato().prefix}|n=1\n{it.raw}", coherencia=False))
    ev.finales = len(legado.items)
    return ev


def leer_bloque(texto: str, pedidos: int, bloque: str, llamar, pedir_faltantes) -> tuple[str, Bloque]:
    """
    Procesa la respuesta del modelo para un bloque y devuelve (bloque .mini limpio, informe).

    llamar(prompt) -> str                    llama al modelo con un prompt libre (reparación).
    pedir_faltantes(n, enunciados) -> str    pide n ítems nuevos distintos de los enunciados dados.
    """
    ev = Bloque(bloque=bloque, lector="minifmt", pedidos=pedidos)
    # lo que el lector anterior habría hecho con esta misma respuesta, para comparar sobre los mismos datos
    antes = diagnostico_legado(texto, pedidos, bloque)
    ev.legado_aceptados = antes.legado_aceptados
    ev.legado_sin_correcta = antes.legado_sin_correcta
    ev.legado_descartados = antes.legado_descartados
    ev.legado_invalidos = antes.legado_invalidos

    doc, leido, ajustes = _leer(texto)
    ev.normalizados = ajustes["normalizados"]
    ev.prosa_descartada = ajustes["prosa_descartada"]
    ev.sin_cabecera = ajustes["sin_cabecera"]
    ev.borradores = ajustes["borradores"]
    cabecera = dict(leido.header) if leido is not None else {}
    registros = list(leido.records) if leido is not None else []
    ev.recibidos = len(registros)
    if leido is not None:
        ev.lineas_invalidas = [(e.line, e.code, e.field or "") for e in leido.errors if e.line]
        ev.truncado = _cortado(leido, doc)

    if leido is not None and ev.truncado:
        # la línea cortada no se repara: ese ítem se pide junto con los faltantes
        lineas = doc.splitlines()[:-1]
        lineas[0] = re.sub(r"\|n=[^|]*", f"|n={len(lineas) - 1}", lineas[0], count=1)
        doc = "\n".join(lineas)
        try:
            leido = parse(doc, contrato(), strict=False)
        except MiniValidationError:
            leido = None

    # 1) reparar solo las líneas de ítem inválidas (una sola vez; lo que siga inválido se pide como faltante)
    if leido is not None and any(e.line and e.line > 1 for e in leido.errors):
        solicitud = repair_request(doc, contrato(), "es")
        if solicitud.items:
            respuesta = llamar(solicitud.system + "\n\n" + solicitud.user)
            ev.llamadas += 1
            _, correcciones, _ = _lineas_item(respuesta)
            fusion = merge_repair(doc, "\n".join(correcciones), contrato(), solicitud)
            ev.reparados = list(fusion.replaced)
            ev.rechazados = list(fusion.unresolved)
            if fusion.document is not None:
                cabecera = dict(fusion.document.header)
                registros = list(fusion.document.records)

    # 2) pedir solo los ítems que faltan
    faltan = max(0, pedidos - len(registros))
    if faltan:
        ev.faltantes_pedidos = faltan
        enunciados = [r.get("statement", "") for r in registros]
        _, extra, _ = _leer(pedir_faltantes(faltan, enunciados))
        ev.llamadas += 1
        if extra is not None:
            vistos = {e.strip().lower() for e in enunciados}
            nuevos = [r for r in extra.records if r.get("statement", "").strip().lower() not in vistos][:faltan]
            ev.recuperados = len(nuevos)
            registros.extend(nuevos)
            if not cabecera:
                cabecera = dict(extra.header)

    ev.finales = len(registros)
    if not registros:
        return "", ev
    # ids consecutivos: merge_mini_chunks vuelve a numerar al unir los bloques de la clase
    for i, r in enumerate(registros, 1):
        r["id"] = f"i{i}"
    return _texto(cabecera, registros), ev


def resumen(bloques: list[dict]) -> dict:
    """Totales de la clase para mostrar en pantalla."""
    total = lambda k: sum(b.get(k, 0) for b in bloques)  # noqa: E731
    return {
        "lector": bloques[0]["lector"] if bloques else lector_activo(),
        "bloques": len(bloques),
        "pedidos": total("pedidos"),
        "recibidos": total("recibidos"),
        "invalidos": sum(len(b.get("lineas_invalidas", [])) for b in bloques),
        "truncados": sum(1 for b in bloques if b.get("truncado")),
        "normalizados": total("normalizados"),
        "borradores": total("borradores"),
        "prosa_descartada": total("prosa_descartada"),
        "sin_cabecera": sum(1 for b in bloques if b.get("sin_cabecera")),
        "reparados": sum(len(b.get("reparados", [])) for b in bloques),
        "rechazados": sum(len(b.get("rechazados", [])) for b in bloques),
        "faltantes_pedidos": total("faltantes_pedidos"),
        "recuperados": total("recuperados"),
        "finales": total("finales"),
        "llamadas": total("llamadas"),
        "legado_aceptados": total("legado_aceptados"),
        "legado_sin_correcta": total("legado_sin_correcta"),
        "legado_descartados": total("legado_descartados"),
        "legado_invalidos": total("legado_invalidos"),
    }


def linea_log(r: dict) -> str:
    """Una línea para el registro de procesamiento de la clase."""
    if r["lector"] == "legado":
        return (
            f"{r['finales']} ítems aceptados de {r['pedidos']} pedidos. Con el contrato: {r['invalidos']} líneas inválidas, "
            f"{r['truncados']} respuestas cortadas, {r['legado_sin_correcta']} ítems sin respuesta marcada "
            f"(se marcó la primera opción) y {r['legado_descartados']} líneas de ítem omitidas sin aviso."
        )
    return (
        f"{r['finales']} de {r['pedidos']} ítems válidos en {r['llamadas']} llamadas: {r['recibidos']} en la primera respuesta, "
        f"{r['reparados']} líneas reparadas ({r['invalidos']} inválidas, {r['truncados']} respuestas cortadas) "
        f"y {r['recuperados']} de {r['faltantes_pedidos']} faltantes pedidos aparte. "
        f"El lector anterior habría aceptado {r['legado_aceptados']}."
    )


def validar_item(texto: str, coherencia: bool = True) -> str:
    """Motivo por el que un ítem (cabecera + una línea) no es válido, o "" si cumple el contrato y es coherente."""
    try:
        doc = parse(texto, contrato(), strict=False)
    except MiniValidationError as e:
        return "; ".join(f"{x.code} {x.message}" for x in e.errors[:2])
    errores = [e for e in doc.errors if e.line and e.line > 1]
    if errores or not doc.records:
        return "; ".join(f"{e.code} {e.message}" for e in errores[:2]) or "ítem ilegible"
    enunciado = str(doc.records[0].get("statement", "")).strip()
    if coherencia and "____" not in enunciado and not enunciado.endswith("?"):
        return "el enunciado dejó de ser una pregunta o una completación"
    return ""


def medir_tokens(banco: str) -> dict:
    """
    Tokens de salida del banco en .mini y del mismo banco convertido a JSON (compacto y con sangría).
    Usa el tokenizador o200k_base si tiktoken está instalado; si no, estima 4 caracteres por token.
    """
    import json

    try:
        registros = parse(banco, contrato(), strict=False).records
    except MiniValidationError:
        return {}
    compacto = json.dumps({"items": registros}, ensure_ascii=False, separators=(",", ":"))
    sangria = json.dumps({"items": registros}, ensure_ascii=False, indent=2)
    try:
        import tiktoken

        cod = tiktoken.get_encoding("o200k_base")
        contar, nombre = (lambda s: len(cod.encode(s))), "o200k_base"
    except Exception:  # noqa: BLE001 - la medición es informativa
        contar, nombre = (lambda s: max(1, round(len(s) / 4))), "estimado (4 caracteres por token)"
    return {"tokenizador": nombre, "mini": contar(banco), "json_compacto": contar(compacto), "json": contar(sangria)}
