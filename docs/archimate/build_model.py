# -*- coding: utf-8 -*-
"""
Genera el modelo ArchiMate de SIMA en el formato nativo de Archi (.archimate),
con capas de motivacion, negocio, aplicacion y tecnologia, relaciones validas
en ArchiMate 3.2 y vistas con disposicion calculada.

    python docs/archimate/build_model.py            -> escribe docs/archimate/SIMA.archimate desde cero
    python docs/archimate/build_model.py --merge    -> conserva el archivo existente (vistas editadas en Archi,
                                                       p. ej. las "b" con ruteo MCP) y solo agrega/actualiza
                                                       los elementos, relaciones y vistas definidos aqui

Abrir en Archi: File > Open. Los PNG de las vistas se exportan con el reporte
HTML de Archi (ver docs/archimate/README.md).
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from xml.sax.saxutils import escape

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SIMA.archimate")

W, H, GAP_X, GAP_Y = 165, 66, 28, 78
GAP_Y_IN = 40          # separacion vertical dentro de un contenedor (nodo o componente con hijos)
HEAD = 42              # alto de la cabecera de un contenedor
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
el("app_nucleo", "ApplicationComponent", "Núcleo adaptativo", "application", "adaptive, psychometrics (IRT 3PL, EAP, randomesque, Elo, BKT), segments, progress.")
el("app_pipeline", "ApplicationComponent", "Pipeline de generación verificada", "application", "pipeline.py + parse_mini: transcripción → generación .mini → filtros → reparación → verificación factual → corrección → banco.")
el("app_servicios", "ApplicationComponent", "Servicios de IA", "application", "learning/services: prompts, backends (call_ai, proveedores), generation, repairs, evidence (web, EduQG), transcription (Whisper).")
el("app_cola", "ApplicationComponent", "Cola de trabajos y worker", "application", "job_queue (modo thread o db, límite por usuario) y comando run_worker.")
el("app_refuerzo", "ApplicationComponent", "Refuerzo y resúmenes", "application", "adaptive_generation (ReinforcementJob) y summaries (SummaryJob).")
el("app_creditos", "ApplicationComponent", "Créditos y planes", "application", "credits: estimación, cobro y reembolso.")
el("app_llm", "ApplicationComponent", "Proveedor de LLM (externo)", "application", "API compatible con OpenAI: Qwen 3.8 y GPT-OSS vía Groq, DeepSeek; o Anthropic.")
el("app_whisper", "ApplicationComponent", "Whisper (local)", "application", "Transcripción con segmentos y marcas de tiempo; el audio no sale del servidor.")
# --- detalle para la arquitectura logica (capas de presentacion, aplicacion, dominio, infraestructura)
el("pres_estaticos", "ApplicationComponent", "Plantillas HTML, CSS y JS", "application", "templates/learning y static/learning; hotkeys de práctica, tema claro/oscuro, SVG de progreso generado en servidor.")
el("app_transcripcion", "ApplicationComponent", "Transcripción con segmentos", "application", "services/transcription + segments.py: Whisper con marcas de tiempo, TranscriptSegment, enlace pregunta↔segmento.")
el("app_repaso", "ApplicationComponent", "Repetición espaciada (SM-2)", "application", "spaced_repetition.py: EF≥1.3, intervalos 1→6→×EF, cola de repaso por curso.")
el("app_plan", "ApplicationComponent", "Plan diario y progreso", "application", "adaptive.daily_plan (reglas repasar/refuerzo/riesgo/examen), progress.py (serie de 14 días).")
el("app_recordatorios", "ApplicationComponent", "Recordatorios por correo", "application", "reminders.py + comando send_study_reminders (EMAIL_*, SIMA_SITE_URL).")
el("app_portabilidad", "ApplicationComponent", "Portabilidad de cursos", "application", "portability.py + comandos export_course / import_course (JSON).")
el("do_resumen", "DataObject", "Resúmenes (Summary)", "application", "Resumen de clase y de curso en formato t|/c|/p|/r|.")
el("do_usuario", "DataObject", "Usuario, plan y créditos", "application")
el("inf_orm", "ApplicationComponent", "ORM de Django", "application", "Modelos y migraciones sobre PostgreSQL (DB_ENGINE / DATABASE_URL).")
el("inf_backends", "ApplicationComponent", "Cliente de LLM (API compatible con OpenAI)", "application", "services/backends: call_ai, modelo por rol, presupuesto de tokens, reintentos 429/413, limitador por minuto.")
el("inf_parse", "ApplicationComponent", "Parser .mini (parse_mini)", "application", "Filtros de formato de la notación .mini, reparación y conversión a ítems.")
el("inf_correo", "ApplicationComponent", "Envío de correo (SMTP)", "application", "django.core.mail con EMAIL_HOST/EMAIL_PORT/TLS.")
el("inf_archivos", "ApplicationComponent", "Archivos y registros", "application", "Audios temporales, logs/sima.log rotativo, exportaciones CSV/JSON.")
el("inf_config", "ApplicationComponent", "Configuración", "application", "sima/settings.py + .env (proveedor de LLM, cola, límites, correo, seguridad).")
el("ext_smtp", "ApplicationComponent", "Servidor SMTP (externo)", "application")
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
for c in ("app_vistas", "app_nucleo", "app_pipeline", "app_servicios", "app_cola", "app_refuerzo", "app_creditos",
          "pres_estaticos", "app_transcripcion", "app_repaso", "app_plan", "app_recordatorios", "app_portabilidad",
          "inf_orm", "inf_backends", "inf_parse", "inf_correo", "inf_archivos", "inf_config"):
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
rel("Serving", "ai_web", "act_docente")
rel("Serving", "ai_admin", "act_admin")
rel("Serving", "app_servicios", "app_pipeline")
rel("Serving", "app_servicios", "app_refuerzo")
rel("Serving", "app_llm", "app_servicios")
rel("Serving", "app_whisper", "app_servicios")
rel("Serving", "app_cola", "app_pipeline")
rel("Serving", "app_cola", "app_refuerzo")
rel("Serving", "app_creditos", "app_vistas")
rel("Serving", "app_nucleo", "app_vistas")
rel("Serving", "app_llm", "inf_backends")
rel("Serving", "ext_smtp", "inf_correo")
rel("Serving", "app_whisper", "app_transcripcion")
rel("Serving", "inf_backends", "app_servicios")
rel("Serving", "inf_parse", "app_pipeline")
rel("Serving", "inf_orm", "app_nucleo")
rel("Serving", "inf_correo", "app_recordatorios")
rel("Flow", "app_vistas", "app_cola", "encola trabajos")
rel("Flow", "app_pipeline", "app_nucleo", "ítems al banco")
rel("Access", "app_pipeline", "do_lesson", access="readwrite")
rel("Access", "app_pipeline", "do_transcript", access="write")
rel("Access", "app_pipeline", "do_banco", access="write")
rel("Access", "app_nucleo", "do_banco", access="readwrite")
rel("Access", "app_nucleo", "do_sesion", access="write")
rel("Access", "app_nucleo", "do_perfil", access="readwrite")
rel("Access", "app_nucleo", "do_flashcard", access="readwrite")
rel("Access", "app_repaso", "do_flashcard", access="readwrite")
rel("Access", "app_refuerzo", "do_trabajos", access="readwrite")
rel("Access", "app_refuerzo", "do_resumen", access="write")
rel("Access", "app_cola", "do_trabajos", access="readwrite")
rel("Access", "app_vistas", "do_curso", access="readwrite")
rel("Access", "app_creditos", "do_usuario", access="readwrite")
rel("Realization", "do_lesson", "bo_clase")
rel("Realization", "do_banco", "bo_item")
rel("Realization", "do_perfil", "bo_perfil")

# ============================================================ TECNOLOGIA
el("node_servidor", "Node", "Servidor de aplicación", "technology", "Azure VM con Ubuntu 22.04 (o servidor Linux equivalente). En desarrollo: PC Windows 11 con runserver.")
el("sw_python", "SystemSoftware", "Python 3 + Django", "technology")
el("sw_postgres", "SystemSoftware", "PostgreSQL 18 (:5432)", "technology", "Azure Database for PostgreSQL o instancia en el mismo servidor; en desarrollo :5433.")
el("sw_whisper", "SystemSoftware", "Whisper + ffmpeg", "technology", "Modelo base en CPU; el audio se descarta tras transcribir.")
el("sw_scheduler", "SystemSoftware", "cron: send_study_reminders", "technology", "Tarea diaria que envía recordatorios de estudio por correo.")
el("node_worker", "Node", "Proceso worker (run_worker)", "technology", "manage.py run_worker con SIMA_QUEUE_MODE=db: reclama trabajos con SELECT ... FOR UPDATE SKIP LOCKED.")
el("node_navegador", "Device", "Dispositivo del estudiante", "technology", "PC o móvil con navegador moderno.")
el("node_llm", "Node", "Nube del proveedor de LLM", "technology", "Groq (gpt-oss-120b, qwen3.8) u otro proveedor compatible con OpenAI.")
el("net_https", "CommunicationNetwork", "Internet (HTTPS / TLS 1.3)", "technology")
el("ts_web", "TechnologyService", "Servicio web HTTPS", "technology")
el("ts_db", "TechnologyService", "Servicio de base de datos", "technology")
el("ts_llm", "TechnologyService", "API de chat completions", "technology")
el("art_codigo", "Artifact", "Código de SIMAApp", "technology")
el("art_logs", "Artifact", "logs/sima.log (rotativo)", "technology")
el("art_audio", "Artifact", "Audios subidos (temporales)", "technology")
el("art_env", "Artifact", ".env (configuración)", "technology")
# --- detalle para la arquitectura fisica
el("sw_browser", "SystemSoftware", "Navegador web", "technology", "Chrome, Edge, Firefox o Safari; sin instalación en el cliente.")
el("node_edge", "Node", "DNS y certificado TLS (Cloudflare)", "technology", "Dominio público (SIMA_PUBLIC_HOST), certificado y protección básica; opcional.")
el("sw_nginx", "SystemSoftware", "Nginx (proxy inverso :443)", "technology", "Termina TLS, sirve estáticos y reenvía a Gunicorn.")
el("sw_gunicorn", "SystemSoftware", "Gunicorn + Django (WSGI :8000)", "technology", "Aplicación SIMA; varios workers WSGI.")
el("node_db", "Node", "Servidor de base de datos", "technology", "Azure Database for PostgreSQL (subred privada) o PostgreSQL en el mismo servidor.")
el("art_static", "Artifact", "Archivos estáticos", "technology", "collectstatic: CSS, JS, imágenes.")
el("node_smtp", "Node", "Servidor SMTP", "technology", "Proveedor de correo para los recordatorios de estudio.")
el("ts_correo", "TechnologyService", "Servicio de correo", "technology")
for sw in ("sw_python", "sw_postgres", "sw_whisper", "sw_scheduler", "sw_nginx", "sw_gunicorn"):
    rel("Assignment", "node_servidor", sw)
rel("Composition", "node_servidor", "node_worker")
rel("Assignment", "node_navegador", "sw_browser")
rel("Assignment", "node_db", "sw_postgres")
rel("Assignment", "sw_python", "art_codigo")
rel("Assignment", "node_worker", "art_codigo")
rel("Assignment", "node_servidor", "art_logs")
rel("Assignment", "node_servidor", "art_audio")
rel("Assignment", "node_servidor", "art_env")
rel("Assignment", "node_servidor", "art_static")
rel("Realization", "art_codigo", "app_sima")
rel("Realization", "sw_python", "ts_web")
rel("Realization", "sw_postgres", "ts_db")
rel("Realization", "node_llm", "ts_llm")
rel("Realization", "node_smtp", "ts_correo")
rel("Serving", "ts_web", "app_sima")
rel("Serving", "ts_db", "app_sima")
rel("Serving", "ts_llm", "app_llm")
rel("Serving", "ts_correo", "ext_smtp")
rel("Association", "node_navegador", "net_https")
rel("Association", "net_https", "node_servidor")
rel("Association", "node_servidor", "node_llm")
rel("Serving", "sw_whisper", "app_whisper")
rel("Serving", "sw_scheduler", "app_cola")
# flujos con puerto y protocolo (arquitectura fisica)
rel("Flow", "sw_browser", "node_edge", "HTTPS 443")
rel("Flow", "node_edge", "sw_nginx", "HTTPS 443")
rel("Flow", "sw_nginx", "sw_gunicorn", "HTTP 8000 (localhost)")
rel("Flow", "sw_gunicorn", "sw_postgres", "TCP 5432 (red privada)")
rel("Flow", "node_worker", "sw_postgres", "TCP 5432 (cola y datos)")
rel("Flow", "sw_gunicorn", "node_worker", "trabajos vía BD")
rel("Flow", "sw_gunicorn", "node_llm", "HTTPS 443 (API)")
rel("Flow", "node_worker", "node_llm", "HTTPS 443 (API)")
rel("Flow", "sw_gunicorn", "node_smtp", "SMTP 587 (STARTTLS)")
rel("Serving", "sw_whisper", "node_worker", "transcripción local")
rel("Triggering", "sw_scheduler", "sw_gunicorn", "diario")


# ============================================================ VISTAS
def view(name: str, viewpoint: str, bands: list, doc: str = "", links=None, notes=None, rels=None, fills=None, gap_x_in: int = GAP_X,
         text_pos=None):
    """bands: lista de bandas apiladas; cada banda es un grupo (titulo, filas) o una lista de grupos lado a lado.
    Una fila es una lista de celdas: clave de elemento, None (hueco) o (clave contenedora, filas anidadas).
    links: conexiones simples entre grupos [(grupo_origen, grupo_destino, etiqueta)].
    notes: [(texto, grupo junto al que se coloca, ancho, alto)].
    rels: si se da, solo se dibujan las relaciones (tipo, origen, destino) listadas; si no, todas las presentes
          salvo Assignment/Composition entre un objeto y su contenedor.
    fills: {titulo de grupo: color de relleno #RRGGBB}.
    gap_x_in: separacion horizontal dentro de los contenedores (mas ancha si las conexiones llevan etiqueta).
    text_pos: {(tipo, origen, destino): 0|1|2} posicion de la etiqueta de la conexion (origen, medio, destino)."""
    views.append({"name": name, "viewpoint": viewpoint, "bands": bands, "doc": doc, "id": nid("view:" + name),
                  "links": links or [], "notes": notes or [], "rels": rels, "fills": fills or {}, "gap_x_in": gap_x_in,
                  "text_pos": text_pos or {}})


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
], "Capa 1 (pipeline + notación .mini) y capa 2 (núcleo adaptativo) como componentes de la misma aplicación.",
    rels=[(r["type"][:-12], r["src"], r["dst"]) for r in relations
          if r["type"] not in ("CompositionRelationship",) and not (r["src"].startswith("inf_") or r["dst"].startswith("inf_"))
          and r["src"] not in ("app_transcripcion", "app_repaso", "app_plan", "app_recordatorios", "app_portabilidad", "ext_smtp", "pres_estaticos")
          and r["dst"] not in ("app_transcripcion", "app_repaso", "app_plan", "app_recordatorios", "app_portabilidad", "ext_smtp", "pres_estaticos")])

view("4. Tecnología: despliegue", "", [
    ("Cliente", [["node_navegador", "net_https"]]),
    ("Servicios tecnológicos", [["ts_web", "ts_db", "ts_llm"]]),
    ("Servidor de SIMA", [["node_servidor", "sw_python", "sw_postgres", "sw_whisper", "sw_scheduler", "node_worker"],
                          [None, "art_codigo", "art_env", "art_logs", "art_audio"]]),
    ("Externo", [["node_llm"]]),
], "Un servidor con Django, PostgreSQL y Whisper local; worker aparte opcional; proveedor de LLM en la nube.",
    rels=[(r["type"][:-12], r["src"], r["dst"]) for r in relations if r["type"] not in ("FlowRelationship", "TriggeringRelationship")
          and not (r["src"].startswith(("sw_nginx", "sw_gunicorn", "sw_browser", "node_edge", "node_db", "node_smtp", "art_static"))
                   or r["dst"].startswith(("sw_nginx", "sw_gunicorn", "sw_browser", "node_edge", "node_db", "node_smtp", "art_static")))])

view("5. Capas de SIMA (vista en capas)", "", [
    ("Negocio", [["act_estudiante", "bp_subir", "bp_practicar", "bp_repasar", "bp_reforzar"]]),
    ("Servicios de aplicación", [["as_generacion", "as_evaluacion", "as_repaso", "as_refuerzo"]]),
    ("Componentes de aplicación", [["app_pipeline", "app_nucleo", "app_refuerzo", "app_servicios", "app_cola"]]),
    ("Servicios tecnológicos", [["ts_web", "ts_db", "ts_llm"]]),
    ("Tecnología", [["node_servidor", "sw_python", "sw_postgres", "node_llm"]]),
], "Trazabilidad de arriba abajo: quién usa qué, qué servicio lo realiza y sobre qué corre.",
    rels=[(r["type"][:-12], r["src"], r["dst"]) for r in relations if r["type"] not in ("FlowRelationship", "TriggeringRelationship")])

# --- Diagramas de arquitectura logica y fisica (convencion UPC: capas de presentacion / aplicacion / dominio /
#     infraestructura, y despliegue con nodos, red, puertos y protocolos)
view("6. Arquitectura lógica de SIMA", "", [
    ("Actores", [["act_estudiante", "act_docente", "act_admin"]]),
    ("Capa de presentación", [["ai_web", "pres_estaticos", "app_vistas", "ai_admin", "ai_salud"]]),
    ("Capa de aplicación (servicios de negocio)", [["app_pipeline", "app_servicios", "app_transcripcion", "app_nucleo", "app_repaso", "app_plan"],
                                                  ["app_refuerzo", "app_creditos", "app_cola", "app_recordatorios", "app_portabilidad"]]),
    ("Capa de dominio (modelos)", [["do_curso", "do_lesson", "do_transcript", "do_banco", "do_sesion"],
                                  ["do_perfil", "do_flashcard", "do_resumen", "do_trabajos", "do_usuario"]]),
    ("Capa de infraestructura", [["inf_orm", "inf_backends", "inf_parse", "app_whisper", "inf_correo", "inf_archivos", "inf_config"]]),
    ("Servicios externos", [[None, "app_llm", None, None, "ext_smtp"]]),
], "Arquitectura lógica en cuatro capas (presentación, aplicación, dominio, infraestructura) según la convención de la UPC; "
   "cada caja corresponde a un módulo real del repositorio SIMAApp.",
    links=[("Actores", "Capa de presentación", "usa por HTTPS"),
           ("Capa de presentación", "Capa de aplicación (servicios de negocio)", "invoca servicios"),
           ("Capa de aplicación (servicios de negocio)", "Capa de dominio (modelos)", "lee y escribe modelos"),
           ("Capa de dominio (modelos)", "Capa de infraestructura", "se persiste y se integra mediante adaptadores")],
    rels=[("Serving", "app_llm", "inf_backends"), ("Serving", "ext_smtp", "inf_correo")],
    fills={"Actores": "#f2f2f2", "Capa de presentación": "#e3ecfa", "Capa de aplicación (servicios de negocio)": "#e4f3e6",
           "Capa de dominio (modelos)": "#ede7f6", "Capa de infraestructura": "#fdf0e0", "Servicios externos": "#ececec"})

view("7. Arquitectura física de SIMA (despliegue)", "", [
    ("Cliente", [[("node_navegador", [["sw_browser"]])]]),
    [("Red pública", [["net_https", "node_edge"]]),
     ("Servicios externos", [[None, None, "node_llm", "node_smtp"]])],
    ("Nube: Azure VM (Ubuntu 22.04) o servidor Linux equivalente",
     [[("node_servidor", [["sw_nginx", "sw_gunicorn", "node_worker", "sw_whisper"],
                          [None, None, "art_codigo", "sw_scheduler"],
                          [None, None, "art_static", "art_env"],
                          [None, None, "art_logs", "art_audio"]])]]),
    ("Datos (subred privada)", [[("node_db", [["sw_postgres"]])]]),
], "Arquitectura física / despliegue: dispositivos, red, nodos y software de sistema con puertos y protocolos. "
   "Producción propuesta sobre una VM Linux (Nginx + Gunicorn + worker + Whisper local) y PostgreSQL en subred privada.",
    notes=[("Entorno de desarrollo actual: Windows 11, runserver :8002, PostgreSQL :5433, cola en hilo (SIMA_QUEUE_MODE=thread), "
            "Whisper base en CPU.\n\nProducción propuesta: Nginx + Gunicorn, worker separado (SIMA_QUEUE_MODE=db), cron diario, "
            "PostgreSQL gestionado en subred privada; el audio nunca sale del servidor.", "Datos (subred privada)", 420, 150)],
    rels=[("Association", "node_navegador", "net_https"), ("Association", "net_https", "node_servidor"),
          ("Flow", "sw_browser", "node_edge"), ("Flow", "node_edge", "sw_nginx"), ("Flow", "sw_nginx", "sw_gunicorn"),
          ("Flow", "sw_gunicorn", "sw_postgres"), ("Flow", "node_worker", "sw_postgres"), ("Flow", "sw_gunicorn", "node_worker"),
          ("Flow", "sw_gunicorn", "node_llm"), ("Flow", "node_worker", "node_llm"), ("Flow", "sw_gunicorn", "node_smtp"),
          ("Serving", "sw_whisper", "node_worker"), ("Triggering", "sw_scheduler", "sw_gunicorn"),
          ("Assignment", "node_worker", "art_codigo")],
    fills={"Cliente": "#f2f2f2", "Red pública": "#f2f2f2", "Nube: Azure VM (Ubuntu 22.04) o servidor Linux equivalente": "#e8f3ea",
           "Datos (subred privada)": "#e8f3ea", "Servicios externos": "#ececec"},
    gap_x_in=130,
    text_pos={("Flow", "node_edge", "sw_nginx"): 2, ("Flow", "sw_gunicorn", "node_llm"): 0, ("Flow", "node_worker", "node_llm"): 2,
              ("Flow", "sw_gunicorn", "node_smtp"): 1, ("Triggering", "sw_scheduler", "sw_gunicorn"): 0})


# ============================================================ DISPOSICION
def cell_size(cell, gx):
    """(ancho, alto) de una celda: elemento suelto o contenedor con filas (gx: separacion interna)."""
    if cell is None or isinstance(cell, str):
        return W, H
    _, rows = cell
    w = max(sum(cell_size(c, gx)[0] + gx for c in row) for row in rows) + gx
    h = HEAD + sum(max(cell_size(c, gx)[1] for c in row) + GAP_Y_IN for row in rows)
    return w, h


def place_rows(rows, x0, y0, gap_x, gap_y, gx, parent, out):
    """Coloca filas a partir de (x0, y0) absolutos; out: lista de objetos {key,x,y,w,h,parent,children}."""
    y = y0
    for row in rows:
        x = x0
        rh = max(cell_size(c, gx)[1] for c in row)
        for c in row:
            cw, ch = cell_size(c, gx)
            if isinstance(c, str):
                out.append({"key": c, "x": x, "y": y, "w": cw, "h": ch, "parent": parent, "children": []})
            elif c is not None:
                key, sub = c
                node = {"key": key, "x": x, "y": y, "w": cw, "h": ch, "parent": parent, "children": []}
                out.append(node)
                place_rows(sub, x + gx, y + HEAD, gx, GAP_Y_IN, gx, node, node["children"])
            x += cw + gap_x
        y += rh + gap_y


def layout(v):
    """Devuelve (grupos, objetos, notas) con coordenadas absolutas."""
    groups, objects, notes = [], [], []
    gx = v["gap_x_in"]
    y = 20
    for band in v["bands"]:
        band_groups = band if isinstance(band, list) else [band]
        x = 20
        band_h = 0
        for gname, rows in band_groups:
            gw = max(sum(cell_size(c, gx)[0] + GAP_X for c in row) for row in rows) + GAP_X
            gh = 35 + sum(max(cell_size(c, gx)[1] for c in row) + GAP_Y for row in rows) - GAP_Y + 20
            g = {"name": gname, "x": x, "y": y, "w": gw, "h": gh, "id": nid(f"grp:{v['name']}:{gname}"), "objs": []}
            place_rows(rows, x + GAP_X, y + 35, GAP_X, GAP_Y, gx, None, g["objs"])
            groups.append(g)
            x += gw + 30
            band_h = max(band_h, gh)
        y += band_h + 25
    # bandas de un solo grupo se estiran al ancho maximo del diagrama
    max_w = max(g["w"] for g in groups)
    band_of = {}
    for band in v["bands"]:
        band_groups = band if isinstance(band, list) else [band]
        for gname, _ in band_groups:
            band_of[gname] = len(band_groups)
    for g in groups:
        if band_of[g["name"]] == 1:
            g["w"] = max(g["w"], max_w)
    for text, near, nw, nh in v["notes"]:
        g = next(g for g in groups if g["name"] == near)
        notes.append({"text": text, "x": g["x"] + g["w"] + 30, "y": g["y"], "w": nw, "h": nh, "id": nid(f"note:{v['name']}:{text[:20]}")})
    return groups, objects, notes


def flatten(objs, acc, ancestors):
    for o in objs:
        o["ancestors"] = set(ancestors)
        acc[o["key"]] = o
        flatten(o["children"], acc, ancestors + [o["key"]])
    return acc


def render_view(v, by_key, out):
    groups, _, notes = layout(v)
    all_objs: dict[str, dict] = {}
    for g in groups:
        flatten(g["objs"], all_objs, [])
    obj_id = {k: nid(f"obj:{v['name']}:{k}") for k in all_objs}
    allowed = None if v["rels"] is None else {(k, s, d) for k, s, d in v["rels"]}
    conns = []
    for r in relations:
        if r["src"] not in obj_id or r["dst"] not in obj_id:
            continue
        kind = r["type"][:-12]
        if allowed is not None:
            if (kind, r["src"], r["dst"]) not in allowed:
                continue
        elif kind in ("Assignment", "Composition") and (
                r["src"] in all_objs[r["dst"]]["ancestors"] or r["dst"] in all_objs[r["src"]]["ancestors"]):
            continue
        conns.append((nid(f"conn:{v['name']}:{r['key']}"), obj_id[r["src"]], obj_id[r["dst"]], r["id"], "",
                      v["text_pos"].get((kind, r["src"], r["dst"]))))
    gid = {g["name"]: g["id"] for g in groups}
    for a, b, label in v["links"]:
        conns.append((nid(f"link:{v['name']}:{a}->{b}"), gid[a], gid[b], None, label, None))
    targets: dict[str, list[str]] = {}
    sources: dict[str, list[tuple]] = {}
    for cid, s, t, rid, label, tp in conns:
        targets.setdefault(t, []).append(cid)
        sources.setdefault(s, []).append((cid, t, rid, label, tp))

    def emit_conns(oid, indent):
        for cid, t, rid, label, tp in sources.get(oid, []):
            # archimate:Connection exige una relacion; los enlaces simples entre grupos son DiagramModelConnection
            ctype = "Connection" if rid else "DiagramModelConnection"
            extra = f' archimateRelationship="{rid}"' if rid else ""
            if label:
                extra += f' name="{escape(label)}"'
            if tp is not None:
                extra += f' textPosition="{tp}"'
            out.append(f'{indent}<sourceConnection xsi:type="archimate:{ctype}" id="{cid}" source="{oid}" target="{t}"{extra}/>')

    def emit_obj(o, px, py, indent):
        oid = obj_id[o["key"]]
        tc = f' targetConnections="{" ".join(targets[oid])}"' if oid in targets else ""
        out.append(f'{indent}<child xsi:type="archimate:DiagramObject" id="{oid}"{tc} archimateElement="{by_key[o["key"]]["id"]}">')
        out.append(f'{indent}  <bounds x="{o["x"] - px}" y="{o["y"] - py}" width="{o["w"]}" height="{o["h"]}"/>')
        emit_conns(oid, indent + "  ")
        for c in o["children"]:
            emit_obj(c, o["x"], o["y"], indent + "  ")
        out.append(f'{indent}</child>')

    vp = f' viewpoint="{v["viewpoint"]}"' if v["viewpoint"] else ""
    out.append(f'    <element xsi:type="archimate:ArchimateDiagramModel" name="{escape(v["name"])}" id="{v["id"]}"{vp}>')
    if v["doc"]:
        out.append(f'      <documentation>{escape(v["doc"])}</documentation>')
    for g in groups:
        tc = f' targetConnections="{" ".join(targets[g["id"]])}"' if g["id"] in targets else ""
        fill = f' fillColor="{v["fills"][g["name"]]}"' if g["name"] in v["fills"] else ""
        out.append(f'      <child xsi:type="archimate:Group" id="{g["id"]}"{tc} name="{escape(g["name"])}"{fill} textAlignment="1">')
        out.append(f'        <bounds x="{g["x"]}" y="{g["y"]}" width="{g["w"]}" height="{g["h"]}"/>')
        emit_conns(g["id"], "        ")
        for o in g["objs"]:
            emit_obj(o, g["x"], g["y"], "        ")
        out.append("      </child>")
    for n in notes:
        out.append(f'      <child xsi:type="archimate:Note" id="{n["id"]}" textAlignment="1">')
        out.append(f'        <bounds x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}"/>')
        out.append(f'        <content>{escape(n["text"])}</content>')
        out.append("      </child>")
    out.append("    </element>")


# ============================================================ SERIALIZACION
FOLDERS = {"motivation": ("Motivation", "motivation"), "business": ("Business", "business"),
           "application": ("Application", "application"), "technology": ("Technology &amp; Physical", "technology")}
ACCESS = {"write": "0", "read": "1", "access": "2", "readwrite": "3"}


def element_line(e) -> str:
    doc = f'<documentation>{escape(e["doc"])}</documentation>' if e["doc"] else ""
    return f'    <element xsi:type="archimate:{e["type"]}" name="{escape(e["name"])}" id="{e["id"]}">{doc}</element>'


def relation_line(r) -> str:
    extra = f' name="{escape(r["name"])}"' if r["name"] else ""
    if r["access"]:
        extra += f' accessType="{ACCESS[r["access"]]}"'
    return f'    <element xsi:type="archimate:{r["type"]}" id="{r["id"]}" source="{nid(r["src"])}" target="{nid(r["dst"])}"{extra}/>'


def render() -> str:
    by_key = {e["key"]: e for e in elements}
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<archimate:model xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:archimate="http://www.archimatetool.com/archimate" '
           f'name="SIMA" id="{nid("model")}" version="5.0.0">',
           '  <purpose>Modelo ArchiMate de SIMA: notación .mini y pipeline de generación verificada de ítems IRT con modelos de lenguaje, '
           'integrados en una plataforma de microaprendizaje con evaluación adaptativa. Generado por docs/archimate/build_model.py.</purpose>',
           f'  <folder name="Strategy" id="{nid("f_strategy")}" type="strategy"/>']
    for layer, (label, ftype) in FOLDERS.items():
        out.append(f'  <folder name="{label}" id="{nid("f_" + layer)}" type="{ftype}">')
        out.extend(element_line(e) for e in elements if e["layer"] == layer)
        out.append("  </folder>")
    out.append(f'  <folder name="Implementation &amp; Migration" id="{nid("f_impl")}" type="implementation_migration"/>')
    out.append(f'  <folder name="Other" id="{nid("f_other")}" type="other"/>')
    out.append(f'  <folder name="Relations" id="{nid("f_rel")}" type="relations">')
    out.extend(relation_line(r) for r in relations)
    out.append("  </folder>")
    out.append(f'  <folder name="Views" id="{nid("f_views")}" type="diagrams">')
    for v in views:
        render_view(v, by_key, out)
    out.append("  </folder>")
    out.append("</archimate:model>")
    return "\n".join(out) + "\n"


def merge(existing: str) -> str:
    """Inserta en el XML existente los elementos y relaciones que falten, actualiza nombres y reemplaza las vistas
    definidas aqui (por id); todo lo demas (vistas creadas a mano, bendpoints, colores) se conserva."""
    by_key = {e["key"]: e for e in elements}
    text = existing

    def insert_in_folder(ftype: str, lines: list[str]) -> None:
        nonlocal text
        if not lines:
            return
        m = re.search(rf'<folder name="[^"]*" id="[^"]*" type="{ftype}">', text)
        if not m:
            raise SystemExit(f"carpeta type={ftype} no encontrada")
        close = text.index("\n  </folder>", m.end())
        text = text[:close] + "\n" + "\n".join(lines) + text[close:]

    added_e = added_r = renamed = replaced = 0
    for layer, (_, ftype) in FOLDERS.items():
        new_lines = []
        for e in elements:
            if e["layer"] != layer:
                continue
            m = re.search(rf'<element xsi:type="archimate:{e["type"]}" name="([^"]*)" id="{e["id"]}"', text)
            if m:
                if m.group(1) != escape(e["name"]):
                    text = text[:m.start(1)] + escape(e["name"]) + text[m.end(1):]
                    renamed += 1
            else:
                new_lines.append(element_line(e))
        insert_in_folder(ftype, new_lines)
        added_e += len(new_lines)
    new_rels = [relation_line(r) for r in relations if f'id="{r["id"]}"' not in text]
    insert_in_folder("relations", new_rels)
    added_r += len(new_rels)
    for v in views:
        buf: list[str] = []
        render_view(v, by_key, buf)
        block = "\n".join(buf)
        pat = re.compile(rf'\n    <element xsi:type="archimate:ArchimateDiagramModel"[^>]*id="{v["id"]}"[^>]*>.*?\n    </element>', re.S)
        if pat.search(text):
            text = pat.sub(lambda _m: "\n" + block, text, count=1)
            replaced += 1
        else:
            insert_in_folder("diagrams", [block])
    print(f"merge: {added_e} elementos nuevos, {renamed} renombrados, {added_r} relaciones nuevas, {replaced} vistas reemplazadas, "
          f"{len(views) - replaced} vistas nuevas")
    return text


if __name__ == "__main__":
    if "--merge" in sys.argv and os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            xml = merge(f.read())
    else:
        xml = render()
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml)
    print(f"{OUT}: {len(elements)} elementos, {len(relations)} relaciones, {len(views)} vistas definidas")
