"""Registro por invitacion o cerrado y detalles de /salud/ solo para el personal."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings


def _signup(client, **extra):
    data = {"username": "nuevo", "email": "nuevo@example.com", "password1": "Clave-Segura-2026", "password2": "Clave-Segura-2026"}
    data.update(extra)
    return client.post("/registro/", data)


class RegistrationModeTests(TestCase):
    @override_settings(SIMA_REGISTRATION="open")
    def test_open_registration_creates_account(self):
        resp = _signup(self.client)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="nuevo").exists())

    @override_settings(SIMA_REGISTRATION="invite", SIMA_INVITE_CODE="upc-2026")
    def test_invite_registration_requires_the_right_code(self):
        self.assertContains(self.client.get("/registro/"), "Código de invitación")
        resp = _signup(self.client, invite_code="otro")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "El código de invitación no es válido.")
        self.assertFalse(User.objects.filter(username="nuevo").exists())
        resp = _signup(self.client, invite_code="upc-2026")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="nuevo").exists())

    @override_settings(SIMA_REGISTRATION="closed")
    def test_closed_registration_rejects_signups_and_hides_links(self):
        self.assertContains(self.client.get("/registro/"), "Registro cerrado", status_code=403)
        resp = _signup(self.client)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(username="nuevo").exists())
        self.assertNotContains(self.client.get("/"), 'href="/registro/"')


class HealthDetailsTests(TestCase):
    def test_public_request_through_proxy_gets_only_basic_status(self):
        data = self.client.get("/salud/", HTTP_X_FORWARDED_FOR="203.0.113.9").json()
        self.assertEqual(data["database"], "ok")
        for key in ("cloud_model", "cloud_backend", "whisper_model", "transcription_backend", "transcription_remote"):
            self.assertNotIn(key, data)

    def test_staff_sees_details(self):
        staff = User.objects.create_user("ops", password="x", is_staff=True)
        self.client.force_login(staff)
        data = self.client.get("/salud/", HTTP_X_FORWARDED_FOR="203.0.113.9").json()
        self.assertIn("cloud_model", data)
        self.assertIn("transcription_backend", data)

    def test_direct_local_request_sees_details(self):
        data = self.client.get("/salud/", REMOTE_ADDR="127.0.0.1").json()
        self.assertIn("transcription_backend", data)
