"""Fecha de examen, limite de trabajos pendientes, ayudantes compartidos entre vistas y cola."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from learning import adaptive, job_queue, pipeline, summaries
from learning.models import Course, LessonJob, Plan, Profile, SummaryJob
from learning.tests_adaptive import MINI
from learning.tests_summaries import TRANSCRIPT
from learning.views import _common


class ExamDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ori", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.course = Course.objects.create(user=self.user, name="Fisica")
        LessonJob.objects.create(user=self.user, course=self.course, title="C", mode=LessonJob.Mode.API,
                                 status=LessonJob.Status.CORRECTED, corrected_output=MINI)
        self.client.force_login(self.user)

    def _know_student(self):
        session = adaptive.start_practice(self.user, self.course, target_count=4)
        while not session.is_complete:
            q = adaptive.Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            adaptive.answer_question(session, q.pk, next(o for o in q.options.all() if o.is_correct).pk)
            session.refresh_from_db()

    def test_exam_date_drives_countdown_and_plan(self):
        self._know_student()
        self.assertFalse(any(a["kind"] == "exam" for a in adaptive.daily_plan(self.user, self.course)))
        resp = self.client.post(reverse("course_edit", args=[self.course.pk]), {
            "name": "Fisica", "level": self.course.level, "exam_date": (timezone.localdate() + timedelta(days=3)).isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        self.course.refresh_from_db()
        self.assertIsNotNone(self.course.exam_date)
        plan = adaptive.daily_plan(self.user, self.course)
        self.assertEqual(plan[0]["kind"], "exam")
        self.assertIn("en 3 dias", plan[0]["title"])
        self.assertEqual(plan[0]["fields"]["focus"], "exam")
        page = self.client.get(reverse("course_detail", args=[self.course.pk]))
        self.assertContains(page, "Examen en 3 dias")
        self.course.exam_date = timezone.localdate() - timedelta(days=1)
        self.course.save()
        self.assertContains(self.client.get(reverse("course_detail", args=[self.course.pk])), "Examen pasado")
        self.assertFalse(any(a["kind"] == "exam" for a in adaptive.daily_plan(self.user, self.course)))


@override_settings(SIMA_MAX_PENDING_JOBS=2)
class PendingJobLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("uma", password="x")
        self.profile, _ = Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.BASIC, "credit_balance": 500})
        self.course = Course.objects.create(user=self.user, name="Biologia")
        self.jobs = [
            LessonJob.objects.create(user=self.user, course=self.course, title=f"Clase {i}", mode=LessonJob.Mode.API,
                                     status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript=TRANSCRIPT)
            for i in range(3)
        ]
        self.client.force_login(self.user)

    @patch("learning.job_queue.enqueue_summary_job")
    @patch("learning.services.resolve_backend", return_value="local")
    def test_limit_blocks_before_charging(self, _rb, _enqueue):
        summaries.create_summary_job(self.user, self.course, lesson=self.jobs[0])
        summaries.create_summary_job(self.user, self.course, lesson=self.jobs[1])
        self.assertEqual(job_queue.pending_jobs_for_user(self.user), 2)
        self.profile.refresh_from_db()
        balance = self.profile.credit_balance
        with self.assertRaises(summaries.SummaryUnavailable):
            summaries.create_summary_job(self.user, self.course, lesson=self.jobs[2])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.credit_balance, balance)  # no cobro
        self.assertEqual(SummaryJob.objects.count(), 2)
        resp = self.client.post(f"/clase/{self.jobs[2].pk}/resumen/", follow=True)
        self.assertContains(resp, "trabajos en proceso")
        SummaryJob.objects.update(status=SummaryJob.Status.DONE)
        self.assertEqual(job_queue.pending_jobs_for_user(self.user), 0)
        summaries.create_summary_job(self.user, self.course, lesson=self.jobs[2])
        self.assertEqual(SummaryJob.objects.count(), 3)


class SharedHelpersTests(TestCase):
    def test_views_reuse_queue_helpers(self):
        self.assertIs(_common._sync_class_session_for_job, pipeline._sync_class_session_status)
        self.assertIs(_common._compile_mini_for_render, pipeline._compile_mini_for_render)
        self.assertEqual(_common._normalize_verification_mode("nope"), pipeline._normalize_verification_mode("nope"))
        self.assertIs(job_queue.process_lesson_job, pipeline.process_lesson_job)  # reexport de compatibilidad
