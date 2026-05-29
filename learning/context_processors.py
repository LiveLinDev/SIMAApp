from django.db.models import Count, Q

from .models import ClassSession, Course, LessonJob, Profile, UserPreference


def sidebar_data(request):
    """Provee datos del sidebar para todas las peticiones autenticadas."""
    if not request.user.is_authenticated:
        return {}

    profile, _ = Profile.objects.get_or_create(user=request.user)
    preferences, _ = UserPreference.objects.get_or_create(user=request.user)

    courses = Course.objects.filter(user=request.user, is_archived=False)
    all_jobs = LessonJob.objects.filter(user=request.user)
    ready_jobs = all_jobs.filter(
        Q(corrected_output__gt="") | Q(toon_output__gt="")
    ).count()
    processing_jobs = all_jobs.filter(
        status__in=[LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING]
    ).count()
    session_count = ClassSession.objects.filter(user=request.user).count()

    # Intentar deducir tab activo desde la URL actual
    active_tab = ""
    try:
        url_name = request.resolver_match.url_name if request.resolver_match else ""
    except Exception:
        url_name = ""

    tab_map = {
        "dashboard": "cursos",
        "course_detail": "cursos",
        "course_create": "cursos",
        "lesson_detail": "mis-clases",
        "quiz_attempt": "mis-clases",
        "api_lesson": "mis-clases",
        "free_lesson": "mis-clases",
        "flashcards": "mis-clases",
        "class_map": "mis-clases",
    }
    active_tab = tab_map.get(url_name, "")
    # Si el request tiene ?tab=... (solo dashboard realmente lo usa)
    if request.GET.get("tab"):
        active_tab = request.GET.get("tab")

    return {
        "sidebar_profile": profile,
        "sidebar_preferences": preferences,
        "sidebar_stats": {
            "course_count": courses.count(),
            "lesson_count": all_jobs.count(),
            "ready_count": ready_jobs,
            "processing_count": processing_jobs,
            "session_count": session_count,
        },
        "sidebar_active_tab": active_tab,
    }
