import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from learning.services import (
    build_verification_prompt,
    build_verification_context,
    call_ai,
)
from learning.parse_mini import parse_mini


def log(msg):
    print(msg, flush=True)


def main():
    log("=" * 60)
    log("PRUEBA DE VERIFICACION REAL")
    log("=" * 60)

    # Leer MINI post-reparacion
    with open("test_pipeline_04_post_repair.txt", "r", encoding="utf-8") as f:
        mini = f.read()

    assessment = parse_mini(mini)
    log(f"Items a verificar: {len(assessment.items)}")

    # Probar modo WEB
    log("\n--- MODO WEB ---")
    ctx, trace = build_verification_context(mini, verification_mode="web")
    log(f"Contexto web chars: {len(ctx)}")
    log(f"Queries: {len(trace.get('web', {}).get('queries', []))}")
    log(f"EduQG enabled: {trace.get('eduqg', {}).get('enabled', False)}")

    prompt = build_verification_prompt(mini, source_context=ctx)
    log(f"Prompt chars: {len(prompt)}")

    try:
        result = call_ai(prompt, backend="local", role="verification")
        log(f"\nResultado (primeros 2000 chars):")
        log(result[:2000])
        with open("test_verif_web_result.txt", "w", encoding="utf-8") as f:
            f.write(result)
    except Exception as e:
        log(f"Error: {e}")

    # Probar modo EDUQG
    log("\n--- MODO EDUQG ---")
    ctx_edu, trace_edu = build_verification_context(mini, verification_mode="eduqg")
    log(f"Contexto EduQG chars: {len(ctx_edu)}")
    log(f"EduQG enabled: {trace_edu.get('eduqg', {}).get('enabled', False)}")
    log(f"EduQG records loaded: {trace_edu.get('eduqg', {}).get('records_loaded', 0)}")
    log(f"EduQG matches: {len(trace_edu.get('eduqg', {}).get('matches', []))}")
    for m in trace_edu.get("eduqg", {}).get("matches", [])[:3]:
        log(f"  Match: {m.get('title', '')[:60]} | Score: {m.get('score', 0)}")

    prompt_edu = build_verification_prompt(mini, source_context=ctx_edu)
    try:
        result_edu = call_ai(prompt_edu, backend="local", role="verification")
        log(f"\nResultado EduQG (primeros 2000 chars):")
        log(result_edu[:2000])
        with open("test_verif_eduqg_result.txt", "w", encoding="utf-8") as f:
            f.write(result_edu)
    except Exception as e:
        log(f"Error EduQG: {e}")

    # Probar modo HYBRID
    log("\n--- MODO HYBRID ---")
    ctx_hyb, trace_hyb = build_verification_context(mini, verification_mode="hybrid")
    log(f"Contexto hibrido chars: {len(ctx_hyb)}")
    log(f"Web queries: {len(trace_hyb.get('web', {}).get('queries', []))}")
    log(f"EduQG matches: {len(trace_hyb.get('eduqg', {}).get('matches', []))}")

    prompt_hyb = build_verification_prompt(mini, source_context=ctx_hyb)
    try:
        result_hyb = call_ai(prompt_hyb, backend="local", role="verification")
        log(f"\nResultado Hybrid (primeros 2000 chars):")
        log(result_hyb[:2000])
        with open("test_verif_hybrid_result.txt", "w", encoding="utf-8") as f:
            f.write(result_hyb)
    except Exception as e:
        log(f"Error Hybrid: {e}")

    log("\n" + "=" * 60)
    log("PRUEBA COMPLETADA")
    log("=" * 60)


if __name__ == "__main__":
    main()
