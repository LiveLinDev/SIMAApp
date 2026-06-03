import requests
import json
import re
import os
import shutil

URL = "http://127.0.0.1:8001/v1/chat/completions"
HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer local"}
MODEL = "qwen3-30b-endpoint"


def call_local(prompt: str, max_tokens: int = 4000, temperature: float = 0.2) -> str:
    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    r = requests.post(URL, headers=HEADERS, json=data, timeout=120)
    r.raise_for_status()
    result = r.json()
    msg = result["choices"][0]["message"]
    text = msg.get("content", "") or msg.get("reasoning_content", "")
    return text.strip()


def extract_mini(text: str) -> str:
    lines = []
    for raw in text.splitlines():
        line = raw.strip().strip("`")
        if line.startswith("a|") or re.match(r"^i\d+\|", line):
            lines.append(line)
    return "\n".join(lines).strip()


CONTENT_FOTOSINTESIS = """La fotosintesis es el proceso mediante el cual las plantas, algas y algunas bacterias
convierten la energia luminica en energia quimica. Este proceso ocurre principalmente
en los cloroplastos, organulos que contienen clorofila. Durante la fotosintesis,
el dioxido de carbono y el agua se transforman en glucosa y oxigeno, utilizando
la energia de la luz solar. La clorofila es el pigmento principal que absorbe
la luz, especialmente en las longitudes de onda roja y azul."""

CONTENT_MANUEL_PARDO = """Manuel Pardo fue un politico peruano que ocupo la presidencia del Peru
entre 1872 y 1876. Fue el primer presidente civil de la Republica. Su gobierno
promovio la educacion publica, la inmigracion europea y la construccion de
infraestructura. El 16 de noviembre de 1878, fue asesinado en Lima por un
artillero del barco de guerra La Union. Este asesinato genero una crisis
politica significativa y fue considerado un punto de inflexion que desencadeno
mayor inestabilidad en el pais durante el periodo posterior."""


def build_test_prompt(content: str, label: str, use_new_prompt: bool = True) -> str:
    template_file = "PROMPT.md" if use_new_prompt else "PROMPT.md.old"
    with open(template_file, "r", encoding="utf-8") as f:
        template = f.read()

    indent = "\n".join(f"    {line}" for line in content.splitlines())
    return (
        f"{template}\n\n"
        "INPUT:\n"
        "  language: es\n"
        "  items_requested: 5\n"
        "  content: |\n"
        f"{indent}\n\n"
        f"GENERA EXACTAMENTE 5 ITEMS MINI SOBRE ESTE TEMA: {label}. "
        "Solo el bloque MINI, sin explicaciones."
    )


def parse_item_line(line: str) -> dict | None:
    parts = line.split("|")
    if len(parts) < 8:
        return None
    try:
        raw_opts = parts[4].split(",")
        opts = [o.rstrip("*") for o in raw_opts]
        correct = [o.endswith("*") for o in raw_opts]
        return {
            "id": parts[0],
            "bloom": parts[1],
            "topic": parts[2],
            "statement": parts[3],
            "options": [{"text": t, "correct": c} for t, c in zip(opts, correct)],
            "irt": parts[5],
            "difficulty": parts[6],
            "cat": parts[7],
            "raw": line,
        }
    except Exception:
        return None


def validate_coherence(item: dict) -> list[str]:
    errors = []
    stmt = item["statement"]
    opts = [o["text"] for o in item["options"]]

    # RS-1: Tipo A o Tipo B
    has_hole = "____" in stmt
    is_question = stmt.strip().endswith("?")
    if not has_hole and not is_question:
        errors.append(f"RS-1: Enunciado no es Tipo A ni Tipo B: [{stmt}]")

    # RS-3: Detectar mezcla de categorias obvias
    disciplines = ["biologia", "quimica", "fisica", "historia", "geografia", "matematica", "literatura", "alimentacion"]
    organelles = ["cloroplasto", "mitocondria", "nucleo", "ribosoma", "lisosoma"]
    processes = ["fotosintesis", "respiracion", "fermentacion", "transpiracion", "digestion", "replicacion"]

    lowered = [o.lower() for o in opts]
    has_disc = any(d in " ".join(lowered) for d in disciplines)
    has_org = any(o in " ".join(lowered) for o in organelles)
    has_proc = any(p in " ".join(lowered) for p in processes)

    cat_count = sum([has_disc, has_org, has_proc])
    if cat_count > 1:
        errors.append(f"RS-3: Mezcla de categorias (disciplina/organulo/proceso): {opts}")

    # Verificar que todas las opciones encajen gramaticalmente si hay hueco
    if has_hole:
        for opt in opts:
            test = stmt.replace("____", opt)
            # Detectar concordancia de articulos simple
            if "los ____" in stmt.lower() or "las ____" in stmt.lower():
                # Si usa plural, la opcion deberia ser plural
                if opt.lower() in ["nucleo", "cloroplasto", "ribosoma", "lisosoma"]:
                    errors.append(f"RS-2: Concordanza rota: '{stmt}' + '{opt}' (deberia ser plural)")

    # Verificar que no haya opciones declarativas sueltas sin sentido
    if not has_hole and not is_question:
        errors.append(f"RS-1: Enunciado sin hueco ni pregunta, opciones flotantes: {opts}")

    correct_count = sum(1 for o in item["options"] if o["correct"])
    if correct_count != 1:
        errors.append(f"Debe haber 1 correcta, hay {correct_count}")

    if len(opts) != 4:
        errors.append(f"No tiene 4 alternativas: {opts}")

    return errors


def run_test(content: str, label: str, use_new: bool = True):
    prompt = build_test_prompt(content, label, use_new)
    prompt_label = "NUEVO" if use_new else "ANTIGUO"
    print(f"\n{'='*70}")
    print(f"TEST: {label} | Prompt: {prompt_label}")
    print(f"{'='*70}")

    try:
        raw = call_local(prompt, max_tokens=3000, temperature=0.2)
    except Exception as e:
        print(f"ERROR LLM: {e}")
        return None

    mini = extract_mini(raw)
    if not mini:
        print("No se extrajo MINI valido. Respuesta cruda (primeros 1500 chars):")
        print(raw[:1500])
        return None

    print("\n--- MINI GENERADO ---")
    for line in mini.splitlines():
        print(line)
    print("\n--- VALIDACION ---")

    items = []
    for line in mini.splitlines():
        if line.startswith("i") and "|" in line:
            item = parse_item_line(line)
            if item:
                items.append(item)

    total_errors = 0
    for item in items:
        errs = validate_coherence(item)
        if errs:
            total_errors += len(errs)
            print(f"\n[{item['id']}] [{item['statement'][:50]}...]")
            for e in errs:
                print(f"  X {e}")
        else:
            print(f"\n[{item['id']}] [OK] Coherente")

    print(f"\nResumen: {len(items)} items, {total_errors} errores")
    return mini


if __name__ == "__main__":
    if not os.path.exists("PROMPT.md.old"):
        shutil.copy("PROMPT.md", "PROMPT.md.old")

    # Comparacion directa: Fotosintesis
    print("\n" + "#"*70)
    print("# COMPARACION 1: FOTOSINTESIS")
    print("#"*70)
    run_test(CONTENT_FOTOSINTESIS, "Fotosintesis", use_new=False)
    run_test(CONTENT_FOTOSINTESIS, "Fotosintesis", use_new=True)

    # Comparacion directa: Manuel Pardo
    print("\n" + "#"*70)
    print("# COMPARACION 2: MANUEL PARDO")
    print("#"*70)
    run_test(CONTENT_MANUEL_PARDO, "Manuel Pardo", use_new=False)
    run_test(CONTENT_MANUEL_PARDO, "Manuel Pardo", use_new=True)
