from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from learning.models import Course, LessonJob, Plan, Profile


@override_settings(
    CLOUD_PROVIDER="deepseek",
    CLOUD_API_KEY="sk-test-real",
    CLOUD_LABEL="DeepSeek",
    CLOUD_MODEL="deepseek-v4-flash",
)
class BackendSelectorRenderTests(TestCase):
    """Las vistas que muestran el selector de backend deben renderizar con el backend 'cloud'."""

    def setUp(self):
        self.user = User.objects.create_user("viewer", password="x")
        self.course = Course.objects.create(user=self.user, name="Curso de prueba")
        # /api/nueva/ redirige a /planes/ si el plan no incluye clases API
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.client.force_login(self.user)

    def test_lesson_form_offers_cloud_and_local(self):
        response = self.client.get("/api/nueva/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('value="cloud"', html)
        self.assertIn('value="local"', html)
        self.assertIn("DeepSeek", html)
        self.assertIn("deepseek-v4-flash", html)
        self.assertNotIn('value="anthropic"', html)
        self.assertNotIn("Nube Claude", html)

    def test_failed_job_detail_offers_cloud_retry(self):
        job = LessonJob.objects.create(
            user=self.user,
            course=self.course,
            title="Clase fallida",
            mode=LessonJob.Mode.API,
            status=LessonJob.Status.ERROR,
            error="fallo simulado",
            ai_backend="cloud",
        )
        response = self.client.get(f"/clase/{job.pk}/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('name="backend" value="cloud"', html)
        self.assertIn("DeepSeek", html)
        self.assertNotIn('value="anthropic"', html)

    @override_settings(CLOUD_API_KEY="local")
    def test_without_cloud_key_the_cloud_option_is_disabled(self):
        response = self.client.get("/api/nueva/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("backend-option--disabled", html)
        self.assertIn("falta CLOUD_API_KEY", html)
