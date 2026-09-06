"""Reintentos ante limite de tasa (429) del proveedor de nube: niveles gratuitos como Groq."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from learning.services import backends


class _FakeRateLimit(Exception):
    pass


def _response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None)


@override_settings(CLOUD_PROVIDER="groq", CLOUD_API_KEY="gsk_real_key_1234567890", CLOUD_API_BASE="https://api.groq.com/openai/v1",
                   CLOUD_MODEL="openai/gpt-oss-120b", CLOUD_LABEL="Groq", CLOUD_RATE_LIMIT_RETRIES=3, CLOUD_RATE_LIMIT_MAX_WAIT=30)
class RateLimitRetryTests(SimpleTestCase):
    def test_parses_suggested_wait(self):
        self.assertAlmostEqual(backends._suggested_wait_seconds("Please try again in 14.2275s. Need more"), 14.2275)
        self.assertAlmostEqual(backends._suggested_wait_seconds("try again in 2m3.5s"), 123.5)
        self.assertIsNone(backends._suggested_wait_seconds("sin pista"))

    @patch("learning.services.backends.time.sleep")
    def test_retries_then_succeeds(self, sleep):
        calls = {"n": 0}

        def create(**kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _FakeRateLimit("Rate limit reached ... Please try again in 1.5s.")
            return _response("i1|L1|Tema|...|a*,b,c,d|1,0,0.25|2|x,0.1,low")

        with patch.object(backends, "_is_rate_limit_error", side_effect=lambda exc: isinstance(exc, _FakeRateLimit)):
            with patch.object(backends, "_chat_client", return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))):
                text = backends._call_openai_compatible("hola")
        self.assertIn("i1|", text)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertGreaterEqual(sleep.call_args_list[0][0][0], 1.5)

    @patch("learning.services.backends.time.sleep")
    def test_gives_up_with_clear_message(self, sleep):
        def create(**kwargs):
            raise _FakeRateLimit("Rate limit reached. Please try again in 5s.")

        with patch.object(backends, "_is_rate_limit_error", side_effect=lambda exc: isinstance(exc, _FakeRateLimit)):
            with patch.object(backends, "_chat_client", return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))):
                with self.assertRaises(RuntimeError) as ctx:
                    backends._call_openai_compatible("hola")
        self.assertIn("limite de uso", str(ctx.exception))
        self.assertEqual(sleep.call_count, 3)
