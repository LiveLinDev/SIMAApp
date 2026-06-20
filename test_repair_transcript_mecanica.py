import os
import sys
import time
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from learning.services import repair_transcript_text


def log(msg):
    print(msg, flush=True)


def main():
    path = "docs/mecanica_3000_palabras.txt"
    with open(path, "r", encoding="utf-8") as f:
        transcript = f.read()

    words = len(transcript.split())
    log("=" * 60)
    log("PRUEBA: repair_transcript_text con texto de mecanica")
    log(f"Archivo: {path}")
    log(f"Palabras en transcripcion: {words}")
    log(f"Caracteres en transcripcion: {len(transcript)}")
    log("=" * 60)

    title = "Introduccion a la Mecanica Clasica"
    tags = "mecanica, cinematica, dinamica, energia, fuerzas"
    source_context = f"TITULO: {title}\nETIQUETAS: {tags}"

    log(f"Caracteres del contexto completo: {len(source_context)}")
    log("Llamando a repair_transcript_text(backend='local')...")
    log(f"Timeout configurado: {getattr(__import__('django.conf', fromlist=['settings']).settings, 'LOCAL_API_TIMEOUT', 'NO DEFINIDO')} segundos")

    start = time.time()
    try:
        prompt, repaired, backend, trace = repair_transcript_text(
            transcript,
            source_context=source_context,
            backend="local",
        )
        elapsed = time.time() - start
        log(f"\nCompletado en {elapsed:.2f} segundos")
        log(f"Backend: {backend}")
        log(f"Prompt chars: {trace.get('prompt_chars')}")
        log(f"Output chars: {trace.get('output_chars')}")
        log(f"Changed: {trace.get('changed')}")

        with open("test_repair_mecanica_prompt.txt", "w", encoding="utf-8") as f:
            f.write(prompt)
        with open("test_repair_mecanica_output.txt", "w", encoding="utf-8") as f:
            f.write(repaired)
        log("Guardados: test_repair_mecanica_prompt.txt y test_repair_mecanica_output.txt")

    except Exception as exc:
        elapsed = time.time() - start
        log(f"\nERROR tras {elapsed:.2f} segundos: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
