import random
from dataclasses import dataclass

from django.contrib.auth.models import User
from django.test import TestCase

from learning import adaptive, psychometrics as ps
from learning.models import Course, LessonJob, Plan, Profile, Question
from learning.tests_adaptive import MINI


@dataclass
class Item:
    irt_a: float = 1.0
    irt_b: float = 0.0
    irt_c: float = 0.25


@dataclass
class Resp:
    item_id: str
    is_correct: bool


class EAPTests(TestCase):
    def setUp(self):
        self.items = {str(i): Item(irt_b=b) for i, b in enumerate([-1.0, -0.5, 0.0, 0.5, 1.0])}

    def test_no_responses_returns_prior(self):
        self.assertEqual(ps.eap_estimate(self.items, [], prior_mean=0.4, prior_sd=0.8), (0.4, 0.8))

    def test_correct_answers_raise_theta_and_shrink_sd(self):
        theta1, sd1 = ps.eap_estimate(self.items, [Resp("2", True)])
        theta4, sd4 = ps.eap_estimate(self.items, [Resp(str(i), True) for i in range(4)])
        self.assertGreater(theta1, 0.0)
        self.assertGreater(theta4, theta1)
        self.assertLess(sd1, 1.0)
        self.assertLess(sd4, sd1)

    def test_wrong_answers_lower_theta(self):
        theta, _ = ps.eap_estimate(self.items, [Resp(str(i), False) for i in range(4)])
        self.assertLess(theta, -0.5)

    def test_prior_pulls_estimate_with_few_answers(self):
        theta, _ = ps.eap_estimate(self.items, [Resp("2", False)], prior_mean=1.5, prior_sd=0.5)
        self.assertGreater(theta, 0.5)  # un fallo no borra un prior fuerte
        theta_weak, _ = ps.eap_estimate(self.items, [Resp("2", False)], prior_mean=1.5, prior_sd=2.0)
        self.assertLess(theta_weak, theta)


class RandomesqueBktCalibrationTests(TestCase):
    def test_randomesque_only_picks_within_top_k(self):
        rng = random.Random(7)
        candidates = list(range(20))
        picks = {ps.randomesque(candidates, score=lambda x: x, k=5, rng=rng) for _ in range(200)}
        self.assertTrue(picks.issubset({15, 16, 17, 18, 19}))
        self.assertGreater(len(picks), 1)
        self.assertEqual(ps.randomesque(candidates, score=lambda x: x, k=1, rng=rng), 19)

    def test_bkt_sequences(self):
        self.assertAlmostEqual(ps.bkt_trace([]), 0.25, places=3)
        self.assertGreaterEqual(ps.bkt_trace([True] * 4), 0.85)
        self.assertLess(ps.bkt_trace([False] * 3), 0.3)
        recovered = ps.bkt_trace([False, False, True, True, True])
        self.assertGreater(recovered, ps.bkt_trace([False, False]))

    def test_calibration_moves_b_toward_observation_with_decaying_step(self):
        b_after_correct = ps.calibrate_difficulty(0.0, 0, theta=0.0, irt_a=1.0, irt_c=0.25, is_correct=True)
        b_after_wrong = ps.calibrate_difficulty(0.0, 0, theta=0.0, irt_a=1.0, irt_c=0.25, is_correct=False)
        self.assertLess(b_after_correct, 0.0)
        self.assertGreater(b_after_wrong, 0.0)
        late = ps.calibrate_difficulty(0.0, 40, theta=0.0, irt_a=1.0, irt_c=0.25, is_correct=False)
        self.assertLess(late, b_after_wrong)
        self.assertEqual(ps.calibrate_difficulty(3.49, 0, theta=-3, irt_a=2, irt_c=0.2, is_correct=False), ps.B_MAX)

    def test_quality_flags(self):
        self.assertEqual(ps.quality_flag(5, 5), "")
        self.assertEqual(ps.quality_flag(10, 10), "too_easy")
        self.assertEqual(ps.quality_flag(10, 0), "suspect")
        self.assertEqual(ps.quality_flag(10, 6), "")


class EngineIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fer", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.course = Course.objects.create(user=self.user, name="Biologia")
        LessonJob.objects.create(
            user=self.user, course=self.course, title="Clase", mode=LessonJob.Mode.API,
            status=LessonJob.Status.CORRECTED, corrected_output=MINI, tags="biologia",
        )

    def _run(self, target=7, correct_topics=("Fotosintesis",)):
        session = adaptive.start_practice(self.user, self.course, target_count=target)
        guard = 0
        while not session.is_complete and guard < 30:
            guard += 1
            q = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            opts = list(q.options.all())
            pick = next(o for o in opts if o.is_correct) if q.topic in correct_topics else next(o for o in opts if not o.is_correct)
            adaptive.answer_question(session, q.pk, pick.pk)
            session.refresh_from_db()
        return session

    def test_session_uses_eap_updates_item_statistics_and_bkt_mastery(self):
        session = self._run()
        self.assertLess(session.standard_error, 1.0)
        self.assertGreater(session.prior_sd, 0)
        stats = Question.objects.filter(quiz__course=self.course, attempts__gt=0)
        self.assertEqual(stats.count(), 7)
        for q in stats:
            self.assertEqual(q.calibration_count, 1)
            self.assertIsNotNone(q.b_calibrated)
            if q.topic == "Fotosintesis":
                self.assertLess(q.b_calibrated, q.irt_b)     # acierto: el item era mas facil
            else:
                self.assertGreater(q.b_calibrated, q.irt_b)  # fallo: mas dificil
        profile = adaptive.get_profile(self.user, self.course)
        self.assertGreaterEqual(profile.mastery_by_topic["Fotosintesis"]["mastery"], 0.85)
        self.assertLess(profile.mastery_by_topic["Respiracion celular"]["mastery"], 0.6)
        self.assertIn("accuracy", profile.mastery_by_topic["Fotosintesis"])
        self.assertIn("Fotosintesis", profile.strong_topics)
        self.assertIn("Respiracion celular", profile.weak_topics)

    def test_second_session_starts_with_tighter_prior(self):
        first = self._run()
        second = adaptive.start_practice(self.user, self.course, target_count=3)
        self.assertLess(second.prior_sd, 1.0)
        self.assertAlmostEqual(second.theta_start, adaptive.get_profile(self.user, self.course).theta)
        self.assertGreater(second.prior_sd, 0.4)

    def test_calibrated_b_used_after_min_observations_and_flagged_items_excluded(self):
        q = Question.objects.filter(quiz__course=self.course).first() or None
        if q is None:
            adaptive.sync_course_bank(self.course)
            q = Question.objects.filter(quiz__course=self.course).first()
        q.b_calibrated = 2.2
        q.calibration_count = adaptive.CALIBRATION_MIN
        q.save()
        bank_item = next(i for i in adaptive.load_bank(self.course) if i.question_id == q.pk)
        self.assertEqual(bank_item.irt_b, 2.2)

        q.quality_flag = "suspect"
        q.save()
        self.assertNotIn(q.pk, [i.question_id for i in adaptive.load_bank(self.course)])
        overview = adaptive.course_overview(self.user, self.course)
        self.assertEqual([x.pk for x in overview["suspect_questions"]], [q.pk])
