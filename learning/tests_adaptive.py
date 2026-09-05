from django.contrib.auth.models import User
from django.test import TestCase

from learning import adaptive
from learning.models import (
    AdaptiveProfile,
    AnswerOption,
    Course,
    LessonJob,
    Plan,
    PracticeSession,
    Profile,
    Question,
    Recommendation,
    StudentAnswer,
    StudyActivity,
)

HEADER = "a|m=IRT3PL|d=20260905|n=8|l=es|t=biologia|bd=3,3,2,0,0,0|cat=0,-3,3,0.3,10,SH"
ITEMS = [
    "i1|L1|Fotosintesis|Donde ocurre la fotosintesis?|cloroplasto*,nucleo,ribosoma,vacuola|1.0,-0.8,0.25|1|biologia,0.2,low",
    "i2|L1|Fotosintesis|Que gas libera la fotosintesis?|oxigeno*,nitrogeno,helio,argon|0.9,-0.4,0.25|2|biologia,0.2,low",
    "i3|L2|Fotosintesis|Que pigmento capta la luz?|clorofila*,melanina,hemoglobina,queratina|1.1,0.0,0.25|3|biologia,0.2,medium",
    "i4|L2|Fotosintesis|Que molecula aporta energia al ciclo de Calvin?|ATP*,ADN,ARN,NADH|1.2,0.4,0.25|3|biologia,0.2,medium",
    "i5|L1|Respiracion celular|Donde ocurre la respiracion celular?|mitocondria*,cloroplasto,lisosoma,peroxisoma|1.0,-0.6,0.25|2|biologia,0.2,low",
    "i6|L2|Respiracion celular|Que produce la glucolisis?|piruvato*,glucosa,sacarosa,lactosa|1.0,0.1,0.25|3|biologia,0.2,medium",
    "i7|L3|Respiracion celular|Cuantos ATP netos genera la glucolisis?|dos*,cuatro|1.3,0.6,0.25|4|biologia,0.2,high",
    "i8|L3|Respiracion celular|Que molecula acepta electrones al final de la cadena?|oxigeno*,carbono,hidrogeno,nitrogeno|1.4,0.9,0.25|4|biologia,0.2,high",
]
MINI = "\n".join([HEADER, *ITEMS])


class AdaptiveEngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ana", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.course = Course.objects.create(user=self.user, name="Biologia General")
        self.job = LessonJob.objects.create(
            user=self.user, course=self.course, title="Clase 1", mode=LessonJob.Mode.API,
            status=LessonJob.Status.CORRECTED, corrected_output=MINI, tags="biologia",
        )

    # ---- banco -----------------------------------------------------------
    def test_sync_bank_persists_valid_items_only(self):
        quiz = adaptive.sync_question_bank(self.job)
        self.assertIsNotNone(quiz)
        questions = list(quiz.questions.all())
        # i7 solo tiene 2 alternativas: se descarta como en build_bank()
        self.assertEqual(len(questions), 7)
        self.assertNotIn("i7", [q.external_id for q in questions])
        self.assertEqual(AnswerOption.objects.filter(question__quiz=quiz).count(), 28)
        self.assertEqual(AnswerOption.objects.filter(question__quiz=quiz, is_correct=True).count(), 7)
        q1 = quiz.questions.get(external_id="i1")
        self.assertEqual(q1.bloom_level, "L1")
        self.assertEqual(q1.topic, "Fotosintesis")
        self.assertAlmostEqual(q1.irt_b, -0.8)

    def test_sync_bank_is_idempotent_and_updates_changed_items(self):
        adaptive.sync_question_bank(self.job)
        changed = MINI.replace("Donde ocurre la fotosintesis?", "En que organelo ocurre la fotosintesis?")
        self.job.corrected_output = changed
        self.job.save()
        quiz = adaptive.sync_question_bank(self.job)
        self.assertEqual(quiz.questions.count(), 7)
        self.assertEqual(quiz.questions.get(external_id="i1").prompt, "En que organelo ocurre la fotosintesis?")
        self.assertEqual(adaptive.sync_course_bank(self.course), 0)  # ya esta al dia

    # ---- sesion completa --------------------------------------------------
    def _run_session(self, target=7, focus="balanced", correct_topics=("Fotosintesis",)):
        session = adaptive.start_practice(self.user, self.course, target_count=target, focus=focus)
        guard = 0
        while not session.is_complete and guard < 30:
            guard += 1
            question = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            options = list(question.options.all())
            if question.topic in correct_topics:
                choice = next(o for o in options if o.is_correct)
            else:
                choice = next(o for o in options if not o.is_correct)
            adaptive.answer_question(session, question.pk, choice.pk)
            session.refresh_from_db()
        return session

    def test_practice_session_builds_profile_feedback_and_recommendations(self):
        session = self._run_session()
        self.assertTrue(session.is_complete)
        self.assertEqual(session.answers.count(), session.target_count)
        fb = session.feedback
        self.assertEqual(fb["total"], 7)
        self.assertEqual(fb["correct"], 4)          # 4 de fotosintesis bien, 3 de respiracion mal
        self.assertTrue(fb["failed"])
        self.assertTrue(all(item["topic"] == "Respiracion celular" for item in fb["failed"]))
        self.assertTrue(all(item["correct"] for item in fb["failed"]))

        profile = AdaptiveProfile.objects.get(user=self.user, course=self.course)
        self.assertIn("Respiracion celular", profile.weak_topics)
        self.assertIn("Fotosintesis", profile.strong_topics)
        self.assertLess(profile.standard_error, 9.99)
        self.assertEqual(profile.mastery_by_topic["Fotosintesis"]["answers"], 4)

        recs = Recommendation.objects.filter(user=self.user, course=self.course, status="pending")
        self.assertTrue(recs.filter(title__contains="Respiracion celular").exists())

        prof = Profile.objects.get(user=self.user)
        self.assertEqual(prof.current_streak, 1)
        self.assertGreater(prof.total_xp, 0)
        self.assertEqual(StudyActivity.objects.filter(user=self.user, course=self.course).count(), 1)
        self.assertEqual(StudentAnswer.objects.filter(practice_session=session).count(), 7)

    def test_second_session_starts_from_known_theta_and_weak_focus_targets_weak_topic(self):
        self._run_session()
        profile = AdaptiveProfile.objects.get(user=self.user, course=self.course)
        second = adaptive.start_practice(self.user, self.course, target_count=3, focus="weak")
        self.assertEqual(second.focus, "weak")
        self.assertAlmostEqual(second.theta_start, profile.theta)
        first_question = Question.objects.get(pk=second.current_question_id)
        self.assertEqual(first_question.topic, "Respiracion celular")

    def test_recently_correct_items_are_not_repeated_when_bank_allows(self):
        first = self._run_session(target=3, correct_topics=("Fotosintesis", "Respiracion celular"))
        seen = set(first.served_question_ids)
        second = adaptive.start_practice(self.user, self.course, target_count=3)
        self.assertNotIn(second.current_question_id, seen)

    def test_start_practice_without_items_raises(self):
        empty = Course.objects.create(user=self.user, name="Vacio")
        with self.assertRaises(adaptive.NoItemsError):
            adaptive.start_practice(self.user, empty)

    def test_answer_rejects_stale_question(self):
        session = adaptive.start_practice(self.user, self.course, target_count=3)
        other = Question.objects.exclude(pk=session.current_question_id).first()
        with self.assertRaises(ValueError):
            adaptive.answer_question(session, other.pk, other.options.first().pk)

    # ---- vistas --------------------------------------------------------------
    def test_views_round_trip(self):
        self.client.force_login(self.user)
        detail = self.client.get(f"/cursos/{self.course.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Practicar")

        start = self.client.post(f"/cursos/{self.course.pk}/practicar/", {"target_count": "4", "focus": "balanced"})
        self.assertEqual(start.status_code, 302)
        session = PracticeSession.objects.get(user=self.user, course=self.course)
        page = self.client.get(start.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="option_id"')

        while not session.is_complete:
            question = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            option = next(o for o in question.options.all() if o.is_correct)
            resp = self.client.post(
                f"/cursos/{self.course.pk}/practica/{session.pk}/responder/",
                {"question_id": question.pk, "option_id": option.pk},
            )
            self.assertEqual(resp.status_code, 302)
            session.refresh_from_db()

        result = self.client.get(f"/cursos/{self.course.pk}/practica/{session.pk}/")
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "100%")
        dashboard = self.client.get("/dashboard/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Hoy en SIMA")

    def test_recommendation_can_be_completed_from_view(self):
        self._run_session()
        rec = Recommendation.objects.filter(user=self.user, course=self.course, status="pending").first()
        self.client.force_login(self.user)
        resp = self.client.post(f"/cursos/{self.course.pk}/recomendaciones/{rec.pk}/", {"status": "completed"})
        self.assertEqual(resp.status_code, 302)
        rec.refresh_from_db()
        self.assertEqual(rec.status, "completed")
