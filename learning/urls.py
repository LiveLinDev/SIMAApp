from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("mini", views.mini_landing, name="mini_landing"),
    path("mini/", views.mini_landing, name="mini_landing_slash"),
    path("mini/benchmark/", views.mini_benchmark, name="mini_benchmark"),
    path("registro/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("cursos/nuevo/", views.course_create, name="course_create"),
    path("cursos/<int:pk>/", views.course_detail, name="course_detail"),
    path("planes/", views.plans, name="plans"),
    path("gratis/nueva/", views.free_lesson, name="free_lesson"),
    path("api/nueva/", views.api_lesson, name="api_lesson"),
    path("clase/<int:pk>/", views.lesson_detail, name="lesson_detail"),
    path("clase/compartida/<str:token>/", views.shared_lesson_detail, name="shared_lesson_detail"),
    path("clase/<int:pk>/estado/", views.lesson_job_status, name="lesson_job_status"),
    path("clase/<int:pk>/reintentar/", views.retry_api_lesson, name="retry_api_lesson"),
    path("clase/<int:pk>/quiz/iniciar/", views.start_quiz, name="start_quiz"),
    path("clase/<int:pk>/quiz/<int:attempt_id>/", views.quiz_attempt, name="quiz_attempt"),
    path("clase/<int:pk>/quiz/<int:attempt_id>/responder/", views.answer_quiz, name="answer_quiz"),
    path("clase/<int:pk>/toon/", views.submit_toon, name="submit_toon"),
    path("clase/<int:pk>/verificacion/", views.submit_verification, name="submit_verification"),
    path("clase/<int:pk>/transcripcion/", views.repair_transcript, name="repair_transcript"),
    path("clase/<int:pk>/coherencia/", views.repair_coherence, name="repair_coherence"),
    path("clase/<int:pk>/visibilidad/", views.set_visibility, name="set_visibility"),
    path("clase/<int:pk>/renombrar/", views.rename_lesson, name="rename_lesson"),
    path("clase/<int:pk>/eliminar/", views.delete_lesson, name="delete_lesson"),
    path("clase/<int:pk>/descargar/", views.download_json, name="download_json"),
]
