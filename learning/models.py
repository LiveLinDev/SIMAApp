from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.utils import OperationalError, ProgrammingError
from django.db.models.signals import post_save
from django.dispatch import receiver


class Plan(models.TextChoices):
    FREE = "free", "Gratis"
    BASIC = "basic", "Basico API"
    PRO = "pro", "Pro API"
    UNLIMITED = "unlimited", "Ilimitado API"


PLAN_DETAILS = {
    Plan.FREE: {"price": 0, "classes": 0, "credits": 30, "api": False, "label": "Gratis"},
    Plan.BASIC: {"price": 5, "classes": 6, "credits": 600, "api": True, "label": "Basico"},
    Plan.PRO: {"price": 10, "classes": 20, "credits": 2200, "api": True, "label": "Pro"},
    Plan.UNLIMITED: {"price": 25, "classes": None, "credits": None, "api": True, "label": "Ilimitado"},
}


class PlanCatalog(models.Model):
    code = models.CharField(max_length=20, choices=Plan.choices, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    monthly_price_usd = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    monthly_api_classes = models.PositiveIntegerField(null=True, blank=True)
    monthly_credits = models.PositiveIntegerField(null=True, blank=True)
    api_enabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "monthly_price_usd", "code"]

    def __str__(self):
        return self.name

    @property
    def detail_dict(self):
        price = float(self.monthly_price_usd)
        if price.is_integer():
            price = int(price)
        return {
            "price": price,
            "classes": self.monthly_api_classes,
            "credits": self.monthly_credits,
            "api": self.api_enabled,
            "label": self.name,
            "description": self.description,
            "active": self.is_active,
        }


def get_plan_info(plan: str) -> dict:
    try:
        catalog = PlanCatalog.objects.filter(code=plan, is_active=True).first()
    except (OperationalError, ProgrammingError):
        catalog = None
    if catalog:
        return catalog.detail_dict
    return PLAN_DETAILS.get(plan, PLAN_DETAILS[Plan.FREE])


def get_plan_details(active_only: bool = True) -> dict:
    try:
        plans = PlanCatalog.objects.all()
        if active_only:
            plans = plans.filter(is_active=True)
        catalog = {plan.code: plan.detail_dict for plan in plans}
    except (OperationalError, ProgrammingError):
        catalog = {}
    return catalog or PLAN_DETAILS


class BloomLevel(models.TextChoices):
    REMEMBER = "L1", "Recordar"
    UNDERSTAND = "L2", "Comprender"
    APPLY = "L3", "Aplicar"
    ANALYZE = "L4", "Analizar"
    EVALUATE = "L5", "Evaluar"
    CREATE = "L6", "Crear"


class Difficulty(models.TextChoices):
    LOW = "low", "Baja"
    MEDIUM = "medium", "Media"
    HIGH = "high", "Alta"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    api_classes_used = models.PositiveIntegerField(default=0)
    credit_balance = models.IntegerField(default=0)
    
    # Gamificacion y progreso
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_study_date = models.DateField(null=True, blank=True)
    total_xp = models.PositiveIntegerField(default=0)
    
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.get_plan_display()}"

    @property
    def plan_info(self):
        return get_plan_info(self.plan)

    @property
    def can_use_api(self):
        info = self.plan_info
        if not info["api"]:
            return False
        if info["classes"] is None:
            return True
        return self.api_classes_used < info["classes"]

    @property
    def remaining_classes(self):
        total = self.plan_info["classes"]
        if total is None:
            return "Infinitas"
        return max(total - self.api_classes_used, 0)

    @property
    def credits_label(self):
        if self.plan_info["credits"] is None:
            return "Ilimitados"
        return str(max(self.credit_balance, 0))
    
    @property
    def level(self):
        """Calcula nivel basado en XP (cada 100 XP = 1 nivel)"""
        return (self.total_xp // 100) + 1


class UserPreference(models.Model):
    class Language(models.TextChoices):
        SPANISH = "es", "Espanol"
        ENGLISH = "en", "Ingles"

    class Theme(models.TextChoices):
        SYSTEM = "system", "Sistema"
        LIGHT = "light", "Claro"
        DARK = "dark", "Oscuro"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preferences")
    daily_goal = models.PositiveIntegerField(default=10)
    default_study_minutes = models.PositiveIntegerField(default=25)
    preferred_language = models.CharField(max_length=8, choices=Language.choices, default=Language.SPANISH)
    theme = models.CharField(max_length=16, choices=Theme.choices, default=Theme.SYSTEM)
    email_reminders = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferencias de {self.user.username}"


class Course(models.Model):
    class Level(models.TextChoices):
        INTRODUCTORY = "introductory", "Introductorio"
        INTERMEDIATE = "intermediate", "Intermedio"
        ADVANCED = "advanced", "Avanzado"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="courses")
    name = models.CharField(max_length=160)
    academic_period = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)
    instructor = models.CharField(max_length=160, blank=True)
    main_topics = models.JSONField(default=list, blank=True)
    vocabulary = models.TextField(
        blank=True,
        help_text="Terminos tecnicos del curso separados por comas. Mejoran la transcripcion y se amplian solos al corregir clases.",
    )
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.INTRODUCTORY)
    student_goal = models.TextField(blank=True)
    exam_date = models.DateField(null=True, blank=True, help_text="Proxima evaluacion: activa la cuenta regresiva y el simulacro en el plan.")
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name", "academic_period"],
                name="unique_course_per_user_period",
            )
        ]
        indexes = [
            models.Index(fields=["user", "is_archived"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        period = f" ({self.academic_period})" if self.academic_period else ""
        return f"{self.name}{period}"


class ClassSession(models.Model):
    class ProcessingStatus(models.TextChoices):
        DRAFT = "draft", "Borrador"
        WAITING_CONFIRMATION = "waiting_confirmation", "Esperando confirmacion"
        QUEUED = "queued", "En cola"
        PROCESSING = "processing", "Procesando"
        READY = "ready", "Lista"
        ERROR = "error", "Error"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="class_sessions")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="class_sessions")
    legacy_lesson_job = models.OneToOneField(
        "LessonJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="class_session",
    )
    title = models.CharField(max_length=180)
    media_file = models.FileField(upload_to="classes/", blank=True)
    class_date = models.DateField(null=True, blank=True)
    main_topic = models.CharField(max_length=180, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=32,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.DRAFT,
    )
    requested_outputs = models.JSONField(default=list, blank=True)
    estimated_credit_cost = models.IntegerField(default=0)
    confirmed_credit_cost = models.IntegerField(default=0)
    processing_log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-class_date", "-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["course", "status"]),
            models.Index(fields=["class_date"]),
        ]

    def __str__(self):
        return self.title


class Transcript(models.Model):
    class Source(models.TextChoices):
        WHISPER = "whisper", "Whisper"
        MANUAL = "manual", "Manual"
        IMPORTED = "imported", "Importada"

    class_session = models.OneToOneField(ClassSession, on_delete=models.CASCADE, related_name="transcript_record")
    full_text = models.TextField()
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WHISPER)
    language = models.CharField(max_length=12, default="es")
    average_confidence = models.FloatField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transcript {self.class_session_id}"


class TranscriptSegment(models.Model):
    transcript = models.ForeignKey(Transcript, on_delete=models.CASCADE, related_name="segments")
    start_seconds = models.FloatField(default=0)
    end_seconds = models.FloatField(default=0)
    text = models.TextField()
    topic = models.CharField(max_length=180, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "start_seconds"]
        indexes = [
            models.Index(fields=["transcript", "order"]),
            models.Index(fields=["topic"]),
        ]

    def __str__(self):
        return f"{self.transcript_id}:{self.order}"


class Summary(models.Model):
    class Kind(models.TextChoices):
        BRIEF = "brief", "Breve"
        STRUCTURED = "structured", "Estructurado"
        COURSE_ACCUMULATED = "course_accumulated", "Acumulado del curso"
        CONCEPT = "concept", "Explicacion de concepto"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="summaries")
    class_session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="summaries",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.BRIEF)
    title = models.CharField(max_length=180, blank=True)
    content = models.TextField()
    key_concepts = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["course", "kind"]),
            models.Index(fields=["class_session", "kind"]),
        ]

    def __str__(self):
        return self.title or f"{self.get_kind_display()} - {self.course}"


class Flashcard(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="flashcards")
    class_session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="flashcards",
    )
    question = models.TextField()
    answer = models.TextField()
    topic = models.CharField(max_length=180, blank=True)
    difficulty = models.CharField(max_length=12, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    source_timestamp_seconds = models.FloatField(null=True, blank=True)
    source_excerpt = models.TextField(blank=True)
    mastery_level = models.PositiveSmallIntegerField(default=0)
    next_review_at = models.DateTimeField(null=True, blank=True)
    # SM-2
    ease_factor = models.FloatField(default=2.5)
    interval_days = models.PositiveIntegerField(default=0)
    repetitions = models.PositiveIntegerField(default=0)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["topic", "created_at"]
        indexes = [
            models.Index(fields=["course", "topic"]),
            models.Index(fields=["next_review_at"]),
        ]

    def __str__(self):
        return self.question[:80]


class Quiz(models.Model):
    class QuizType(models.TextChoices):
        PRACTICE = "practice", "Practica"
        ADAPTIVE = "adaptive", "Adaptativo"
        DIAGNOSTIC = "diagnostic", "Diagnostico"
        REINFORCEMENT = "reinforcement", "Refuerzo"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="quizzes")
    class_session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="quizzes",
    )
    title = models.CharField(max_length=180)
    topic = models.CharField(max_length=180, blank=True)
    quiz_type = models.CharField(max_length=20, choices=QuizType.choices, default=QuizType.ADAPTIVE)
    bloom_distribution = models.JSONField(default=dict, blank=True)
    cat_config = models.JSONField(default=dict, blank=True)
    mini_source = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["course", "quiz_type"]),
            models.Index(fields=["class_session", "quiz_type"]),
        ]

    def __str__(self):
        return self.title


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    external_id = models.CharField(max_length=40, blank=True)
    bloom_level = models.CharField(max_length=2, choices=BloomLevel.choices, default=BloomLevel.REMEMBER)
    topic = models.CharField(max_length=180, blank=True)
    prompt = models.TextField()
    explanation = models.TextField(blank=True)
    difficulty = models.CharField(max_length=12, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    irt_a = models.FloatField(default=1.0)
    irt_b = models.FloatField(default=0.0)
    irt_c = models.FloatField(default=0.25)
    source_timestamp_seconds = models.FloatField(null=True, blank=True)
    source_excerpt = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    # estadisticas en linea (motor v2)
    attempts = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    b_calibrated = models.FloatField(null=True, blank=True, help_text="Dificultad corregida con respuestas reales (Elo).")
    calibration_count = models.PositiveIntegerField(default=0)
    quality_flag = models.CharField(max_length=16, blank=True, help_text="'' | too_easy | suspect")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["quiz", "order"]),
            models.Index(fields=["bloom_level"]),
            models.Index(fields=["topic"]),
        ]

    def __str__(self):
        return self.prompt[:80]


class AnswerOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["question", "is_correct"])]

    def __str__(self):
        return self.text[:80]


class StudentAnswer(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_answers")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="student_answers")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="student_answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="student_answers")
    selected_option = models.ForeignKey(
        AnswerOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_answers",
    )
    practice_session = models.ForeignKey(
        "PracticeSession",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="answers",
    )
    is_correct = models.BooleanField(default=False)
    theta_before = models.FloatField(null=True, blank=True)
    theta_after = models.FloatField(null=True, blank=True)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-answered_at"]
        indexes = [
            models.Index(fields=["user", "course", "answered_at"]),
            models.Index(fields=["quiz", "answered_at"]),
        ]


class AdaptiveProfile(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="adaptive_profiles")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="adaptive_profiles")
    theta = models.FloatField(default=0.0)
    standard_error = models.FloatField(default=9.99)
    mastery_by_topic = models.JSONField(default=dict, blank=True)
    bloom_mastery = models.JSONField(default=dict, blank=True)
    weak_topics = models.JSONField(default=list, blank=True)
    strong_topics = models.JSONField(default=list, blank=True)
    recommended_difficulty = models.CharField(max_length=12, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "course"], name="unique_adaptive_profile_per_course")
        ]
        indexes = [models.Index(fields=["user", "course"])]

    def __str__(self):
        return f"{self.user} - {self.course}"


class PracticeSession(models.Model):
    """Sesion de practica adaptativa (CAT) sobre el banco completo de un curso."""

    class Focus(models.TextChoices):
        BALANCED = "balanced", "Equilibrada"
        WEAK = "weak", "Refuerzo de temas debiles"
        RISK = "risk", "Repaso de temas en riesgo de olvido"
        EXAM = "exam", "Simulacro"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="practice_sessions")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="practice_sessions")
    lesson = models.ForeignKey(
        "LessonJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="practice_sessions",
        help_text="Si esta definido, la practica se limita al banco de esa clase.",
    )
    focus = models.CharField(max_length=16, choices=Focus.choices, default=Focus.BALANCED)
    target_count = models.PositiveIntegerField(default=10)
    theta_start = models.FloatField(default=0.0)
    prior_sd = models.FloatField(default=1.0, help_text="Desviacion del prior N(theta_start, prior_sd) usado por EAP.")
    theta = models.FloatField(default=0.0)
    standard_error = models.FloatField(default=9.99)
    current_question = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    served_question_ids = models.JSONField(default=list, blank=True)
    correct_count = models.PositiveIntegerField(default=0)
    feedback = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "course", "completed_at"]),
        ]

    def __str__(self):
        return f"Practica {self.pk} - {self.course}"

    @property
    def is_complete(self):
        return self.completed_at is not None

    @property
    def answered_count(self):
        return self.answers.count()

    @property
    def accuracy(self):
        total = self.answered_count
        return round((self.correct_count / total) * 100) if total else 0


class ReinforcementJob(models.Model):
    """Generacion adaptativa: material nuevo dirigido a los temas debiles del perfil."""

    class Status(models.TextChoices):
        QUEUED = "queued", "En cola"
        PROCESSING = "processing", "Procesando"
        DONE = "done", "Listo"
        ERROR = "error", "Error"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reinforcement_jobs")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="reinforcement_jobs")
    practice_session = models.ForeignKey(
        PracticeSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="reinforcement_jobs"
    )
    topics = models.JSONField(default=list, blank=True)
    theta = models.FloatField(default=0.0)
    requested_items = models.PositiveIntegerField(default=8)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    processing_log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    quiz = models.ForeignKey(Quiz, on_delete=models.SET_NULL, null=True, blank=True, related_name="reinforcement_jobs")
    summary_ids = models.JSONField(default=list, blank=True)
    flashcard_ids = models.JSONField(default=list, blank=True)
    credits_charged = models.IntegerField(default=0)
    credits_refunded = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "course", "status"])]

    def __str__(self):
        return f"Refuerzo {self.pk} - {self.course}"

    @property
    def is_done(self):
        return self.status == self.Status.DONE


class CreditLedgerEntry(models.Model):
    class Action(models.TextChoices):
        PLAN_GRANT = "plan_grant", "Creditos de plan"
        CLASS_TRANSCRIPTION = "class_transcription", "Transcripcion de clase"
        SUMMARY_GENERATION = "summary_generation", "Generacion de resumen"
        FLASHCARD_GENERATION = "flashcard_generation", "Generacion de flashcards"
        QUIZ_GENERATION = "quiz_generation", "Generacion de quiz"
        ADAPTIVE_EVALUATION = "adaptive_evaluation", "Evaluacion adaptativa"
        REGENERATION = "regeneration", "Regeneracion"
        MANUAL_ADJUSTMENT = "manual_adjustment", "Ajuste manual"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit_entries")
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="credit_entries")
    class_session = models.ForeignKey(
        ClassSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_entries",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    amount = models.IntegerField(help_text="Positive grants credits; negative amounts consume credits.")
    balance_after = models.IntegerField(default=0)
    description = models.CharField(max_length=240, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["course", "created_at"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.user} {self.action} {self.amount}"


class StudyActivity(models.Model):
    class ActivityType(models.TextChoices):
        CLASS_UPLOADED = "class_uploaded", "Clase subida"
        SUMMARY_REVIEWED = "summary_reviewed", "Resumen revisado"
        FLASHCARDS_REVIEWED = "flashcards_reviewed", "Flashcards repasadas"
        QUIZ_COMPLETED = "quiz_completed", "Quiz completado"
        ERRORS_REVIEWED = "errors_reviewed", "Errores revisados"
        RECOMMENDATION_DONE = "recommendation_done", "Recomendacion completada"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="study_activities")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="study_activities")
    class_session = models.ForeignKey(
        ClassSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="study_activities",
    )
    activity_type = models.CharField(max_length=32, choices=ActivityType.choices)
    xp_awarded = models.PositiveIntegerField(default=0)
    study_seconds = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["user", "occurred_at"]),
            models.Index(fields=["course", "occurred_at"]),
            models.Index(fields=["activity_type"]),
        ]


class StudyStreak(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="study_streak")
    current_count = models.PositiveIntegerField(default=0)
    longest_count = models.PositiveIntegerField(default=0)
    last_activity_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} - {self.current_count} dias"


class Recommendation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        COMPLETED = "completed", "Completada"
        DISMISSED = "dismissed", "Descartada"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendations")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="recommendations")
    class_session = models.ForeignKey(
        ClassSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendations",
    )
    title = models.CharField(max_length=180)
    message = models.TextField()
    reason = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(default=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    due_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "priority", "due_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["course", "status"]),
            models.Index(fields=["due_at"]),
        ]

    def __str__(self):
        return self.title


class LessonJob(models.Model):
    class Mode(models.TextChoices):
        FREE_MANUAL = "free_manual", "Gratis manual"
        API = "api", "API"

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        QUEUED = "queued", "En cola"
        PROCESSING = "processing", "Procesando"
        PROMPT_READY = "prompt_ready", "Prompt listo"
        TOON_READY = "toon_ready", "Ítems listos"
        VERIFIED = "verified", "Verificación lista"
        CORRECTED = "corrected", "Corregido y listo"
        ERROR = "error", "Error"

    class Visibility(models.TextChoices):
        PRIVATE = "private", "Privada"
        SHARED = "shared", "Compartida con link"
        PUBLIC = "public", "Pública en explorar"

    class VerificationMode(models.TextChoices):
        WEB = "web", "Fuentes web"
        EDUQG = "eduqg", "EduQG local"
        HYBRID = "hybrid", "Web + EduQG"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="legacy_lesson_jobs",
    )
    title = models.CharField(max_length=140, default="Clase sin titulo")
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.FREE_MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.PRIVATE)
    share_token = models.CharField(max_length=32, blank=True, unique=True, null=True)
    
    source_text = models.TextField(blank=True)
    audio = models.FileField(upload_to="audio/", blank=True)
    transcript = models.TextField(blank=True)
    generation_prompt = models.TextField(blank=True)
    toon_output = models.TextField(blank=True)
    verification_prompt = models.TextField(blank=True)
    verification_output = models.TextField(blank=True)
    corrected_output = models.TextField(blank=True)
    error = models.TextField(blank=True)
    ai_backend = models.CharField(max_length=20, default="auto")
    verification_mode = models.CharField(max_length=20, choices=VerificationMode.choices, default=VerificationMode.WEB)
    processing_stage = models.CharField(max_length=120, blank=True)
    processing_log = models.TextField(blank=True)
    transcript_repair_prompt = models.TextField(blank=True)
    transcript_repair_trace = models.JSONField(default=list, blank=True)
    mini_coherence_prompt = models.TextField(blank=True)
    mini_coherence_trace = models.JSONField(default=list, blank=True)
    verification_trace = models.JSONField(default=dict, blank=True)
    correction_trace = models.JSONField(default=list, blank=True)
    tags = models.CharField(max_length=260, blank=True)
    api_usage_counted = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def tag_list(self):
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        # loaddata / import de respaldos: el perfil y las preferencias vienen en los mismos datos
        return
    if created:
        Profile.objects.create(user=instance)
        UserPreference.objects.create(user=instance)
    else:
        # garantiza que usuarios existentes siempre tengan datos base
        Profile.objects.get_or_create(user=instance)
        UserPreference.objects.get_or_create(user=instance)


class SummaryJob(models.Model):
    """Generacion de un resumen (de clase o acumulado del curso) en la cola de trabajos."""

    class Kind(models.TextChoices):
        CLASS = "class", "Resumen de clase"
        COURSE = "course", "Resumen del curso"

    class Status(models.TextChoices):
        QUEUED = "queued", "En cola"
        PROCESSING = "processing", "Procesando"
        DONE = "done", "Listo"
        ERROR = "error", "Error"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="summary_jobs")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="summary_jobs")
    lesson = models.ForeignKey(LessonJob, on_delete=models.CASCADE, null=True, blank=True, related_name="summary_jobs")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.CLASS)
    backend = models.CharField(max_length=16, default="auto")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    processing_log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    summary = models.ForeignKey(Summary, on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs")
    credits_charged = models.IntegerField(default=0)
    credits_refunded = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "course", "status"])]

    def __str__(self):
        return f"Resumen {self.get_kind_display()} {self.pk} - {self.course}"

    @property
    def is_pending(self):
        return self.status in {self.Status.QUEUED, self.Status.PROCESSING}


def days_until(date_value):
    """Dias que faltan para una fecha (negativo si ya paso); None si no hay fecha."""
    if not date_value:
        return None
    from django.utils import timezone as _tz

    return (date_value - _tz.localdate()).days
