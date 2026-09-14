import os
import socket
import tempfile
import threading
from http.server import ThreadingHTTPServer
from unittest import mock

from django.test import SimpleTestCase, override_settings

from learning.management.commands.serve_whisper import build_handler
from learning.services import transcription


def fake_transcriber(path):
    with open(path, "rb") as fh:
        size = len(fh.read())
    return {
        "text": f" clase de prueba ({size} bytes) ",
        "language": "es",
        "segments": [
            {"start": 0.0, "end": 2.5, "text": " Hola clase. "},
            {"start": 2.5, "end": 5.0, "text": "Hoy vemos priones."},
            {"start": 5.0, "end": 6.0, "text": "   "},
        ],
    }


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RemoteTranscriptionTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.port = free_port()
        cls.token = "token-de-prueba"
        handler = build_handler(fake_transcriber, cls.token, "tiny", log=lambda msg: None)
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def setUp(self):
        fd, self.audio = tempfile.mkstemp(suffix=".mp3")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"\x00" * 4096)

    def tearDown(self):
        os.remove(self.audio)

    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def test_remote_returns_text_and_segments(self):
        with override_settings(TRANSCRIPTION_BACKEND="remote", WHISPER_REMOTE_URL=self.url(), WHISPER_REMOTE_TOKEN=self.token,
                               TRANSCRIPTION_FALLBACK=""):
            text, segments = transcription.transcribe_audio_detailed(self.audio)
        self.assertEqual(text, "clase de prueba (4096 bytes)")
        self.assertEqual([s["text"] for s in segments], ["Hola clase.", "Hoy vemos priones."])
        self.assertEqual(segments[1]["start"], 2.5)

    def test_wrong_token_is_rejected(self):
        with override_settings(TRANSCRIPTION_BACKEND="remote", WHISPER_REMOTE_URL=self.url(), WHISPER_REMOTE_TOKEN="otro",
                               TRANSCRIPTION_FALLBACK=""):
            with self.assertRaisesMessage(transcription.TranscriptionUnavailable, "token"):
                transcription.transcribe_audio_detailed(self.audio)

    def test_health_reports_remote_status(self):
        with override_settings(TRANSCRIPTION_BACKEND="remote", WHISPER_REMOTE_URL=self.url(), WHISPER_REMOTE_TOKEN=self.token):
            status = transcription.remote_status()
        self.assertTrue(status["reachable"])
        self.assertEqual(status["model"], "tiny")

    def test_unreachable_pc_gives_clear_error(self):
        with override_settings(TRANSCRIPTION_BACKEND="remote", WHISPER_REMOTE_URL=f"http://127.0.0.1:{free_port()}",
                               WHISPER_REMOTE_TOKEN=self.token, TRANSCRIPTION_FALLBACK=""):
            with self.assertRaisesMessage(transcription.TranscriptionUnavailable, "no responde"):
                transcription.transcribe_audio_detailed(self.audio)
            self.assertFalse(transcription.remote_status(timeout=0.5)["reachable"])

    def test_fallback_is_used_when_remote_is_down(self):
        with override_settings(TRANSCRIPTION_BACKEND="remote", WHISPER_REMOTE_URL=f"http://127.0.0.1:{free_port()}",
                               WHISPER_REMOTE_TOKEN=self.token, TRANSCRIPTION_FALLBACK="cloud"):
            with mock.patch.object(transcription, "transcribe_cloud", return_value=("texto nube", [])) as cloud:
                self.assertEqual(transcription.transcribe_audio_detailed(self.audio), ("texto nube", []))
        cloud.assert_called_once()

    def test_local_is_default_backend(self):
        with override_settings(TRANSCRIPTION_BACKEND="", TRANSCRIPTION_FALLBACK=""):
            with mock.patch.object(transcription, "transcribe_local", return_value=("local", [])) as local:
                self.assertEqual(transcription.transcribe_audio_detailed(self.audio), ("local", []))
        local.assert_called_once()
        self.assertEqual(transcription.transcription_backend(), "local")
