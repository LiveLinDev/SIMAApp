"""
Motor adaptativo a nivel de curso.

Cierra el ciclo que convierte a SIMA en acompanante de estudio:

    banco del curso  ->  sesion de practica (CAT)  ->  perfil por tema y Bloom
        ^                                                       |
        +------  recomendaciones y refuerzo dirigido  <---------+

- El banco del curso se construye persistiendo los items MINI verificados de
  cada clase como Question/AnswerOption, de modo que todas las clases de un
  curso alimentan la misma practica.
- La sesion de practica usa IRT 3PL (cat.py) sobre ese banco, arranca desde la
  habilidad ya conocida del estudiante y evita repetir lo que ya acerto hace
  poco.
- Al terminar, el perfil adaptativo del curso se recalcula desde el historial
  completo (con peso a lo reciente), se generan recomendaciones concretas y se
  registra la actividad (XP y racha).
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .cat import BLOOM_LABELS, item_information, theta_to_level
from .psychometrics import bkt_trace, calibrate_difficulty, eap_estimate, quality_flag, randomesque
from .segments import attach_sources, format_timestamp
from .progress import progress_panel
from .summaries import course_summary_for
from .models import (
    days_until,
    AdaptiveProfile,
    AnswerOption,
    BloomLevel,
    Course,
    Difficulty,
    LessonJob,
    PracticeSession,
    Profile,
    Question,
    Quiz,
    Recommendation,
    ReinforcementJob,
    StudentAnswer,
    StudyActivity,
    StudyStreak,
    Summary,
    UserPreference,
)
from .credits import estimate_reinforcement_cost
from .spaced_repetition import due_count
from .parse_mini import check_option_uniformity, parse_header, parse_mini

THETA_MIN, THETA_MAX = -3.0, 3.0
SE_STOP = 0.30                 # error estandar para detener antes del objetivo
MIN_ITEMS_BEFORE_SE_STOP = 4
RECENT_CORRECT_DAYS = 3        # no repetir items acertados hace menos de N dias
WEAK_THRESHOLD = 0.60
STRONG_THRESHOLD = 0.85
MIN_ANSWERS_FOR_TOPIC = 2
MIN_ANSWERS_FOR_STRONG = 3
RECENCY_HALF_LIFE_DAYS = 14.0  # una respuesta de hace 14 dias pesa la mitad
KNOWN_SE = 2.0                 # por debajo de este SE el perfil ya "conoce" al estudiante
PRIOR_WEIGHT_KNOWN = 2.0
PRIOR_WEIGHT_UNKNOWN = 1.0
XP_SESSION_BASE = 10
XP_PER_CORRECT = 2
XP_RECOMMENDATION = 3
CALIBRATION_MIN = 3            # observaciones antes de usar la dificultad calibrada
RANDOMESQUE_K = 5              # candidatos entre los que se sortea el siguiente item
PRIOR_SD_UNKNOWN = 1.0         # prior N(0,1) cuando el curso aun no conoce al estudiante
PRIOR_SD_MIN = 0.5             # el prior nunca se vuelve mas estrecho que esto
HALF_LIFE_BASE_DAYS = 3.0      # vida media de la retencion tras un solo acierto
HALF_LIFE_GROWTH = 2.0         # cada acierto consecutivo la duplica (regresion de vida media simplificada)
HALF_LIFE_MAX_DAYS = 90.0
RISK_THRESHOLD = WEAK_THRESHOLD  # dominio efectivo (dominio x retencion) bajo esto = en riesgo de olvido
EXAM_DEFAULT_ITEMS = 15
EXAM_COUNTDOWN_DAYS = 10       # con examen a <= N dias, el plan propone simulacro
_rng = random.Random()

DIFFICULTY_FROM_INT = {1: Difficulty.LOW, 2: Difficulty.LOW, 3: Difficulty.MEDIUM, 4: Difficulty.HIGH, 5: Difficulty.HIGH}
VALID_BLOOM = {choice for choice, _ in BloomLevel.choices}


class NoItemsError(RuntimeError):
    """El curso no tiene items validos para practicar."""


# ---------------------------------------------------------------------------
# 1. Banco del curso
# ---------------------------------------------------------------------------
def lesson_mini(job: LessonJob) -> str:
    return (job.corrected_output or job.toon_output or "").strip()


def sync_question_bank(job: LessonJob) -> Quiz | None:
    """
    Persiste (o actualiza) los items MINI verificados de una clase como
    Question/AnswerOption dentro de un Quiz ligado a su ClassSession.
    Es idempotente: se puede llamar en cada cambio del MINI.
    """
    mini_text = lesson_mini(job)
    if not (job.course_id and mini_text):
        return None
    from .pipeline import _sync_class_session_status  # import perezoso: evita ciclo

    session = _sync_class_session_status(job)
    if session is None:
        return None

    assessment = parse_mini(mini_text)
    header = parse_header(assessment.header) if assessment.header else {}
    with transaction.atomic():
        quiz, _created = Quiz.objects.get_or_create(
            class_session=session,
            quiz_type=Quiz.QuizType.ADAPTIVE,
            defaults={"course": job.course, "title": job.title, "topic": session.main_topic},
        )
        quiz.course = job.course
        quiz.title = job.title
        quiz.topic = session.main_topic
        quiz.mini_source = mini_text
        quiz.cat_config = {key: header.get(key, "") for key in ("m", "cat", "bd")}
        quiz.save(update_fields=["course", "title", "topic", "mini_source", "cat_config", "updated_at"])

        persist_items(quiz, assessment.items, default_topic=session.main_topic or "")
    attach_sources(quiz, session, job)
    return quiz


PRACTICE_QUIZ_TYPES = (Quiz.QuizType.ADAPTIVE, Quiz.QuizType.REINFORCEMENT)


def persist_items(quiz: Quiz, items, default_topic: str = "", prune: bool = True) -> int:
    """
    Guarda items MINI como Question/AnswerOption dentro de `quiz`. Idempotente:
    actualiza los existentes por external_id, crea los nuevos y (si prune) borra
    los que desaparecieron y nadie respondio. Devuelve cuantos quedaron.
    """
    existing = {q.external_id: q for q in quiz.questions.all().prefetch_related("options")}
    kept_ids: set[int] = set()
    for order, item in enumerate(items):
        if len(item.options) != 4 or check_option_uniformity(item):
            continue  # misma regla que build_bank(): 4 alternativas y calidad semantica
        fields = {
            "bloom_level": item.bloom if item.bloom in VALID_BLOOM else BloomLevel.REMEMBER,
            "topic": (item.topic or default_topic or "")[:180],
            "prompt": item.statement,
            "difficulty": DIFFICULTY_FROM_INT.get(int(item.difficulty or 3), Difficulty.MEDIUM),
            "irt_a": float(item.irt_a),
            "irt_b": float(item.irt_b),
            "irt_c": float(item.irt_c),
            "order": order,
        }
        question = existing.get(item.id)
        if question is None:
            question = Question.objects.create(quiz=quiz, external_id=item.id, **fields)
        else:
            dirty = [name for name, value in fields.items() if getattr(question, name) != value]
            if dirty:
                for name in dirty:
                    setattr(question, name, fields[name])
                question.save(update_fields=dirty)
        kept_ids.add(question.pk)

        desired = [(opt["text"], bool(opt.get("correct"))) for opt in item.options]
        current = [(opt.text, opt.is_correct) for opt in question.options.all()]
        if current != desired:
            question.options.all().delete()
            AnswerOption.objects.bulk_create(
                [AnswerOption(question=question, text=text, is_correct=correct, order=i) for i, (text, correct) in enumerate(desired)]
            )
    if prune:
        quiz.questions.exclude(pk__in=kept_ids).filter(student_answers__isnull=True).delete()
    return len(kept_ids)


def sync_course_bank(course: Course) -> int:
    """Asegura que todas las clases listas del curso tengan su banco persistido y al dia."""
    synced = 0
    jobs = LessonJob.objects.filter(course=course).exclude(corrected_output="", toon_output="")
    for job in jobs:
        mini_text = lesson_mini(job)
        quiz = Quiz.objects.filter(class_session__legacy_lesson_job=job, quiz_type=Quiz.QuizType.ADAPTIVE).first()
        if quiz is None or quiz.mini_source != mini_text:
            if sync_question_bank(job) is not None:
                synced += 1
    return synced


@dataclass
class BankItem:
    """Vista ligera de una Question compatible con las funciones de cat.py."""
    id: str
    question_id: int
    bloom: str
    topic: str
    irt_a: float
    irt_b: float
    irt_c: float
    prompt: str
    demand: str = "medium"
    exposure_cap: float = 0.2
    attempts: int = 0
    calibrated: bool = False
    options: list = field(default_factory=list)

    @property
    def correct_option(self):
        return next((opt for opt in self.options if opt.is_correct), None)


def load_bank(course: Course, lesson: LessonJob | None = None) -> list[BankItem]:
    """Banco practicable del curso; con `lesson`, solo los items de esa clase."""
    questions = Question.objects.filter(quiz__course=course, quiz__quiz_type__in=PRACTICE_QUIZ_TYPES)
    if lesson is not None:
        questions = questions.filter(quiz__class_session__legacy_lesson_job=lesson)
    questions = (
        questions
        .select_related("quiz")
        .prefetch_related("options")
        .order_by("quiz_id", "order", "id")
    )
    bank: list[BankItem] = []
    for question in questions:
        options = list(question.options.all())
        if len(options) < 2 or not any(opt.is_correct for opt in options):
            continue
        if question.quality_flag:
            continue  # puerta de calidad: clave dudosa o item trivial
        calibrated = question.b_calibrated is not None and question.calibration_count >= CALIBRATION_MIN
        bank.append(
            BankItem(
                id=str(question.pk),
                question_id=question.pk,
                bloom=question.bloom_level,
                topic=question.topic,
                irt_a=question.irt_a,
                irt_b=question.b_calibrated if calibrated else question.irt_b,
                irt_c=question.irt_c,
                prompt=question.prompt,
                demand={"low": "low", "high": "high"}.get(question.difficulty, "medium"),
                attempts=question.attempts,
                calibrated=calibrated,
                options=options,
            )
        )
    return bank


# ---------------------------------------------------------------------------
# 2. Perfil adaptativo por curso
# ---------------------------------------------------------------------------
def get_profile(user, course: Course) -> AdaptiveProfile:
    profile, _ = AdaptiveProfile.objects.get_or_create(user=user, course=course)
    return profile


def profile_is_known(profile: AdaptiveProfile) -> bool:
    return profile.standard_error < KNOWN_SE


def _recency_weight(answered_at) -> float:
    age_days = max((timezone.now() - answered_at).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def update_profile(user, course: Course, session: PracticeSession | None = None) -> AdaptiveProfile:
    """
    Recalcula el perfil del curso desde el historial completo.

    - Dominio por tema y por nivel Bloom: Bayesian Knowledge Tracing sobre la
      secuencia cronologica de respuestas (probabilidad de dominio), mas la
      precision reciente como dato de apoyo.
    - theta / error estandar: la media y desviacion posterior (EAP) de la
      ultima sesion completada, que ya integra el prior del perfil.
    """
    profile = get_profile(user, course)
    answers = list(
        StudentAnswer.objects.filter(user=user, course=course)
        .select_related("question")
        .order_by("answered_at")[:600]
    )
    topic_seq: dict[str, list[bool]] = defaultdict(list)
    bloom_seq: dict[str, list[bool]] = defaultdict(list)
    topic_acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    bloom_acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for answer in answers:
        topic = answer.question.topic or "General"
        level = answer.question.bloom_level
        topic_seq[topic].append(answer.is_correct)
        bloom_seq[level].append(answer.is_correct)
        weight = _recency_weight(answer.answered_at)
        for bucket, key in ((topic_acc, topic), (bloom_acc, level)):
            bucket[key][0] += weight * (1.0 if answer.is_correct else 0.0)
            bucket[key][1] += weight

    last_seen: dict[str, object] = {}
    for answer in answers:
        last_seen[answer.question.topic or "General"] = answer.answered_at

    def _summary(seq: dict, acc: dict, labels: bool = False, with_forgetting: bool = False) -> dict:
        out = {}
        for key, outcomes in seq.items():
            entry = {
                "mastery": bkt_trace(outcomes),
                "accuracy": round(acc[key][0] / acc[key][1], 3) if acc[key][1] > 0 else 0.0,
                "answers": len(outcomes),
            }
            if labels:
                entry["label"] = BLOOM_LABELS.get(key, key)
            if with_forgetting:
                entry["half_life_days"] = half_life_days(outcomes)
                entry["last_answered"] = last_seen[key].isoformat() if key in last_seen else None
            out[key] = entry
        return out

    mastery_by_topic = _summary(topic_seq, topic_acc, with_forgetting=True)
    bloom_mastery = _summary(bloom_seq, bloom_acc, labels=True)
    weak = sorted(
        (t for t, v in mastery_by_topic.items() if v["answers"] >= MIN_ANSWERS_FOR_TOPIC and v["mastery"] < WEAK_THRESHOLD),
        key=lambda t: mastery_by_topic[t]["mastery"],
    )
    strong = sorted(
        (t for t, v in mastery_by_topic.items() if v["answers"] >= MIN_ANSWERS_FOR_STRONG and v["mastery"] >= STRONG_THRESHOLD),
        key=lambda t: -mastery_by_topic[t]["mastery"],
    )

    if session is not None and session.is_complete:
        profile.theta = round(session.theta, 3)
        profile.standard_error = round(session.standard_error, 3)

    profile.mastery_by_topic = mastery_by_topic
    profile.bloom_mastery = bloom_mastery
    profile.weak_topics = weak
    profile.strong_topics = strong
    if profile.theta < -0.7:
        profile.recommended_difficulty = Difficulty.LOW
    elif profile.theta > 0.7:
        profile.recommended_difficulty = Difficulty.HIGH
    else:
        profile.recommended_difficulty = Difficulty.MEDIUM
    profile.last_activity_at = timezone.now()
    profile.save()
    return profile


# ---------------------------------------------------------------------------
# 3. Sesion de practica (CAT sobre el banco del curso)
# ---------------------------------------------------------------------------
@dataclass
class _Response:
    item_id: str
    is_correct: bool
    item_bloom: str
    topic: str


def half_life_days(outcomes: list[bool]) -> float:
    """
    Vida media de la retencion de un tema (regresion de vida media simplificada,
    Settles & Meeder 2016): parte de HALF_LIFE_BASE_DAYS y se duplica con cada
    acierto consecutivo al final de la secuencia; un fallo la devuelve a la base.
    """
    streak = 0
    for ok in reversed(outcomes):
        if not ok:
            break
        streak += 1
    if streak == 0:
        return HALF_LIFE_BASE_DAYS
    return min(HALF_LIFE_MAX_DAYS, HALF_LIFE_BASE_DAYS * HALF_LIFE_GROWTH ** (streak - 1))


def topic_retention(entry: dict, now=None) -> float:
    """Fraccion de lo aprendido que se conserva hoy: 2^(-dias / vida media)."""
    last = entry.get("last_answered")
    if not last:
        return 1.0
    now = now or timezone.now()
    try:
        last_dt = timezone.datetime.fromisoformat(last)
    except (TypeError, ValueError):
        return 1.0
    if timezone.is_naive(last_dt):
        last_dt = timezone.make_aware(last_dt)
    days = max(0.0, (now - last_dt).total_seconds() / 86400.0)
    half_life = float(entry.get("half_life_days") or HALF_LIFE_BASE_DAYS)
    return 0.5 ** (days / max(half_life, 0.1))


def at_risk_topics(profile: AdaptiveProfile | None, now=None) -> list[dict]:
    """
    Temas que se dominaban pero cuya retencion estimada ya cayo bajo el umbral:
    conviene repasarlos antes de que haya que reaprenderlos.
    """
    if profile is None:
        return []
    rows = []
    for topic, entry in (profile.mastery_by_topic or {}).items():
        if entry.get("answers", 0) < MIN_ANSWERS_FOR_TOPIC or entry.get("mastery", 0.0) < WEAK_THRESHOLD:
            continue
        retention = topic_retention(entry, now)
        effective = entry["mastery"] * retention
        if effective < RISK_THRESHOLD:
            rows.append({"topic": topic, "mastery": round(entry["mastery"], 3), "retention": round(retention, 3),
                         "effective": round(effective, 3), "half_life_days": entry.get("half_life_days")})
    rows.sort(key=lambda r: r["effective"])
    return rows


def _session_responses(session: PracticeSession) -> list[_Response]:
    answers = session.answers.select_related("question").order_by("answered_at")
    return [
        _Response(item_id=str(a.question_id), is_correct=a.is_correct, item_bloom=a.question.bloom_level, topic=a.question.topic)
        for a in answers
    ]


def _recently_correct_ids(user, course: Course) -> set[int]:
    since = timezone.now() - timedelta(days=RECENT_CORRECT_DAYS)
    return set(
        StudentAnswer.objects.filter(user=user, course=course, is_correct=True, answered_at__gte=since)
        .values_list("question_id", flat=True)
    )


def select_next_item(session: PracticeSession, bank: list[BankItem], responses: list[_Response], profile: AdaptiveProfile) -> BankItem | None:
    """
    Maxima informacion de Fisher en theta actual, con tres correcciones propias
    del acompanamiento: no repetir lo acertado hace poco, equilibrar niveles
    Bloom y empujar hacia temas debiles o nunca evaluados.
    """
    served = set(session.served_question_ids or [])
    candidates = [item for item in bank if item.question_id not in served]
    if not candidates:
        return None
    exam = session.focus == PracticeSession.Focus.EXAM
    if not exam:
        fresh = [item for item in candidates if item.question_id not in _recently_correct_ids(session.user, session.course)]
        if len(fresh) >= 3:
            candidates = fresh
    if session.focus == PracticeSession.Focus.WEAK and profile.weak_topics:
        weak_only = [item for item in candidates if item.topic in profile.weak_topics]
        if len(weak_only) >= 2:
            candidates = weak_only
    if session.focus == PracticeSession.Focus.RISK:
        risky = {row["topic"] for row in at_risk_topics(profile)}
        risk_only = [item for item in candidates if item.topic in risky]
        if len(risk_only) >= 2:
            candidates = risk_only

    theta = session.theta
    mastery = profile.mastery_by_topic or {}
    answered_bloom = Counter(r.item_bloom for r in responses)
    bank_bloom = Counter(item.bloom for item in bank)
    total = max(len(bank), 1)

    answered_topic = Counter(r.topic for r in responses)
    bank_topic = Counter(item.topic for item in bank)

    def score(item: BankItem) -> float:
        information = item_information(item, theta)
        expected_share = bank_bloom[item.bloom] / total
        current_share = answered_bloom[item.bloom] / max(len(responses), 1)
        bloom_bonus = max(expected_share - current_share, 0.0) * 0.35
        if exam:
            # Simulacro: cobertura proporcional de temas, sin sesgo hacia lo debil.
            topic_expected = bank_topic[item.topic] / total
            topic_current = answered_topic[item.topic] / max(len(responses), 1)
            return information + bloom_bonus + max(topic_expected - topic_current, 0.0) * 0.6
        topic_info = mastery.get(item.topic)
        if topic_info is None:
            topic_bonus = 0.15  # tema nunca evaluado: conviene medirlo
        elif topic_info["mastery"] < WEAK_THRESHOLD:
            topic_bonus = (WEAK_THRESHOLD - topic_info["mastery"]) * 0.5
        else:
            topic_bonus = 0.0
        return information + bloom_bonus + topic_bonus

    # Kingsbury-Zara: sortear entre los k mas informativos evita sobreexponer
    # siempre el mismo item a estudiantes con el mismo nivel.
    return randomesque(candidates, score, k=RANDOMESQUE_K, rng=_rng)


def start_practice(
    user, course: Course, target_count: int = 10, focus: str = PracticeSession.Focus.BALANCED, lesson: LessonJob | None = None
) -> PracticeSession:
    sync_course_bank(course)
    bank = load_bank(course, lesson)
    if not bank:
        raise NoItemsError(
            "Esta clase aun no tiene items validos para practicar." if lesson else "El curso aun no tiene items validos para practicar."
        )
    profile = get_profile(user, course)
    known = profile_is_known(profile)
    theta_start = profile.theta if known else 0.0
    prior_sd = max(PRIOR_SD_MIN, min(profile.standard_error, PRIOR_SD_UNKNOWN)) if known else PRIOR_SD_UNKNOWN
    focus = focus if focus in PracticeSession.Focus.values else PracticeSession.Focus.BALANCED
    if focus == PracticeSession.Focus.WEAK and not profile.weak_topics:
        focus = PracticeSession.Focus.BALANCED
    if focus == PracticeSession.Focus.RISK and not at_risk_topics(profile):
        focus = PracticeSession.Focus.BALANCED
    try:
        target = int(target_count)
    except (TypeError, ValueError):
        target = EXAM_DEFAULT_ITEMS if focus == PracticeSession.Focus.EXAM else 10
    target = max(3, min(target, len(bank), 30 if focus == PracticeSession.Focus.EXAM else 25))

    session = PracticeSession.objects.create(
        user=user,
        course=course,
        lesson=lesson,
        focus=focus,
        target_count=target,
        theta_start=theta_start,
        prior_sd=prior_sd,
        theta=theta_start,
        standard_error=prior_sd,
    )
    first = select_next_item(session, bank, [], profile)
    session.current_question_id = first.question_id
    session.served_question_ids = [first.question_id]
    session.save(update_fields=["current_question", "served_question_ids", "updated_at"])
    return session


def answer_question(session: PracticeSession, question_id: int, option_id) -> StudentAnswer:
    if session.is_complete:
        raise ValueError("La sesion ya termino.")
    if session.current_question_id != int(question_id):
        raise ValueError("La pregunta enviada no es la pregunta actual de la sesion.")
    question = Question.objects.select_related("quiz").prefetch_related("options").get(pk=question_id, quiz__course=session.course)
    try:
        option = question.options.get(pk=int(option_id))
    except (AnswerOption.DoesNotExist, TypeError, ValueError):
        option = None
    is_correct = bool(option and option.is_correct)

    answer = StudentAnswer.objects.create(
        user=session.user,
        course=session.course,
        quiz=question.quiz,
        question=question,
        selected_option=option,
        is_correct=is_correct,
        theta_before=session.theta,
        practice_session=session,
    )

    bank = load_bank(session.course, session.lesson)
    by_id = {item.id: item for item in bank}
    responses = _session_responses(session)
    theta, se = eap_estimate(by_id, responses, prior_mean=session.theta_start, prior_sd=session.prior_sd)
    answer.theta_after = theta
    answer.save(update_fields=["theta_after"])
    _update_item_statistics(question, theta_before=session.theta, is_correct=is_correct)

    session.theta = theta
    session.standard_error = se
    session.correct_count = sum(1 for r in responses if r.is_correct)
    answered = len(responses)
    exhausted = answered >= len(bank)
    # Un simulacro tiene longitud fija: no se detiene antes por precision.
    precise = session.focus != PracticeSession.Focus.EXAM and answered >= MIN_ITEMS_BEFORE_SE_STOP and se <= SE_STOP
    if answered >= session.target_count or precise or exhausted:
        finish_session(session, bank)
        return answer

    profile = get_profile(session.user, session.course)
    nxt = select_next_item(session, bank, responses, profile)
    if nxt is None:
        finish_session(session, bank)
        return answer
    session.current_question_id = nxt.question_id
    session.served_question_ids = [*session.served_question_ids, nxt.question_id]
    session.save(update_fields=["theta", "standard_error", "correct_count", "current_question", "served_question_ids", "updated_at"])
    return answer


def _update_item_statistics(question: Question, theta_before: float, is_correct: bool):
    """Exposicion, calibracion Elo de la dificultad y puerta de calidad del item."""
    question.attempts += 1
    question.correct_count += 1 if is_correct else 0
    b_now = question.b_calibrated if question.b_calibrated is not None else question.irt_b
    question.b_calibrated = calibrate_difficulty(
        b_now, question.calibration_count, theta_before, question.irt_a, question.irt_c, is_correct
    )
    question.calibration_count += 1
    question.quality_flag = quality_flag(question.attempts, question.correct_count)
    question.save(update_fields=["attempts", "correct_count", "b_calibrated", "calibration_count", "quality_flag"])


# ---------------------------------------------------------------------------
# 4. Cierre: retroalimentacion, perfil, recomendaciones y actividad
# ---------------------------------------------------------------------------
def finish_session(session: PracticeSession, bank: list[BankItem] | None = None) -> dict:
    if session.is_complete:
        return session.feedback
    bank = bank if bank is not None else load_bank(session.course, session.lesson)
    by_id = {item.question_id: item for item in bank}
    answers = list(session.answers.select_related("question", "selected_option").order_by("answered_at"))

    per_topic: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_bloom: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    failed = []
    for answer in answers:
        topic = answer.question.topic or "General"
        per_topic[topic][1] += 1
        per_bloom[answer.question.bloom_level][1] += 1
        if answer.is_correct:
            per_topic[topic][0] += 1
            per_bloom[answer.question.bloom_level][0] += 1
        else:
            item = by_id.get(answer.question_id)
            correct = item.correct_option if item else None
            failed.append({
                "question_id": answer.question_id,
                "prompt": answer.question.prompt,
                "topic": topic,
                "bloom": answer.question.bloom_level,
                "bloom_label": BLOOM_LABELS.get(answer.question.bloom_level, answer.question.bloom_level),
                "chosen": answer.selected_option.text if answer.selected_option else "(sin respuesta)",
                "correct": correct.text if correct else "",
                "excerpt": answer.question.source_excerpt,
                "timestamp": answer.question.source_timestamp_seconds,
                "timestamp_label": format_timestamp(answer.question.source_timestamp_seconds),
            })

    total = len(answers)
    correct_count = sum(1 for a in answers if a.is_correct)
    level_value, level_label = theta_to_level(session.theta)
    start_value, start_label = theta_to_level(session.theta_start)
    topics = sorted(
        ({"topic": t, "correct": c, "total": n, "pct": round(100 * c / n) if n else 0} for t, (c, n) in per_topic.items()),
        key=lambda row: (row["pct"], -row["total"]),
    )
    blooms = [
        {"level": lvl, "label": BLOOM_LABELS.get(lvl, lvl), "correct": c, "total": n, "pct": round(100 * c / n) if n else 0}
        for lvl, (c, n) in sorted(per_bloom.items())
    ]

    session.completed_at = timezone.now()
    session.current_question = None
    session.correct_count = correct_count
    session.save(update_fields=["completed_at", "current_question", "correct_count", "theta", "standard_error", "updated_at"])

    profile = update_profile(session.user, session.course, session)
    recommendations = refresh_recommendations(session.user, session.course, profile, topics)
    xp = XP_SESSION_BASE + XP_PER_CORRECT * correct_count
    register_activity(
        session.user,
        session.course,
        StudyActivity.ActivityType.QUIZ_COMPLETED,
        xp=xp,
        metadata={"practice_session": session.pk, "theta": session.theta, "accuracy": round(100 * correct_count / total) if total else 0},
    )

    feedback = {
        "total": total,
        "correct": correct_count,
        "accuracy": round(100 * correct_count / total) if total else 0,
        "theta_start": session.theta_start,
        "theta_end": session.theta,
        "standard_error": session.standard_error,
        "level_value": level_value,
        "level_label": level_label,
        "start_level_label": start_label,
        "level_delta": level_value - start_value,
        "xp": xp,
        "topics": topics,
        "blooms": blooms,
        "failed": failed,
        "weak_topics": profile.weak_topics,
        "strong_topics": profile.strong_topics,
        "recommendations": [{"id": r.pk, "title": r.title, "message": r.message} for r in recommendations],
        "focus": session.focus,
        "is_exam": session.focus == PracticeSession.Focus.EXAM,
        "grade": round(20 * correct_count / total, 1) if total else 0.0,  # escala vigesimal (Peru)
    }
    session.feedback = feedback
    session.save(update_fields=["feedback", "updated_at"])
    return feedback


def refresh_recommendations(user, course: Course, profile: AdaptiveProfile, session_topics: list[dict] | None = None) -> list[Recommendation]:
    """Recomendaciones basadas en reglas; deduplica por titulo y cierra las que ya no aplican."""
    mastery = profile.mastery_by_topic or {}
    pending = Recommendation.objects.filter(user=user, course=course, status=Recommendation.Status.PENDING)

    # cerrar refuerzos de temas que dejaron de ser debiles
    for rec in pending.filter(title__startswith="Refuerza"):
        topic = rec.title.split("«", 1)[-1].rstrip("»").strip()
        info = mastery.get(topic)
        if info and info["mastery"] >= WEAK_THRESHOLD:
            rec.status = Recommendation.Status.COMPLETED
            rec.save(update_fields=["status", "updated_at"])

    wanted: list[tuple[str, str, str, int]] = []
    for topic in profile.weak_topics[:2]:
        pct = round(100 * mastery[topic]["mastery"])
        wanted.append((
            f"Refuerza «{topic}»",
            f"Llevas {pct}% de aciertos en este tema. Repasa sus flashcards y practica en modo refuerzo.",
            "tema debil",
            1,
        ))
    if profile.standard_error > 0.6:
        wanted.append((
            "Haz otra sesion de practica",
            "Tu nivel aun se estima con poca precision; una sesion mas afina la seleccion de preguntas.",
            "error estandar alto",
            2,
        ))
    if not profile.weak_topics and session_topics and all(row["pct"] >= 85 for row in session_topics):
        wanted.append((
            "Sube el nivel",
            "Dominas lo evaluado hasta ahora. Sube una clase nueva o practica con mas preguntas por sesion.",
            "sesion sobresaliente",
            3,
        ))

    created: list[Recommendation] = []
    existing_titles = set(pending.values_list("title", flat=True))
    for title, message, reason, priority in wanted:
        if title in existing_titles:
            continue
        created.append(Recommendation.objects.create(
            user=user, course=course, title=title, message=message, reason=reason, priority=priority,
            due_at=timezone.now() + timedelta(days=2),
        ))
    return created


def register_activity(user, course: Course, activity_type: str, xp: int = 0, study_seconds: int = 0, metadata: dict | None = None):
    """Registra la actividad y actualiza XP y racha (en Profile y StudyStreak)."""
    StudyActivity.objects.create(
        user=user, course=course, activity_type=activity_type, xp_awarded=xp, study_seconds=study_seconds, metadata=metadata or {}
    )
    today = timezone.localdate()
    profile, _ = Profile.objects.get_or_create(user=user)
    if profile.last_study_date != today:
        if profile.last_study_date == today - timedelta(days=1):
            profile.current_streak += 1
        else:
            profile.current_streak = 1
        profile.longest_streak = max(profile.longest_streak, profile.current_streak)
        profile.last_study_date = today
    profile.total_xp += xp
    profile.save(update_fields=["current_streak", "longest_streak", "last_study_date", "total_xp", "updated_at"])

    streak, _ = StudyStreak.objects.get_or_create(user=user)
    streak.current_count = profile.current_streak
    streak.longest_count = profile.longest_streak
    streak.last_activity_date = profile.last_study_date
    streak.save(update_fields=["current_count", "longest_count", "last_activity_date", "updated_at"])
    return profile


def complete_recommendation(rec: Recommendation, status: str):
    if status not in Recommendation.Status.values:
        raise ValueError(status)
    rec.status = status
    rec.save(update_fields=["status", "updated_at"])
    if status == Recommendation.Status.COMPLETED:
        register_activity(rec.user, rec.course, StudyActivity.ActivityType.RECOMMENDATION_DONE, xp=XP_RECOMMENDATION, metadata={"recommendation": rec.pk})


# ---------------------------------------------------------------------------
# 5. Vistas de solo lectura para curso y dashboard
# ---------------------------------------------------------------------------
def course_overview(user, course: Course) -> dict:
    profile = AdaptiveProfile.objects.filter(user=user, course=course).first()
    bank_size = Question.objects.filter(quiz__course=course, quiz__quiz_type__in=PRACTICE_QUIZ_TYPES).count()
    pending_bank = LessonJob.objects.filter(course=course).exclude(corrected_output="", toon_output="").exclude(
        class_session__quizzes__quiz_type=Quiz.QuizType.ADAPTIVE
    ).count()
    sessions = PracticeSession.objects.filter(user=user, course=course, completed_at__isnull=False)
    last = sessions.first()
    known = bool(profile and profile_is_known(profile))
    level_value, level_label = theta_to_level(profile.theta) if known else (None, "Sin evaluar")
    mastery_rows = []
    if profile:
        mastery_rows = sorted(
            ({"topic": t, "pct": round(100 * v["mastery"]), "answers": v["answers"]} for t, v in (profile.mastery_by_topic or {}).items()),
            key=lambda row: row["pct"],
        )
    return {
        "profile": profile,
        "known": known,
        "level_value": level_value,
        "level_label": level_label,
        "bank_size": bank_size + 0,
        "bank_pending_classes": pending_bank,
        "sessions_count": sessions.count(),
        "last_session": last,
        "answered_total": StudentAnswer.objects.filter(user=user, course=course).count(),
        "weak_topics": profile.weak_topics if profile else [],
        "strong_topics": profile.strong_topics if profile else [],
        "mastery_rows": mastery_rows,
        "recommendations": list(
            Recommendation.objects.filter(user=user, course=course, status=Recommendation.Status.PENDING)[:4]
        ),
        "reinforcements": list(ReinforcementJob.objects.filter(user=user, course=course)[:3]),
        "plan": daily_plan(user, course),
        "due_cards": due_count(course),
        "suspect_questions": list(Question.objects.filter(quiz__course=course, quality_flag="suspect")[:5]),
        "calibrated_count": Question.objects.filter(quiz__course=course, calibration_count__gte=CALIBRATION_MIN).count(),
        "concepts": list(Summary.objects.filter(course=course, kind=Summary.Kind.CONCEPT)[:5]),
        "reinforcement_cost": estimate_reinforcement_cost("auto").amount,
        "course_summary": course_summary_for(course),
        "at_risk_topics": at_risk_topics(profile),
        "exam_days_left": days_until(course.exam_date),
        "exam_items": min(EXAM_DEFAULT_ITEMS, bank_size) if bank_size else 0,
        "class_summary_count": Summary.objects.filter(course=course, kind=Summary.Kind.STRUCTURED).count(),
        "progress": progress_panel(user, course),
    }


def dashboard_today(user) -> dict:
    profile, _ = Profile.objects.get_or_create(user=user)
    courses = Course.objects.filter(user=user, is_archived=False)
    rows = []
    for course in courses:
        adaptive = AdaptiveProfile.objects.filter(user=user, course=course).first()
        bank = Question.objects.filter(quiz__course=course, quiz__quiz_type__in=PRACTICE_QUIZ_TYPES).count()
        ready_classes = LessonJob.objects.filter(course=course).exclude(corrected_output="", toon_output="").count()
        recs = list(Recommendation.objects.filter(user=user, course=course, status=Recommendation.Status.PENDING)[:2])
        known = bool(adaptive and profile_is_known(adaptive))
        if recs:
            next_action = recs[0].title
        elif bank or ready_classes:
            next_action = "Practica adaptativa" if not known else "Sigue practicando"
        else:
            next_action = "Sube una clase para empezar"
        plan = daily_plan(user, course)
        rows.append({
            "course": course,
            "level_label": theta_to_level(adaptive.theta)[1] if known else "Sin evaluar",
            "weak_topics": adaptive.weak_topics[:2] if adaptive else [],
            "recommendations": recs,
            "can_practice": bool(bank or ready_classes),
            "next_action": plan[0]["title"] if plan else next_action,
            "plan": plan[:3],
            "due_cards": due_count(course),
        })
    studied_today = profile.last_study_date == timezone.localdate()
    return {
        "streak": profile.current_streak,
        "studied_today": studied_today,
        "pending_recommendations": Recommendation.objects.filter(user=user, status=Recommendation.Status.PENDING).count(),
        "due_cards_total": sum(row["due_cards"] for row in rows),
        "progress": today_progress(user),
        "courses": rows,
    }


def last_answer_feedback(session: PracticeSession, answer_id) -> dict | None:
    """Retroalimentacion inmediata de la ultima respuesta de la sesion."""
    try:
        answer = (
            session.answers.select_related("question", "selected_option")
            .prefetch_related("question__options")
            .get(pk=int(answer_id))
        )
    except (StudentAnswer.DoesNotExist, TypeError, ValueError):
        return None
    latest = session.answers.order_by("-answered_at", "-id").first()
    if latest is None or latest.pk != answer.pk:
        return None
    question = answer.question
    correct = next((o for o in question.options.all() if o.is_correct), None)
    explanation = question.explanation
    if not explanation:
        for summary in Summary.objects.filter(course=session.course, kind=Summary.Kind.CONCEPT).order_by("-created_at")[:60]:
            concepts = summary.key_concepts or []
            if question.topic and question.topic in concepts:
                explanation = summary.content
                break
    return {
        "is_correct": answer.is_correct,
        "prompt": question.prompt,
        "topic": question.topic,
        "chosen": answer.selected_option.text if answer.selected_option else "(sin respuesta)",
        "correct": correct.text if correct else "",
        "explanation": explanation,
        "excerpt": question.source_excerpt,
        "timestamp_label": format_timestamp(question.source_timestamp_seconds),
        "theta_after": answer.theta_after,
    }


def session_context(session: PracticeSession, last_answer_id=None) -> dict:
    """Contexto para la plantilla de practica: pregunta actual o retroalimentacion."""
    question = None
    options = []
    if not session.is_complete and session.current_question_id:
        question = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
        options = list(question.options.all())
    answered = session.answers.count()
    level_value, level_label = theta_to_level(session.theta)
    last = last_answer_feedback(session, last_answer_id) if last_answer_id else None
    return {
        "session": session,
        "course": session.course,
        "question": question,
        "options": options,
        "answered": answered,
        "progress_pct": min(100, round(100 * answered / max(session.target_count, 1))),
        "level_value": level_value,
        "level_label": level_label,
        "bloom_label": BLOOM_LABELS.get(question.bloom_level, question.bloom_level) if question else "",
        "feedback": session.feedback if session.is_complete else None,
        "reinforcement_cost": estimate_reinforcement_cost("auto").amount,
        "lesson": session.lesson,
        "last": last,
    }


# ---------------------------------------------------------------------------
# 6. Ritmo: plan diario y progreso de la meta
# ---------------------------------------------------------------------------
PLAN_MAX_ACTIONS = 4
MAINTENANCE_DAYS = 2           # sin practicar N dias -> sesion de mantenimiento
REINFORCEMENT_FRESH_DAYS = 7   # un refuerzo generado hace menos de N dias se considera vigente


def _post_action(kind, title, detail, url, fields, priority, **extra):
    return {"kind": kind, "title": title, "detail": detail, "post": url, "fields": fields, "priority": priority, **extra}


def _link_action(kind, title, detail, href, priority, **extra):
    return {"kind": kind, "title": title, "detail": detail, "href": href, "priority": priority, **extra}


def daily_plan(user, course: Course) -> list[dict]:
    """
    La ruta de estudio del documento de vision convertida en reglas sobre el
    perfil: repasar lo vencido -> reforzar lo debil -> revisar fallos -> practicar
    -> avanzar. Devuelve como maximo PLAN_MAX_ACTIONS acciones ordenadas.
    """
    from .spaced_repetition import due_count as _due

    now = timezone.now()
    actions: list[dict] = []
    profile = AdaptiveProfile.objects.filter(user=user, course=course).first()
    known = bool(profile and profile_is_known(profile))
    bank = Question.objects.filter(quiz__course=course, quiz__quiz_type__in=PRACTICE_QUIZ_TYPES).exists()
    ready_jobs = list(LessonJob.objects.filter(course=course).exclude(corrected_output="", toon_output=""))
    practice_url = reverse("practice_start", args=[course.pk])

    due = _due(course, now)
    if due:
        actions.append(_link_action(
            "review", f"Repasa {due} tarjeta{'s' if due != 1 else ''}", "vencidas o nuevas en tu cola de repaso",
            reverse("course_review", args=[course.pk]), 1, count=due,
        ))

    if not (bank or ready_jobs):
        actions.append(_link_action("upload", "Sube tu primera clase", "el banco de preguntas se llena con cada clase lista",
                                    reverse("api_lesson") + f"?course={course.pk}", 5))
        return actions[:PLAN_MAX_ACTIONS]

    if not known:
        actions.append(_post_action("practice", "Práctica inicial", "5 preguntas para estimar tu nivel en este curso",
                                    practice_url, {"target_count": 5, "focus": "balanced"}, 2))
        return actions[:PLAN_MAX_ACTIONS]

    days_left = days_until(course.exam_date)
    if days_left is not None and 0 <= days_left <= EXAM_COUNTDOWN_DAYS and bank:
        bank_size = Question.objects.filter(quiz__course=course, quiz__quiz_type__in=PRACTICE_QUIZ_TYPES, quality_flag="").count()
        when = "hoy" if days_left == 0 else ("manana" if days_left == 1 else f"en {days_left} dias")
        actions.append(_post_action("exam", f"Simulacro: examen {when}", "longitud fija, todos los temas, nota sobre 20",
                                    practice_url, {"target_count": min(EXAM_DEFAULT_ITEMS, bank_size), "focus": "exam"}, 1))

    last_session = PracticeSession.objects.filter(user=user, course=course, completed_at__isnull=False).first()

    if profile.weak_topics:
        topic = profile.weak_topics[0]
        fresh_reinforcement = ReinforcementJob.objects.filter(
            user=user, course=course, status=ReinforcementJob.Status.DONE,
            completed_at__gte=now - timedelta(days=REINFORCEMENT_FRESH_DAYS),
        ).first()
        if fresh_reinforcement:
            actions.append(_post_action("weak", f"Practica el refuerzo de «{topic}»", "preguntas nuevas generadas para tu tema debil",
                                        practice_url, {"target_count": 8, "focus": "weak"}, 2))
        else:
            actions.append(_post_action("weak", f"Refuerza «{topic}»", "practica solo tus temas debiles",
                                        practice_url, {"target_count": 8, "focus": "weak"}, 2))
            actions.append(_post_action("generate", f"Genera refuerzo de «{topic}»",
                                        f"material nuevo a tu medida · {estimate_reinforcement_cost('auto').amount} creditos",
                                        reverse("reinforcement_start", args=[course.pk]), {}, 4))

    risky = at_risk_topics(profile, now)
    if risky:
        topic = risky[0]["topic"]
        actions.append(_post_action("risk", f"Repasa «{topic}» antes de olvidarlo",
                                    f"lo dominabas, pero su retencion estimada cayo al {round(100 * risky[0]['retention'])} %",
                                    practice_url, {"target_count": 6, "focus": "risk"}, 2))

    if last_session and last_session.feedback.get("failed") and last_session.completed_at >= now - timedelta(days=2):
        n = len(last_session.feedback["failed"])
        actions.append(_link_action("failures", f"Revisa tus {n} fallo{'s' if n != 1 else ''}",
                                    "las respuestas correctas de tu ultima sesion",
                                    reverse("practice_session", args=[course.pk, last_session.pk]), 3, count=n))

    if profile.standard_error > 0.6:
        actions.append(_post_action("practice", "Otra sesion de practica", "tu nivel aun se estima con poca precision",
                                    practice_url, {"target_count": 10, "focus": "balanced"}, 3))
    elif not last_session or last_session.completed_at < now - timedelta(days=MAINTENANCE_DAYS):
        actions.append(_post_action("practice", "Sesion de mantenimiento", "llevas dias sin practicar este curso",
                                    practice_url, {"target_count": 10, "focus": "balanced"}, 3))

    for job in ready_jobs:
        practiced = StudentAnswer.objects.filter(
            user=user, question__quiz__class_session__legacy_lesson_job=job
        ).exists()
        if not practiced:
            actions.append(_post_action("class", f"Practica «{job.title}»", "una clase lista que aun no has trabajado",
                                        reverse("start_quiz", args=[job.pk]), {"target_count": 8}, 4))
            break

    if not actions:
        actions.append(_link_action("advance", "Al dia: sube una clase nueva", "no tienes pendientes en este curso",
                                    reverse("api_lesson") + f"?course={course.pk}", 5))
    actions.sort(key=lambda a: a["priority"])
    return actions[:PLAN_MAX_ACTIONS]


def today_progress(user) -> dict:
    """Preguntas respondidas + tarjetas repasadas hoy frente a la meta diaria."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    answered = StudentAnswer.objects.filter(user=user, answered_at__gte=start).count()
    reviewed = StudyActivity.objects.filter(
        user=user, activity_type=StudyActivity.ActivityType.FLASHCARDS_REVIEWED, occurred_at__gte=start
    ).count()
    prefs = UserPreference.objects.filter(user=user).first()
    goal = max(1, prefs.daily_goal if prefs else 10)
    done = answered + reviewed
    return {"done": done, "answered": answered, "reviewed": reviewed, "goal": goal, "pct": min(100, round(100 * done / goal))}


# ---------------------------------------------------------------------------
# 9. Salud del banco (evidencia de calibracion para el curso)
# ---------------------------------------------------------------------------
def bank_report(course: Course) -> dict:
    """Filas por pregunta con dificultad generada vs calibrada, uso y bandera de calidad."""
    questions = (
        Question.objects.filter(quiz__course=course, quiz__quiz_type__in=PRACTICE_QUIZ_TYPES)
        .select_related("quiz", "quiz__class_session")
        .order_by("quiz__class_session__created_at", "quiz_id", "order")
    )
    rows = []
    drift_sum, drift_n = 0.0, 0
    for q in questions:
        accuracy = round(100 * q.correct_count / q.attempts) if q.attempts else None
        drift = round(q.b_calibrated - q.irt_b, 2) if q.b_calibrated is not None else None
        if drift is not None and q.calibration_count >= CALIBRATION_MIN:
            drift_sum += abs(drift)
            drift_n += 1
        source = q.quiz.class_session.title if q.quiz.class_session_id else q.quiz.get_quiz_type_display()
        rows.append({
            "id": q.pk, "prompt": q.prompt, "topic": q.topic, "bloom": q.bloom_level,
            "bloom_label": BLOOM_LABELS.get(q.bloom_level, q.bloom_level),
            "b": round(q.irt_b, 2), "b_calibrated": round(q.b_calibrated, 2) if q.b_calibrated is not None else None,
            "drift": drift, "calibrated": q.calibration_count >= CALIBRATION_MIN,
            "attempts": q.attempts, "accuracy": accuracy, "flag": q.quality_flag, "source": source,
            "timestamp": format_timestamp(q.source_timestamp_seconds), "quiz_type": q.quiz.quiz_type,
        })
    return {
        "rows": rows,
        "total": len(rows),
        "calibrated": sum(1 for r in rows if r["calibrated"]),
        "flagged": sum(1 for r in rows if r["flag"]),
        "used": sum(1 for r in rows if r["attempts"]),
        "mean_drift": round(drift_sum / drift_n, 2) if drift_n else None,
        "by_topic": sorted(Counter(r["topic"] for r in rows).items()),
    }
