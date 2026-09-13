from django.test import SimpleTestCase, override_settings

from learning.services.backends import get_available_backends, resolve_backend


class LocalFallbackTests(SimpleTestCase):
    @override_settings(LOCAL_AI_ENABLED=False, CLOUD_PROVIDER="groq", CLOUD_API_KEY="gsk_real_key_for_tests")
    def test_local_requests_use_cloud_when_local_disabled(self):
        self.assertEqual(resolve_backend("local"), "cloud")
        backends = get_available_backends()
        self.assertFalse(backends["local"])
        self.assertEqual(backends["default"], "cloud")

    @override_settings(LOCAL_AI_ENABLED=True, CLOUD_PROVIDER="groq", CLOUD_API_KEY="gsk_real_key_for_tests")
    def test_local_kept_when_enabled(self):
        self.assertEqual(resolve_backend("local"), "local")
        self.assertTrue(get_available_backends()["local"])

    @override_settings(LOCAL_AI_ENABLED=False, CLOUD_PROVIDER="groq", CLOUD_API_KEY="")
    def test_local_kept_when_no_cloud_either(self):
        self.assertEqual(resolve_backend("local"), "local")
