# -*- coding: utf-8 -*-
"""Modelo de datos de SIMA (diagrama entidad-relacion, pata de gallo) con posiciones controladas.

    python manage.py shell -c "exec(open('docs/uml/draw_er.py', encoding='utf-8').read())"

Escribe docs/uml/modelo_datos.png. Lee los modelos Django reales; muestra PK, FK y columnas clave.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from django.apps import apps
from django.contrib.auth import get_user_model
from matplotlib.patches import FancyBboxPatch, Rectangle

OUT = os.path.join(os.getcwd(), "docs", "uml", "modelo_datos.png")
FONT = "Segoe UI"
PG = {"BigAutoField": "bigserial", "AutoField": "serial", "CharField": "varchar", "TextField": "text", "IntegerField": "int",
      "PositiveIntegerField": "int", "PositiveSmallIntegerField": "smallint", "FloatField": "double", "DecimalField": "numeric",
      "BooleanField": "bool", "DateField": "date", "DateTimeField": "timestamptz", "JSONField": "jsonb", "FileField": "varchar"}
KEY = {
    "User": ["username", "email"], "Profile": ["plan", "credit_balance", "total_xp"], "UserPreference": ["daily_goal", "email_reminders"],
    "PlanCatalog": ["code", "monthly_credits", "monthly_price_usd"], "CreditLedgerEntry": ["action", "amount", "balance_after"],
    "StudyStreak": ["current_count", "longest_count"], "Course": ["name", "academic_period", "exam_date"],
    "ClassSession": ["title", "class_date", "status"], "LessonJob": ["title", "status", "transcript", "toon_output", "corrected_output"],
    "Transcript": ["full_text", "language"], "TranscriptSegment": ["start_seconds", "end_seconds", "text"],
    "Quiz": ["title", "topic", "mini_source"], "Question": ["prompt", "bloom_level", "irt_a", "irt_b", "irt_c", "quality_flag"],
    "AnswerOption": ["text", "is_correct"], "Summary": ["kind", "title", "content"],
    "Flashcard": ["question", "answer", "ease_factor", "next_review_at"], "PracticeSession": ["focus", "theta", "standard_error"],
    "StudentAnswer": ["is_correct", "theta_before", "theta_after"], "AdaptiveProfile": ["theta", "mastery_by_topic", "weak_topics"],
    "Recommendation": ["title", "priority", "status"], "StudyActivity": ["activity_type", "xp_awarded"],
    "ReinforcementJob": ["topics", "theta", "status"], "SummaryJob": ["kind", "status"],
}
# (columna, fila) de cada entidad y grupo tematico
POS = {
    "User": (0, 0), "Profile": (1, 0), "UserPreference": (2, 0), "StudyStreak": (3, 0), "PlanCatalog": (4, 0), "CreditLedgerEntry": (5, 0),
    "Course": (0, 1), "ClassSession": (1, 1), "LessonJob": (2, 1), "Transcript": (3, 1), "TranscriptSegment": (4, 1),
    "Quiz": (1, 2), "Question": (2, 2), "AnswerOption": (3, 2), "Summary": (4, 2), "Flashcard": (5, 2),
    "AdaptiveProfile": (0, 3), "PracticeSession": (1, 3), "StudentAnswer": (2, 3), "Recommendation": (4, 3), "StudyActivity": (5, 3),
    "ReinforcementJob": (1, 4), "SummaryJob": (4, 4),
}
GROUPS = [("Usuario, plan y créditos", 0, "#EAF0FA"), ("Cursos y clases", 1, "#EEF5EE"), ("Contenido generado (banco .mini)", 2, "#FDF3E3"),
          ("Práctica adaptativa", 3, "#EFE9F7"), ("Trabajos en cola", 4, "#F1F1F1")]
# FK que se dibujan (las demas FK a User/Course se omiten y se explican en la nota)
SKIP = {("User", n) for n in POS if n not in ("Course", "Profile", "UserPreference", "StudyStreak")} | \
       {("Course", n) for n in POS if n not in ("ClassSession", "LessonJob", "AdaptiveProfile", "PracticeSession")}

models = {m.__name__: m for m in apps.get_app_config("learning").get_models()}
models["User"] = get_user_model()

COL_W, BOX_W, LINE_H, HEAD_H = 33, 27, 1.55, 3.2
ROW_GAP = 12


def box_lines(name):
    m = models[name]
    lines = [("id", "bigserial", "PK")]
    for f in m._meta.concrete_fields:
        if f.is_relation:
            lines.append((f.name + "_id", "bigint", "FK 1:1" if f.one_to_one else "FK"))
    for f in m._meta.concrete_fields:
        if f.is_relation or f.primary_key or f.name not in KEY.get(name, []):
            continue
        t = PG.get(f.get_internal_type(), "text")
        if t == "varchar" and getattr(f, "max_length", None):
            t = f"varchar({f.max_length})"
        lines.append((f.name, t, ""))
    rest = len([f for f in m._meta.concrete_fields if not f.primary_key and not f.is_relation and f.name not in KEY.get(name, [])])
    return lines, rest


boxes = {}
row_h = {}
for name, (c, r) in POS.items():
    lines, rest = box_lines(name)
    h = HEAD_H + LINE_H * (len(lines) + (1 if rest else 0)) + 1.2
    boxes[name] = {"lines": lines, "rest": rest, "h": h, "col": c, "row": r}
    row_h[r] = max(row_h.get(r, 0), h)
row_y = {}
y = 13
for r in sorted(row_h):
    row_y[r] = y
    y += row_h[r] + ROW_GAP
for b in boxes.values():
    b["x"] = 6 + b["col"] * COL_W
    b["y"] = row_y[b["row"]]

fig, ax = plt.subplots(figsize=(20, 12.5), dpi=150)
ax.set_xlim(0, 6 * COL_W + 8)
ax.set_ylim(0, y + 2)
ax.axis("off")
ax.invert_yaxis()
ax.text((6 * COL_W + 8) / 2, 2.2, "Modelo de datos de SIMA · PostgreSQL · app learning (22 tablas) + auth_user", ha="center", va="top",
        fontsize=13, family=FONT, fontweight="bold")

for title, r, color in GROUPS:
    ax.add_patch(Rectangle((1, row_y[r] - 6.6), 6 * COL_W + 4, row_h[r] + 9.4, fc=color, ec="#B8B8B8", lw=0.8, zorder=0))
    ax.text(6 * COL_W + 3, row_y[r] - 5.3, title, ha="right", va="center", fontsize=9, family=FONT, fontweight="bold", color="#444444")

for name, b in boxes.items():
    x, yy, h = b["x"], b["y"], b["h"]
    ax.add_patch(FancyBboxPatch((x, yy), BOX_W, h, boxstyle="round,pad=0,rounding_size=0.6", fc="white", ec="#4C6A92", lw=1.1, zorder=2))
    ax.add_patch(Rectangle((x, yy), BOX_W, HEAD_H, fc="#DCE6F5", ec="#4C6A92", lw=1.1, zorder=2))
    ax.text(x + BOX_W / 2, yy + HEAD_H / 2, name, ha="center", va="center", fontsize=9, family=FONT, fontweight="bold", zorder=3)
    ty = yy + HEAD_H + 0.9
    for col, typ, tag in b["lines"]:
        style = dict(fontweight="bold") if tag == "PK" else {}
        ax.text(x + 1.2, ty + LINE_H / 2, ("● " if tag == "PK" else "○ " if tag else "   ") + col, ha="left", va="center", fontsize=7.2,
                family=FONT, zorder=3, **style)
        ax.text(x + BOX_W - 1.0, ty + LINE_H / 2, (tag + " · " if tag else "") + typ, ha="right", va="center", fontsize=6.4,
                family=FONT, color="#555555", zorder=3)
        ty += LINE_H
    if b["rest"]:
        ax.text(x + BOX_W / 2, ty + LINE_H / 2, f"… +{b['rest']} columnas", ha="center", va="center", fontsize=6.6, family=FONT,
                color="#777777", style="italic", zorder=3)


def mark(p, up, many):
    """Cardinalidad en el extremo p de un segmento vertical que entra por arriba (up=True) o por abajo."""
    x, yv = p
    s = 1 if up else -1          # sentido hacia el interior de la caja
    if many:
        for dx in (-1.1, 0, 1.1):
            ax.plot([x, x + dx], [yv + s * 1.7, yv], color="#333333", lw=1, zorder=3)
    else:
        ax.plot([x - 1.1, x + 1.1], [yv + s * 0.9, yv + s * 0.9], color="#333333", lw=1, zorder=3)


def channel_y(r):
    """y del pasillo horizontal debajo de la fila r."""
    return row_y[r] + row_h[r] + ROW_GAP / 2


conns = []
for name, m in models.items():
    if name == "User":
        continue
    for f in m._meta.concrete_fields:
        if f.is_relation and f.related_model.__name__ in boxes and (f.related_model.__name__, name) not in SKIP:
            conns.append((f.related_model.__name__, name, f.name, f.one_to_one))
conns.sort(key=lambda c: (abs(boxes[c[0]]["row"] - boxes[c[1]]["row"]), c[0], c[1]))

top_used, bot_used, chan_used, gut_used = {}, {}, {}, {}


def slot(d, key, step, span=None):
    """Desplazamiento escalonado por clave; con span, se reparte dentro de [-span, span] sin desbordar."""
    k = d.get(key, 0)
    d[key] = k + 1
    if span is None:
        return k * step
    n = int(2 * span / step) + 1
    return -span + (k % n) * step


for src, dst, fk, one in conns:
    a, b = boxes[src], boxes[dst]
    label_pts = None
    if a["row"] == b["row"]:
        # misma fila: por encima de la fila, por el pasillo superior
        ch = row_y[a["row"]] - 1.8 - slot(chan_used, ("top", a["row"]), 0.9)
        ax_ = a["x"] + BOX_W / 2 + slot(top_used, src, 2.2) - 4
        bx_ = b["x"] + BOX_W / 2 + slot(top_used, dst, 2.2) - 4
        pts = [(ax_, a["y"]), (ax_, ch), (bx_, ch), (bx_, b["y"])]
        mark(pts[0], True, False); mark(pts[-1], True, not one)
        label_pts = ((ax_ + bx_) / 2, ch)
    else:
        down = b["row"] > a["row"]
        if down:
            sx = a["x"] + BOX_W / 2 + slot(bot_used, src, 2.2) - 4
            tx = b["x"] + BOX_W / 2 + slot(top_used, dst, 2.2) - 4
            sy, ty = a["y"] + a["h"], b["y"]
            ch1 = channel_y(a["row"]) + slot(chan_used, a["row"], 1.0, 4.0)
            ch2 = channel_y(b["row"] - 1) + slot(chan_used, b["row"] - 1, 1.0, 4.0) if b["row"] - 1 != a["row"] else ch1
        else:
            sx = a["x"] + BOX_W / 2 + slot(top_used, src, 2.2) - 4
            tx = b["x"] + BOX_W / 2 + slot(bot_used, dst, 2.2) - 4
            sy, ty = a["y"], b["y"] + b["h"]
            ch1 = channel_y(a["row"] - 1) + slot(chan_used, a["row"] - 1, 1.0, 4.0)
            ch2 = channel_y(b["row"]) + slot(chan_used, b["row"], 1.0, 4.0) if b["row"] != a["row"] - 1 else ch1
        if ch1 == ch2:
            pts = [(sx, sy), (sx, ch1), (tx, ch1), (tx, ty)]
        else:
            gx = (b["x"] - 3 if b["col"] >= a["col"] else b["x"] + BOX_W + 3) + slot(gut_used, b["col"], 0.8, 1.6)
            pts = [(sx, sy), (sx, ch1), (gx, ch1), (gx, ch2), (tx, ch2), (tx, ty)]
        mark(pts[0], not down, False); mark(pts[-1], down, not one)
        label_pts = ((pts[1][0] + pts[2][0]) / 2, pts[1][1])
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color="#333333", lw=0.9, zorder=1)
    if os.environ.get("ER_DEBUG"):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            for n, bb in boxes.items():
                if n in (src, dst):
                    continue
                inx = min(x1, x2) < bb["x"] + BOX_W and max(x1, x2) > bb["x"]
                iny = min(y1, y2) < bb["y"] + bb["h"] and max(y1, y2) > bb["y"]
                if inx and iny:
                    print("CRUZA", src, "->", dst, fk, "segmento", (x1, y1), (x2, y2), "caja", n)
    ax.text(label_pts[0], label_pts[1], fk, ha="center", va="center", fontsize=6.0, family=FONT, color="#333333",
            bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.9), zorder=4)

ax.text(4, y + 0.5, "● clave primaria   ○ clave foránea   pata de gallo = lado \"muchos\"   barra = lado \"uno\".  Columnas resumidas; "
        "esquema completo en learning/models.py (23 migraciones).\n"
        "Toda tabla de actividad lleva además user_id (auth_user) y course_id (learning_course): esas líneas se omiten para no saturar.",
        ha="left", va="top", fontsize=7.6, family=FONT, color="#444444")
fig.savefig(OUT, bbox_inches="tight", facecolor="white")
print(OUT)
