from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from learning import adaptive, segments
from learning.job_queue import _sync_class_session_status, _sync_transcript_record
from learning.models import Course, LessonJob, Plan, Profile, Question, Summary, TranscriptSegment
from learning.tests_adaptive import MINI

TRANSCRIPT = (
    "Hoy vamos a hablar de la celula. La fotosintesis ocurre en los cloroplastos, "
    "que contienen clorofila, el pigmento que capta la luz. "
    "Durante la fotosintesis la planta libera oxigeno como producto. "
    "En cambio la respiracion celular ocurre en la mitocondria. "
    "La glucolisis produce piruvato y genera dos ATP netos en el citoplasma. "
    "Al final de la cadena de transporte el oxigeno acepta los electrones. "
    "Repasemos: cloroplasto para fotosintesis, mitocondria para respiracion celular."
)


class SegmentTests(TestCase):
    def test_text_windows_and_best_segment(self):
        segs = segments.build_segments_from_text(TRANSCRIPT, window_words=12)
        self.assertGreater(len(segs), 4)
        self.assertIsNone(segs[0]["start"])
        hit = segments.best_segment("Que molecula acepta electrones al final de la cadena? oxigeno", segs)
        self.assertIsNotNone(hit)
        self.assertIn("cadena de transporte", hit["text"])
        self.assertIsNone(segments.best_segment("zzz qqq", segs))

    def test_normalize_whisper_result_and_timestamp(self):
        text, segs = segments.normalize_whisper_result({
            "text": " hola mundo ",
            "segments": [{"start": 0.0, "end": 2.5, "text": " hola "}, {"start": 2.5, "end": 5.0, "text": "mundo"}, {"start": 5, "end": 6, "text": "  "}],
        })
        self.assertEqual(text, "hola mundo")
        self.assertEqual([s["text"] for s in segs], ["hola", "mundo"])
        self.assertEqual(segments.format_timestamp(754), "12:34")
        self.assertEqual(segments.format_timestamp(3725), "1:02:05")
        self.assertEqual(segments.format_timestamp(None), "")


class LoopUXTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("gabi", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.course = Course.objects.create(user=self.user, name="Biologia")
        self.job = LessonJob.objects.create(
            user=self.user, course=self.course, title="Clase 1", mode=LessonJob.Mode.API,
            status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript=TRANSCRIPT, tags="biologia",
        )
        self.client.force_login(self.user)

    def test_bank_sync_attaches_source_excerpts_and_stored_segments_keep_timestamps(self):
        quiz = adaptive.sync_question_bank(self.job)
        linked = Question.objects.filter(quiz=quiz).exclude(source_excerpt="")
        self.assertGreaterEqual(linked.count(), 3)
        q = Question.objects.get(quiz=quiz, external_id="i8")  # cadena de transporte
        self.assertIn("cadena de transporte", q.source_excerpt)
        self.assertIsNone(q.source_timestamp_seconds)

        session = _sync_class_session_status(self.job)
        _sync_transcript_record(self.job, segments=[
            {"start": 0.0, "end": 30.0, "text": "La fotosintesis ocurre en los cloroplastos y libera oxigeno", "order": 0},
            {"start": 30.0, "end": 61.0, "text": "Al final de la cadena de transporte el oxigeno acepta los electrones", "order": 1},
        ])
        self.assertEqual(TranscriptSegment.objects.filter(transcript__class_session=session).count(), 2)
        segments.attach_sources(quiz, session, self.job, force=True)
        q.refresh_from_db()
        self.assertEqual(q.source_timestamp_seconds, 30.0)

    def test_answer_redirects_with_last_and_page_shows_immediate_feedback(self):
        start = self.client.post(f"/cursos/{self.course.pk}/practicar/", {"target_count": "3"})
        session = adaptive.PracticeSession.objects.get(user=self.user)
        question = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
        wrong = next(o for o in question.options.all() if not o.is_correct)
        correct = next(o for o in question.options.all() if o.is_correct)
        Summary.objects.create(course=self.course, kind=Summary.Kind.CONCEPT, title="Concepto", content="Explicacion breve del concepto.", key_concepts=[question.topic])

        resp = self.client.post(f"/cursos/{self.course.pk}/practica/{session.pk}/responder/", {"question_id": question.pk, "option_id": wrong.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("?last=", resp.url)
        page = self.client.get(resp.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Incorrecto")
        self.assertContains(page, correct.text)
        self.assertContains(page, "Explicacion breve del concepto.")
        self.assertContains(page, "fb-source")  # extracto de la transcripcion

    def test_feedback_failed_items_carry_source_excerpt(self):
        session = adaptive.start_practice(self.user, self.course, target_count=3)
        while not session.is_complete:
            q = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            wrong = next(o for o in q.options.all() if not o.is_correct)
            adaptive.answer_question(session, q.pk, wrong.pk)
            session.refresh_from_db()
        failed = session.feedback["failed"]
        self.assertEqual(len(failed), 3)
        self.assertTrue(all("excerpt" in row and "timestamp_label" in row for row in failed))
        self.assertTrue(any(row["excerpt"] for row in failed))

    def test_legacy_quiz_routes_are_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse("quiz_attempt", args=[self.job.pk, 1])
        self.assertEqual(self.client.get(f"/clase/{self.job.pk}/quiz/1/").status_code, 404)
        detail = self.client.get(f"/clase/{self.job.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "quiz_attempt")
