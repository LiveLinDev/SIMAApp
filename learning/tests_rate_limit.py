"""Reintentos ante limite de tasa (429) del proveedor de nube: niveles gratuitos como Groq."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from learning.services import backends


class _FakeRateLimit(Exception):
    pass


def _response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None)


class TokenRateLimiterTests(SimpleTestCase):
    def test_waits_only_when_window_is_full(self):
        clock = {"t": 0.0}
        sleeps = []

        def sleeper(s):
            sleeps.append(s)
            clock["t"] += s

        limiter = backends.TokenRateLimiter(clock=lambda: clock["t"], sleeper=sleeper)
        self.assertEqual(limiter.acquire(3000, 6000), 0.0)
        self.assertEqual(limiter.acquire(2500, 6000), 0.0)
        waited = limiter.acquire(2000, 6000)  # 7500 > 6000: espera a que expire la ventana
        self.assertGreater(waited, 0)
        self.assertGreaterEqual(clock["t"], 60.0)
        self.assertEqual(limiter.acquire(100, 0), 0.0)  # sin limite configurado
        self.assertEqual(backends.estimate_tokens("hola mundo" * 35), 101)


class ReasoningBudgetTests(SimpleTestCase):
    @override_settings(CLOUD_MAX_TOKENS=4000)
    def test_reasoning_models_get_extra_output(self):
        self.assertTrue(backends.is_reasoning_model("openai/gpt-oss-120b"))
        self.assertFalse(backends.is_reasoning_model("qwen/qwen3.8-27b"))
        self.assertEqual(backends.effective_max_tokens(1000, "qwen/qwen3.8-27b"), 1000)
        self.assertEqual(backends.effective_max_tokens(1000, "openai/gpt-oss-120b"), 3500)
        self.assertEqual(backends.effective_max_tokens(3000, "openai/gpt-oss-120b"), 4000)  # recortado al tope
        self.assertEqual(backends.effective_max_tokens(None, "openai/gpt-oss-120b"), 4000)


class RoleModelTests(SimpleTestCase):
    @override_settings(CLOUD_MODEL="qwen/qwen3.8-27b", CLOUD_VERIFICATION_MODEL="openai/gpt-oss-120b")
    def test_model_per_role(self):
        self.assertEqual(backends.model_for_role("generation"), "qwen/qwen3.8-27b")
        self.assertEqual(backends.model_for_role("verification"), "openai/gpt-oss-120b")
        self.assertEqual(backends.model_for_role("coherence"), "openai/gpt-oss-120b")
        with override_settings(CLOUD_VERIFICATION_MODEL=""):
            self.assertEqual(backends.model_for_role("verification"), "qwen/qwen3.8-27b")

    def test_degenerate_report_detection_and_retry(self):
        from learning.services import repairs

        mini = "a|m=IRT3PL|d=20260906|n=2|l=es|t=x|bd=1,1,0,0,0,0|cat=0,-3,3,0.3,10,SH\ni1|L1|T|q1?|a*,b,c,d|1,0,0.25|2|x,0,low\ni2|L1|T|q2?|a*,b,c,d|1,0,0.25|2|x,0,low"
        self.assertTrue(repairs.verification_report_is_degenerate("v|d=20240522|n=0|e=0|s=VERIFICADO", mini))
        self.assertFalse(repairs.verification_report_is_degenerate("v|d=20260906|n=2|e=0|s=VERIFICADO", mini))
        self.assertFalse(repairs.verification_report_is_degenerate("texto sin formato", mini))
        with patch.object(repairs, "call_ai", return_value="v|d=20260906|n=2|e=1|s=CORREGIDO\ne1|i1|wrong_answer|options|a|b|razon") as call:
            fixed = repairs.ensure_verification_report_format("v|d=20240522|n=0|e=0|s=VERIFICADO", mini, "cloud")
        self.assertIn("n=2", fixed)
        self.assertEqual(call.call_count, 1)
        with patch.object(repairs, "call_ai", return_value="v|d=20240522|n=0|e=0|s=VERIFICADO"):
            same = repairs.ensure_verification_report_format("v|d=20240522|n=0|e=0|s=VERIFICADO", mini, "cloud")
        self.assertIn("n=0", same)  # insiste: se deja constancia en la traza


class ContextBudgetTests(SimpleTestCase):
    def test_fit_context_keeps_whole_blocks(self):
        from learning.services.evidence import fit_context

        blocks = [f"URL: https://f{i}\nCONTENIDO: " + ("x" * 900) for i in range(6)]
        context = "\n\n".join(blocks)
        fitted = fit_context(context, 2000)
        self.assertLessEqual(len(fitted), 2000)
        self.assertEqual(fitted.count("URL:"), 2)  # bloques completos, sin cortar a la mitad
        self.assertTrue(fit_context(context, len(context) + 1) == context)
        huge = "y" * 5000
        self.assertTrue(fit_context(huge, 1000).endswith("[...]"))

    @override_settings(VERIFICATION_CONTEXT_MAX_CHARS=1500, VERIFICATION_FETCH_SOURCES=True)
    def test_verification_context_is_capped(self):
        from learning.services import evidence

        big = "\n\n".join(f"URL: https://s{i}\nCONTENIDO: " + ("z" * 700) for i in range(5))
        with patch.object(evidence, "build_web_context", return_value=(big, {"enabled": True, "queries": [], "configured_sources": []})):
            context, trace = evidence.build_verification_context("i1|L1|t|q?|a*,b,c,d|1,0,0.25|2|x,0,low", "web")
        self.assertLessEqual(len(context), 1500)
        self.assertTrue(trace["context_truncated"])
        self.assertEqual(trace["context_chars"], len(context))


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
