from django.test import SimpleTestCase, override_settings

from learning import services


class NormalizeBackendTests(SimpleTestCase):
    def test_legacy_names_map_to_cloud_or_local(self):
        for legacy in ("anthropic", "claude", "deepseek", "nube", "cloud", "CLOUD"):
            self.assertEqual(services.normalize_backend(legacy), "cloud", legacy)
        for legacy in ("local", "qwen", "local_qwen", "ollama"):
            self.assertEqual(services.normalize_backend(legacy), "local", legacy)

    def test_auto_and_unknown_pass_through(self):
        self.assertEqual(services.normalize_backend(None), "auto")
        self.assertEqual(services.normalize_backend(""), "auto")
        self.assertEqual(services.normalize_backend("otro"), "otro")


class AvailableBackendsTests(SimpleTestCase):
    @override_settings(CLOUD_PROVIDER="openai_compatible", CLOUD_API_KEY="sk-real-key",
                       CLOUD_LABEL="DeepSeek", CLOUD_MODEL="deepseek-v4-flash")
    def test_cloud_available_with_real_key(self):
        backends = services.get_available_backends()
        self.assertTrue(backends["cloud"])
        self.assertEqual(backends["default"], "cloud")
        self.assertEqual(backends["cloud_label"], "DeepSeek")
        self.assertEqual(backends["cloud_model"], "deepseek-v4-flash")
        self.assertTrue(backends["anthropic"])  # alias heredado
        self.assertEqual(services.resolve_backend("auto"), "cloud")
        self.assertEqual(services.resolve_backend("anthropic"), "cloud")

    @override_settings(CLOUD_PROVIDER="openai_compatible", CLOUD_API_KEY="local")
    def test_placeholder_key_falls_back_to_local(self):
        backends = services.get_available_backends()
        self.assertFalse(backends["cloud"])
        self.assertEqual(backends["default"], "local")
        self.assertEqual(services.resolve_backend("auto"), "local")

    @override_settings(CLOUD_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant-real", CLOUD_API_KEY="")
    def test_anthropic_provider_uses_anthropic_key(self):
        self.assertTrue(services.cloud_backend_available())

    @override_settings(CLOUD_PROVIDER="openai_compatible", CLOUD_API_KEY="sk-real-key", CLOUD_DIRECT_MINI=True)
    def test_direct_mini_only_for_cloud(self):
        self.assertTrue(services.use_direct_cloud_mini("cloud"))
        self.assertTrue(services.use_direct_cloud_mini("anthropic"))
        self.assertFalse(services.use_direct_cloud_mini("local"))

    @override_settings(CLOUD_PROVIDER="openai_compatible", CLOUD_API_KEY="sk-real-key", CLOUD_DIRECT_MINI=False)
    def test_direct_mini_off_keeps_verification(self):
        self.assertFalse(services.use_direct_cloud_mini("cloud"))

    @override_settings(CLOUD_PROVIDER="openai_compatible", CLOUD_API_KEY="local")
    def test_call_ai_cloud_without_key_raises(self):
        with self.assertRaises(RuntimeError):
            services.call_ai("hola", backend="cloud")
