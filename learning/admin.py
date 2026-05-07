from django.contrib import admin

from .models import LessonJob, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "api_classes_used", "updated_at")
    search_fields = ("user__username", "user__email")


@admin.register(LessonJob)
class LessonJobAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "mode", "status", "visibility", "tags", "created_at")
    list_filter = ("mode", "status", "visibility", "created_at")
    search_fields = ("title", "tags", "user__username")
