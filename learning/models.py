from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Plan(models.TextChoices):
    FREE = "free", "Gratis"
    BASIC = "basic", "Basico API"
    PRO = "pro", "Pro API"
    UNLIMITED = "unlimited", "Ilimitado API"


PLAN_DETAILS = {
    Plan.FREE: {"price": 0, "classes": 0, "api": False, "label": "Gratis"},
    Plan.BASIC: {"price": 5, "classes": 6, "api": True, "label": "Basico"},
    Plan.PRO: {"price": 10, "classes": 20, "api": True, "label": "Pro"},
    Plan.UNLIMITED: {"price": 25, "classes": None, "api": True, "label": "Ilimitado"},
}


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    api_classes_used = models.PositiveIntegerField(default=0)
    
    # Gamificación y progreso
    daily_goal = models.PositiveIntegerField(default=10)  # preguntas por día
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_study_date = models.DateField(null=True, blank=True)
    total_xp = models.PositiveIntegerField(default=0)
    
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.get_plan_display()}"

    @property
    def plan_info(self):
        return PLAN_DETAILS[self.plan]

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
    def level(self):
        """Calcula nivel basado en XP (cada 100 XP = 1 nivel)"""
        return (self.total_xp // 100) + 1


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


class QuizAttempt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    lesson = models.ForeignKey(LessonJob, on_delete=models.CASCADE, related_name="quiz_attempts")
    target_count = models.PositiveIntegerField(default=10)
    theta = models.FloatField(default=0.0)
    standard_error = models.FloatField(default=9.99)
    current_item_id = models.CharField(max_length=20, blank=True)
    selected_item_ids = models.JSONField(default=list, blank=True)
    correct_count = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def answered_count(self):
        return self.responses.count()

    @property
    def is_complete(self):
        return self.completed_at is not None

    @property
    def accuracy(self):
        total = self.answered_count
        return round((self.correct_count / total) * 100) if total else 0


class QuizResponse(models.Model):
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name="responses")
    item_id = models.CharField(max_length=20)
    item_bloom = models.CharField(max_length=4)
    item_topic = models.CharField(max_length=160)
    item_area = models.CharField(max_length=160, blank=True)
    item_demand = models.CharField(max_length=20, blank=True)
    theta_before = models.FloatField(default=0.0)
    theta_after = models.FloatField(default=0.0)
    selected_index = models.IntegerField()
    correct_index = models.IntegerField()
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["answered_at"]


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
    else:
        # garantiza que usuarios existentes siempre tengan perfil
        Profile.objects.get_or_create(user=instance)
