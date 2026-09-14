"""PDF para descargar: preguntas de una clase (con hoja de respuestas) y resumenes.

Usa reportlab con DejaVu Sans (incluida en learning/fonts) para que tildes, enes, letras griegas y simbolos
como ± o ≥ se vean igual en cualquier servidor.
"""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

FONT_DIR = Path(__file__).resolve().parent / "fonts"
BODY_FONT = "SimaSans"
BOLD_FONT = "SimaSans-Bold"
INK = "#1a1a1a"
MUTED = "#6b6b6b"
ACCENT = "#d4380d"
LETTERS = "abcdefghij"

_fonts_ready = False


def _register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont(BODY_FONT, str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(BOLD_FONT, str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(BODY_FONT, normal=BODY_FONT, bold=BOLD_FONT, italic=BODY_FONT, boldItalic=BOLD_FONT)
    _fonts_ready = True


def _styles():
    from reportlab.lib.styles import ParagraphStyle

    base = ParagraphStyle("base", fontName=BODY_FONT, fontSize=10.5, leading=15, textColor=INK)
    return {
        "title": ParagraphStyle("title", parent=base, fontName=BOLD_FONT, fontSize=19, leading=24, spaceAfter=4),
        "meta": ParagraphStyle("meta", parent=base, fontSize=9.5, textColor=MUTED, spaceAfter=14),
        "h2": ParagraphStyle("h2", parent=base, fontName=BOLD_FONT, fontSize=13, leading=18, spaceBefore=12, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base, spaceAfter=8),
        "question": ParagraphStyle("question", parent=base, fontName=BOLD_FONT, spaceBefore=8, spaceAfter=3),
        "option": ParagraphStyle("option", parent=base, leftIndent=16, spaceAfter=1),
        "answer": ParagraphStyle("answer", parent=base, fontSize=10, leading=14),
        "chip": ParagraphStyle("chip", parent=base, fontSize=9.5, textColor=MUTED, spaceAfter=10),
    }


def _p(text: str) -> str:
    """Texto plano seguro para Paragraph (escapa < > & y conserva saltos de linea)."""
    return escape(" ".join(str(text or "").split()))


def _build(title: str, flowables: list) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate

    buffer = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(BODY_FONT, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, 1.2 * cm, f"SIMA · {title[:80]}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"{doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm,
                            bottomMargin=2 * cm, title=title, author="SIMA")
    doc.build(flowables, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _header(styles, title: str, subtitle: str) -> list:
    from reportlab.platypus import Paragraph

    return [Paragraph(_p(title), styles["title"]), Paragraph(_p(subtitle), styles["meta"])]


def safe_filename(text: str, fallback: str = "sima") -> str:
    import unicodedata

    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    return (slug[:60] or fallback)


# ------------------------------------------------------------------------------------------ preguntas
def questions_pdf(job) -> bytes:
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer

    from .parse_mini import parse_mini

    _register_fonts()
    styles = _styles()
    mini_text = job.corrected_output or job.toon_output
    items = parse_mini(mini_text).items if mini_text else []
    course = f"{job.course.name} · " if getattr(job, "course", None) else ""
    subtitle = f"{course}{len(items)} preguntas · {date.today().strftime('%d/%m/%Y')}"
    story = _header(styles, job.title, subtitle)
    if not items:
        story.append(Paragraph("Esta clase todavía no tiene preguntas.", styles["body"]))
        return _build(job.title, story)

    answers = []
    for number, item in enumerate(items, start=1):
        block = [Paragraph(f"{number}. {_p(item.statement)}", styles["question"])]
        correct_letter = ""
        for index, option in enumerate(item.options):
            letter = LETTERS[index] if index < len(LETTERS) else str(index + 1)
            text = option.get("text", "") if isinstance(option, dict) else getattr(option, "text", "")
            is_correct = option.get("correct") if isinstance(option, dict) else getattr(option, "correct", False)
            if is_correct and not correct_letter:
                correct_letter = letter
                answers.append((number, letter, text))
            block.append(Paragraph(f"{letter}) {_p(text)}", styles["option"]))
        story.append(KeepTogether(block))

    story += [PageBreak(), Paragraph("Respuestas", styles["h2"]), Spacer(1, 4)]
    for number, letter, text in answers:
        story.append(Paragraph(f"<b>{number}.</b> {letter}) {_p(text)}", styles["answer"]))
    return _build(job.title, story)


# ------------------------------------------------------------------------------------------ resumen
def summary_pdf(title: str, subtitle: str, summary) -> bytes:
    from reportlab.platypus import Paragraph

    _register_fonts()
    styles = _styles()
    story = _header(styles, summary.title or title, subtitle)
    if summary.key_concepts:
        story.append(Paragraph("Conceptos clave", styles["h2"]))
        story.append(Paragraph(_p(" · ".join(summary.key_concepts)), styles["chip"]))
    story.append(Paragraph("Resumen", styles["h2"]))
    review_lines = []
    in_review = False
    for block in re.split(r"\n\s*\n", summary.content or ""):
        block = block.strip()
        if not block:
            continue
        if block.lower().startswith(("que repasar primero", "qué repasar primero")):
            in_review = True
            lines = block.splitlines()[1:]
            review_lines += [line.lstrip("- ").strip() for line in lines if line.strip()]
            continue
        if in_review:
            review_lines += [line.lstrip("- ").strip() for line in block.splitlines() if line.strip()]
            continue
        story.append(Paragraph(_p(block), styles["body"]))
    if review_lines:
        story.append(Paragraph("Qué repasar primero", styles["h2"]))
        for line in review_lines:
            story.append(Paragraph(f"• {_p(line)}", styles["body"]))
    return _build(summary.title or title, story)
