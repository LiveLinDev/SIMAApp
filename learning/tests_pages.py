"""Red de seguridad tras las reorganizaciones: toda pagina GET del producto responde 200 con datos reales."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from learning import adaptive, spaced_repetition
from learning.pipeline import _sync_class_session_status
from learning.models import Course, Flashcard, LessonJob, Plan, Profile, Question, Summary
from learning.tests_adaptive import MINI
from learning.tests_summaries import TRANSCRIPT


class EveryPageRendersTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pau", password="x", email="pau@example.com")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.PRO, "credit_balance": 200})
        self.course = Course.objects.create(user=self.user, name="Biologia", main_topics=["celula"])
        self.job = LessonJob.objects.create(
            user=self.user, course=self.course, title="Clase 1", mode=LessonJob.Mode.API,
            status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript=TRANSCRIPT, tags="biologia",
            visibility=LessonJob.Visibility.SHARED, share_token="tok123",
        )
        self.session = _sync_class_session_status(self.job)
        quiz = adaptive.sync_question_bank(self.job)
        for q in Question.objects.filter(quiz=quiz)[:3]:
            Flashcard.objects.create(course=self.course, class_session=self.session, question=q.prompt, answer="respuesta", topic=q.topic)
        practice = adaptive.start_practice(self.user, self.course, target_count=3)
        while not practice.is_complete:
            q = Question.objects.prefetch_related("options").get(pk=practice.current_question_id)
            adaptive.answer_question(practice, q.pk, next(o for o in q.options.all() if not o.is_correct).pk)
            practice.refresh_from_db()
        self.practice = practice
        Summary.objects.create(course=self.course, class_session=self.session, kind=Summary.Kind.STRUCTURED, title="R", content="Resumen.")
        Summary.objects.create(course=self.course, kind=Summary.Kind.COURSE_ACCUMULATED, title="RC", content="Resumen curso.")
        self.client.force_login(self.user)

    def test_all_get_pages(self):
        pages = [
            reverse("dashboard"), reverse("dashboard") + "?tab=mis-clases", reverse("dashboard") + "?tab=horario",
            reverse("dashboard") + "?tab=explorar&q=bio", reverse("dashboard") + "?tab=preferencias",
            reverse("dashboard") + "?tab=guardadas", reverse("course_create"), reverse("plans"),
            reverse("mini_landing"), reverse("mini_benchmark"), reverse("free_lesson"), reverse("api_lesson"),
            reverse("course_detail", args=[self.course.pk]), reverse("course_edit", args=[self.course.pk]),
            reverse("course_summary", args=[self.course.pk]), reverse("course_bank", args=[self.course.pk]),
            reverse("course_bank_csv", args=[self.course.pk]), reverse("course_answers_csv", args=[self.course.pk]),
            reverse("course_review", args=[self.course.pk]),
            reverse("practice_session", args=[self.course.pk, self.practice.pk]),
            reverse("lesson_detail", args=[self.job.pk]), reverse("lesson_job_status", args=[self.job.pk]),
            reverse("class_summary", args=[self.job.pk]), reverse("flashcards", args=[self.job.pk]),
            reverse("class_map", args=[self.job.pk]), reverse("matching_exercise", args=[self.job.pk]),
            reverse("cloze_exercise", args=[self.job.pk]), reverse("pipeline_visualization", args=[self.job.pk]),
            reverse("download_json", args=[self.job.pk]), reverse("health"),
        ]
        failures = []
        for url in pages:
            resp = self.client.get(url)
            if resp.status_code != 200:
                failures.append((url, resp.status_code))
        self.assertEqual(failures, [])
        # la clase compartida por enlace resuelve el token y redirige al detalle
        self.assertEqual(self.client.get(reverse("shared_lesson_detail", args=["tok123"])).status_code, 302)

    def test_anonymous_is_redirected_from_private_pages(self):
        self.client.logout()
        for name in ("dashboard", "course_create", "plans"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)
        self.assertEqual(self.client.get(reverse("course_detail", args=[self.course.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("health")).status_code, 200)
