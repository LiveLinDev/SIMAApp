"""
Diagnostico de generacion MINI con el texto APA del usuario.
Reproduce exactamente el flujo de la app:
  build_generation_prompt -> call_ai(local) -> extract_mini_lines
  -> filter_incoherent_items -> parse_mini -> validate_mini_parse
Y muestra el output CRUDO de la IA para ver por que la cabecera
declara N items pero solo 1 parsea.
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django
django.setup()

from learning.services import (
    build_generation_prompt,
    call_ai,
    extract_mini_lines,
    count_mini_items,
)
from learning.parse_mini import (
    parse_mini,
    validate_mini_parse,
    filter_incoherent_items,
    _parse_item_line,
)


CONTENT_APA = """Las Normas APA siguen siendo el estándar global para las ciencias sociales y empresariales. Sin embargo, su aparente menor uso se debe a que disciplinas como la medicina, el derecho o la literatura prefieren otros formatos, sumado a que las herramientas automatizadas han reemplazado su memorización estricta. Las razones principales de este cambio de percepción son: Adopción de estilos disciplinarios: Las ciencias de la salud utilizan ampliamente Vancouver, las humanidades optan por MLA, y las ciencias exactas emplean IEEE. Cada facultad se ha vuelto más estricta en utilizar el formato propio de su área en lugar de generalizar con APA. Reemplazo por gestores de referencias: El engorroso trabajo manual de aplicar sangrías o cursivas ha sido superado por herramientas automatizadas como Zotero o Mendeley. Estos programas configuran los documentos en cualquier estilo automáticamente, por lo que el usuario ya no necesita aprenderse el manual de memoria. Flexibilidad en las instituciones: Aunque el formato es importante para evitar el plagio, muchas universidades y revistas científicas han flexibilizado sus manuales de estilo. Las instituciones están priorizando la originalidad y el contenido práctico sobre la rigidez de márgenes y espacios. Simplicidad de la última edición: La última versión simplificó drásticamente el formato original. Por ejemplo, se eliminó la obligación de colocar la ubicación de la editorial al referenciar un libro y se añadieron más opciones de fuentes (como Arial o Calibri), lo que lo hace menos visiblemente técnico que en ediciones anteriores."""


def main():
    word_count = len(CONTENT_APA.split())
    print(f"=== TEXTO APA: {word_count} palabras ===\n")

    # Pedimos 7 items para reproducir el escenario reportado (cabecera n=7)
    items_requested = 7
    prompt = build_generation_prompt(
        CONTENT_APA, language="es", items_requested=items_requested
    )

    print("=== 1. LLAMANDO A LA IA LOCAL (qwen3-30b-endpoint) ===\n")
    raw_output = call_ai(prompt, backend="local", role="generation")

    print("===== OUTPUT CRUDO DE LA IA (entre delimitadores) =====")
    print(">>>BEGIN_RAW>>>")
    print(raw_output)
    print("<<<END_RAW<<<\n")

    # Cuantas lineas iN| tiene el output crudo
    raw_item_lines = count_mini_items(raw_output)
    print(f"=== Lineas 'iN|' detectadas en el output CRUDO: {raw_item_lines} ===")

    # extract_mini_lines: lo que la app realmente conserva
    mini_block = extract_mini_lines(raw_output)
    extracted_lines = mini_block.splitlines()
    extracted_item_lines = count_mini_items(mini_block)
    print(f"=== Tras extract_mini_lines: {len(extracted_lines)} lineas, "
          f"{extracted_item_lines} lineas 'iN|' ===\n")
    print("===== MINI EXTRACTO =====")
    print(mini_block)
    print("===== FIN EXTRACTO =====\n")

    # Cabecera declarada
    assessment = parse_mini(mini_block)
    print(f"=== Cabecera declarada: {assessment.header!r} ===")
    print(f"=== Items que parse_mini logro parsear: {len(assessment.items)} ===\n")

    # Diagnostico item por item: cuales se caen y por que
    print("===== DIAGNOSTICO LINEA POR LINEA =====")
    for raw_line in extracted_lines:
        line = raw_line.strip()
        if not (line.startswith("i") and "|" in line):
            continue
        parts = line.split("|")
        item = _parse_item_line(line)
        if item:
            print(f"  [OK   ] {line[:90]}")
        else:
            # Razon del descarte
            reason = ""
            if len(parts) < 8:
                reason = f"solo {len(parts)} campos (necesita >= 8)"
            else:
                # probar campos criticos: irt, difficulty, cat
                try:
                    irt_parts = parts[-3].split(",")
                    float(irt_parts[0]); float(irt_parts[1]); float(irt_parts[2])
                except Exception as e:
                    reason = f"IRT '{parts[-3]}' no es numerico ({e})"
                try:
                    int(parts[-2])
                except Exception as e:
                    reason += f" | dificultad '{parts[-2]}' no es entero"
            print(f"  [DROP ] {line[:90]}  -> motivo: {reason}")
    print("===== FIN DIAGNOSTICO =====\n")

    # Reproducir el error exacto de la app
    print("===== REPRODUCCION DEL ERROR DE LA APP =====")
    try:
        # flujo exacto: filter_incoherent_items -> normalize_mini_text -> validate_mini_parse
        filtered, dropped, incoherent = filter_incoherent_items(mini_block)
        if dropped:
            print(f"Filtrados incoherentes (sin ? ni ____): {dropped}")
        assessment_ok = validate_mini_parse(filtered, stage="Generacion MINI")
        print(f"OK: {len(assessment_ok.items)} items validados.")
    except ValueError as exc:
        print(f"ERROR REPRODUCIDO: {exc}")
    print("===== FIN =====")


if __name__ == "__main__":
    main()
