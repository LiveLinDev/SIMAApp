from django.contrib import admin

from .models import (
    AdaptiveProfile,
    AnswerOption,
    ClassSession,
    Course,
    CreditLedgerEntry,
    Flashcard,
    LessonJob,
    PlanCatalog,
    PracticeSession,
    ReinforcementJob,
    SummaryJob,
    Profile,
    Question,
    Quiz,
    Recommendation,
    StudentAnswer,
    StudyActivity,
    StudyStreak,
    Summary,
    Transcript,
    TranscriptSegment,
    UserPreference,
)


@admin.register(PlanCatalog)
class PlanCatalogAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "monthly_price_usd", "monthly_api_classes", "monthly_credits", "api_enabled", "is_active", "sort_order")
    list_filter = ("api_enabled", "is_active")
    search_fields = ("name", "code", "description")
    ordering = ("sort_order", "monthly_price_usd")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "api_classes_used", "updated_at")
    search_fields = ("user__username", "user__email")


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "daily_goal", "default_study_minutes", "preferred_language", "theme", "email_reminders", "updated_at")
    list_filter = ("preferred_language", "theme", "email_reminders")
    search_fields = ("user__username", "user__email")


@admin.register(LessonJob)
class LessonJobAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "mode", "status", "visibility", "tags", "created_at")
    list_filter = ("mode", "status", "visibility", "created_at")
    search_fields = ("title", "tags", "user__username")


class TranscriptSegmentInline(admin.TabularInline):
    model = TranscriptSegment
    extra = 0
    fields = ("order", "start_seconds", "end_seconds", "topic", "confidence", "text")


class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 0
    fields = ("order", "text", "is_correct")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "academic_period", "level", "is_archived", "updated_at")
    list_filter = ("level", "is_archived", "academic_period")
    search_fields = ("name", "description", "instructor", "user__username", "user__email")


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "user", "status", "class_date", "estimated_credit_cost", "updated_at")
    list_filter = ("status", "class_date", "created_at")
    search_fields = ("title", "main_topic", "course__name", "user__username")
    autocomplete_fields = ("user", "course", "legacy_lesson_job")


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ("class_session", "source", "language", "average_confidence", "updated_at")
    list_filter = ("source", "language", "created_at")
    search_fields = ("class_session__title", "full_text")
    inlines = [TranscriptSegmentInline]


@admin.register(Summary)
class SummaryAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "class_session", "kind", "updated_at")
    list_filter = ("kind", "created_at")
    search_fields = ("title", "content", "course__name", "class_session__title")


@admin.register(Flashcard)
class FlashcardAdmin(admin.ModelAdmin):
    list_display = ("question", "course", "class_session", "topic", "difficulty", "mastery_level", "next_review_at")
    list_filter = ("difficulty", "mastery_level", "next_review_at")
    search_fields = ("question", "answer", "topic", "course__name")


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "class_session", "quiz_type", "updated_at")
    list_filter = ("quiz_type", "created_at")
    search_fields = ("title", "topic", "course__name", "class_session__title")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("prompt", "quiz", "bloom_level", "topic", "difficulty", "order")
    list_filter = ("bloom_level", "difficulty")
    search_fields = ("prompt", "topic", "explanation", "quiz__title")
    inlines = [AnswerOptionInline]


@admin.register(StudentAnswer)
class StudentAnswerAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "quiz", "question", "is_correct", "answered_at")
    list_filter = ("is_correct", "answered_at")
    search_fields = ("user__username", "course__name", "quiz__title", "question__prompt")


@admin.register(AdaptiveProfile)
class AdaptiveProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "theta", "standard_error", "recommended_difficulty", "last_activity_at")
    list_filter = ("recommended_difficulty",)
    search_fields = ("user__username", "course__name")


@admin.register(CreditLedgerEntry)
class CreditLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "amount", "balance_after", "course", "class_session", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("user__username", "course__name", "class_session__title", "description")


@admin.register(StudyActivity)
class StudyActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "activity_type", "xp_awarded", "study_seconds", "occurred_at")
    list_filter = ("activity_type", "occurred_at")
    search_fields = ("user__username", "course__name", "class_session__title")


@admin.register(StudyStreak)
class StudyStreakAdmin(admin.ModelAdmin):
    list_display = ("user", "current_count", "longest_count", "last_activity_date", "updated_at")
    search_fields = ("user__username", "user__email")


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "course", "status", "priority", "due_at", "updated_at")
    list_filter = ("status", "priority", "due_at")
    search_fields = ("title", "message", "reason", "user__username", "course__name")


@admin.register(PracticeSession)
class PracticeSessionAdmin(admin.ModelAdmin):
    list_display = ("pk", "user", "course", "focus", "target_count", "correct_count", "theta", "standard_error", "completed_at", "created_at")
    list_filter = ("focus", "course")
    search_fields = ("user__username", "course__name")
    readonly_fields = ("feedback", "served_question_ids")


@admin.register(ReinforcementJob)
class ReinforcementJobAdmin(admin.ModelAdmin):
    list_display = ("pk", "user", "course", "status", "topics", "credits_charged", "credits_refunded", "created_at", "completed_at")
    list_filter = ("status", "course")
    search_fields = ("user__username", "course__name")
    readonly_fields = ("processing_log", "error")


@admin.register(SummaryJob)
class SummaryJobAdmin(admin.ModelAdmin):
    list_display = ("pk", "user", "course", "lesson", "kind", "status", "backend", "credits_charged", "credits_refunded", "created_at", "completed_at")
    list_filter = ("status", "kind", "backend")
    search_fields = ("user__username", "course__name", "lesson__title")
    readonly_fields = ("processing_log", "error")
