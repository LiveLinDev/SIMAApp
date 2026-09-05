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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .cat import BLOOM_LABELS, estimate_theta, item_information, theta_to_level
from .models import (
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
)
from .credits import estimate_reinforcement_cost
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
    from .job_queue import _sync_class_session_status  # import perezoso: evita ciclo

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
        bank.append(
            BankItem(
                id=str(question.pk),
                question_id=question.pk,
                bloom=question.bloom_level,
                topic=question.topic,
                irt_a=question.irt_a,
                irt_b=question.irt_b,
                irt_c=question.irt_c,
                prompt=question.prompt,
                demand={"low": "low", "high": "high"}.get(question.difficulty, "medium"),
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
    Recalcula el perfil del curso desde el historial completo de respuestas,
    ponderando lo reciente. theta/SE se toman de la ultima sesion completada,
    suavizados con el valor anterior del perfil.
    """
    profile = get_profile(user, course)
    answers = (
        StudentAnswer.objects.filter(user=user, course=course)
        .select_related("question")
        .order_by("-answered_at")[:400]
    )
    topic_acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])   # peso correcto, peso total, n
    bloom_acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    for answer in answers:
        weight = _recency_weight(answer.answered_at)
        for bucket, key in ((topic_acc, answer.question.topic or "General"), (bloom_acc, answer.question.bloom_level)):
            bucket[key][0] += weight * (1.0 if answer.is_correct else 0.0)
            bucket[key][1] += weight
            bucket[key][2] += 1

    mastery_by_topic = {
        topic: {"mastery": round(acc[0] / acc[1], 3), "answers": acc[2]}
        for topic, acc in topic_acc.items() if acc[1] > 0
    }
    bloom_mastery = {
        level: {"mastery": round(acc[0] / acc[1], 3), "answers": acc[2], "label": BLOOM_LABELS.get(level, level)}
        for level, acc in bloom_acc.items() if acc[1] > 0
    }
    weak = sorted(
        (t for t, v in mastery_by_topic.items() if v["answers"] >= MIN_ANSWERS_FOR_TOPIC and v["mastery"] < WEAK_THRESHOLD),
        key=lambda t: mastery_by_topic[t]["mastery"],
    )
    strong = sorted(
        (t for t, v in mastery_by_topic.items() if v["answers"] >= MIN_ANSWERS_FOR_STRONG and v["mastery"] >= STRONG_THRESHOLD),
        key=lambda t: -mastery_by_topic[t]["mastery"],
    )

    if session is not None and session.is_complete:
        answered = session.answers.count()
        prior_known = profile_is_known(profile)
        prior_weight = PRIOR_WEIGHT_KNOWN if prior_known else PRIOR_WEIGHT_UNKNOWN
        prior_theta = profile.theta if prior_known else 0.0
        profile.theta = round((session.theta * answered + prior_theta * prior_weight) / (answered + prior_weight), 3)
        profile.standard_error = round(min(session.standard_error, profile.standard_error), 3)

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
    fresh = [item for item in candidates if item.question_id not in _recently_correct_ids(session.user, session.course)]
    if len(fresh) >= 3:
        candidates = fresh
    if session.focus == PracticeSession.Focus.WEAK and profile.weak_topics:
        weak_only = [item for item in candidates if item.topic in profile.weak_topics]
        if len(weak_only) >= 2:
            candidates = weak_only

    theta = session.theta
    mastery = profile.mastery_by_topic or {}
    answered_bloom = Counter(r.item_bloom for r in responses)
    bank_bloom = Counter(item.bloom for item in bank)
    total = max(len(bank), 1)

    def score(item: BankItem) -> float:
        information = item_information(item, theta)
        expected_share = bank_bloom[item.bloom] / total
        current_share = answered_bloom[item.bloom] / max(len(responses), 1)
        bloom_bonus = max(expected_share - current_share, 0.0) * 0.35
        topic_info = mastery.get(item.topic)
        if topic_info is None:
            topic_bonus = 0.15  # tema nunca evaluado: conviene medirlo
        elif topic_info["mastery"] < WEAK_THRESHOLD:
            topic_bonus = (WEAK_THRESHOLD - topic_info["mastery"]) * 0.5
        else:
            topic_bonus = 0.0
        return information + bloom_bonus + topic_bonus

    return max(candidates, key=score)


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
    focus = focus if focus in PracticeSession.Focus.values else PracticeSession.Focus.BALANCED
    if focus == PracticeSession.Focus.WEAK and not profile.weak_topics:
        focus = PracticeSession.Focus.BALANCED
    try:
        target = int(target_count)
    except (TypeError, ValueError):
        target = 10
    target = max(3, min(target, len(bank), 25))

    session = PracticeSession.objects.create(
        user=user,
        course=course,
        lesson=lesson,
        focus=focus,
        target_count=target,
        theta_start=theta_start,
        theta=theta_start,
        standard_error=profile.standard_error if known else 9.99,
    )
    first = select_next_item(session, bank, [], profile)
    session.current_question_id = first.question_id
    session.served_question_ids = [first.question_id]
    session.save(update_fields=["current_question", "served_question_ids", "updated_at"])
    return session


def _shrunk_theta(mle: float, n: int, prior: float, prior_weight: float) -> float:
    return (mle * n + prior * prior_weight) / (n + prior_weight)


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
    mle, se = estimate_theta(by_id, responses, THETA_MIN, THETA_MAX)
    prior_weight = PRIOR_WEIGHT_KNOWN if session.standard_error < KNOWN_SE or session.theta_start != 0.0 else PRIOR_WEIGHT_UNKNOWN
    theta = round(_shrunk_theta(mle, len(responses), session.theta_start, prior_weight), 3)
    answer.theta_after = theta
    answer.save(update_fields=["theta_after"])

    session.theta = theta
    session.standard_error = se
    session.correct_count = sum(1 for r in responses if r.is_correct)
    answered = len(responses)
    exhausted = answered >= len(bank)
    precise = answered >= MIN_ITEMS_BEFORE_SE_STOP and se <= SE_STOP
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
        "concepts": list(Summary.objects.filter(course=course, kind=Summary.Kind.CONCEPT)[:5]),
        "reinforcement_cost": estimate_reinforcement_cost("auto").amount,
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
        rows.append({
            "course": course,
            "level_label": theta_to_level(adaptive.theta)[1] if known else "Sin evaluar",
            "weak_topics": adaptive.weak_topics[:2] if adaptive else [],
            "recommendations": recs,
            "can_practice": bool(bank or ready_classes),
            "next_action": next_action,
        })
    studied_today = profile.last_study_date == timezone.localdate()
    return {
        "streak": profile.current_streak,
        "studied_today": studied_today,
        "pending_recommendations": Recommendation.objects.filter(user=user, status=Recommendation.Status.PENDING).count(),
        "courses": rows,
    }


def session_context(session: PracticeSession) -> dict:
    """Contexto para la plantilla de practica: pregunta actual o retroalimentacion."""
    question = None
    options = []
    if not session.is_complete and session.current_question_id:
        question = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
        options = list(question.options.all())
    answered = session.answers.count()
    level_value, level_label = theta_to_level(session.theta)
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
    }
