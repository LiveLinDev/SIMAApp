from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from learning import job_queue
from learning.models import LessonJob


class RequeueOrphanedJobsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="x")

    def _job(self, status, backend="auto"):
        return LessonJob.objects.create(
            user=self.user,
            mode=LessonJob.Mode.API,
            status=status,
            ai_backend=backend,
            processing_log="Preparando contenido - Leyendo texto.",
        )

    @mock.patch("learning.job_queue.enqueue_lesson_job")
    def test_requeues_only_queued_and_processing(self, enqueue):
        queued = self._job(LessonJob.Status.QUEUED)
        processing = self._job(LessonJob.Status.PROCESSING, backend="anthropic")
        done = self._job(LessonJob.Status.CORRECTED)
        failed = self._job(LessonJob.Status.ERROR)

        count = job_queue.requeue_orphaned_jobs(reason="prueba")

        self.assertEqual(count, 2)
        enqueue.assert_has_calls(
            [mock.call(queued.pk, "auto"), mock.call(processing.pk, "anthropic")],
            any_order=True,
        )
        self.assertEqual(enqueue.call_count, 2)

        processing.refresh_from_db()
        self.assertEqual(processing.status, LessonJob.Status.QUEUED)
        self.assertEqual(processing.processing_stage, "En cola")
        self.assertIn("Reencolado", processing.processing_log)
        self.assertIn("prueba", processing.processing_log)
        # el log previo se conserva
        self.assertIn("Preparando contenido", processing.processing_log)

        done.refresh_from_db()
        failed.refresh_from_db()
        self.assertEqual(done.status, LessonJob.Status.CORRECTED)
        self.assertEqual(failed.status, LessonJob.Status.ERROR)

    @mock.patch("learning.job_queue.enqueue_lesson_job", side_effect=RuntimeError("cola llena"))
    def test_full_queue_does_not_abort_the_sweep(self, enqueue):
        self._job(LessonJob.Status.QUEUED)
        self._job(LessonJob.Status.QUEUED)

        count = job_queue.requeue_orphaned_jobs()

        self.assertEqual(count, 0)
        self.assertEqual(enqueue.call_count, 2)

    @mock.patch("learning.job_queue.enqueue_lesson_job")
    def test_nothing_pending_is_a_noop(self, enqueue):
        self._job(LessonJob.Status.CORRECTED)
        self.assertEqual(job_queue.requeue_orphaned_jobs(), 0)
        enqueue.assert_not_called()
