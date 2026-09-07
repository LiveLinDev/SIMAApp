# -*- coding: utf-8 -*-
"""
Genera el modelo ArchiMate de SIMA en el formato nativo de Archi (.archimate),
con capas de motivacion, negocio, aplicacion y tecnologia, relaciones validas
en ArchiMate 3.2 y cuatro vistas con disposicion calculada.

    python docs/archimate/build_model.py            -> docs/archimate/SIMA.archimate

Abrir en Archi: File > Open. El modelo es la fuente; los PNG de las vistas se
exportan con el reporte HTML de Archi (ver docs/archimate/README.md).
"""
from __future__ import annotations

import os
import uuid
from xml.sax.saxutils import escape

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SIMA.archimate")

W, H, GAP_X, GAP_Y = 165, 66, 28, 78
ids: dict[str, str] = {}
elements: list[dict] = []
relations: list[dict] = []
views: list[dict] = []


def nid(key: str) -> str:
    if key not in ids:
        ids[key] = "id-" + uuid.uuid5(uuid.NAMESPACE_URL, "sima/" + key).hex[:24]
    return ids[key]


def el(key: str, xsi: str, name: str, layer: str, doc: str = ""):
    elements.append({"key": key, "id": nid(key), "type": xsi, "name": name, "layer": layer, "doc": doc})
    return key


def rel(kind: str, src: str, dst: str, name: str = "", access: str | None = None):
    key = f"{kind}:{src}->{dst}:{name}"
    relations.append({"key": key, "id": nid(key), "type": kind + "Relationship", "src": src, "dst": dst, "name": name, "access": access})
    return key


# ============================================================ MOTIVACION
el("st_estudiante", "Stakeholder", "Estudiante universitario", "motivation")
el("st_docente", "Stakeholder", "Docente del curso", "motivation")
el("goal_retencion", "Goal", "Mejorar la retención y el rendimiento en el curso", "motivation")
el("goal_calidad", "Goal", "Ítems de evaluación fiables generados con modelos de lenguaje", "motivation")
el("req_formato", "Requirement", "Salida del modelo parseable, compacta y verificable (notación .mini)", "motivation")
el("req_adaptativa", "Requirement", "Evaluación adaptativa con memoria del estudiante (IRT 3PL)", "motivation")
el("req_verificacion", "Requirement", "Verificación factual contra fuentes antes de persistir", "motivation")
el("principio_privacidad", "Principle", "Transcripción local: el audio no sale del servidor", "motivation")
rel("Association", "st_estudiante", "goal_retencion")
rel("Association", "st_docente", "goal_calidad")
rel("Realization", "req_formato", "goal_calidad")
rel("Realization", "req_verificacion", "goal_calidad")
rel("Realization", "req_adaptativa", "goal_retencion")
rel("Influence", "principio_privacidad", "req_verificacion", "+")

# ============================================================ NEGOCIO
el("act_estudiante", "BusinessActor", "Estudiante", "business", "Sube clases, practica, repasa, genera refuerzo y resúmenes, revisa su progreso.")
el("act_docente", "BusinessActor", "Docente", "business", "Fuente de las grabaciones; juez de calidad de los ítems en la validación.")
el("act_admin", "BusinessActor", "Administrador", "business", "Gestiona usuarios, planes, trabajos y contenido en Django Admin.")
el("rol_aprendiz", "BusinessRole", "Aprendiz del curso", "business")
el("bp_subir", "BusinessProcess", "Subir clase (audio o texto)", "business")
el("bp_practicar", "BusinessProcess", "Practicar (sesión adaptativa)", "business")
el("bp_repasar", "BusinessProcess", "Repasar con repetición espaciada", "business")
el("bp_reforzar", "BusinessProcess", "Generar refuerzo dirigido", "business")
el("bp_resumir", "BusinessProcess", "Leer resumen de clase o curso", "business")
el("bp_plan", "BusinessProcess", "Seguir el plan de hoy", "business")
el("bs_acompanamiento", "BusinessService", "Acompañamiento adaptativo del estudio", "business")
el("bo_clase", "BusinessObject", "Clase grabada", "business")
el("bo_item", "BusinessObject", "Ítem de evaluación", "business")
el("bo_perfil", "BusinessObject", "Perfil de aprendizaje", "business")
rel("Assignment", "act_estudiante", "rol_aprendiz")
for p in ("bp_subir", "bp_practicar", "bp_repasar", "bp_reforzar", "bp_resumir", "bp_plan"):
    rel("Assignment", "rol_aprendiz", p)
    rel("Realization", p, "bs_acompanamiento")
rel("Serving", "bs_acompanamiento", "act_estudiante")
rel("Association", "act_docente", "bo_clase")
rel("Access", "bp_subir", "bo_clase", access="write")
rel("Access", "bp_practicar", "bo_item", access="read")
rel("Access", "bp_practicar", "bo_perfil", access="readwrite")
rel("Access", "bp_plan", "bo_perfil", access="read")
rel("Triggering", "bp_subir", "bp_practicar")
rel("Triggering", "bp_practicar", "bp_reforzar")
rel("Triggering", "bp_practicar", "bp_repasar")

# ============================================================ APLICACION
el("app_sima", "ApplicationComponent", "SIMA (aplicación web Django)", "application")
el("app_vistas", "ApplicationComponent", "Vistas por dominio", "application", "learning/views: core, courses, lessons, practice, study, summaries, pipeline.")
el("app_nucleo", "ApplicationComponent", "Núcleo adaptativo", "application", "adaptive, psychometrics (IRT 3PL, EAP, randomesque, Elo, BKT), spaced_repetition (SM-2), segments, progress.")
el("app_pipeline", "ApplicationComponent", "Pipeline de generación verificada", "application", "pipeline.py + parse_mini: transcripción → generación .mini → filtros → reparación → verificación factual → corrección → banco.")
el("app_servicios", "ApplicationComponent", "Servicios de IA", "application", "learning/services: prompts, backends (call_ai, proveedores), generation, repairs, evidence (web, EduQG), transcription (Whisper).")
el("app_cola", "ApplicationComponent", "Cola de trabajos y worker", "application", "job_queue (modo thread o db, límite por usuario) y comando run_worker.")
el("app_refuerzo", "ApplicationComponent", "Refuerzo y resúmenes", "application", "adaptive_generation (ReinforcementJob) y summaries (SummaryJob).")
el("app_creditos", "ApplicationComponent", "Créditos y planes", "application", "credits: estimación, cobro y reembolso.")
el("app_llm", "ApplicationComponent", "Proveedor de LLM (externo)", "application", "API compatible con OpenAI: Qwen 3.8 y GPT-OSS vía Groq, DeepSeek; o Anthropic.")
el("app_whisper", "ApplicationComponent", "Whisper (local)", "application", "Transcripción con segmentos y marcas de tiempo; el audio no sale del servidor.")
el("as_generacion", "ApplicationService", "Generación verificada de ítems", "application")
el("as_evaluacion", "ApplicationService", "Evaluación adaptativa por IRT", "application")
el("as_refuerzo", "ApplicationService", "Refuerzo dirigido", "application")
el("as_resumen", "ApplicationService", "Resúmenes de clase y curso", "application")
el("as_repaso", "ApplicationService", "Repaso espaciado y plan de estudio", "application")
el("ai_web", "ApplicationInterface", "Interfaz web (HTTPS)", "application")
el("ai_admin", "ApplicationInterface", "Django Admin", "application")
el("ai_salud", "ApplicationInterface", "/salud/ (monitoreo)", "application")
el("do_curso", "DataObject", "Curso", "application")
el("do_lesson", "DataObject", "Clase (LessonJob)", "application", "Transcripción, .mini bruto y corregido, trazas del pipeline.")
el("do_transcript", "DataObject", "Transcripción y segmentos", "application")
el("do_banco", "DataObject", "Banco de ítems .mini", "application", "Question y AnswerOption con parámetros IRT, calibración y bandera de calidad.")
el("do_sesion", "DataObject", "Sesiones y respuestas", "application", "PracticeSession y StudentAnswer (theta antes/después).")
el("do_perfil", "DataObject", "Perfil adaptativo", "application", "AdaptiveProfile: theta, error estándar, dominio por tema y Bloom, vida media de retención.")
el("do_trabajos", "DataObject", "Trabajos de refuerzo y resumen", "application", "ReinforcementJob y SummaryJob.")
el("do_flashcard", "DataObject", "Flashcards (SM-2)", "application")
for c in ("app_vistas", "app_nucleo", "app_pipeline", "app_servicios", "app_cola", "app_refuerzo", "app_creditos"):
    rel("Composition", "app_sima", c)
rel("Composition", "app_sima", "ai_web"); rel("Composition", "app_sima", "ai_admin"); rel("Composition", "app_sima", "ai_salud")
rel("Realization", "app_pipeline", "as_generacion")
rel("Realization", "app_nucleo", "as_evaluacion")
rel("Realization", "app_nucleo", "as_repaso")
rel("Realization", "app_refuerzo", "as_refuerzo")
rel("Realization", "app_refuerzo", "as_resumen")
rel("Serving", "as_generacion", "bp_subir")
rel("Serving", "as_evaluacion", "bp_practicar")
rel("Serving", "as_repaso", "bp_repasar")
rel("Serving", "as_repaso", "bp_plan")
rel("Serving", "as_refuerzo", "bp_reforzar")
rel("Serving", "as_resumen", "bp_resumir")
rel("Serving", "ai_web", "act_estudiante")
rel("Serving", "ai_admin", "act_admin")
rel("Serving", "app_servicios", "app_pipeline")
rel("Serving", "app_servicios", "app_refuerzo")
rel("Serving", "app_llm", "app_servicios")
rel("Serving", "app_whisper", "app_servicios")
rel("Serving", "app_cola", "app_pipeline")
rel("Serving", "app_cola", "app_refuerzo")
rel("Serving", "app_creditos", "app_vistas")
rel("Serving", "app_nucleo", "app_vistas")
rel("Flow", "app_vistas", "app_cola", "encola trabajos")
rel("Flow", "app_pipeline", "app_nucleo", "ítems al banco")
rel("Access", "app_pipeline", "do_lesson", access="readwrite")
rel("Access", "app_pipeline", "do_transcript", access="write")
rel("Access", "app_pipeline", "do_banco", access="write")
rel("Access", "app_nucleo", "do_banco", access="readwrite")
rel("Access", "app_nucleo", "do_sesion", access="write")
rel("Access", "app_nucleo", "do_perfil", access="readwrite")
rel("Access", "app_nucleo", "do_flashcard", access="readwrite")
rel("Access", "app_refuerzo", "do_trabajos", access="readwrite")
rel("Access", "app_cola", "do_trabajos", access="readwrite")
rel("Access", "app_vistas", "do_curso", access="readwrite")
rel("Realization", "do_lesson", "bo_clase")
rel("Realization", "do_banco", "bo_item")
rel("Realization", "do_perfil", "bo_perfil")

# ============================================================ TECNOLOGIA
el("node_servidor", "Node", "Servidor de SIMA", "technology")
el("sw_python", "SystemSoftware", "Python 3 + Django", "technology")
el("sw_postgres", "SystemSoftware", "PostgreSQL 18", "technology")
el("sw_whisper", "SystemSoftware", "Whisper + ffmpeg", "technology")
el("sw_scheduler", "SystemSoftware", "Programador de tareas / cron", "technology")
el("node_worker", "Node", "Proceso worker", "technology")
el("node_navegador", "Device", "Dispositivo del estudiante", "technology")
el("node_llm", "Node", "Nube del proveedor de LLM", "technology")
el("net_https", "CommunicationNetwork", "Internet (HTTPS)", "technology")
el("ts_web", "TechnologyService", "Servicio web HTTPS", "technology")
el("ts_db", "TechnologyService", "Servicio de base de datos", "technology")
el("ts_llm", "TechnologyService", "API de chat completions", "technology")
el("art_codigo", "Artifact", "Código de SIMAApp", "technology")
el("art_logs", "Artifact", "logs/sima.log (rotativo)", "technology")
el("art_audio", "Artifact", "Audios subidos (temporales)", "technology")
el("art_env", "Artifact", ".env (configuración)", "technology")
for sw in ("sw_python", "sw_postgres", "sw_whisper", "sw_scheduler"):
    rel("Assignment", "node_servidor", sw)
rel("Composition", "node_servidor", "node_worker")
rel("Assignment", "sw_python", "art_codigo")
rel("Assignment", "node_worker", "art_codigo")
rel("Assignment", "node_servidor", "art_logs")
rel("Assignment", "node_servidor", "art_audio")
rel("Assignment", "node_servidor", "art_env")
rel("Realization", "art_codigo", "app_sima")
rel("Realization", "sw_python", "ts_web")
rel("Realization", "sw_postgres", "ts_db")
rel("Realization", "node_llm", "ts_llm")
rel("Serving", "ts_web", "app_sima")
rel("Serving", "ts_db", "app_sima")
rel("Serving", "ts_llm", "app_llm")
rel("Association", "node_navegador", "net_https")
rel("Association", "net_https", "node_servidor")
rel("Association", "node_servidor", "node_llm")
rel("Serving", "sw_whisper", "app_whisper")
rel("Serving", "sw_scheduler", "app_cola")

# ============================================================ VISTAS
def view(name: str, viewpoint: str, groups: list[tuple[str, list[list[str]]]], doc: str = ""):
    """groups: [(titulo del grupo o "", [fila de claves, fila de claves...]), ...] apiladas verticalmente."""
    views.append({"name": name, "viewpoint": viewpoint, "groups": groups, "doc": doc, "id": nid("view:" + name)})


view("1. Motivación", "motivation", [
    ("Interesados", [["st_estudiante", "st_docente"]]),
    ("Metas", [["goal_retencion", "goal_calidad"]]),
    ("Requisitos y principios", [["req_adaptativa", "req_formato", "req_verificacion", "principio_privacidad"]]),
], "Por qué existe SIMA y qué exige de la notación, el pipeline y la evaluación.")

view("2. Negocio: el ciclo del estudiante", "", [
    ("Actores", [["act_estudiante", "rol_aprendiz", None, "act_docente", "act_admin"]]),
    ("Servicio", [[None, None, "bs_acompanamiento"]]),
    ("Procesos", [["bp_subir", "bp_practicar", "bp_reforzar", "bp_repasar", "bp_resumir", "bp_plan"]]),
    ("Objetos de negocio", [["bo_clase", "bo_item", "bo_perfil"]]),
], "Clase → práctica → refuerzo y repaso → plan de hoy.")

view("3. Aplicación: componentes, servicios y datos", "", [
    ("Procesos de negocio servidos", [["bp_subir", None, "bp_practicar", "bp_repasar", "bp_plan", "bp_reforzar", "bp_resumir"]]),
    ("Servicios de aplicación", [[None, "as_generacion", "as_evaluacion", "as_repaso", None, "as_refuerzo", "as_resumen"]]),
    ("SIMA (aplicación web Django)", [["ai_web", "ai_admin", "ai_salud", "app_creditos"],
                                     ["app_vistas", "app_pipeline", "app_nucleo", None, "app_refuerzo", "app_servicios", "app_cola"]]),
    ("Sistemas externos", [[None, None, None, None, None, "app_llm", "app_whisper"]]),
    ("Objetos de datos", [["do_curso", "do_lesson", "do_transcript", "do_banco", "do_sesion", "do_perfil", "do_flashcard", "do_trabajos"]]),
], "Capa 1 (pipeline + notación .mini) y capa 2 (núcleo adaptativo) como componentes de la misma aplicación.")

view("4. Tecnología: despliegue", "", [
    ("Cliente", [["node_navegador", "net_https"]]),
    ("Servicios tecnológicos", [["ts_web", "ts_db", "ts_llm"]]),
    ("Servidor de SIMA", [["node_servidor", "sw_python", "sw_postgres", "sw_whisper", "sw_scheduler", "node_worker"],
                          [None, "art_codigo", "art_env", "art_logs", "art_audio"]]),
    ("Externo", [["node_llm"]]),
], "Un servidor con Django, PostgreSQL y Whisper local; worker aparte opcional; proveedor de LLM en la nube.")

view("5. Capas de SIMA (vista en capas)", "", [
    ("Negocio", [["act_estudiante", "bp_subir", "bp_practicar", "bp_repasar", "bp_reforzar"]]),
    ("Servicios de aplicación", [["as_generacion", "as_evaluacion", "as_repaso", "as_refuerzo"]]),
    ("Componentes de aplicación", [["app_pipeline", "app_nucleo", "app_refuerzo", "app_servicios", "app_cola"]]),
    ("Servicios tecnológicos", [["ts_web", "ts_db", "ts_llm"]]),
    ("Tecnología", [["node_servidor", "sw_python", "sw_postgres", "node_llm"]]),
], "Trazabilidad de arriba abajo: quién usa qué, qué servicio lo realiza y sobre qué corre.")


# ============================================================ SERIALIZACION
def render() -> str:
    by_key = {e["key"]: e for e in elements}
    folders = {"motivation": ("Motivation", "motivation"), "business": ("Business", "business"), "application": ("Application", "application"),
               "technology": ("Technology &amp; Physical", "technology")}
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<archimate:model xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:archimate="http://www.archimatetool.com/archimate" '
           f'name="SIMA" id="{nid("model")}" version="5.0.0">',
           '  <purpose>Modelo ArchiMate de SIMA: notación .mini y pipeline de generación verificada de ítems IRT con modelos de lenguaje, '
           'integrados en una plataforma de microaprendizaje con evaluación adaptativa. Generado por docs/archimate/build_model.py.</purpose>',
           f'  <folder name="Strategy" id="{nid("f_strategy")}" type="strategy"/>']
    for layer, (label, ftype) in folders.items():
        out.append(f'  <folder name="{label}" id="{nid("f_" + layer)}" type="{ftype}">')
        for e in elements:
            if e["layer"] != layer:
                continue
            doc = f'<documentation>{escape(e["doc"])}</documentation>' if e["doc"] else ""
            out.append(f'    <element xsi:type="archimate:{e["type"]}" name="{escape(e["name"])}" id="{e["id"]}">{doc}</element>')
        out.append("  </folder>")
    out.append(f'  <folder name="Implementation &amp; Migration" id="{nid("f_impl")}" type="implementation_migration"/>')
    out.append(f'  <folder name="Other" id="{nid("f_other")}" type="other"/>')
    out.append(f'  <folder name="Relations" id="{nid("f_rel")}" type="relations">')
    access_codes = {"write": "0", "read": "1", "access": "2", "readwrite": "3"}
    for r in relations:
        extra = f' name="{escape(r["name"])}"' if r["name"] else ""
        if r["access"]:
            extra += f' accessType="{access_codes[r["access"]]}"'
        out.append(f'    <element xsi:type="archimate:{r["type"]}" id="{r["id"]}" source="{nid(r["src"])}" target="{nid(r["dst"])}"{extra}/>')
    out.append("  </folder>")
    out.append(f'  <folder name="Views" id="{nid("f_views")}" type="diagrams">')
    for v in views:
        vp = f' viewpoint="{v["viewpoint"]}"' if v["viewpoint"] else ""
        out.append(f'    <element xsi:type="archimate:ArchimateDiagramModel" name="{escape(v["name"])}" id="{v["id"]}"{vp}>')
        if v["doc"]:
            out.append(f'      <documentation>{escape(v["doc"])}</documentation>')
        # posiciones absolutas de cada objeto de diagrama
        obj_id: dict[str, str] = {}
        pos: dict[str, tuple[int, int]] = {}
        group_boxes = []
        y = 20
        max_w = 0
        for gname, rows in v["groups"]:
            gw = max(len(row) for row in rows) * (W + GAP_X) + GAP_X
            gh = len(rows) * (H + GAP_Y) + 30
            group_boxes.append((gname, 20, y, gw, gh, nid(f"grp:{v['name']}:{gname}")))
            ry = y + 35
            for row in rows:
                rx = 20 + GAP_X
                for key in row:
                    if key is not None:
                        obj_id[key] = nid(f"obj:{v['name']}:{key}")
                        pos[key] = (rx, ry)
                    rx += W + GAP_X
                ry += H + GAP_Y
            max_w = max(max_w, gw)
            y += gh + 25
        # conexiones entre objetos presentes en la vista
        conns = []
        for r in relations:
            if r["src"] in obj_id and r["dst"] in obj_id:
                conns.append((nid(f"conn:{v['name']}:{r['key']}"), obj_id[r["src"]], obj_id[r["dst"]], r["id"]))
        targets: dict[str, list[str]] = {}
        sources: dict[str, list[tuple]] = {}
        for cid, s, t, rid in conns:
            targets.setdefault(t, []).append(cid)
            sources.setdefault(s, []).append((cid, t, rid))
        for gname, gx, gy, gw, gh, gid in group_boxes:
            out.append(f'      <child xsi:type="archimate:Group" id="{gid}" name="{escape(gname)}" textAlignment="1">')
            out.append(f'        <bounds x="{gx}" y="{gy}" width="{max(gw, max_w)}" height="{gh}"/>')
            for key, (px, py) in pos.items():
                if not (gy <= py < gy + gh):
                    continue
                oid = obj_id[key]
                tc = f' targetConnections="{" ".join(targets[oid])}"' if oid in targets else ""
                out.append(f'        <child xsi:type="archimate:DiagramObject" id="{oid}"{tc} archimateElement="{by_key[key]["id"]}">')
                out.append(f'          <bounds x="{px - gx}" y="{py - gy}" width="{W}" height="{H}"/>')
                for cid, t, rid in sources.get(oid, []):
                    out.append(f'          <sourceConnection xsi:type="archimate:Connection" id="{cid}" source="{oid}" target="{t}" archimateRelationship="{rid}"/>')
                out.append("        </child>")
            out.append("      </child>")
        out.append("    </element>")
    out.append("  </folder>")
    out.append("</archimate:model>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    xml = render()
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml)
    print(f"{OUT}: {len(elements)} elementos, {len(relations)} relaciones, {len(views)} vistas")
