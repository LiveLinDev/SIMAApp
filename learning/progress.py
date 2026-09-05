"""
Progreso semanal: serie diaria de respuestas, aciertos y habilidad (theta),
y su render como SVG en el servidor (sin JavaScript ni librerias).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from html import escape

from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import Course, StudentAnswer, StudyActivity

DEFAULT_DAYS = 14
_DAY_LABELS = ["L", "M", "X", "J", "V", "S", "D"]


def weekly_series(user, course: Course | None = None, days: int = DEFAULT_DAYS) -> list[dict]:
    """Un registro por dia (los ultimos `days`, hoy incluido)."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    start_dt = timezone.make_aware(timezone.datetime.combine(start, timezone.datetime.min.time()))

    answers = StudentAnswer.objects.filter(user=user, answered_at__gte=start_dt).order_by("answered_at")
    activities = StudyActivity.objects.filter(user=user, occurred_at__gte=start_dt)
    if course is not None:
        answers = answers.filter(course=course)
        activities = activities.filter(course=course)

    by_day = defaultdict(lambda: {"answered": 0, "correct": 0, "theta": None, "xp": 0})
    for a in answers.values_list("answered_at", "is_correct", "theta_after"):
        day = timezone.localtime(a[0]).date()
        row = by_day[day]
        row["answered"] += 1
        row["correct"] += 1 if a[1] else 0
        if a[2] is not None:
            row["theta"] = a[2]
    for occurred_at, xp in activities.values_list("occurred_at", "xp_awarded"):
        by_day[timezone.localtime(occurred_at).date()]["xp"] += xp

    series = []
    for i in range(days):
        day = start + timedelta(days=i)
        row = by_day.get(day, {"answered": 0, "correct": 0, "theta": None, "xp": 0})
        series.append({
            "date": day,
            "label": _DAY_LABELS[day.weekday()],
            "answered": row["answered"],
            "correct": row["correct"],
            "theta": row["theta"],
            "xp": row["xp"],
            "is_today": day == today,
        })
    return series


def week_stats(series: list[dict]) -> dict:
    """Comparativa de los ultimos 7 dias contra los 7 anteriores."""
    recent, previous = series[-7:], series[:-7]

    def agg(rows):
        answered = sum(r["answered"] for r in rows)
        correct = sum(r["correct"] for r in rows)
        thetas = [r["theta"] for r in rows if r["theta"] is not None]
        return {
            "answered": answered,
            "accuracy": round(100 * correct / answered) if answered else None,
            "theta": thetas[-1] if thetas else None,
            "active_days": sum(1 for r in rows if r["answered"] or r["xp"]),
            "xp": sum(r["xp"] for r in rows),
        }

    now, before = agg(recent), agg(previous)
    theta_delta = None
    if now["theta"] is not None and before["theta"] is not None:
        theta_delta = round(now["theta"] - before["theta"], 2)
    return {"current": now, "previous": before, "theta_delta": theta_delta, "answered_delta": now["answered"] - before["answered"]}


def render_progress_svg(series: list[dict], width: int = 640, height: int = 170) -> str:
    """
    Barras por dia (respuestas; la parte llena son los aciertos) y linea de theta.
    Usa variables CSS del tema para integrarse con claro/oscuro.
    """
    n = max(len(series), 1)
    pad_l, pad_r, pad_t, pad_b = 34, 14, 14, 26
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    slot = plot_w / n
    bar_w = max(slot * 0.58, 6)
    max_answers = max([r["answered"] for r in series] + [1])
    thetas = [r["theta"] for r in series if r["theta"] is not None]
    t_min, t_max = (min(thetas) - 0.5, max(thetas) + 0.5) if thetas else (-1.5, 1.5)
    if t_max - t_min < 1.0:
        mid = (t_max + t_min) / 2
        t_min, t_max = mid - 0.5, mid + 0.5

    def x_of(i):
        return pad_l + slot * i + slot / 2

    def y_answers(v):
        return pad_t + plot_h - (v / max_answers) * plot_h

    def y_theta(t):
        return pad_t + plot_h - ((t - t_min) / (t_max - t_min)) * plot_h

    parts = [
        f'<svg class="progress-svg" viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Progreso de los ultimos {n} dias" xmlns="http://www.w3.org/2000/svg">',
        f'<line x1="{pad_l}" y1="{pad_t + plot_h:.1f}" x2="{width - pad_r}" y2="{pad_t + plot_h:.1f}" stroke="var(--line)" stroke-width="1"/>',
        f'<text x="{pad_l - 6}" y="{pad_t + 10}" text-anchor="end" font-size="10" fill="var(--muted)">{max_answers}</text>',
        f'<text x="{pad_l - 6}" y="{pad_t + plot_h:.1f}" text-anchor="end" font-size="10" fill="var(--muted)">0</text>',
    ]
    for i, row in enumerate(series):
        x = x_of(i) - bar_w / 2
        if row["answered"]:
            y_all, y_ok = y_answers(row["answered"]), y_answers(row["correct"])
            parts.append(f'<rect x="{x:.1f}" y="{y_all:.1f}" width="{bar_w:.1f}" height="{pad_t + plot_h - y_all:.1f}" rx="3" fill="var(--line)"/>')
            if row["correct"]:
                parts.append(f'<rect x="{x:.1f}" y="{y_ok:.1f}" width="{bar_w:.1f}" height="{pad_t + plot_h - y_ok:.1f}" rx="3" fill="var(--acid)"/>')
            parts.append(
                f'<title>{escape(row["date"].strftime("%d/%m"))}: {row["correct"]} de {row["answered"]} correctas</title>'
            )
        weight = ' font-weight="700"' if row["is_today"] else ""
        parts.append(
            f'<text x="{x_of(i):.1f}" y="{height - 8}" text-anchor="middle" font-size="10" fill="var(--muted)"{weight}>{escape(row["label"])}</text>'
        )
    points = [(x_of(i), y_theta(row["theta"])) for i, row in enumerate(series) if row["theta"] is not None]
    if len(points) >= 2:
        d = " ".join(f"{'M' if k == 0 else 'L'}{px:.1f},{py:.1f}" for k, (px, py) in enumerate(points))
        parts.append(f'<path d="{d}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    for px, py in points:
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="var(--ink)"/>')
    parts.append("</svg>")
    return mark_safe("".join(parts))


def progress_panel(user, course: Course | None = None, days: int = DEFAULT_DAYS) -> dict:
    series = weekly_series(user, course, days)
    return {
        "series": series,
        "stats": week_stats(series),
        "svg": render_progress_svg(series),
        "has_data": any(r["answered"] or r["xp"] for r in series),
    }
