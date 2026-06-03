"""
Parser, corrector y serializador del formato MINI.

Formato:
  a|m=...|d=...|n=...|l=...|t=...|bd=...|cat=...
  i<N>|<bloom>|<topic>|<statement>|<optA>,<optB>,<optC>,<optD>|<a>,<b>,<c>|<difficulty>|<area>,<exp_cap>,<demand>

La opcion correcta lleva * al final de su texto: "cloroplastos*".
Los campos separados por coma aceptan comillas CSV, por ejemplo:
  "Garcia [2021], p. 1"
"""

import csv
import io
from dataclasses import dataclass, field
from html import escape


@dataclass
class MiniItem:
    id: str
    bloom: str
    topic: str
    statement: str
    options: list
    irt_a: float
    irt_b: float
    irt_c: float
    difficulty: int
    area: str
    exposure_cap: float
    demand: str
    raw: str = ""


@dataclass
class MiniAssessment:
    header: str
    items: list = field(default_factory=list)


def parse_mini(text: str) -> MiniAssessment:
    """Parsea un bloque MINI y devuelve un MiniAssessment."""
    assessment = MiniAssessment(header="")
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("a|"):
            assessment.header = line
        elif line.startswith("i") and "|" in line:
            item = _parse_item_line(line)
            if item:
                assessment.items.append(item)
    return assessment


def _has_coherent_statement(statement: str) -> bool:
    """Verifica que el enunciado sea una pregunta (?) o completacion (____)."""
    s = statement.strip()
    return "____" in s or s.endswith("?")


def _parse_item_line(line: str, strict_coherence: bool = False) -> MiniItem | None:
    parts = line.split("|")
    if len(parts) < 8:
        return None
    try:
        item_id = parts[0]
        bloom = parts[1]
        topic = parts[2]
        statement = parts[3]
        if strict_coherence and not _has_coherent_statement(statement):
            return None
        if len(parts) == 8:
            opts_raw = _split_csv(parts[4])
            irt_parts = _split_csv(parts[5])
            difficulty = int(parts[6])
            cat_parts = _split_csv(parts[7])
        else:
            # Some local models drift and separate the four answer options with
            # pipes instead of CSV commas. Keep those items parseable instead of
            # dropping the whole question.
            opts_raw = [part.strip() for part in parts[4:-3] if part.strip()]
            irt_parts = _split_csv(parts[-3])
            difficulty = int(parts[-2])
            cat_parts = _split_csv(parts[-1])

        options = [{"text": option.rstrip("*"), "correct": option.endswith("*")} for option in opts_raw]
        if options and not any(option["correct"] for option in options):
            options[0]["correct"] = True
        irt_a, irt_b, irt_c = float(irt_parts[0]), float(irt_parts[1]), float(irt_parts[2])
        area = cat_parts[0]
        exposure_cap = float(cat_parts[1]) if len(cat_parts) > 1 else 0.2
        demand = cat_parts[2] if len(cat_parts) > 2 else ""

        return MiniItem(
            id=item_id,
            bloom=bloom,
            topic=topic,
            statement=statement,
            options=options,
            irt_a=irt_a,
            irt_b=irt_b,
            irt_c=irt_c,
            difficulty=difficulty,
            area=area,
            exposure_cap=exposure_cap,
            demand=demand,
            raw=line,
        )
    except (IndexError, ValueError):
        return None


def expected_item_count(header: str) -> int | None:
    meta = parse_header(header) if header else {}
    try:
        return int(meta.get("n", ""))
    except (TypeError, ValueError):
        return None


def filter_incoherent_items(mini_text: str) -> tuple[str, list[str], str]:
    """
    Filtra items cuyo enunciado no tenga ? ni ____.
    Retorna: (mini_coherentes, lista_log_descartados, mini_incoherentes)
    El mini_incoherentes puede repararse y mergearse de vuelta.
    """
    assessment = parse_mini(mini_text)
    if not assessment.header:
        return mini_text, [], ""

    kept = []
    dropped_items = []
    dropped_log = []
    for item in assessment.items:
        if _has_coherent_statement(item.statement):
            kept.append(item)
        else:
            dropped_items.append(item)
            dropped_log.append(f"{item.id}: {item.statement[:80]}")

    if not dropped_log:
        return mini_text, [], ""

    # MINI de coherentes
    coherent_assessment = MiniAssessment(header=assessment.header, items=kept)
    coherent_serialized = _serialize(coherent_assessment)
    header_lines = coherent_serialized.splitlines()
    if header_lines:
        header = header_lines[0]
        meta = parse_header(header)
        meta["n"] = str(len(kept))
        new_header = "a|" + "|".join(f"{k}={v}" for k, v in meta.items() if k != "_type")
        header_lines[0] = new_header
        coherent_serialized = "\n".join(header_lines)

    # MINI de incoherentes (mismo header para poder repararlos)
    incoherent_assessment = MiniAssessment(header=assessment.header, items=dropped_items)
    incoherent_serialized = _serialize(incoherent_assessment)

    return coherent_serialized, dropped_log, incoherent_serialized


def validate_mini_parse(mini_text: str, stage: str = "MINI", strict_coherence: bool = False) -> MiniAssessment:
    if strict_coherence:
        mini_text, dropped, _incoherent_mini = filter_incoherent_items(mini_text)
        if dropped:
            # Loguear pero no fallar si quedan items validos
            pass
    assessment = parse_mini(mini_text)
    expected = expected_item_count(assessment.header)
    actual = len(assessment.items)
    if not assessment.header:
        raise ValueError(f"{stage}: falta cabecera MINI a|.")
    if actual <= 0:
        raise ValueError(f"{stage}: no se pudo parsear ningun item MINI.")
    if expected is not None and actual != expected:
        raise ValueError(f"{stage}: la cabecera declara {expected} items, pero parsean {actual}.")
    return assessment


def normalize_mini_text(mini_text: str, stage: str = "MINI") -> str:
    assessment = validate_mini_parse(mini_text, stage=stage)
    return _serialize(assessment)


def _split_csv(value: str) -> list[str]:
    return next(csv.reader([value], delimiter=",", quotechar='"', skipinitialspace=False))


def _join_csv(values: list) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", quotechar='"', lineterminator="")
    writer.writerow(["" if value is None else str(value) for value in values])
    return buffer.getvalue()


def parse_header(header: str) -> dict:
    meta = {}
    for part in header.lstrip("a|").split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            meta[key] = value
    return meta


def assessment_to_dict(assessment: MiniAssessment) -> dict:
    meta = parse_header(assessment.header) if assessment.header else {}
    cat_parts = _split_csv(meta.get("cat", "")) if meta.get("cat") else []
    bloom_distribution = []
    if meta.get("bd"):
        raw_bloom = _split_csv(meta["bd"])
        try:
            bloom_distribution = [int(value) for value in raw_bloom]
        except ValueError:
            bloom_distribution = raw_bloom

    items = []
    for item in assessment.items:
        items.append({
            "id": item.id,
            "bloom_level": item.bloom,
            "topic": item.topic,
            "statement": item.statement,
            "options": [
                {"text": option["text"], "correct": option["correct"]}
                for option in item.options
            ],
            "irt": {"a": item.irt_a, "b": item.irt_b, "c": item.irt_c},
            "difficulty_level": item.difficulty,
            "cat_meta": {
                "content_area": item.area,
                "exposure_cap": item.exposure_cap,
                "cognitive_demand": item.demand,
            },
        })

    return {
        "assessment": {
            "meta": {
                "model": meta.get("m", ""),
                "generated_at": meta.get("d", ""),
                "total_items": len(items),
                "language": meta.get("l", ""),
                "topic": meta.get("t", ""),
                "bloom_distribution": bloom_distribution,
                "cat_params": {
                    "theta_init": _number_or_text(cat_parts, 0),
                    "theta_min": _number_or_text(cat_parts, 1),
                    "theta_max": _number_or_text(cat_parts, 2),
                    "se_stop": _number_or_text(cat_parts, 3),
                    "max_items": _number_or_text(cat_parts, 4),
                    "exposure_control": cat_parts[5] if len(cat_parts) > 5 else "",
                },
                "raw": meta,
            },
            "items": items,
        }
    }


def _number_or_text(values: list[str], index: int):
    if len(values) <= index:
        return ""
    value = values[index]
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def dict_to_mini(data: dict) -> str:
    assessment = data.get("assessment", data)
    meta = assessment.get("meta", {})
    items = assessment.get("items", [])
    raw = meta.get("raw", {})
    cat = meta.get("cat_params", raw.get("cat", "0,-3,3,0.3,12,SH"))

    if isinstance(cat, dict):
        cat = _join_csv([
            cat.get("theta_init", 0),
            cat.get("theta_min", -3),
            cat.get("theta_max", 3),
            cat.get("se_stop", 0.3),
            cat.get("max_items", len(items)),
            cat.get("exposure_control", "SH"),
        ])

    bloom_distribution = meta.get("bloom_distribution", raw.get("bd", ""))
    if isinstance(bloom_distribution, list):
        bloom_distribution = _join_csv(bloom_distribution)

    header = (
        f'a|m={meta.get("model", raw.get("m", "IRT3PL"))}'
        f'|d={meta.get("generated_at", raw.get("d", ""))}'
        f'|n={len(items)}'
        f'|l={meta.get("language", raw.get("l", "es"))}'
        f'|t={meta.get("topic", raw.get("t", "Evaluacion"))}'
        f'|bd={bloom_distribution}'
        f'|cat={cat}'
    )
    lines = [header]

    for index, item in enumerate(items, start=1):
        options = []
        for option in item.get("options", []):
            text = str(option.get("text", ""))
            options.append(f"{text}*" if option.get("correct") else text)
        irt = item.get("irt", {})
        cat_meta = item.get("cat_meta", {})
        lines.append(
            "|".join([
                item.get("id", f"i{index}"),
                item.get("bloom_level", item.get("bloom", "L1")),
                item.get("topic", ""),
                item.get("statement", ""),
                _join_csv(options),
                _join_csv([irt.get("a", 1), irt.get("b", 0), irt.get("c", 0.25)]),
                str(item.get("difficulty_level", item.get("difficulty", 1))),
                _join_csv([
                    cat_meta.get("content_area", item.get("area", "")),
                    cat_meta.get("exposure_cap", item.get("exposure_cap", 0.2)),
                    cat_meta.get("cognitive_demand", item.get("demand", "medium")),
                ]),
            ])
        )
    return "\n".join(lines)


def apply_corrections(mini_text: str, report_text: str) -> str:
    """
    Aplica automaticamente las correcciones del reporte v| sobre el MINI original.
    Devuelve el MINI corregido como string.
    """
    corrected, _trace = apply_corrections_with_trace(mini_text, report_text)
    return corrected


def apply_corrections_with_trace(mini_text: str, report_text: str) -> tuple[str, list[dict]]:
    """
    Aplica correcciones y devuelve una traza auditable.
    Soporta reportes que referencian items como "1", "i1", o incluso "L1" (fallback al primer item con ese nivel Bloom).
    """
    assessment = parse_mini(mini_text)
    errors = _parse_report(report_text)
    item_index = {}
    bloom_index: dict[str, list] = {}
    for item in assessment.items:
        item_index[item.id] = item
        if item.id.startswith("i") and item.id[1:].isdigit():
            item_index[item.id[1:]] = item
        if item.bloom and item.bloom.startswith("L"):
            bloom_index.setdefault(item.bloom, []).append(item)

    trace = []
    for err in errors:
        item_id = err["item_id"]
        item = item_index.get(item_id)
        # Fallback: si el ID es un nivel Bloom (L1-L6), usar el primer item con ese nivel
        if not item and item_id in bloom_index:
            item = bloom_index[item_id][0]
        entry = {
            "report_item_id": item_id,
            "matched": bool(item),
            "matched_item_id": item.id if item else "",
            "error_type": err.get("error_type", ""),
            "field": err.get("field", ""),
            "original": err.get("original", ""),
            "fix": err.get("fix", ""),
            "justification": err.get("justification", ""),
            "before": _item_snapshot(item) if item else None,
            "after": None,
            "applied": False,
            "note": "",
        }
        if not item:
            entry["note"] = "No se encontro un item MINI con ese id."
            trace.append(entry)
            continue

        before = _item_snapshot(item)
        _apply_fix(item, err)
        after = _item_snapshot(item)
        entry["after"] = after
        entry["applied"] = before != after
        entry["note"] = "Cambio aplicado al MINI." if entry["applied"] else "La correccion no cambio el MINI."
        trace.append(entry)

    return _serialize(assessment), trace


def _item_snapshot(item: MiniItem | None) -> dict | None:
    if not item:
        return None
    return {
        "id": item.id,
        "statement": item.statement,
        "options": [
            {"text": option["text"], "correct": option["correct"]}
            for option in item.options
        ],
        "irt": {"a": item.irt_a, "b": item.irt_b, "c": item.irt_c},
        "difficulty": item.difficulty,
        "area": item.area,
        "demand": item.demand,
    }


def _parse_report(report_text: str) -> list:
    """Parsea lineas e<N>|<item_id>|<error_type>|<field>|<original>|<fix>|<justif>."""
    errors = []
    for line in report_text.strip().splitlines():
        line = line.strip()
        if line.startswith("e") and "|" in line:
            parts = line.split("|", 6)
            if len(parts) >= 6:
                errors.append({
                    "item_id": parts[1],
                    "error_type": parts[2],
                    "field": parts[3],
                    "original": parts[4],
                    "fix": parts[5],
                    "justification": parts[6] if len(parts) > 6 else "",
                })
    return errors


def _apply_fix(item: MiniItem, err: dict):
    error_type = err["error_type"]
    field = err.get("field", "")
    fix = err["fix"].strip()

    if error_type == "wrong_answer":
        fixed_options = _split_csv(fix)
        if len(fixed_options) >= 2 and any(option.endswith("*") for option in fixed_options):
            item.options = [
                {"text": option.rstrip("*"), "correct": option.endswith("*")}
                for option in fixed_options
            ]
        else:
            correct_text = fix.rstrip("*")
            for opt in item.options:
                opt["correct"] = opt["text"] == correct_text

    elif error_type in {"ambiguous_statement", "wrong_statement"} or field in {"enunciado", "statement"}:
        item.statement = fix

    elif error_type == "implausible_distractor":
        old, new = "", ""
        if "->" in fix:
            old, new = fix.split("->", 1)
        elif "→" in fix:
            old, new = fix.split("→", 1)
        if old:
            for opt in item.options:
                if opt["text"].strip() == old.strip():
                    opt["text"] = new.strip()

    elif error_type == "irt_mismatch":
        try:
            for part in fix.split(","):
                key, value = part.split("=")
                if key.strip() == "a":
                    item.irt_a = float(value)
                elif key.strip() == "b":
                    item.irt_b = float(value)
                elif key.strip() == "c":
                    item.irt_c = float(value)
        except ValueError:
            pass


def _serialize(assessment: MiniAssessment) -> str:
    lines = [assessment.header]
    for item in assessment.items:
        opts = _join_csv([
            option["text"] + "*" if option["correct"] else option["text"]
            for option in item.options
        ])
        lines.append(
            f"{item.id}|{item.bloom}|{item.topic}|{item.statement}|"
            f"{opts}|{_join_csv([item.irt_a, item.irt_b, item.irt_c])}|"
            f"{item.difficulty}|{_join_csv([item.area, item.exposure_cap, item.demand])}"
        )
    return "\n".join(lines)


def render_mini_html(mini_text: str) -> str:
    """Convierte un bloque MINI en HTML legible para mostrar en el template."""
    assessment = parse_mini(mini_text)
    if not assessment.items:
        return f'<pre class="mini-raw">{mini_text}</pre>'

    meta = parse_header(assessment.header)
    html = ['<div class="mini-viewer">']
    html.append(
        f'<div class="mini-meta">'
        f'<span>Modelo: {escape(meta.get("m", "-"))}</span>'
        f'<span>Idioma: {escape(meta.get("l", "-"))}</span>'
        f'<span>Tema: {escape(meta.get("t", "-"))}</span>'
        f'<span>Total: {escape(meta.get("n", "-"))} items</span>'
        f'</div>'
    )

    bloom_color = {
        "L1": "#7dd3fc",
        "L2": "#d4ff00",
        "L3": "#ffc800",
        "L4": "#ff9600",
        "L5": "#ff5f57",
        "L6": "#ce82ff",
    }
    demand_label = {"low": "Baja", "medium": "Media", "high": "Alta"}

    for item in assessment.items:
        color = bloom_color.get(item.bloom, "#8a8a82")
        html.append('<div class="mini-item">')
        html.append(
            f'<div class="mini-item-header">'
            f'<span class="mini-id">{escape(item.id)}</span>'
            f'<span class="mini-bloom" style="background:{color}">{escape(item.bloom)}</span>'
            f'<span class="mini-topic">{escape(item.topic)}</span>'
            f'<span class="mini-diff">Dif. {item.difficulty}</span>'
            f'</div>'
        )
        html.append(f'<p class="mini-statement">{escape(item.statement)}</p>')
        html.append('<ol class="mini-options" type="A">')
        for opt in item.options:
            cls = "mini-opt-correct" if opt["correct"] else "mini-opt"
            mark = (
                ' <span class="mini-correct-icon" aria-label="Correcta">'
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="3" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>'
                "</span>"
            ) if opt["correct"] else ""
            html.append(f'<li class="{cls}">{escape(opt["text"])}{mark}</li>')
        html.append("</ol>")
        html.append(
            f'<div class="mini-irt">'
            f'<span>a={item.irt_a}</span>'
            f'<span>b={item.irt_b}</span>'
            f'<span>c={item.irt_c}</span>'
            f'<span>Demanda: {escape(demand_label.get(item.demand, item.demand))}</span>'
            f'</div>'
        )
        html.append("</div>")

    html.append("</div>")
    return "\n".join(html)


def check_option_uniformity(item: MiniItem) -> list[str]:
    """
    Detecta problemas de calidad en las opciones de un item:
    - Opciones fusionadas por comas (3 en 1)
    - Ratio de longitud > 3x (sesgo de longitud)
    - Menos de 4 opciones
    """
    problems = []
    opts = [o["text"] for o in item.options]

    if len(opts) != 4:
        problems.append(f"tiene_{len(opts)}_opciones")
        return problems

    # Detectar fusion por comas: una opcion tiene comas, las demas no
    comma_counts = [opt.count(",") for opt in opts]
    if max(comma_counts) > 0 and min(comma_counts) == 0:
        problems.append("opciones_fusionadas_por_comas")

    # Ratio de longitud max/min > 3 (sesgo de longitud)
    lengths = [len(opt.strip()) for opt in opts]
    if min(lengths) > 0:
        ratio = max(lengths) / min(lengths)
        if ratio > 3:
            problems.append(f"ratio_longitud_{ratio:.1f}x")

    return problems


def filter_nonuniform_items(mini_text: str) -> tuple[str, list[str], str]:
    """
    Filtra items con opciones malformadas (fusionadas, desiguales, etc.).
    Retorna: (mini_uniforme, lista_log, mini_no_uniforme)
    """
    assessment = parse_mini(mini_text)
    if not assessment.header:
        return mini_text, [], ""

    kept = []
    bad_items = []
    dropped_log = []
    for item in assessment.items:
        problems = check_option_uniformity(item)
        if problems:
            bad_items.append(item)
            dropped_log.append(f"{item.id}: {item.statement[:50]}... ({', '.join(problems)})")
        else:
            kept.append(item)

    if not dropped_log:
        return mini_text, [], ""

    uniform_assessment = MiniAssessment(header=assessment.header, items=kept)
    uniform_serialized = _serialize(uniform_assessment)
    header_lines = uniform_serialized.splitlines()
    if header_lines:
        header = header_lines[0]
        meta = parse_header(header)
        meta["n"] = str(len(kept))
        new_header = "a|" + "|".join(f"{k}={v}" for k, v in meta.items() if k != "_type")
        header_lines[0] = new_header
        uniform_serialized = "\n".join(header_lines)

    bad_assessment = MiniAssessment(header=assessment.header, items=bad_items)
    bad_serialized = _serialize(bad_assessment)

    return uniform_serialized, dropped_log, bad_serialized


def merge_mini_chunks(chunks: list[str]) -> str:
    """
    Mergea múltiples bloques MINI en uno solo.
    - Usa la cabecera a| del primer chunk como base
    - Renumera todos los ítems secuencialmente (i1, i2, ...)
    - Recalcula bloom_distribution y total en la cabecera
    - Elimina ítems duplicados por enunciado (mismo statement)
    """
    from datetime import date

    all_items = []
    base_header_meta = {}
    seen_statements = set()

    for chunk in chunks:
        if not chunk.strip():
            continue
        assessment = parse_mini(chunk)
        if not base_header_meta and assessment.header:
            base_header_meta = parse_header(assessment.header)
        for item in assessment.items:
            # deduplicar por enunciado normalizado
            key = item.statement.strip().lower()
            if key not in seen_statements:
                seen_statements.add(key)
                all_items.append(item)

    if not all_items:
        return chunks[0] if chunks else ""

    # recalcular bloom distribution
    bloom_counts = {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 0, "L6": 0}
    for item in all_items:
        if item.bloom in bloom_counts:
            bloom_counts[item.bloom] += 1
    bd = _join_csv([bloom_counts[f"L{i}"] for i in range(1, 7)])

    n = len(all_items)
    # CAT: max_items = min(20, n) para no agotar el banco en una sesión
    max_session = min(20, n)
    cat = f"0,-3,3,0.3,{max_session},SH"

    header = (
        f'a|m={base_header_meta.get("m", "IRT3PL")}'
        f'|d={date.today().strftime("%Y%m%d")}'
        f'|n={n}'
        f'|l={base_header_meta.get("l", "es")}'
        f'|t={base_header_meta.get("t", "Evaluacion")}'
        f'|bd={bd}'
        f'|cat={cat}'
    )

    lines = [header]
    for idx, item in enumerate(all_items, 1):
        item.id = f"i{idx}"
        opts = _join_csv([
            opt["text"] + "*" if opt["correct"] else opt["text"]
            for opt in item.options
        ])
        lines.append(
            f"{item.id}|{item.bloom}|{item.topic}|{item.statement}|"
            f"{opts}|{_join_csv([item.irt_a, item.irt_b, item.irt_c])}|"
            f"{item.difficulty}|{_join_csv([item.area, item.exposure_cap, item.demand])}"
        )

    return "\n".join(lines)
