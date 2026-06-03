import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

import requests
import re
from learning.parse_mini import filter_incoherent_items, parse_mini, validate_mini_parse
from learning.services import build_coherence_prompt, extract_mini_lines

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


def build_gen_prompt(content: str, label: str) -> str:
    with open("PROMPT.md", "r", encoding="utf-8") as f:
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


def build_repair_prompt(mini: str, context: str) -> str:
    template = open("coherence_prompt.md", "r", encoding="utf-8").read()
    return (
        f"{template}\n\n"
        "CONTEXTO_ORIGEN:\n"
        f"{context}\n\n"
        "MINI_ACTUAL:\n"
        f"{mini}"
    )


def analyze_mini(mini: str, label: str):
    print(f"\n--- {label} ---")
    print(mini)
    assessment = parse_mini(mini)
    print(f"Items parseados: {len(assessment.items)}")
    for item in assessment.items:
        has_q = "?" in item.statement
        has_hole = "____" in item.statement
        status = "OK" if (has_q or has_hole) else "FALLA"
        print(f"  [{status}] {item.id}: {item.statement[:70]}...")


def run_pipeline(content: str, label: str):
    print(f"\n{'='*70}")
    print(f"PIPELINE: {label}")
    print(f"{'='*70}")

    # PASO 1: Generacion
    gen_prompt = build_gen_prompt(content, label)
    raw = call_local(gen_prompt, max_tokens=3000, temperature=0.2)
    mini_gen = extract_mini_lines(raw)
    analyze_mini(mini_gen, "1. GENERACION RAW")

    # PASO 2: Filtro automatico de incoherentes
    filtered, dropped, _incoherent = filter_incoherent_items(mini_gen)
    if dropped:
        print(f"\n2. FILTRO AUTOMATICO: {len(dropped)} items descartados")
        for d in dropped:
            print(f"   - {d}")
    else:
        print("\n2. FILTRO AUTOMATICO: 0 items descartados")
    analyze_mini(filtered, "2. POST-FILTRO")

    # PASO 3: Reparacion de coherencia con IA
    if dropped:
        repair_prompt = build_repair_prompt(filtered, content[:800])
        raw_repaired = call_local(repair_prompt, max_tokens=3000, temperature=0.2)
        mini_repaired = extract_mini_lines(raw_repaired)
        analyze_mini(mini_repaired, "3. POST-REPARACION IA")

        # Re-filtrar despues de reparacion
        filtered2, dropped2, _ = filter_incoherent_items(mini_repaired)
        if dropped2:
            print(f"\n3b. RE-FILTRO: {len(dropped2)} items aun incoherentes")
        analyze_mini(filtered2, "3b. POST-REPARACION + FILTRO")
        return filtered2

    return filtered


if __name__ == "__main__":
    run_pipeline(CONTENT_FOTOSINTESIS, "Fotosintesis")
    run_pipeline(CONTENT_MANUEL_PARDO, "Manuel Pardo")
