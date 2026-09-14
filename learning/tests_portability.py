"""Exportar e importar un curso (ida y vuelta) y sus comandos."""
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from learning import adaptive, portability
from learning.models import Course, Flashcard, LessonJob, Plan, Profile, Question, Summary
from learning.pipeline import _sync_class_session_status
from learning.tests_adaptive import MINI
from learning.tests_summaries import TRANSCRIPT


class PortabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("exp", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.course = Course.objects.create(user=self.user, name="Biologia", main_topics=["celula"], academic_period="2026-2")
        self.job = LessonJob.objects.create(user=self.user, course=self.course, title="Clase 1", mode=LessonJob.Mode.API,
                                            status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript=TRANSCRIPT,
                                            tags="biologia", visibility=LessonJob.Visibility.PUBLIC)
        session = _sync_class_session_status(self.job)
        adaptive.sync_question_bank(self.job)
        Summary.objects.create(course=self.course, class_session=session, kind=Summary.Kind.STRUCTURED, title="R1", content="Resumen de clase.", key_concepts=["a"])
        Flashcard.objects.create(course=self.course, class_session=session, question="Q", answer="A", topic="Fotosintesis", ease_factor=2.7, interval_days=6, repetitions=2)

    def test_roundtrip_rebuilds_bank_and_links(self):
        payload = portability.export_course(self.course)
        self.assertEqual(payload["format"], portability.FORMAT)
        self.assertEqual(len(payload["lessons"]), 1)
        self.assertEqual(payload["summaries"][0]["lesson_index"], 0)
        text = portability.dumps(payload)
        other = User.objects.create_user("imp", password="x")
        course = portability.import_course(other, json.loads(text), name="Biologia (copia)")
        self.assertEqual(course.user, other)
        self.assertEqual(course.name, "Biologia (copia)")
        self.assertEqual(course.main_topics, ["celula"])
        job = LessonJob.objects.get(course=course)
        self.assertEqual(job.visibility, LessonJob.Visibility.PRIVATE)  # nunca se importa como publica
        self.assertEqual(job.transcript, TRANSCRIPT)
        self.assertEqual(Question.objects.filter(quiz__course=course).count(), Question.objects.filter(quiz__course=self.course).count())
        summary = Summary.objects.get(course=course)
        self.assertEqual(summary.class_session.legacy_lesson_job_id, job.pk)
        card = Flashcard.objects.get(course=course)
        self.assertEqual((card.ease_factor, card.interval_days, card.repetitions), (2.7, 6, 2))
        # el curso importado se puede practicar de inmediato
        practice = adaptive.start_practice(other, course, target_count=3)
        self.assertIsNotNone(practice.current_question_id)

    def test_commands(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "curso.json"
            stdout = StringIO()
            call_command("export_course", self.course.pk, "--out", str(out), stdout=stdout)
            self.assertIn("1 clases", stdout.getvalue())
            self.assertTrue(out.exists())
            stdout = StringIO()
            call_command("import_course", str(out), "--user", "exp", "--name", "Copia", stdout=stdout)
            self.assertIn("Importado", stdout.getvalue())
            self.assertTrue(Course.objects.filter(user=self.user, name="Copia").exists())

    def test_rejects_unknown_format(self):
        with self.assertRaises(ValueError):
            portability.import_course(self.user, {"format": "otro", "course": {}})


class FixtureRestoreTests(TestCase):
    def test_loaddata_with_profiles_does_not_duplicate(self):
        import json
        import tempfile

        from django.contrib.auth import get_user_model
        from django.core.management import call_command

        from learning.models import Profile, UserPreference

        user = get_user_model().objects.create_user("respaldo", password="x-12345678")
        Profile.objects.filter(user=user).update(credit_balance=77)
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False, encoding="utf-8") as fh:
            call_command("dumpdata", "auth.user", "learning.profile", "learning.userpreference", stdout=fh)
            path = fh.name
        get_user_model().objects.all().delete()
        call_command("loaddata", path, verbosity=0)
        self.assertEqual(Profile.objects.get(user__username="respaldo").credit_balance, 77)
        self.assertEqual(UserPreference.objects.filter(user__username="respaldo").count(), 1)
        json.load(open(path, encoding="utf-8"))
