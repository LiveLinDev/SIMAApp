from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from learning import adaptive, progress, reminders, summaries
from learning.models import Course, CreditLedgerEntry, LessonJob, Plan, Profile, Question, Summary, UserPreference
from learning.tests_adaptive import MINI

TRANSCRIPT = ("La fotosintesis ocurre en los cloroplastos y libera oxigeno. " * 8) + (
    "La respiracion celular ocurre en la mitocondria y produce ATP. " * 8
)
RAW = """t|Fotosintesis y respiracion
c|Cloroplasto: sede de la fotosintesis
c|Mitocondria: sede de la respiracion celular
p|La fotosintesis capta luz en los cloroplastos y libera oxigeno.
p|La respiracion celular degrada glucosa en la mitocondria y produce ATP.
r|Repasar la diferencia entre ambos organelos
"""


class ParseTests(TestCase):
    def test_parse_summary_response(self):
        parsed = summaries.parse_summary_response(RAW)
        self.assertEqual(parsed["title"], "Fotosintesis y respiracion")
        self.assertEqual(len(parsed["key_concepts"]), 2)
        self.assertIn("libera oxigeno", parsed["content"])
        self.assertIn("Que repasar primero", parsed["content"])

    def test_parse_falls_back_to_plain_text(self):
        parsed = summaries.parse_summary_response("Primer parrafo.\n\nSegundo parrafo.", fallback_title="X")
        self.assertEqual(parsed["title"], "X")
        self.assertEqual(parsed["content"], "Primer parrafo.\n\nSegundo parrafo.")


class SummaryGenerationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("lu", password="x", email="lu@example.com")
        self.profile, _ = Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.FREE, "credit_balance": 50})
        self.course = Course.objects.create(user=self.user, name="Biologia")
        self.job = LessonJob.objects.create(
            user=self.user, course=self.course, title="Clase 1", mode=LessonJob.Mode.API,
            status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript=TRANSCRIPT,
        )
        self.client.force_login(self.user)

    @patch("learning.services.resolve_backend", return_value="local")
    @patch("learning.services.call_ai", return_value=RAW)
    def test_class_summary_charges_credits_and_upserts(self, call_ai, _rb):
        summary = summaries.generate_class_summary(self.user, self.job)
        self.assertEqual(summary.kind, Summary.Kind.STRUCTURED)
        self.assertEqual(summary.class_session.legacy_lesson_job_id, self.job.pk)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.credit_balance, 50 - summaries.estimate_summary_cost("local").amount)
        self.assertEqual(CreditLedgerEntry.objects.filter(action=CreditLedgerEntry.Action.SUMMARY_GENERATION).count(), 1)
        prompt = call_ai.call_args[0][0]
        self.assertIn("TRANSCRIPCION", prompt)
        self.assertIn("cloroplastos", prompt)
        summaries.generate_class_summary(self.user, self.job)  # regenerar no duplica
        self.assertEqual(Summary.objects.filter(course=self.course, kind=Summary.Kind.STRUCTURED).count(), 1)

    @patch("learning.services.resolve_backend", return_value="local")
    @patch("learning.services.call_ai", side_effect=RuntimeError("proveedor caido"))
    def test_failed_summary_refunds(self, _ai, _rb):
        with self.assertRaises(summaries.SummaryUnavailable):
            summaries.generate_class_summary(self.user, self.job)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.credit_balance, 50)
        self.assertFalse(Summary.objects.exists())

    def test_insufficient_credits_or_short_transcript(self):
        self.profile.credit_balance = 1
        self.profile.save()
        with self.assertRaises(summaries.SummaryUnavailable):
            summaries.generate_class_summary(self.user, self.job)
        self.job.transcript = "corto"
        self.job.save()
        self.profile.credit_balance = 50
        self.profile.save()
        with self.assertRaises(summaries.SummaryUnavailable):
            summaries.generate_class_summary(self.user, self.job)

    @patch("learning.services.resolve_backend", return_value="local")
    @patch("learning.services.call_ai", return_value=RAW)
    def test_course_summary_uses_class_summaries_or_transcripts(self, call_ai, _rb):
        course_summary = summaries.generate_course_summary(self.user, self.course)
        self.assertEqual(course_summary.kind, Summary.Kind.COURSE_ACCUMULATED)
        self.assertIn("[Clase 1]", call_ai.call_args[0][0])  # sin resumenes de clase: transcripciones
        summaries.generate_class_summary(self.user, self.job)
        summaries.generate_course_summary(self.user, self.course)
        self.assertIn("Conceptos:", call_ai.call_args[0][0])  # ahora integra el resumen de clase
        self.assertEqual(Summary.objects.filter(kind=Summary.Kind.COURSE_ACCUMULATED).count(), 1)

    @patch("learning.job_queue.enqueue_summary_job")
    @patch("learning.services.resolve_backend", return_value="local")
    @patch("learning.services.call_ai", return_value=RAW)
    def test_summary_views(self, _ai, _rb, _enqueue):
        from learning import job_queue
        from learning.models import SummaryJob

        page = self.client.get(f"/clase/{self.job.pk}/resumen/")
        self.assertContains(page, "Generar resumen")
        resp = self.client.post(f"/clase/{self.job.pk}/resumen/")
        self.assertEqual(resp.status_code, 302)
        job_queue._process_summary_job(SummaryJob.objects.get().pk)  # lo que haria el worker
        page = self.client.get(resp.url)
        self.assertContains(page, "Fotosintesis y respiracion")
        self.assertContains(page, "Regenerar resumen")
        page = self.client.get(f"/cursos/{self.course.pk}/resumen/")
        self.assertContains(page, "Resúmenes por clase")
        resp = self.client.post(f"/cursos/{self.course.pk}/resumen/")
        self.assertEqual(resp.status_code, 302)
        job_queue._process_summary_job(SummaryJob.objects.get(kind=SummaryJob.Kind.COURSE).pk)
        detail = self.client.get(f"/cursos/{self.course.pk}/")
        self.assertContains(detail, "Resumen del curso")
        lesson = self.client.get(f"/clase/{self.job.pk}/")
        self.assertContains(lesson, f"/clase/{self.job.pk}/resumen/")


class ProgressTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mar", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.course = Course.objects.create(user=self.user, name="Biologia")
        LessonJob.objects.create(user=self.user, course=self.course, title="C", mode=LessonJob.Mode.API, status=LessonJob.Status.CORRECTED, corrected_output=MINI)

    def test_series_and_svg(self):
        empty = progress.progress_panel(self.user, self.course)
        self.assertFalse(empty["has_data"])
        self.assertIn("<svg", empty["svg"])
        session = adaptive.start_practice(self.user, self.course, target_count=3)
        while not session.is_complete:
            q = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            adaptive.answer_question(session, q.pk, next(o for o in q.options.all() if o.is_correct).pk)
            session.refresh_from_db()
        panel = progress.progress_panel(self.user, self.course)
        self.assertTrue(panel["has_data"])
        today = panel["series"][-1]
        self.assertEqual((today["answered"], today["correct"]), (3, 3))
        self.assertIsNotNone(today["theta"])
        self.assertEqual(panel["stats"]["current"]["accuracy"], 100)
        self.assertIn('fill="var(--acid)"', panel["svg"])
        self.assertIn("<path", panel["svg"]) if len([r for r in panel["series"] if r["theta"] is not None]) >= 2 else None
        overview = adaptive.course_overview(self.user, self.course)
        self.assertIn("progress", overview)
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/dashboard/"), "progress-svg")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="sima@example.com", SIMA_SITE_URL="http://sima.test")
class ReminderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("noe", password="x", email="noe@example.com", first_name="Noe")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED, "current_streak": 3})
        self.course = Course.objects.create(user=self.user, name="Biologia")
        LessonJob.objects.create(user=self.user, course=self.course, title="C", mode=LessonJob.Mode.API, status=LessonJob.Status.CORRECTED, corrected_output=MINI)

    def test_reminder_only_when_enabled_and_not_studied_today(self):
        self.assertIsNone(reminders.build_reminder(self.user))
        UserPreference.objects.update_or_create(user=self.user, defaults={"email_reminders": True})
        reminder = reminders.build_reminder(self.user)
        self.assertIsNotNone(reminder)
        self.assertIn("racha de 3 dias", reminder.body)
        self.assertIn("http://sima.test/cursos/", reminder.body)
        sent = reminders.send_reminders()
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["noe@example.com"])
        profile = Profile.objects.get(user=self.user)
        profile.last_study_date = timezone.localdate()
        profile.save()
        self.assertIsNone(reminders.build_reminder(self.user))

    def test_dashboard_preferences_toggle_email_reminders(self):
        self.client.force_login(self.user)
        self.client.post("/dashboard/", {"dashboard_action": "update_preferences", "daily_goal": "12", "email_reminders": "on"})
        prefs = UserPreference.objects.get(user=self.user)
        self.assertTrue(prefs.email_reminders)
        self.assertEqual(prefs.daily_goal, 12)
        self.client.post("/dashboard/", {"dashboard_action": "update_preferences", "daily_goal": "12"})
        prefs.refresh_from_db()
        self.assertFalse(prefs.email_reminders)
