"""
PRUEBA DE SOLUCION: llama al servidor real (8001) saltando el proxy 8003
que recorta max_tokens a 128. Usa el mismo prompt que la app.
Si aqui se genera un MINI completo y coherente, confirma que el unico
problema es el cap de tokens del proxy.
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django
django.setup()

from openai import OpenAI
from learning.services import build_generation_prompt, extract_mini_lines
from learning.parse_mini import parse_mini, validate_mini_parse, _parse_item_line

CONTENT_APA = """Las Normas APA siguen siendo el estandar global para las ciencias sociales y empresariales. Sin embargo, su aparente menor uso se debe a que disciplinas como la medicina, el derecho o la literatura prefieren otros formatos, sumado a que las herramientas automatizadas han reemplazado su memorizacion estricta. Las razones principales de este cambio de percepcion son: Adopcion de estilos disciplinarios: Las ciencias de la salud utilizan ampliamente Vancouver, las humanidades optan por MLA, y las ciencias exactas emplean IEEE. Cada facultad se ha vuelto mas estricta en utilizar el formato propio de su area en lugar de generalizar con APA. Reemplazo por gestores de referencias: El engorroso trabajo manual de aplicar sangrias o cursivas ha sido superado por herramientas automatizadas como Zotero o Mendeley. Estos programas configuran los documentos en cualquier estilo automaticamente, por lo que el usuario ya no necesita aprenderse el manual de memoria. Flexibilidad en las instituciones: Aunque el formato es importante para evitar el plagio, muchas universidades y revistas cientificas han flexibilizado sus manuales de estilo. Las instituciones estan priorizando la originalidad y el contenido practico sobre la rigidez de margenes y espacios. Simplicidad de la ultima edicion: La ultima version simplifico drasticamente el formato original. Por ejemplo, se elimino la obligacion de colocar la ubicacion de la editorial al referenciar un libro y se anadieron mas opciones de fuentes (como Arial o Calibri), lo que lo hace menos visiblemente tecnico que en ediciones anteriores."""


def main():
    prompt = build_generation_prompt(CONTENT_APA, language="es", items_requested=7)
    client = OpenAI(api_key="local", base_url="http://127.0.0.1:8001/v1", max_retries=0, timeout=300)

    print("=== Llamada DIRECTA a 8001 (sin proxy), max_tokens=6000 ===\n")
    resp = client.chat.completions.create(
        model="qwen3-30b-endpoint",
        messages=[{"role": "user", "content": prompt + "\n/no_think"}],
        max_tokens=6000,
        temperature=0.4,
        stream=False,
    )
    choice = resp.choices[0]
    print(f"finish_reason: {choice.finish_reason}")
    content = (choice.message.content or "").strip()
    if not content:
        content = (getattr(choice.message, "reasoning_content", None) or "").strip()
        print("(content vacio, usando reasoning_content)")

    mini = extract_mini_lines(content)
    assessment = parse_mini(mini)
    print(f"\nCabecera: {assessment.header}")
    print(f"Items parseados: {len(assessment.items)}\n")
    print("===== MINI GENERADO =====")
    print(mini)
    print("===== FIN =====\n")

    try:
        ok = validate_mini_parse(mini, stage="PRUEBA-8001")
        print(f"VALIDACION OK: {len(ok.items)} items coherentes.")
        print("\nMuestra de items (coherencia enunciado-alternativas):")
        for it in ok.items[:7]:
            opts = [o['text'] + ('*' if o['correct'] else '') for o in it.options]
            print(f"  {it.id} [{it.bloom}] {it.statement}")
            print(f"       opc: {opts}")
    except ValueError as exc:
        print(f"VALIDACION FALLO: {exc}")


if __name__ == "__main__":
    main()
