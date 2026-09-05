"""Visualizacion del pipeline de una clase (etapas, trazas y metricas)."""
from __future__ import annotations

import csv
import json
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.db import connection
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from .. import adaptive, adaptive_generation, progress, summaries
from .. import spaced_repetition
from ..cat import BLOOM_LABELS, build_bank, choose_next_item, estimate_theta, option_index, parse_cat_params, theta_to_level
from ..credits import (
    REGENERATION_COST,
    consume_credits,
    estimate_lesson_job_cost,
    grant_plan_credits,
    has_enough_credits,
)
from ..forms import ApiLessonForm, CourseForm, FreeLessonForm, ManualResultForm, PlanForm, RegisterForm, VerificationResultForm
from ..job_queue import enqueue_lesson_job
from ..models import ClassSession, Course, Difficulty, Flashcard, LessonJob, UserPreference, get_plan_details
from ..parse_mini import apply_corrections_with_trace, assessment_to_dict, filter_incoherent_items, normalize_mini_text, parse_mini, render_mini_html, validate_mini_parse
from ..services import (
    build_generation_prompt,
    build_verification_prompt,
    clean_ai_error,
    extract_mini_lines,
    get_available_backends,
    normalize_backend,
    repair_mini_coherence,
    repair_transcript_text,
    text_change_summary,
)
import random


@login_required
def pipeline_visualization(request, pk):
    """Visualizacion del pipeline de generacion como diagrama de flujo."""
    job = get_object_or_404(LessonJob, pk=pk, user=request.user)

    # Parsear processing_log en etapas
    stages = _parse_pipeline_stages(job)

    # Extraer metricas clave
    metrics = _extract_pipeline_metrics(job)

    # Preparar datos de modal por etapa
    stage_details = _build_stage_details(job, stages)

    return render(request, "learning/pipeline_viz.html", {
        "job": job,
        "stages": stages,
        "metrics": metrics,
        "stage_details": stage_details,
    })


def _format_transcript_trace(trace):
    lines = []
    changes = trace.get("changes", [])
    if changes:
        lines.append("<strong>Cambios detectados:</strong>")
        for ch in changes[:8]:
            lines.append(f"<code>{ch.get('before','')[:60]}...</code> → <code>{ch.get('after','')[:60]}...</code>")
    else:
        lines.append("No se detectaron cambios significativos.")
    return "<br>".join(lines)


def _format_coherence_trace(trace):
    lines = []
    changes = trace.get("changes", [])
    if changes:
        lines.append(f"<strong>Cambios:</strong> {len(changes)} items modificados")
        for ch in changes[:5]:
            lines.append(f"<code>{ch.get('before','')[:80]}...</code> → <code>{ch.get('after','')[:80]}...</code>")
    else:
        lines.append("No se requirieron cambios de coherencia.")
    return "<br>".join(lines)


def _format_verification_trace(verif):
    lines = []
    web = verif.get("web", {})
    queries = web.get("queries", [])
    if queries:
        lines.append(f"<strong>Queries web:</strong> {len(queries)}")
        for q in queries:
            results = q.get("results", [])
            lines.append(f"• <em>{q.get('query','')[:50]}...</em> → {len(results)} resultados")
    eduqg = verif.get("eduqg", {})
    matches = eduqg.get("matches", [])
    if matches:
        lines.append(f"<strong>Matches EduQG:</strong> {len(matches)}")
    return "<br>".join(lines)


def _format_corrections_trace(applied, ignored):
    lines = []
    if applied:
        lines.append(f"<strong>Aplicadas ({len(applied)}):</strong>")
        for c in applied[:10]:
            lines.append(f"• [{c.get('matched_item_id','?')}] {c.get('error_type','')} — {c.get('note','')}")
    if ignored:
        lines.append(f"<strong>Ignoradas ({len(ignored)}):</strong>")
        for c in ignored[:5]:
            lines.append(f"• [{c.get('report_item_id','?')}] {c.get('note','')}")
    return "<br>".join(lines)


def _build_stage_details(job, stages):
    """Construye dossiers estructurados para exponer prompts, MINI y evidencia."""
    details = {}
    source_content = job.source_text or job.transcript or ""

    if source_content:
        details["source"] = _stage_detail(
            "Entrada de la clase",
            "Texto base usado para transcripcion, generacion o reparacion.",
            [_text_section("Contenido de entrada", source_content)],
        )

    if job.transcript:
        details["transcript"] = _stage_detail(
            "Transcripcion local",
            "Texto obtenido o revisado antes de generar items.",
            [_text_section("Transcripcion", job.transcript)],
        )

    if job.generation_prompt or job.toon_output:
        details["generation"] = _stage_detail(
            "Generacion de microcontenidos MINI",
            "Prompt real enviado al backend y salida MINI inicial renderizable.",
            [
                _text_section("Prompt de generacion", job.generation_prompt, kind="prompt"),
                _text_section("Salida MINI generada", job.toon_output, kind="mini"),
            ],
        )

    for index, trace in enumerate(job.transcript_repair_trace or []):
        details[f"transcript_repair_{index}"] = _stage_detail(
            "Correccion de transcripcion",
            "El modelo revisa errores probables de audio antes de crear items.",
            [
                _text_section("Prompt de reparacion", job.transcript_repair_prompt, kind="prompt"),
                _diff_section("Antes / despues", trace.get("before", ""), trace.get("after", ""), trace.get("changes", [])),
                _json_section("Trace tecnico", trace),
            ],
        )

    for index, trace in enumerate(job.mini_coherence_trace or []):
        details[f"coherence_{index}"] = _stage_detail(
            "Revision de coherencia MINI",
            "Control local de sentido antes de verificar contra fuentes externas.",
            [
                _text_section("Prompt de coherencia", job.mini_coherence_prompt, kind="prompt"),
                _diff_section("MINI antes / despues", trace.get("before", ""), trace.get("after", ""), trace.get("changes", [])),
                _json_section("Trace tecnico", trace),
            ],
        )

    verif = job.verification_trace or {}
    if verif or job.verification_prompt or job.verification_output:
        details["verification"] = _stage_detail(
            "Verificacion con fuentes",
            "La IA valida afirmaciones MINI usando consultas generadas y documentos recuperados.",
            [
                _text_section("Prompt de verificacion", job.verification_prompt, kind="prompt"),
                _web_section("Evidencia web y EduQG", verif),
                _text_section("Reporte del verificador", job.verification_output, kind="code"),
            ],
        )

    corr_traces = job.correction_trace or []
    if corr_traces or job.corrected_output:
        applied = [entry for entry in corr_traces if entry.get("applied")]
        ignored = [entry for entry in corr_traces if not entry.get("applied")]
        details["corrections"] = _stage_detail(
            f"Correcciones aplicadas ({len(applied)})",
            f"{len(applied)} cambios aplicados, {len(ignored)} observaciones sin cambio.",
            [
                _diff_section("MINI generado / MINI final", job.toon_output, job.corrected_output, corr_traces),
                _json_section("Correcciones aplicadas", applied),
                _json_section("Observaciones ignoradas", ignored),
            ],
        )

    if job.corrected_output or job.toon_output:
        details["final"] = _stage_detail(
            "MINI final listo para estudiar",
            "Banco que alimenta quiz adaptativo, flashcards, mapa y ejercicios.",
            [_text_section("MINI final", job.corrected_output or job.toon_output, kind="mini")],
        )

    for stage in stages:
        stage["detail_key"] = _detail_key_for_stage(stage, details)

    return details


def _stage_detail(title: str, summary: str, sections: list[dict]) -> dict:
    return {
        "title": title,
        "summary": summary,
        "sections": [
            section for section in sections
            if section.get("content") or section.get("kind") in {"web", "diff", "json"}
        ],
    }


def _text_section(label: str, content: str, kind: str = "text") -> dict:
    content = content or ""
    return {
        "label": label,
        "kind": kind,
        "content": content,
        "stats": _content_stats(content, is_mini=kind == "mini"),
    }


def _json_section(label: str, value) -> dict:
    return {
        "label": label,
        "kind": "json",
        "content": json.dumps(value or [], ensure_ascii=False, indent=2),
        "stats": [{"label": "entradas", "value": len(value or []) if isinstance(value, list) else len(value or {})}],
    }


def _diff_section(label: str, before: str, after: str, changes) -> dict:
    return {
        "label": label,
        "kind": "diff",
        "content": after or before or "",
        "before": before or "",
        "after": after or "",
        "changes": changes or [],
        "stats": [
            {"label": "antes", "value": f"{len(before or '')} chars"},
            {"label": "despues", "value": f"{len(after or '')} chars"},
            {"label": "cambios", "value": len(changes or [])},
        ],
    }


def _web_section(label: str, trace: dict) -> dict:
    web = (trace or {}).get("web", {})
    eduqg = (trace or {}).get("eduqg", {})
    queries = web.get("queries", [])
    configured = web.get("configured_sources", [])
    matches = eduqg.get("matches", [])
    return {
        "label": label,
        "kind": "web",
        "content": "web",
        "mode": (trace or {}).get("mode", ""),
        "search_provider": web.get("search_provider", ""),
        "academic_search": web.get("academic_search", {}),
        "query_generation": web.get("query_generation", {}),
        "queries": queries,
        "configured_sources": configured,
        "eduqg_matches": matches,
        "stats": [
            {"label": "queries", "value": len(queries)},
            {"label": "fuentes", "value": len(configured) + sum(len(q.get("results", [])) for q in queries)},
            {"label": "EduQG", "value": len(matches)},
        ],
    }


def _content_stats(content: str, is_mini: bool = False) -> list[dict]:
    stats = [
        {"label": "chars", "value": len(content or "")},
        {"label": "lineas", "value": len((content or "").splitlines())},
    ]
    if is_mini:
        stats.append({"label": "items", "value": _count_view_mini_items(content)})
    return stats


def _count_view_mini_items(content: str) -> int:
    try:
        return len(parse_mini(content or "").items)
    except Exception:
        return 0


def _detail_key_for_stage(stage: dict, details: dict) -> str:
    name = (stage.get("name") or "").lower()
    if "preparando contenido" in name:
        return "source" if "source" in details else ""
    if "transcribiendo audio" in name:
        return "transcript" if "transcript" in details else ""
    if "transcripcion" in name and "transcript_repair_0" in details:
        return "transcript_repair_0"
    if "generando items" in name or "mini parseado" in name or "relleno mini" in name:
        return "generation" if "generation" in details else ""
    if "coherencia" in name:
        return "coherence_0" if "coherence_0" in details else ("generation" if "generation" in details else "")
    if "verificando" in name or "verificacion" in name:
        return "verification" if "verification" in details else ""
    if "aplicando correcciones" in name:
        return "corrections" if "corrections" in details else ""
    if "final" in name or "listo" in name:
        return "final" if "final" in details else ""
    return ""


def _parse_pipeline_stages(job):
    """Parsea processing_log en lista de etapas estructuradas."""
    import re
    log_text = (job.processing_log or "").strip()
    if not log_text:
        return []

    # Patron: [HH:MM:SS] Etapa - Detalle
    # O: Etapa - Detalle (sin timestamp)
    pattern = re.compile(r"^(?:\[(\d{2}:\d{2}:\d{2})\]\s+)?(.+?)(?:\s+-\s+(.*))?$", re.MULTILINE)

    stages = []
    stage_map = {
        "en cola": {"icon": "queue", "type": "queue", "color": "#6c757d"},
        "preparando contenido": {"icon": "doc", "type": "prep", "color": "#495057"},
        "transcribiendo audio": {"icon": "mic", "type": "whisper", "color": "#0d6efd"},
        "audio temporal eliminado": {"icon": "trash", "type": "cleanup", "color": "#6c757d"},
        "corrigiendo transcripcion": {"icon": "brain", "type": "ai", "color": "#6610f2"},
        "transcripcion local revisada": {"icon": "check", "type": "success", "color": "#198754"},
        "transcripcion revisada": {"icon": "check", "type": "success", "color": "#198754"},
        "generando items": {"icon": "brain", "type": "ai", "color": "#6610f2"},
        "mini parseado": {"icon": "code", "type": "parse", "color": "#0dcaf0"},
        "recuperando items incoherentes": {"icon": "wrench", "type": "recovery", "color": "#fd7e14"},
        "recuperacion mini": {"icon": "check-wrench", "type": "recovery", "color": "#fd7e14"},
        "opciones no uniformes detectadas": {"icon": "alert", "type": "warning", "color": "#ffc107"},
        "opciones reparadas": {"icon": "wrench", "type": "recovery", "color": "#fd7e14"},
        "reparacion de opciones fallida": {"icon": "alert", "type": "error", "color": "#dc3545"},
        "revisando coherencia": {"icon": "brain", "type": "ai", "color": "#6610f2"},
        "coherencia mini revisada": {"icon": "check", "type": "success", "color": "#198754"},
        "relleno mini": {"icon": "plus", "type": "fill", "color": "#20c997"},
        "generando items de relleno": {"icon": "plus", "type": "fill", "color": "#20c997"},
        "verificando con fuentes": {"icon": "globe", "type": "verify", "color": "#0d6efd"},
        "verificacion recibida": {"icon": "check-globe", "type": "verify", "color": "#0d6efd"},
        "aplicando correcciones": {"icon": "pencil", "type": "correct", "color": "#6f42c1"},
        "mini final parseado": {"icon": "flag", "type": "done", "color": "#198754"},
        "listo": {"icon": "flag", "type": "done", "color": "#198754"},
        "error": {"icon": "alert", "type": "error", "color": "#dc3545"},
        "pipeline reiniciado": {"icon": "refresh", "type": "warning", "color": "#ffc107"},
    }

    for line in log_text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            timestamp = match.group(1) or ""
            stage_name = (match.group(2) or "").strip()
            detail = (match.group(3) or "").strip()
        else:
            timestamp = ""
            stage_name = line
            detail = ""

        # Buscar en stage_map (case-insensitive partial match)
        meta = {"icon": "circle", "type": "generic", "color": "#6c757d"}
        stage_lower = stage_name.lower()
        for key, value in stage_map.items():
            if key in stage_lower:
                meta = value
                break

        stages.append({
            "timestamp": timestamp,
            "name": stage_name,
            "detail": detail,
            "icon": meta["icon"],
            "type": meta["type"],
            "color": meta["color"],
        })

    return stages


def _extract_pipeline_metrics(job):
    """Extrae metricas clave del pipeline para el panel lateral."""
    metrics = {
        "word_count": len((job.source_text or job.transcript or "").split()),
        "target_items": max(50, len((job.source_text or job.transcript or "").split()) // 50),
        "final_items": 0,
        "recovered_items": 0,
        "web_sources": 0,
        "eduqg_matches": 0,
        "corrections_applied": 0,
        "backend": job.ai_backend or "auto",
        "verification_mode": job.get_verification_mode_display(),
        "duration_seconds": 0,
    }

    # Contar items finales
    mini_text = job.corrected_output or job.toon_output
    if mini_text:
        try:
            assessment = parse_mini(mini_text)
            metrics["final_items"] = len(assessment.items)
        except Exception:
            pass

    # Contar fuentes web
    verif_trace = job.verification_trace or {}
    web = verif_trace.get("web", {})
    metrics["web_sources"] = len(web.get("configured_sources", [])) + sum(
        len(q.get("results", [])) for q in web.get("queries", [])
    )
    metrics["eduqg_matches"] = len((verif_trace.get("eduqg") or {}).get("matches", []))

    # Contar correcciones aplicadas
    corr_trace = job.correction_trace or []
    metrics["corrections_applied"] = sum(1 for c in corr_trace if c.get("applied"))

    # Contar items recuperados de incoherentes
    # Estimacion: contar cuantos items tenia toon_output vs corrected_output
    if job.toon_output and job.corrected_output:
        try:
            toon_assessment = parse_mini(job.toon_output)
            corrected_assessment = parse_mini(job.corrected_output)
            # Si corrected tiene mas items, asumimos recuperacion
            if len(corrected_assessment.items) > len(toon_assessment.items):
                metrics["recovered_items"] = len(corrected_assessment.items) - len(toon_assessment.items)
        except Exception:
            pass

    # Duracion estimada desde created_at hasta updated_at
    if job.created_at and job.updated_at:
        metrics["duration_seconds"] = int((job.updated_at - job.created_at).total_seconds())

    return metrics
