import os
import sys
import json
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from learning.services import (
    build_generation_prompt,
    build_verification_prompt,
    build_verification_context,
    call_ai,
    chunk_content,
    extract_mini_lines,
    generate_items,
    repair_incoherent_mini,
    repair_mini_coherence,
    repair_option_uniformity,
    verify_items,
    resolve_backend,
)
from learning.parse_mini import (
    apply_corrections_with_trace,
    filter_incoherent_items,
    filter_nonuniform_items,
    merge_mini_chunks,
    parse_mini,
    validate_mini_parse,
)


def log(msg):
    print(msg, flush=True)


def main():
    log("=" * 60)
    log("PIPELINE COMPLETO: transcripciontemplate.md")
    log("=" * 60)

    # 1. Leer transcripcion
    with open("docs/transcripciontemplate.md", "r", encoding="utf-8") as f:
        transcript = f.read()
    words = len(transcript.split())
    log(f"Transcripcion: {words} palabras, {len(transcript)} chars")

    # Objetivo de items para IRT (~1 item cada 50 palabras)
    planned_items = max(50, words // 50)
    log(f"Objetivo IRT: ~{planned_items} items")

    # 2. Generacion de items
    log("\n[1/6] GENERANDO ITEMS...")
    prompt_gen, mini_raw, backend = generate_items(
        transcript,
        backend="local",
        language="es",
        items_requested="auto",
    )
    mini_lines = extract_mini_lines(mini_raw)
    log(f"Backend usado: {backend}")
    raw_count = len([l for l in mini_lines.splitlines() if l.startswith("i")])
    log(f"Items crudos extraidos: {raw_count}")
    with open("test_pipeline_01_generation.txt", "w", encoding="utf-8") as f:
        f.write(mini_lines)

    # 3. Filtro automatico de incoherentes + RECUPERACION
    log("\n[2/6] FILTRANDO Y RECUPERANDO INCOHERENTES...")
    filtered, dropped, incoherent_mini = filter_incoherent_items(mini_lines)
    log(f"Items coherentes inicial: {len([l for l in filtered.splitlines() if l.startswith('i')])}")
    log(f"Items incoherentes detectados: {len(dropped)}")
    for d in dropped:
        log(f"  - {d}")

    # Recuperar incoherentes en lugar de descartarlos permanentemente
    if incoherent_mini:
        log("\n[2b/6] REPARANDO ITEMS INCOHERENTES ESPECIFICAMENTE...")
        try:
            source_ctx = f"TITULO: Historia del Peru - Independencia\nTRANSCRIPCION:\n{transcript[:2000]}"
            prompt_rec, repaired_inc, backend_rec, trace_rec = repair_incoherent_mini(
                incoherent_mini,
                source_context=source_ctx,
                backend="local",
            )
            recovered_count = len([l for l in repaired_inc.splitlines() if l.startswith("i")])
            log(f"Items reparados especificamente: {recovered_count}")
            if recovered_count > 0:
                merged = merge_mini_chunks([filtered, repaired_inc])
                log(f"Merge coherentes + reparados: {len([l for l in merged.splitlines() if l.startswith('i')])} items")
                # Re-filtrar para verificar que la reparacion funciono
                filtered, dropped2, _ = filter_incoherent_items(merged)
                if dropped2:
                    log(f"Items aun incoherentes tras recuperacion: {len(dropped2)}")
                else:
                    log("Recuperacion: 0 items incoherentes restantes")
        except Exception as e:
            log(f"Error en recuperacion de incoherentes: {e}")
            import traceback
            traceback.print_exc()

    # 3b. Filtrar y recuperar opciones no uniformes (fusionadas por comas, sesgo de longitud)
    log("\n[2c/6] FILTRANDO OPCIONES NO UNIFORMES...")
    uniform_mini, bad_opts_log, bad_opts_mini = filter_nonuniform_items(filtered)
    if bad_opts_log:
        log(f"Items con opciones malformadas: {len(bad_opts_log)}")
        for b in bad_opts_log:
            log(f"  - {b}")
    if bad_opts_mini:
        log("\n[2d/6] REPARANDO OPCIONES MALFORMADAS...")
        try:
            source_ctx = f"TITULO: Historia del Peru - Independencia\nTRANSCRIPCION:\n{transcript[:2000]}"
            prompt_opts, repaired_opts, backend_opts, trace_opts = repair_option_uniformity(
                bad_opts_mini,
                source_context=source_ctx,
                backend="local",
            )
            repaired_count = len([l for l in repaired_opts.splitlines() if l.startswith("i")])
            log(f"Items con opciones reparadas: {repaired_count}")
            if repaired_count > 0:
                filtered = merge_mini_chunks([uniform_mini, repaired_opts])
                log(f"Merge uniformes + opciones reparadas: {len([l for l in filtered.splitlines() if l.startswith('i')])} items")
                # Re-filtrar opciones para verificar
                filtered, bad2, _ = filter_nonuniform_items(filtered)
                if bad2:
                    log(f"Items aun con opciones malas: {len(bad2)}")
                else:
                    log("Opciones: 0 items malformados restantes")
        except Exception as e:
            log(f"Error en reparacion de opciones: {e}")
            import traceback
            traceback.print_exc()

    with open("test_pipeline_02_filtered.txt", "w", encoding="utf-8") as f:
        f.write(filtered)

    # 4. Reparacion de coherencia general con IA local
    log("\n[3/6] REPARANDO COHERENCIA GENERAL CON IA LOCAL...")
    try:
        source_ctx = f"TITULO: Historia del Peru - Independencia\nTRANSCRIPCION:\n{transcript[:2000]}"
        prompt_repair, repaired, backend_repair, trace = repair_mini_coherence(
            filtered,
            source_context=source_ctx,
            backend="local",
        )
        log(f"Reparacion general aplicada: {trace.get('changed', False)}")
        log(f"Items tras reparacion general: {len([l for l in repaired.splitlines() if l.startswith('i')])}")
        with open("test_pipeline_03_repaired.txt", "w", encoding="utf-8") as f:
            f.write(repaired)
        # Re-filtrar despues de reparacion
        filtered2, dropped2, _ = filter_incoherent_items(repaired)
        if dropped2:
            log(f"Items aun incoherentes post-reparacion: {len(dropped2)}")
            for d in dropped2:
                log(f"  - {d}")
        else:
            log("Post-reparacion general: 0 items incoherentes")
        filtered = filtered2
    except Exception as e:
        log(f"Error en reparacion de coherencia: {e}")
        import traceback
        traceback.print_exc()

    with open("test_pipeline_04_post_repair.txt", "w", encoding="utf-8") as f:
        f.write(filtered)

    current_count = len([l for l in filtered.splitlines() if l.startswith("i")])

    # 5. Relleno de items si es necesario para IRT
    if current_count < planned_items * 0.8:
        needed = min(planned_items - current_count, 15)
        log(f"\n[3b/6] GENERANDO {needed} ITEMS DE RELLENO PARA IRT...")
        try:
            fill_prompt = (
                f"Genera exactamente {needed} items MINI adicionales sobre el siguiente contenido. "
                f"Cada item debe ser una pregunta con ? o una completacion con ____. "
                f"Distribuye las respuestas correctas entre A, B, C, D. "
                f"Varia los niveles Bloom (L1-L6).\n\n"
                f"CONTENIDO:\n{transcript[:4000]}\n\n"
                f"Responde SOLO con el bloque MINI (cabecera a| + items iN|)."
            )
            raw_output = call_ai(fill_prompt, backend="local", role="generation")
            fill_mini = extract_mini_lines(raw_output)
            if fill_mini:
                filtered = merge_mini_chunks([filtered, fill_mini])
                new_count = len([l for l in filtered.splitlines() if l.startswith("i")])
                log(f"Relleno aplicado: {new_count} items totales")
        except Exception as e:
            log(f"Error en relleno de items: {e}")
            import traceback
            traceback.print_exc()

    # 6. Verificacion web
    log("\n[4/6] VERIFICANDO CON FUENTES WEB...")
    try:
        prompt_verif, verification_output, backend_verif, verif_trace = verify_items(
            filtered,
            backend="local",
            verification_mode="web",
        )
        log(f"Verificacion completada. Backend: {backend_verif}")
        web_sources = verif_trace.get("web", {})
        log(f"Fuentes web consultadas: {len(web_sources.get('queries', []))}")
        for q in web_sources.get("queries", []):
            log(f"  Query: {q.get('query', '')}")
            for r in q.get("results", [])[:2]:
                log(f"    -> {r.get('title', '')[:60]} ({r.get('url', '')[:60]})")
        with open("test_pipeline_05_verification.txt", "w", encoding="utf-8") as f:
            f.write(verification_output)
    except Exception as e:
        log(f"Error en verificacion web: {e}")
        import traceback
        traceback.print_exc()
        verification_output = ""

    # 7. Aplicar correcciones
    log("\n[5/6] APLICANDO CORRECCIONES...")
    if verification_output and verification_output.strip():
        try:
            corrected, correction_trace = apply_corrections_with_trace(filtered, verification_output)
            corrected, dropped_final, _ = filter_incoherent_items(corrected)
            if dropped_final:
                log(f"Items descartados post-correccion: {len(dropped_final)}")
            with open("test_pipeline_06_final.txt", "w", encoding="utf-8") as f:
                f.write(corrected)
            # Validacion final
            try:
                assessment = validate_mini_parse(corrected)
                log(f"VALIDACION FINAL: {len(assessment.items)} items parseados correctamente")
                for item in assessment.items[:10]:
                    log(f"  [{item.id}] {item.statement[:70]}...")
                    log(f"      opts: {[o['text'] for o in item.options]}")
            except Exception as e:
                log(f"Validacion final fallo: {e}")
        except Exception as e:
            log(f"Error aplicando correcciones: {e}")
            import traceback
            traceback.print_exc()
    else:
        log("No hay output de verificacion; saltando correcciones")
        with open("test_pipeline_06_final.txt", "w", encoding="utf-8") as f:
            f.write(filtered)

    final_count = len([l for l in open("test_pipeline_06_final.txt", encoding="utf-8").read().splitlines() if l.startswith("i")])
    log(f"\n[6/6] RESUMEN: {final_count} items finales (objetivo IRT: ~{planned_items})")
    log("=" * 60)
    log("PIPELINE COMPLETADO")
    log("=" * 60)


if __name__ == "__main__":
    main()
