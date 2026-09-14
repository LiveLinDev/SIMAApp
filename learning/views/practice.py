"""Practica adaptativa por curso, recomendaciones y refuerzo dirigido."""
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
def practice_start(request, pk):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    try:
        session = adaptive.start_practice(
            request.user,
            course,
            target_count=request.POST.get("target_count", 10),
            focus=request.POST.get("focus", "balanced"),
        )
    except adaptive.NoItemsError:
        messages.warning(request, "Este curso aún no tiene preguntas. Sube una clase para empezar.")
        return redirect("course_detail", pk=course.pk)
    return redirect("practice_session", pk=course.pk, session_id=session.pk)


@login_required
def practice_session(request, pk, session_id):
    course = get_object_or_404(Course, pk=pk, user=request.user)
    session = get_object_or_404(adaptive.PracticeSession, pk=session_id, course=course, user=request.user)
    return render(request, "learning/practice_session.html", adaptive.session_context(session, last_answer_id=request.GET.get("last")))


@login_required
def practice_answer(request, pk, session_id):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user)
    session = get_object_or_404(adaptive.PracticeSession, pk=session_id, course=course, user=request.user)
    answer = None
    if not session.is_complete:
        try:
            answer = adaptive.answer_question(session, int(request.POST.get("question_id", 0)), request.POST.get("option_id"))
        except (ValueError, adaptive.Question.DoesNotExist):
            messages.info(request, "Esa pregunta ya no está disponible. Sigue con la siguiente.")
    url = reverse("practice_session", args=[course.pk, session.pk])
    return redirect(f"{url}?last={answer.pk}" if answer else url)


@login_required
def recommendation_update(request, pk, rec_id):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user)
    rec = get_object_or_404(adaptive.Recommendation, pk=rec_id, course=course, user=request.user)
    try:
        adaptive.complete_recommendation(rec, request.POST.get("status", "completed"))
    except ValueError:
        raise Http404()
    return redirect("course_detail", pk=course.pk)


@login_required
def reinforcement_start(request, pk):
    if request.method != "POST":
        raise Http404()
    course = get_object_or_404(Course, pk=pk, user=request.user, is_archived=False)
    practice_session = None
    if request.POST.get("practice_session"):
        practice_session = adaptive.PracticeSession.objects.filter(
            pk=request.POST.get("practice_session"), user=request.user, course=course
        ).first()
    topics = [t.strip() for t in request.POST.getlist("topic") if t.strip()]
    try:
        job = adaptive_generation.create_reinforcement_job(
            request.user, course, practice_session=practice_session, topics=topics,
            requested_items=request.POST.get("items", adaptive_generation.DEFAULT_ITEMS),
        )
    except adaptive_generation.ReinforcementUnavailable as exc:
        messages.warning(request, str(exc))
        return redirect("course_detail", pk=course.pk)
    except RuntimeError as exc:  # cola llena
        messages.warning(request, str(exc))
        return redirect("course_detail", pk=course.pk)
    return redirect("reinforcement_detail", pk=course.pk, job_id=job.pk)


@login_required
def reinforcement_detail(request, pk, job_id):
    course = get_object_or_404(Course, pk=pk, user=request.user)
    job = get_object_or_404(adaptive.ReinforcementJob, pk=job_id, course=course, user=request.user)
    summaries = list(adaptive.Summary.objects.filter(pk__in=job.summary_ids or []))
    flashcards_url = ""
    if job.quiz_id and job.quiz.class_session_id and job.quiz.class_session.legacy_lesson_job_id:
        flashcards_url = reverse("flashcards", args=[job.quiz.class_session.legacy_lesson_job_id])
    return render(request, "learning/reinforcement_detail.html", {
        "course": course,
        "job": job,
        "summaries": summaries,
        "question_count": job.quiz.questions.count() if job.quiz_id else 0,
        "flashcards_url": flashcards_url,
    })
