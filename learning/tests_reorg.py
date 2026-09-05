"""Paquete de vistas, tablas heredadas eliminadas, editar/archivar curso, atajos de practica."""
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from learning import adaptive, models, views
from learning.models import Course, LessonJob, Plan, Profile
from learning.tests_adaptive import MINI


class ReorgTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ivo", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.course = Course.objects.create(user=self.user, name="Quimica")
        self.client.force_login(self.user)

    def test_legacy_quiz_tables_are_gone(self):
        self.assertFalse(hasattr(models, "QuizAttempt"))
        self.assertFalse(hasattr(models, "QuizResponse"))
        tables = set(connection.introspection.table_names())
        self.assertNotIn("learning_quizattempt", tables)
        self.assertNotIn("learning_quizresponse", tables)

    def test_views_package_exposes_every_url_callback(self):
        from learning import urls

        for pattern in urls.urlpatterns:
            callback = pattern.callback
            name = getattr(callback, "__name__", "")
            if callback.__module__.startswith("learning.views"):
                self.assertIs(getattr(views, name), callback, name)
        self.assertTrue(views.__name__ == "learning.views" and hasattr(views, "_get_accessible_job"))

    def test_course_edit_archive_and_restore(self):
        page = self.client.get(reverse("course_edit", args=[self.course.pk]))
        self.assertContains(page, "Editar curso")
        resp = self.client.post(reverse("course_edit", args=[self.course.pk]), {
            "name": "Quimica general", "academic_period": "2026-2", "level": self.course.level,
            "main_topics_text": "enlaces, estequiometria",
        })
        self.assertEqual(resp.status_code, 302, resp.content[:300])
        self.course.refresh_from_db()
        self.assertEqual(self.course.name, "Quimica general")
        self.assertIn("enlaces", self.course.main_topics)

        self.assertContains(self.client.get(reverse("course_detail", args=[self.course.pk])), "Archivar")
        resp = self.client.post(reverse("course_archive", args=[self.course.pk]))
        self.assertRedirects(resp, reverse("dashboard"))
        self.course.refresh_from_db()
        self.assertTrue(self.course.is_archived)
        self.assertEqual(self.client.get(reverse("course_detail", args=[self.course.pk])).status_code, 404)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "Cursos archivados (1)")
        self.assertContains(dashboard, "Restaurar")

        resp = self.client.post(reverse("course_archive", args=[self.course.pk]), {"action": "restore"})
        self.assertRedirects(resp, reverse("course_detail", args=[self.course.pk]))
        self.course.refresh_from_db()
        self.assertFalse(self.course.is_archived)

    def test_practice_page_has_hotkeys_and_live_feedback_region(self):
        LessonJob.objects.create(user=self.user, course=self.course, title="C", mode=LessonJob.Mode.API,
                                 status=LessonJob.Status.CORRECTED, corrected_output=MINI)
        session = adaptive.start_practice(self.user, self.course, target_count=3)
        page = self.client.get(reverse("practice_session", args=[self.course.pk, session.pk]))
        self.assertContains(page, "data-hotkeys")
        self.assertContains(page, "requestSubmit")
