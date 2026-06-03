import csv
import io
import json
from dataclasses import dataclass, field


@dataclass
class MiniItem:
    id: str
    bloom: str
    topic: str
    statement: str
    options: list[dict]
    irt_a: float
    irt_b: float
    irt_c: float
    difficulty: int
    area: str
    exposure_cap: float
    demand: str
    feedback: str = ""


@dataclass
class MiniAssessment:
    header: str = ""
    items: list[MiniItem] = field(default_factory=list)


def parse_mini(text: str) -> MiniAssessment:
    assessment = MiniAssessment()
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("a|") or line.startswith("q|"):
            assessment.header = line
        elif line.startswith("i") and "|" in line:
            item = _parse_item_line(line)
            if item:
                assessment.items.append(item)
    return assessment


def _split_csv(value: str) -> list[str]:
    return next(csv.reader([value], delimiter=",", quotechar='"', skipinitialspace=False))


def _parse_item_line(line: str) -> MiniItem | None:
    parts = line.split("|")
    if len(parts) < 8:
        return None
    try:
        item_id = parts[0]
        bloom = parts[1]
        topic = parts[2]
        statement = parts[3]

        if len(parts) == 8:
            opts_raw = _split_csv(parts[4])
            irt_parts = _split_csv(parts[5])
            difficulty = int(parts[6])
            cat_parts = _split_csv(parts[7])
            feedback = ""
        elif len(parts) == 9:
            if parts[4].count(",") >= 3:
                opts_raw = _split_csv(parts[4])
                irt_parts = _split_csv(parts[5])
                difficulty = int(parts[6])
                cat_parts = _split_csv(parts[7])
                feedback = parts[8]
            else:
                opts_raw = [p.strip() for p in parts[4:6] if p.strip()]
                irt_parts = _split_csv(parts[6])
                difficulty = int(parts[7])
                cat_parts = _split_csv(parts[8])
                feedback = ""
        else:
            opts_raw = [p.strip() for p in parts[4:-3] if p.strip()]
            irt_parts = _split_csv(parts[-3])
            difficulty = int(parts[-2])
            cat_parts = _split_csv(parts[-1])
            feedback = ""

        options = [{"text": opt.rstrip("*"), "correct": opt.endswith("*")} for opt in opts_raw]
        if options and not any(o["correct"] for o in options):
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
            feedback=feedback,
        )
    except (IndexError, ValueError):
        return None


def parse_header(header: str) -> dict:
    meta = {}
    prefix = header[:2]
    rest = header[2:]
    for part in rest.split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            meta[key] = value
    meta["_type"] = "quiz" if prefix == "q|" else "assessment"
    return meta


def assessment_to_dict(assessment: MiniAssessment) -> dict:
    meta = parse_header(assessment.header) if assessment.header else {}
    cat_parts = _split_csv(meta.get("cat", "")) if meta.get("cat") else []
    bloom_distribution = []
    if meta.get("bd"):
        try:
            bloom_distribution = [int(v) for v in _split_csv(meta["bd"])]
        except ValueError:
            bloom_distribution = _split_csv(meta["bd"])
    items = []
    for item in assessment.items:
        item_dict = {
            "id": item.id,
            "bloom_level": item.bloom,
            "topic": item.topic,
            "statement": item.statement,
            "options": [{"text": o["text"], "correct": o["correct"]} for o in item.options],
            "irt": {"a": item.irt_a, "b": item.irt_b, "c": item.irt_c},
            "difficulty_level": item.difficulty,
            "cat_meta": {
                "content_area": item.area,
                "exposure_cap": item.exposure_cap,
                "cognitive_demand": item.demand,
            },
        }
        if item.feedback:
            item_dict["feedback"] = item.feedback
        items.append(item_dict)
    return {
        "type": meta.get("_type", "assessment"),
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
                "raw": {k: v for k, v in meta.items() if not k.startswith("_")},
            },
            "items": items,
        }
    }


def _number_or_text(values: list[str], index: int):
    if len(values) <= index:
        return ""
    try:
        number = float(values[index])
        return int(number) if number.is_integer() else number
    except ValueError:
        return values[index]


def validate_mini(text: str) -> dict:
    assessment = parse_mini(text)
    expected = None
    if assessment.header:
        meta = parse_header(assessment.header)
        try:
            expected = int(meta.get("n", ""))
        except (TypeError, ValueError):
            pass
    if not assessment.header:
        raise ValueError("Missing MINI header.")
    if not assessment.items:
        raise ValueError("No parseable MINI items found.")
    if expected is not None and len(assessment.items) != expected:
        raise ValueError(
            f"Header declares {expected} items, but parsed {len(assessment.items)}."
        )
    return assessment_to_dict(assessment)


def mini_to_json(text: str) -> str:
    return json.dumps(validate_mini(text), ensure_ascii=False, indent=2)


# ==========================================
# EJEMPLOS REALES Y PRUEBAS
# ==========================================

MINI_ASSESSMENT = """a|m=IRT3PL|d=20250602|n=3|l=es|t=Fotosíntesis|bd=1,1,1|cat=0,-3,3,0.3,12,SH
i1|L1|Botánica|¿Dónde ocurre la fotosíntesis?|cloroplastos*,núcleo,mitocondria,citoplasma|1.2,0.0,0.25|1|botánica,0.2,low
i2|L2|Biología|¿Qué gas liberan las plantas?|oxígeno*,dióxido de carbono,nitrógeno,hidrógeno|1.0,-0.5,0.2|2|botánica,0.3,medium
i3|L3|Fisiología vegetal|Explique relación entre luz y clorofila|La clorofila absorbe luz para convertir CO2 y agua en glucosa|1.5,1.0,0.15|3|fisiología,0.25,high"""

MINI_QUIZ = """q|m=Qwen2.5|d=20250602|n=2|l=es|t=Genética Molecular
i1|L2|ADN|¿Qué base nitrogenada NO existe en el ADN?|uracilo*,timina,citosina,adenina|1.0,0.0,0.25|2|genética,0.2,medium|El uracilo solo aparece en ARN; el ADN usa timina en su lugar.
i2|L3|Replicación|Durante la replicación, ¿qué enzima une los fragmentos de Okazaki?|ADN polimerasa I*,ADN polimerasa III,ligasa,primasa|1.2,0.5,0.2|3|genética,0.3,high|La ligasa es la encargada de unir los fragmentos de Okazaki, no la polimerasa I."""

MINI_DRIFT = """a|m=LocalLLM|d=20250602|n=2|l=es|t=Química|bd=1,1|cat=0,-3,3,0.3,10,SH
i1|L1|Átomos|¿Qué parte del átomo tiene carga positiva?|protón*|neutrón|electrón|núcleo|1.0,0.0,0.25|1|química,0.2,low
i2|L2|Enlaces|Tipo de enlace en el NaCl|iónico*|covalente|metálico|puente de hidrógeno|1.1,-0.3,0.2|2|química,0.25,medium"""

MINI_QUOTED = """a|m=GPT-4|d=20250602|n=1|l=es|t=Citas|bd=1|cat=0,-3,3,0.3,5,SH
i1|L4|Literatura|Según García [2021, p. 45], ¿qué tema central aborda?|"La identidad, la memoria y el olvido"*,"El amor romántico","La guerra civil","La naturaleza"|1.3,0.8,0.15|4|literatura,0.2,high"""


def run_tests():
    print("=" * 60)
    print("EJEMPLO 1: Assessment IRT estandar (.mini)")
    print("=" * 60)
    print(mini_to_json(MINI_ASSESSMENT))

    print("\n" + "=" * 60)
    print("EJEMPLO 2: Cuestionario con retroalimentacion (.mini-q)")
    print("=" * 60)
    print(mini_to_json(MINI_QUIZ))

    print("\n" + "=" * 60)
    print("EJEMPLO 3: Desviacion de pipes (fallback robusto)")
    print("=" * 60)
    print(mini_to_json(MINI_DRIFT))

    print("\n" + "=" * 60)
    print("EJEMPLO 4: CSV entrecomillado con comas internas")
    print("=" * 60)
    print(mini_to_json(MINI_QUOTED))

    print("\n" + "=" * 60)
    print("TODAS LAS PRUEBAS PASARON")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
