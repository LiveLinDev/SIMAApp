"""Comando check_ai: diagnostico de configuracion y prueba del proveedor (con llamadas simuladas)."""
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from learning.tests_adaptive import MINI


@override_settings(CLOUD_PROVIDER="qwen", CLOUD_API_KEY="sk-qwen-real-key-123456", CLOUD_MODEL="qwen-flash",
                   CLOUD_API_BASE="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", CLOUD_LABEL="Qwen")
class CheckAiTests(TestCase):
    def test_config_only(self):
        out = StringIO()
        call_command("check_ai", stdout=out)
        text = out.getvalue()
        self.assertIn("qwen-flash", text)
        self.assertIn("clave real", text)
        self.assertIn("migraciones al dia", text)
        self.assertIn("Todo listo", text)
        self.assertNotIn("sk-qwen-real-key-123456", text)  # la clave nunca se imprime completa

    @patch("learning.management.commands.check_ai.generate_items", return_value=("PROMPT", MINI, "cloud"))
    @patch("learning.management.commands.check_ai.call_ai", return_value="OK")
    def test_ping_and_mini(self, call_ai, generate_items):
        out = StringIO()
        call_command("check_ai", "--ping", "--mini", "--runs", "2", "--items", "5", stdout=out)
        text = out.getvalue()
        self.assertIn("respondio en", text)
        self.assertIn("items validos de 5 pedidos", text)
        self.assertIn("formato respetado en 2 de 2", text)
        self.assertIn("~$", text)  # estimacion de costo para qwen
        self.assertEqual(call_ai.call_count, 1)
        self.assertEqual(generate_items.call_count, 2)

    @patch("learning.management.commands.check_ai.call_ai", side_effect=RuntimeError("Qwen rechazo la API key"))
    def test_ping_failure_exits_nonzero(self, _call):
        out = StringIO()
        with self.assertRaises(SystemExit):
            call_command("check_ai", "--ping", stdout=out)
        self.assertIn("rechazo la API key", out.getvalue())

    @override_settings(CLOUD_API_KEY="sk-...")
    def test_missing_key_blocks(self):
        out = StringIO()
        with self.assertRaises(SystemExit):
            call_command("check_ai", stdout=out)
        self.assertIn("no tiene una clave real", out.getvalue())
