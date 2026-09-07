# -*- coding: utf-8 -*-
"""Diagrama de despliegue UML de SIMA dibujado con matplotlib (posiciones controladas).

    python docs/uml/draw_deployment.py  -> docs/uml/despliegue.png
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Polygon, Rectangle

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "despliegue.png")
FONT = "Segoe UI"
GREEN, GREEN_D, GREY, GREY_D, BLUE, BLUE_D = "#EEF5EE", "#4F7A57", "#F2F2F2", "#7A7A7A", "#EAF0FA", "#4C6A92"

fig, ax = plt.subplots(figsize=(19, 11.5), dpi=150)
ax.set_xlim(0, 190)
ax.set_ylim(0, 112)
ax.axis("off")
ax.invert_yaxis()


def node(x, y, w, h, title, stereo="device", fill=GREEN, edge=GREEN_D, depth=2.2, title_size=10.5, align="center"):
    """Caja 3D de nodo UML."""
    ax.add_patch(Polygon([(x, y), (x + depth, y - depth), (x + w + depth, y - depth), (x + w, y)], closed=True, fc=fill, ec=edge, lw=1.3))
    ax.add_patch(Polygon([(x + w, y), (x + w + depth, y - depth), (x + w + depth, y + h - depth), (x + w, y + h)], closed=True, fc=fill, ec=edge, lw=1.3))
    ax.add_patch(Rectangle((x, y), w, h, fc=fill, ec=edge, lw=1.3))
    tx = x + w / 2 if align == "center" else x + 2
    ha = "center" if align == "center" else "left"
    ax.text(tx, y + 2.0, f"«{stereo}»", ha=ha, va="top", fontsize=8.5, family=FONT, color="#333333")
    ax.text(tx, y + 5.2, title, ha=ha, va="top", fontsize=title_size, family=FONT, fontweight="bold", color="#111111")


def artifact(x, y, w, h, text, size=8.2):
    ax.add_patch(Rectangle((x, y), w, h, fc="white", ec="#666666", lw=1.0))
    ix, iy = x + w - 4.0, y + 0.9
    ax.add_patch(Polygon([(ix, iy), (ix + 2.0, iy), (ix + 3.0, iy + 1), (ix + 3.0, iy + 3.4), (ix, iy + 3.4)], closed=True, fc="white", ec="#666666", lw=0.8))
    ax.plot([ix + 2.0, ix + 2.0, ix + 3.0], [iy, iy + 1, iy + 1], color="#666666", lw=0.8)
    ax.text(x + 1.3, y + h / 2, text, ha="left", va="center", fontsize=size, family=FONT, color="#222222")


def cloud(x, y, w, h, text):
    ax.add_patch(Rectangle((x, y), w, h, fc=GREY, ec=GREY_D, lw=1.2, linestyle=(0, (4, 2))))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9, family=FONT, color="#222222")


def label(x, y, text, ha="center"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=8.3, family=FONT, color="#222222",
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.95), zorder=5)


def link(p1, p2, text="", dashed=False, lpos=0.5, dx=0, dy=0, lha="center"):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=12, lw=1.2, color="#333333",
                                 linestyle=(0, (5, 3)) if dashed else "solid", shrinkA=0, shrinkB=0, zorder=4))
    if text:
        label(p1[0] + (p2[0] - p1[0]) * lpos + dx, p1[1] + (p2[1] - p1[1]) * lpos + dy, text, lha)


def polyline(points, text="", at=1, dashed=False, dx=0, dy=0, lha="center"):
    """Ruta ortogonal; flecha en el ultimo tramo; etiqueta en el punto medio del tramo `at`."""
    for i in range(len(points) - 2):
        ax.plot([points[i][0], points[i + 1][0]], [points[i][1], points[i + 1][1]], color="#333333", lw=1.2,
                linestyle=(0, (5, 3)) if dashed else "solid", zorder=4)
    link(points[-2], points[-1], dashed=dashed)
    if text:
        a, b = points[at], points[at + 1]
        label((a[0] + b[0]) / 2 + dx, (a[1] + b[1]) / 2 + dy, text, lha)


ax.text(95, 2.5, "Diagrama de despliegue de SIMA (UML)", ha="center", va="top", fontsize=14, family=FONT, fontweight="bold")

# --- cliente
node(6, 9, 34, 25, "Dispositivo del estudiante", "device", align="left")
node(9, 19, 28, 12.5, "Navegador web", "executionEnvironment", fill="#F7FAF7", title_size=9.5)
artifact(11, 26.4, 24, 4.2, "Interfaz web SIMA (HTML, CSS, JS)", size=7.4)

# --- borde
cloud(56, 16, 30, 9, "«external»\nCloudflare · DNS y certificado TLS")

# --- externos (arriba a la derecha)
cloud(146, 12, 38, 9, "«external»  Proveedor de LLM\n(Groq · API compatible con OpenAI)")
cloud(146, 25, 38, 8, "«external»  Servidor SMTP")

# --- servidor de aplicacion
node(6, 40, 130, 66, "Servidor de aplicación · Azure VM Ubuntu 22.04 (o servidor Linux equivalente)", "device", align="left")
node(10, 52, 27, 18, "Nginx :443", "executionEnvironment", fill="#F7FAF7", title_size=9.5)
artifact(12, 62, 23, 5.2, "Archivos estáticos\n(collectstatic)", size=7.6)
node(47, 52, 33, 18, "Gunicorn (WSGI) :8000\nPython 3 · Django 4.2", "executionEnvironment", fill="#F7FAF7", title_size=9.5)
artifact(49, 63.2, 14, 5.2, "SIMAApp\n(código)", size=7.6)
artifact(64.5, 63.2, 13.5, 5.2, ".env\n(configuración)", size=7.6)
node(90, 52, 30, 18, "Proceso worker\nmanage.py run_worker", "executionEnvironment", fill="#F7FAF7", title_size=9.5)
artifact(92, 63.2, 26, 5.2, "SIMAApp (pipeline, refuerzo,\nresúmenes)", size=7.6)
ax.add_patch(Rectangle((10, 82), 27, 18, fc="white", ec="#555555", lw=1.0))
ax.text(23.5, 84.2, "Sistema de archivos", ha="center", va="top", fontsize=9.5, family=FONT, fontweight="bold")
artifact(12, 89, 23, 4.4, "Audios subidos (temporales)", size=7.2)
artifact(12, 94.2, 23, 4.4, "logs/sima.log (rotativo)", size=7.2)
node(47, 82, 33, 18, "cron", "executionEnvironment", fill="#F7FAF7", title_size=9.5)
artifact(49, 90.5, 29, 5.2, "send_study_reminders\n(tarea diaria)", size=7.6)
node(90, 82, 30, 18, "Whisper + ffmpeg (CPU)", "executionEnvironment", fill="#F7FAF7", title_size=9.5)
artifact(92, 92.5, 26, 4.6, "Modelo Whisper base", size=7.6)

# --- base de datos
node(146, 42, 38, 28, "Servidor de base de datos\nsubred privada", "device", fill=BLUE, edge=BLUE_D)
node(150, 52.5, 30, 15, "PostgreSQL 18 :5432", "executionEnvironment", fill="#F5F8FD", edge=BLUE_D, title_size=9.5)
artifact(152, 61, 26, 5.2, "Esquema sima_platform\n(23 migraciones)", size=7.6)

# --- rutas de comunicacion
link((40, 20.5), (56, 20.5), "HTTPS 443", dy=-2.6)                                        # dispositivo -> cloudflare
polyline([(71, 25), (71, 34), (23, 34), (23, 52)], "HTTPS 443", at=2, dx=2, lha="left")    # cloudflare -> nginx
link((37, 61), (47, 61), "HTTP 8000\n(localhost)", dy=-4.2)                                # nginx -> gunicorn
link((80, 58), (90, 58), "trabajos\nvía BD", dashed=True, dy=-4.2)                         # gunicorn -> worker (cola en PostgreSQL)
polyline([(70, 52), (70, 47.5), (177, 47.5), (177, 52.5)], "TCP 5432 (red privada)", at=1, dy=-2.4)  # gunicorn -> postgres
link((120, 61), (150, 61), "TCP 5432", dy=-2.4)                                            # worker -> postgres
link((105, 82), (105, 70), "transcripción local", dx=1.5, lha="left")                      # whisper -> worker
link((63, 82), (63, 70), "manage.py (diario)", dx=1.5, lha="left")                         # cron -> gunicorn
link((50, 70), (30, 82), "lee y borra audios,\nescribe logs", dashed=True, dx=2.5, lha="left")  # gunicorn / worker -> archivos
link((74, 52), (146, 17), "HTTPS 443 (API)", lpos=0.32, dy=-2.4)                           # gunicorn -> LLM
link((110, 52), (150, 21), "HTTPS 443 (chat completions)", lpos=0.55, dx=2, lha="left")    # worker -> LLM
link((78, 52), (146, 30), "SMTP 587 (STARTTLS)", lpos=0.62, dy=2.6)                        # gunicorn -> SMTP

fig.savefig(OUT, bbox_inches="tight", facecolor="white")
print(OUT)
