# -*- coding: utf-8 -*-
"""Diagramas C4 (contexto, contenedores, componentes por capas) con la arquitectura real de SIMA, estilo Structurizr."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
import textwrap, os

OUT = os.path.dirname(os.path.abspath(__file__))
PERSON, SYSTEM, EXT, CONT, DB, COMP = "#1cb0f6", "#1e2761", "#6b7a88", "#2a7fbf", "#24323f", "#0e6b5c"
FONT = "DejaVu Sans"
NL = chr(10)


def wrap(text, width):
    return NL.join(textwrap.wrap(text, width))


def box(ax, x, y, w, h, title, kind, desc="", color=SYSTEM, fs=11, radius=0.25):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.02,rounding_size={radius}", fc=color, ec="none"))
    ax.text(x + w / 2, y + h - 0.42, title, ha="center", va="center", color="white", fontsize=fs + 1.5, fontweight="bold", family=FONT)
    ax.text(x + w / 2, y + h - 0.78, f"[{kind}]", ha="center", va="center", color="white", fontsize=fs - 3, family=FONT)
    if desc:
        ax.text(x + w / 2, y + (h - 0.95) / 2 + 0.05, wrap(desc, 30), ha="center", va="center", color="white", fontsize=fs - 2, family=FONT)


def person(ax, x, y, w, h, title, desc, fs=11):
    ax.add_patch(Circle((x + w / 2, y + h + 0.05), 0.55, fc=PERSON, ec="none"))
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.35", fc=PERSON, ec="none"))
    ax.text(x + w / 2, y + h - 0.45, title, ha="center", va="center", color="white", fontsize=fs + 1.5, fontweight="bold", family=FONT)
    ax.text(x + w / 2, y + h - 0.78, "[Person]", ha="center", va="center", color="white", fontsize=fs - 3, family=FONT)
    ax.text(x + w / 2, y + (h - 0.95) / 2 + 0.05, wrap(desc, 26), ha="center", va="center", color="white", fontsize=fs - 2, family=FONT)


def arrow(ax, p1, p2, label, fs=9, color="#222222", shrink=6, lpos=0.5):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=16, linestyle=(0, (5, 3)), color=color, lw=1.4, shrinkA=shrink, shrinkB=shrink))
    mx, my = p1[0] + (p2[0] - p1[0]) * lpos, p1[1] + (p2[1] - p1[1]) * lpos
    ax.text(mx, my, wrap(label, 26), ha="center", va="center", fontsize=fs, family=FONT, color="#333333",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.95))


def canvas(w=16, h=9):
    fig, ax = plt.subplots(figsize=(w, h), dpi=130)
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off"); fig.patch.set_facecolor("white")
    return fig, ax


def save(fig, name):
    path = os.path.join(OUT, name); fig.savefig(path, bbox_inches="tight", pad_inches=0.15, facecolor="white"); plt.close(fig); return path


# ------------------------------------------------------------------ 1. Contexto
fig, ax = canvas()
person(ax, 0.6, 5.6, 3.0, 1.9, "Estudiante", "Sube clases, practica, repasa, genera refuerzo y resúmenes, revisa progreso")
person(ax, 0.6, 1.4, 3.0, 1.9, "Administrador", "Gestiona usuarios, planes, trabajos y contenido (Django Admin)")
box(ax, 5.6, 3.0, 4.6, 3.2, "SIMA", "Software System", "Notación .mini + pipeline de generación verificada; plataforma de microaprendizaje con evaluación adaptativa por IRT", SYSTEM, fs=12)
box(ax, 12.0, 6.4, 3.6, 2.1, "Proveedor de LLM", "Software System · externo", "API compatible con OpenAI (Qwen, GPT-OSS vía Groq, DeepSeek) o Anthropic", EXT)
box(ax, 12.0, 3.6, 3.6, 2.1, "Whisper (local)", "Software System · externo", "Transcripción con segmentos y marcas de tiempo", EXT)
box(ax, 12.0, 0.8, 3.6, 2.1, "Servidor de correo (SMTP)", "Software System · externo", "Recordatorios de estudio", EXT)
arrow(ax, (3.6, 6.5), (5.6, 5.2), "Usa la plataforma (HTTPS)")
arrow(ax, (3.6, 2.3), (5.6, 3.8), "Administra (HTTPS)")
arrow(ax, (10.2, 5.4), (12.0, 7.3), "Envía contenido de clase o del perfil; recibe ítems .mini, explicaciones y resúmenes")
arrow(ax, (10.2, 4.6), (12.0, 4.6), "Envía audio; recibe transcripción")
arrow(ax, (10.2, 3.7), (12.0, 1.9), "Envía recordatorios")
ax.text(0.6, 0.35, "Diagrama de contexto (C4 nivel 1) · SIMA · septiembre 2026 · fuente: docs/c4-contexto.dsl", fontsize=9, color="#666666", family=FONT)
print(save(fig, "c4_contexto.png"))

# ------------------------------------------------------------------ 2. Contenedores
fig, ax = canvas()
person(ax, 0.5, 5.4, 2.8, 1.9, "Estudiante", "Navegador, escritorio o móvil")
person(ax, 0.5, 1.6, 2.8, 1.9, "Administrador", "Django Admin")
ax.add_patch(FancyBboxPatch((4.2, 0.5), 7.6, 8.0, boxstyle="round,pad=0.02,rounding_size=0.2", fc="none", ec="#1e2761", lw=1.5, linestyle=(0, (6, 4))))
ax.text(4.4, 8.25, "SIMA [Software System]", fontsize=11, fontweight="bold", color="#1e2761", family=FONT)
box(ax, 4.5, 5.6, 3.4, 2.4, "Aplicación web", "Container · Django", "Vistas por dominio, motor adaptativo, servicios de IA, créditos; worker en hilos (modo thread)", CONT)
box(ax, 8.2, 5.6, 3.4, 2.4, "Worker de trabajos", "Container · run_worker", "Modo db: reclama en la BD los trabajos en cola (clases, refuerzos, resúmenes) con bloqueo", CONT)
box(ax, 4.5, 2.6, 3.4, 2.3, "Base de datos", "Container · PostgreSQL", "Cursos, clases, transcripciones, banco de ítems calibrado, sesiones, perfiles, trabajos", DB, radius=0.15)
box(ax, 8.2, 2.6, 3.4, 2.3, "Archivos", "Container · sistema de archivos", "Audios (se descartan tras transcribir) y logs rotativos", DB, radius=0.15)
box(ax, 4.5, 0.7, 7.1, 1.5, "Tareas programadas", "Container · cron / Programador de Windows", "send_study_reminders (diario) · run_worker --once · requeue_jobs", CONT, fs=10)
box(ax, 12.6, 6.5, 3.0, 1.9, "Proveedor de LLM", "externo", "Qwen · GPT-OSS (Groq) · DeepSeek", EXT, fs=10)
box(ax, 12.6, 4.0, 3.0, 1.9, "Whisper (local)", "externo", "Transcripción con segmentos", EXT, fs=10)
box(ax, 12.6, 1.5, 3.0, 1.9, "SMTP", "externo", "Recordatorios", EXT, fs=10)
arrow(ax, (3.3, 6.4), (4.5, 6.8), "HTTPS")
arrow(ax, (3.3, 2.6), (4.5, 6.2), "Admin (HTTPS)")
arrow(ax, (6.2, 5.6), (6.2, 4.9), "Lee y escribe; deja trabajos QUEUED")
arrow(ax, (9.9, 5.6), (9.9, 4.9), "Lee audios; escribe logs")
arrow(ax, (8.4, 5.6), (7.6, 4.9), "Reclama trabajos (skip_locked) y guarda resultados", fs=8, lpos=0.7)
arrow(ax, (11.6, 7.2), (12.6, 7.4), "Genera y verifica ítems, refuerzo y resúmenes (o el web en modo thread)", fs=8)
arrow(ax, (11.6, 6.0), (12.6, 4.9), "Transcribe", fs=8)
arrow(ax, (11.6, 1.45), (12.6, 2.2), "Envía recordatorios", fs=8)
ax.text(0.5, 0.25, "Diagrama de contenedores (C4 nivel 2) · SIMA · septiembre 2026 · fuente: docs/c4-contenedores.dsl", fontsize=9, color="#666666", family=FONT)
print(save(fig, "c4_contenedores.png"))

# ------------------------------------------------------------------ 3. Componentes por capas
fig, ax = canvas(16, 9)
layers = [
    ("Vistas (learning/views/)", 7.35, "#2a7fbf", [
        ("core", "inicio, panel, preferencias, salud"), ("courses", "curso, banco, CSV, editar/archivar"), ("lessons", "carga de clase, estado, reparaciones"),
        ("practice", "práctica, retroalimentación, refuerzo"), ("study", "flashcards, repaso SM-2, ejercicios"), ("summaries", "resúmenes de clase y curso"), ("pipeline", "trazas del pipeline")]),
    ("Núcleo adaptativo", 5.55, COMP, [
        ("adaptive", "banco por curso, sesión CAT, perfil, plan de hoy"), ("psychometrics", "IRT 3PL, EAP, randomesque, Elo, BKT"), ("spaced_repetition", "SM-2 y cola de repaso"),
        ("adaptive_generation", "refuerzo dirigido"), ("summaries", "resúmenes (SummaryJob)"), ("segments · progress · reminders", "fragmentos con minuto, progreso, correos"), ("credits", "planes, cobro y reembolso")]),
    ("Pipeline y servicios de IA", 3.75, "#8a5a12", [
        ("job_queue", "cola en hilos o BD, worker, límite por usuario"), ("pipeline", "transcripción → generación → reparación → verificación → banco"), ("services/prompts", "plantillas .mini"),
        ("services/backends", "proveedores y call_ai"), ("services/generation", "chunks y presupuesto"), ("services/repairs · evidence", "verificación factual, web, EduQG"), ("parse_mini · transcription", "parser .mini · Whisper")]),
    ("Infraestructura", 1.95, DB, [
        ("models", "Course, LessonJob, Question, PracticeSession, AdaptiveProfile, SummaryJob…"), ("templates", "24 plantillas, claro/oscuro, móvil"), ("auth · admin", "django.contrib"),
        ("portability", "exportar/importar curso"), ("management/commands", "run_worker, requeue_jobs, check_ai…"), ("PostgreSQL", "23 migraciones"), ("logs", "rotativos")]),
]
for name, y, color, comps in layers:
    ax.add_patch(FancyBboxPatch((0.4, y), 15.2, 1.55, boxstyle="round,pad=0.02,rounding_size=0.15", fc="none", ec=color, lw=1.4))
    ax.text(0.55, y + 1.32, name, fontsize=11, fontweight="bold", color=color, family=FONT)
    n = len(comps); w = 14.6 / n - 0.12
    for k, (t, d) in enumerate(comps):
        x = 0.7 + k * (14.6 / n)
        ax.add_patch(FancyBboxPatch((x, y + 0.12), w, 1.05, boxstyle="round,pad=0.02,rounding_size=0.12", fc=color, ec="none"))
        ax.text(x + w / 2, y + 0.92, wrap(t, 17), ha="center", va="center", color="white", fontsize=7.8, fontweight="bold", family=FONT)
        ax.text(x + w / 2, y + 0.42, wrap(d, 22), ha="center", va="center", color="white", fontsize=6.8, family=FONT)
for y1, y2 in ((7.35, 7.10), (5.55, 5.30), (3.75, 3.50)):
    ax.add_patch(FancyArrowPatch((8.0, y1), (8.0, y2), arrowstyle="-|>", mutation_scale=14, color="#444444", lw=1.2))
ax.text(0.4, 1.35, "Diagrama de componentes (C4 nivel 3) por capas · aplicación web de SIMA · septiembre 2026 · fuente: docs/c4-componentes.dsl", fontsize=9, color="#666666", family=FONT)
ax.set_ylim(1.2, 9.0)
print(save(fig, "c4_componentes.png"))
