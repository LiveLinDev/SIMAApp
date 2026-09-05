from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from learning import adaptive, spaced_repetition as sr
from learning.models import Course, Flashcard, LessonJob, Plan, Profile, Question, StudyActivity, UserPreference
from learning.tests_adaptive import MINI


class SM2Tests(TestCase):
    def setUp(self):
        user = User.objects.create_user("carla", password="x")
        self.course = Course.objects.create(user=user, name="Quimica")
        self.card = Flashcard.objects.create(course=self.course, question="Que es un mol?", answer="6.022e23 particulas", topic="Estequiometria")

    def test_progression_medium_easy(self):
        now = timezone.now()
        sr.sm2_update(self.card, "medium", now=now)
        self.assertEqual((self.card.repetitions, self.card.interval_days), (1, 1))
        self.assertAlmostEqual(self.card.ease_factor, 2.5, places=2)
        sr.sm2_update(self.card, "easy", now=now)
        self.assertEqual((self.card.repetitions, self.card.interval_days), (2, 6))
        self.assertAlmostEqual(self.card.ease_factor, 2.6, places=2)
        sr.sm2_update(self.card, "easy", now=now)
        self.assertEqual(self.card.repetitions, 3)
        self.assertEqual(self.card.interval_days, round(6 * 2.6))
        self.assertEqual(self.card.mastery_level, 3)
        self.assertGreater(self.card.next_review_at, now + timedelta(days=14))

    def test_again_resets_and_returns_in_minutes(self):
        now = timezone.now()
        for _ in range(3):
            sr.sm2_update(self.card, "easy", now=now)
        sr.sm2_update(self.card, "again", now=now)
        self.assertEqual(self.card.repetitions, 0)
        self.assertEqual(self.card.mastery_level, 0)
        self.assertLess(self.card.next_review_at, now + timedelta(minutes=11))
        self.assertGreaterEqual(self.card.ease_factor, sr.MIN_EASE)

    def test_ease_never_below_minimum(self):
        for _ in range(12):
            sr.sm2_update(self.card, "again")
        self.assertEqual(self.card.ease_factor, sr.MIN_EASE)

    def test_review_queue_prioritizes_overdue_then_new(self):
        now = timezone.now()
        overdue = Flashcard.objects.create(course=self.course, question="Vencida", answer="a", next_review_at=now - timedelta(days=2))
        later = Flashcard.objects.create(course=self.course, question="Manana", answer="b", next_review_at=now + timedelta(days=1))
        queue = sr.review_queue(self.course, limit=10, now=now)
        self.assertEqual(queue[0].pk, overdue.pk)
        self.assertIn(self.card.pk, [c.pk for c in queue])       # nueva
        self.assertNotIn(later.pk, [c.pk for c in queue])        # no vence aun
        self.assertEqual(sr.due_count(self.course, now), 2)


class RhythmViewsAndPlanTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dani", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        UserPreference.objects.update_or_create(user=self.user, defaults={"daily_goal": 12})
        self.course = Course.objects.create(user=self.user, name="Biologia")
        self.job = LessonJob.objects.create(
            user=self.user, course=self.course, title="Clase 1", mode=LessonJob.Mode.API,
            status=LessonJob.Status.CORRECTED, corrected_output=MINI, tags="biologia",
        )
        self.client.force_login(self.user)

    def _weak_session(self):
        session = adaptive.start_practice(self.user, self.course, target_count=7)
        guard = 0
        while not session.is_complete and guard < 30:
            guard += 1
            q = Question.objects.prefetch_related("options").get(pk=session.current_question_id)
            opts = list(q.options.all())
            pick = next(o for o in opts if o.is_correct) if q.topic == "Fotosintesis" else next(o for o in opts if not o.is_correct)
            adaptive.answer_question(session, q.pk, pick.pk)
            session.refresh_from_db()
        return session

    def test_plan_before_any_practice_suggests_initial_session(self):
        plan = adaptive.daily_plan(self.user, self.course)
        self.assertEqual(plan[0]["kind"], "practice")
        self.assertIn("inicial", plan[0]["title"].lower())

    def test_plan_after_weak_session_prioritizes_reinforcement_and_failures(self):
        session = self._weak_session()
        plan = adaptive.daily_plan(self.user, self.course)
        kinds = [a["kind"] for a in plan]
        self.assertIn("weak", kinds)
        self.assertIn("failures", kinds)
        failures = next(a for a in plan if a["kind"] == "failures")
        self.assertIn(f"/practica/{session.pk}/", failures["href"])

    def test_plan_puts_due_cards_first(self):
        Flashcard.objects.create(course=self.course, question="Q", answer="A", next_review_at=timezone.now() - timedelta(hours=1))
        plan = adaptive.daily_plan(self.user, self.course)
        self.assertEqual(plan[0]["kind"], "review")
        self.assertIn(f"/cursos/{self.course.pk}/repasar/", plan[0]["href"])

    def test_course_review_page_and_card_rating_update_sm2_streak_and_progress(self):
        card = Flashcard.objects.create(course=self.course, question="Q1", answer="A1")
        page = self.client.get(f"/cursos/{self.course.pk}/repasar/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Q1")
        resp = self.client.post(
            f"/cursos/{self.course.pk}/repasar/tarjeta/",
            {"flashcard_id": card.pk, "difficulty": "easy"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        card.refresh_from_db()
        self.assertEqual(card.repetitions, 1)
        self.assertEqual(StudyActivity.objects.filter(user=self.user, activity_type="flashcards_reviewed").count(), 1)
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.current_streak, 1)
        progress = adaptive.today_progress(self.user)
        self.assertEqual(progress["done"], 1)
        self.assertEqual(progress["goal"], 12)

    def test_class_review_endpoint_uses_sm2_and_rejects_foreign_cards(self):
        card = Flashcard.objects.create(course=self.course, question="Q", answer="A")
        resp = self.client.post(f"/clase/{self.job.pk}/flashcards/repasar/", {"flashcard_id": card.pk, "difficulty": "hard"},
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(resp.json()["ok"])
        card.refresh_from_db()
        self.assertEqual(card.repetitions, 1)
        self.assertEqual(card.interval_days, 1)

        other_user = User.objects.create_user("eva", password="x")
        other_course = Course.objects.create(user=other_user, name="Ajena")
        foreign = Flashcard.objects.create(course=other_course, question="X", answer="Y")
        resp = self.client.post(f"/clase/{self.job.pk}/flashcards/repasar/", {"flashcard_id": foreign.pk, "difficulty": "easy"},
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.repetitions, 0)

    def test_dashboard_shows_goal_progress_and_plan(self):
        self._weak_session()
        page = self.client.get("/dashboard/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "de 12")
        self.assertContains(page, "Refuerza")
