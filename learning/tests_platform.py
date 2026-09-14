"""Resumenes en cola, worker en BD, simulacro, olvido por tema, banco del curso, salud y pipeline con IA simulada."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from learning import adaptive, job_queue, pipeline, summaries
from learning.models import (
    ClassSession, Course, LessonJob, Plan, PracticeSession, Profile, Question, ReinforcementJob, Summary, SummaryJob, Transcript,
)
from learning.tests_adaptive import MINI
from learning.tests_summaries import RAW, TRANSCRIPT


def _base(test):
    test.user = User.objects.create_user("ana", password="x", email="ana@example.com")
    test.profile, _ = Profile.objects.update_or_create(user=test.user, defaults={"plan": Plan.BASIC, "credit_balance": 100})
    test.course = Course.objects.create(user=test.user, name="Biologia")
    test.job = LessonJob.objects.create(
        user=test.user, course=test.course, title="Clase 1", mode=LessonJob.Mode.API,
        status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript=TRANSCRIPT,
    )
    test.client.force_login(test.user)


class SummaryQueueTests(TestCase):
    def setUp(self):
        _base(self)

    @patch("learning.job_queue.enqueue_summary_job")
    @patch("learning.services.resolve_backend", return_value="local")
    def test_create_job_charges_once_and_dedups(self, _rb, enqueue):
        job = summaries.create_summary_job(self.user, self.course, lesson=self.job)
        self.assertEqual(job.kind, SummaryJob.Kind.CLASS)
        self.assertEqual(job.status, SummaryJob.Status.QUEUED)
        enqueue.assert_called_once_with(job.pk)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.credit_balance, 100 - job.credits_charged)
        again = summaries.create_summary_job(self.user, self.course, lesson=self.job)
        self.assertEqual(again.pk, job.pk)  # pendiente: no cobra ni duplica
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.credit_balance, 100 - job.credits_charged)

    @patch("learning.job_queue.enqueue_summary_job")
    @patch("learning.services.call_ai", return_value=RAW)
    @patch("learning.services.resolve_backend", return_value="local")
    def test_run_job_stores_summary_and_view_flow(self, _rb, _ai, _enqueue):
        resp = self.client.post(f"/clase/{self.job.pk}/resumen/")
        self.assertEqual(resp.status_code, 302)
        page = self.client.get(resp.url)
        self.assertContains(page, "En cola")
        self.assertContains(page, 'http-equiv="refresh"')
        job = SummaryJob.objects.get()
        job_queue._process_summary_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, SummaryJob.Status.DONE)
        self.assertIsNotNone(job.summary)
        self.assertEqual(job.summary.kind, Summary.Kind.STRUCTURED)
        page = self.client.get(f"/clase/{self.job.pk}/resumen/")
        self.assertContains(page, "Fotosintesis y respiracion")
        self.assertNotContains(page, 'http-equiv="refresh"')
        # curso
        self.client.post(f"/cursos/{self.course.pk}/resumen/")
        course_job = SummaryJob.objects.get(kind=SummaryJob.Kind.COURSE)
        summaries.run_summary_job(course_job)
        course_job.refresh_from_db()
        self.assertEqual(course_job.status, SummaryJob.Status.DONE)
        self.assertEqual(Summary.objects.filter(kind=Summary.Kind.COURSE_ACCUMULATED).count(), 1)

    @patch("learning.job_queue.enqueue_summary_job")
    @patch("learning.services.call_ai", side_effect=RuntimeError("proveedor caido"))
    @patch("learning.services.resolve_backend", return_value="local")
    def test_failed_job_refunds_and_shows_error(self, _rb, _ai, _enqueue):
        job = summaries.create_summary_job(self.user, self.course, lesson=self.job)
        summaries.run_summary_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, SummaryJob.Status.ERROR)
        self.assertTrue(job.credits_refunded)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.credit_balance, 100)
        page = self.client.get(f"/clase/{self.job.pk}/resumen/")
        self.assertContains(page, "No pudimos generar el resumen")
        self.assertContains(page, "Generar resumen")

    @patch("learning.job_queue.enqueue_summary_job")
    @patch("learning.services.resolve_backend", return_value="local")
    def test_requeue_covers_summary_jobs(self, _rb, enqueue):
        job = summaries.create_summary_job(self.user, self.course, lesson=self.job)
        job.status = SummaryJob.Status.PROCESSING
        job.save()
        self.assertEqual(job_queue.requeue_orphaned_jobs("test"), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, SummaryJob.Status.QUEUED)


@override_settings(SIMA_QUEUE_MODE="db")
class DbWorkerTests(TransactionTestCase):
    """TransactionTestCase: el worker cierra conexiones entre trabajos, como en produccion."""

    def setUp(self):
        _base(self)

    @patch("learning.services.call_ai", return_value=RAW)
    @patch("learning.services.resolve_backend", return_value="local")
    def test_enqueue_is_noop_and_worker_claims_oldest_first(self, _rb, _ai):
        self.assertEqual(job_queue.queue_mode(), "db")
        lesson = LessonJob.objects.create(user=self.user, course=self.course, title="Pendiente", mode=LessonJob.Mode.API,
                                          status=LessonJob.Status.QUEUED, source_text="x" * 300)
        LessonJob.objects.filter(pk=lesson.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        job_queue.enqueue_lesson_job(lesson.pk)  # no-op en modo db
        self.assertTrue(job_queue._queue.empty())
        summary_job = summaries.create_summary_job(self.user, self.course, lesson=self.job)

        claimed = job_queue.claim_next_job()
        self.assertEqual(claimed[:2], ("lesson", lesson.pk))
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonJob.Status.PROCESSING)

        claimed = job_queue.claim_next_job()
        self.assertEqual(claimed, ("summary", summary_job.pk, "local"))
        job_queue.process_claimed(*claimed)
        summary_job.refresh_from_db()
        self.assertEqual(summary_job.status, SummaryJob.Status.DONE)
        self.assertIsNone(job_queue.claim_next_job())

        # trabajo atascado en PROCESSING vuelve a la cola
        LessonJob.objects.filter(pk=lesson.pk).update(updated_at=timezone.now() - timedelta(hours=5))
        self.assertEqual(job_queue.reset_stale_processing(120), 1)
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonJob.Status.QUEUED)
        snap = job_queue.queue_snapshot()
        self.assertEqual((snap["mode"], snap["lesson"]["queued"]), ("db", 1))

    @patch("learning.services.call_ai", return_value=RAW)
    @patch("learning.services.resolve_backend", return_value="local")
    def test_run_worker_once_processes_queue(self, _rb, _ai):
        summaries.create_summary_job(self.user, self.course)
        out = StringIO()
        call_command("run_worker", "--once", stdout=out)
        self.assertIn("Procesados 1", out.getvalue())
        self.assertEqual(SummaryJob.objects.get().status, SummaryJob.Status.DONE)

    def test_run_worker_refuses_thread_mode(self):
        from django.core.management.base import CommandError

        with override_settings(SIMA_QUEUE_MODE="thread"):
            with self.assertRaises(CommandError):
                call_command("run_worker", "--once", stdout=StringIO())


class ExamAndForgettingTests(TestCase):
    def setUp(self):
        _base(self)

    def _answer_all(self, session, correct=True):
        while not session.is_complete:
            q = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            pick = next(o for o in q.options.all() if o.is_correct == correct)
            adaptive.answer_question(session, q.pk, pick.pk)
            session.refresh_from_db()
        return session

    def test_exam_has_fixed_length_and_grade(self):
        session = adaptive.start_practice(self.user, self.course, target_count=6, focus="exam")
        self.assertEqual(session.focus, PracticeSession.Focus.EXAM)
        self.assertEqual(session.target_count, 6)
        self._answer_all(session, correct=True)
        fb = session.feedback
        self.assertEqual(fb["total"], 6)  # longitud fija: no se detuvo antes por precision
        self.assertTrue(fb["is_exam"])
        self.assertEqual(fb["grade"], 20.0)
        page = self.client.get(f"/cursos/{self.course.pk}/practica/{session.pk}/")
        self.assertContains(page, "/ 20")
        self.assertContains(page, "simulacro")
        detail = self.client.get(f"/cursos/{self.course.pk}/")
        self.assertContains(detail, "Simulacro (")

    def test_half_life_and_retention(self):
        self.assertEqual(adaptive.half_life_days([]), adaptive.HALF_LIFE_BASE_DAYS)
        self.assertEqual(adaptive.half_life_days([True, True, True]), 12.0)
        self.assertEqual(adaptive.half_life_days([True, True, False]), adaptive.HALF_LIFE_BASE_DAYS)
        old = (timezone.now() - timedelta(days=12)).isoformat()
        self.assertAlmostEqual(adaptive.topic_retention({"last_answered": old, "half_life_days": 12}), 0.5, places=2)
        self.assertEqual(adaptive.topic_retention({}), 1.0)

    def test_at_risk_topics_feed_plan_and_risk_focus(self):
        session = adaptive.start_practice(self.user, self.course, target_count=8)
        self._answer_all(session, correct=True)
        profile = adaptive.get_profile(self.user, self.course)
        self.assertIn("half_life_days", next(iter(profile.mastery_by_topic.values())))
        self.assertEqual(adaptive.at_risk_topics(profile), [])
        # simula que pasaron 60 dias
        future = timezone.now() + timedelta(days=60)
        risky = adaptive.at_risk_topics(profile, now=future)
        self.assertTrue(risky)
        self.assertLess(risky[0]["effective"], adaptive.RISK_THRESHOLD)
        with patch("learning.adaptive.timezone.now", return_value=future):
            plan = adaptive.daily_plan(self.user, self.course)
            self.assertTrue(any(a["kind"] == "risk" for a in plan))
            overview = adaptive.course_overview(self.user, self.course)
            self.assertTrue(overview["at_risk_topics"])
            risk_session = adaptive.start_practice(self.user, self.course, target_count=4, focus="risk")
            self.assertEqual(risk_session.focus, PracticeSession.Focus.RISK)
        # sin riesgo, el foco vuelve a equilibrado
        plain = adaptive.start_practice(self.user, self.course, target_count=4, focus="risk")
        self.assertEqual(plain.focus, PracticeSession.Focus.BALANCED)


class BankAndHealthTests(TestCase):
    def setUp(self):
        _base(self)

    def test_bank_report_page_and_csv_exports(self):
        session = adaptive.start_practice(self.user, self.course, target_count=4)
        while not session.is_complete:
            q = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            adaptive.answer_question(session, q.pk, next(o for o in q.options.all() if o.is_correct).pk)
            session.refresh_from_db()
        report = adaptive.bank_report(self.course)
        self.assertEqual(report["used"], 4)
        self.assertEqual(report["total"], Question.objects.filter(quiz__course=self.course).count())
        page = self.client.get(f"/cursos/{self.course.pk}/banco/")
        self.assertContains(page, "Banco de preguntas del curso")
        csv_resp = self.client.get(f"/cursos/{self.course.pk}/banco.csv")
        self.assertEqual(csv_resp["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("b_generada", csv_resp.content.decode("utf-8-sig"))
        answers = self.client.get(f"/cursos/{self.course.pk}/respuestas.csv").content.decode("utf-8-sig")
        self.assertEqual(answers.count("\n"), 5)  # cabecera + 4 respuestas

    def test_health_endpoint(self):
        self.client.logout()
        resp = self.client.get("/salud/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["database"], "ok")
        self.assertIn("lesson", data["queue"])
        self.assertIn("mode", data["queue"])


class PipelineSimulatedTests(TestCase):
    """El pipeline completo de una clase con el modelo simulado (modo MINI directo en la nube)."""

    def setUp(self):
        _base(self)

    @patch("learning.pipeline.use_direct_cloud_mini", return_value=True)
    @patch("learning.pipeline.generate_items", return_value=("PROMPT", MINI, "cloud"))
    @patch("learning.pipeline.resolve_backend", return_value="cloud")
    def test_text_lesson_end_to_end(self, _rb, _gen, _direct):
        job = LessonJob.objects.create(user=self.user, course=self.course, title="Clase 2", mode=LessonJob.Mode.API,
                                       status=LessonJob.Status.QUEUED, source_text=TRANSCRIPT, ai_backend="cloud")
        pipeline.process_lesson_job(job.pk, "cloud")
        job.refresh_from_db()
        self.assertEqual(job.status, LessonJob.Status.CORRECTED, job.error)
        self.assertIn("i1|", job.corrected_output)
        self.assertTrue(job.verification_output.startswith("v|"))
        session = ClassSession.objects.get(legacy_lesson_job=job)
        self.assertEqual(session.status, ClassSession.ProcessingStatus.READY)
        self.assertTrue(Transcript.objects.filter(class_session=session).exists())
        bank = Question.objects.filter(quiz__class_session=session)
        self.assertGreaterEqual(bank.count(), 5)
        self.assertTrue(bank.exclude(source_excerpt="").exists())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.api_classes_used, 1)
        practice = adaptive.start_practice(self.user, self.course, target_count=3, lesson=job)
        self.assertIsNotNone(practice.current_question_id)

    @patch("learning.pipeline.generate_items", side_effect=RuntimeError("proveedor caido"))
    @patch("learning.pipeline.resolve_backend", return_value="cloud")
    def test_pipeline_error_is_recorded(self, _rb, _gen):
        job = LessonJob.objects.create(user=self.user, course=self.course, title="Clase 3", mode=LessonJob.Mode.API,
                                       status=LessonJob.Status.QUEUED, source_text=TRANSCRIPT)
        pipeline.process_lesson_job(job.pk, "cloud")
        job.refresh_from_db()
        self.assertEqual(job.status, LessonJob.Status.ERROR)
        self.assertIn("proveedor caido", job.error)
        self.assertEqual(ClassSession.objects.get(legacy_lesson_job=job).status, ClassSession.ProcessingStatus.ERROR)
