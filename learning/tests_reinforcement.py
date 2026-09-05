from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from learning import adaptive, adaptive_generation
from learning.models import (
    Course,
    CreditLedgerEntry,
    Flashcard,
    LessonJob,
    Plan,
    PracticeSession,
    Profile,
    Question,
    Quiz,
    Recommendation,
    ReinforcementJob,
    Summary,
)
from learning.tests_adaptive import MINI

TRANSCRIPT = (
    "La fotosintesis ocurre en los cloroplastos y libera oxigeno. "
    "La respiracion celular ocurre en la mitocondria; la glucolisis produce piruvato y dos ATP netos, "
    "y el oxigeno acepta los electrones al final de la cadena de transporte. "
) * 6

RAW_AI_OUTPUT = """Aqui tienes el refuerzo:
a|m=IRT3PL|d=20260905|n=3|l=es|t=respiracion|bd=1,2,0,0,0,0|cat=0,-3,3,0.3,10,SH
i1|L1|Respiracion celular|En que organelo ocurre la respiracion celular?|mitocondria*,cloroplasto,nucleo,vacuola|1.0,-0.3,0.25|2|biologia,0.2,low
i2|L2|Respiracion celular|Que producto final genera la glucolisis?|piruvato*,glucosa,fructosa,lactosa|1.1,0.0,0.25|3|biologia,0.2,medium
i3|L2|Respiracion celular|Que molecula acepta electrones al final de la cadena?|oxigeno*,nitrogeno,carbono,helio|1.2,0.2,0.25|3|biologia,0.2,medium

EXPLICACIONES
e1|Respiracion celular|Glucolisis|La glucolisis rompe la glucosa en dos piruvatos y produce dos ATP netos. Ocurre en el citoplasma y no necesita oxigeno.|Que produce la glucolisis?|Dos piruvatos y dos ATP netos
e2|Respiracion celular|Cadena de transporte|El oxigeno es el aceptor final de electrones; sin el, la cadena se detiene y cae la produccion de ATP.|Cual es el aceptor final de electrones?|El oxigeno
"""


class ReinforcementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("beto", password="x")
        self.profile, _ = Profile.objects.update_or_create(
            user=self.user, defaults={"plan": Plan.BASIC, "credit_balance": 100}
        )
        self.course = Course.objects.create(user=self.user, name="Biologia")
        self.job = LessonJob.objects.create(
            user=self.user, course=self.course, title="Clase 1", mode=LessonJob.Mode.API,
            status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript=TRANSCRIPT, tags="biologia",
        )

    def _make_weak_profile(self):
        session = adaptive.start_practice(self.user, self.course, target_count=7)
        guard = 0
        while not session.is_complete and guard < 30:
            guard += 1
            question = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            options = list(question.options.all())
            pick = next(o for o in options if o.is_correct) if question.topic == "Fotosintesis" else next(o for o in options if not o.is_correct)
            adaptive.answer_question(session, question.pk, pick.pk)
            session.refresh_from_db()
        return session

    @mock.patch("learning.job_queue.enqueue_reinforcement_job")
    def test_create_job_charges_credits_and_enqueues(self, enqueue):
        session = self._make_weak_profile()
        job = adaptive_generation.create_reinforcement_job(self.user, self.course, practice_session=session)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.topics, ["Respiracion celular"])
        self.assertGreater(job.credits_charged, 0)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.credit_balance, 100 - job.credits_charged)
        self.assertTrue(CreditLedgerEntry.objects.filter(user=self.user, amount=-job.credits_charged).exists())
        enqueue.assert_called_once_with(job.pk)

    def test_create_job_requires_weak_topics_and_credits(self):
        with self.assertRaises(adaptive_generation.ReinforcementUnavailable):
            adaptive_generation.create_reinforcement_job(self.user, self.course)
        self._make_weak_profile()
        self.profile.credit_balance = 1
        self.profile.save()
        with self.assertRaises(adaptive_generation.ReinforcementUnavailable):
            adaptive_generation.create_reinforcement_job(self.user, self.course)

    @mock.patch("learning.adaptive_generation.call_ai", return_value=RAW_AI_OUTPUT)
    @mock.patch("learning.job_queue.enqueue_reinforcement_job")
    def test_run_reinforcement_adds_items_explanations_and_flashcards(self, _enqueue, call_ai):
        session = self._make_weak_profile()
        before = len(adaptive.load_bank(self.course))
        job = adaptive_generation.create_reinforcement_job(self.user, self.course, practice_session=session)
        job = adaptive_generation.run_reinforcement(job)

        self.assertEqual(job.status, "done", job.error)
        prompt = call_ai.call_args.args[0]
        self.assertIn("Respiracion celular", prompt)
        self.assertIn("theta=", prompt)
        self.assertIn("[Clase: Clase 1]", prompt)

        quiz = job.quiz
        self.assertEqual(quiz.quiz_type, Quiz.QuizType.REINFORCEMENT)
        self.assertEqual(quiz.questions.count(), 3)
        self.assertEqual(len(adaptive.load_bank(self.course)), before + 3)
        self.assertEqual(Summary.objects.filter(course=self.course, kind=Summary.Kind.CONCEPT).count(), 2)
        self.assertEqual(Flashcard.objects.filter(course=self.course, topic="Respiracion celular").count(), 2)
        self.assertTrue(Recommendation.objects.filter(user=self.user, title__startswith="Practica el refuerzo").exists())

        # el refuerzo entra en la practica en modo debil
        follow_up = adaptive.start_practice(self.user, self.course, target_count=3, focus="weak")
        self.assertEqual(Question.objects.get(pk=follow_up.current_question_id).topic, "Respiracion celular")

    @mock.patch("learning.adaptive_generation.call_ai", side_effect=RuntimeError("proveedor caido"))
    @mock.patch("learning.job_queue.enqueue_reinforcement_job")
    def test_failed_reinforcement_refunds_credits(self, _enqueue, _call_ai):
        session = self._make_weak_profile()
        job = adaptive_generation.create_reinforcement_job(self.user, self.course, practice_session=session)
        charged = job.credits_charged
        job = adaptive_generation.run_reinforcement(job)
        self.assertEqual(job.status, "error")
        self.assertIn("proveedor caido", job.error)
        self.assertTrue(job.credits_refunded)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.credit_balance, 100)
        self.assertTrue(CreditLedgerEntry.objects.filter(user=self.user, amount=charged).exists())

    def test_parse_explanations_tolerates_short_lines(self):
        rows = adaptive_generation.parse_explanations("e1|Tema|Concepto|Explica.\ne2|Tema|Otro|Texto|Pregunta?|Resp\nbasura")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["question"], "¿Que es Concepto?")
        self.assertEqual(rows[1]["answer"], "Resp")

    # ---- reemplazo del quiz por clase ------------------------------------
    def test_class_quiz_now_starts_a_course_practice_limited_to_that_class(self):
        other = LessonJob.objects.create(
            user=self.user, course=self.course, title="Clase 2", mode=LessonJob.Mode.API,
            status=LessonJob.Status.CORRECTED, tags="biologia",
            corrected_output=MINI.replace("Fotosintesis", "Genetica").replace("Respiracion celular", "Mitosis"),
        )
        self.client.force_login(self.user)
        resp = self.client.post(f"/clase/{other.pk}/quiz/iniciar/", {"target_count": "5"})
        self.assertEqual(resp.status_code, 302)
        session = PracticeSession.objects.get(user=self.user)
        self.assertEqual(session.lesson_id, other.pk)
        self.assertIn(f"/cursos/{self.course.pk}/practica/{session.pk}/", resp.url)
        served = Question.objects.get(pk=session.current_question_id)
        self.assertIn(served.topic, {"Genetica", "Mitosis"})

    @mock.patch("learning.job_queue.enqueue_reinforcement_job")
    def test_reinforcement_views(self, _enqueue):
        session = self._make_weak_profile()
        self.client.force_login(self.user)
        resp = self.client.post(f"/cursos/{self.course.pk}/refuerzo/", {"practice_session": session.pk})
        self.assertEqual(resp.status_code, 302)
        job = ReinforcementJob.objects.get(user=self.user)
        page = self.client.get(resp.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Generando material")
        detail = self.client.get(f"/cursos/{self.course.pk}/")
        self.assertContains(detail, "Generar refuerzo")
