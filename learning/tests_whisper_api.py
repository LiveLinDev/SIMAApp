"""Cliente de Whisper API con un servidor simulado (httpx.MockTransport): no hace llamadas reales."""
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import httpx
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from learning.services import transcription, whisper_api
from learning.services.whisper_api import RateLimiter, WhisperApiClient

BASE = "https://whisper-api.aquelarredemujeres.com"
HOST = "whisper-api.aquelarredemujeres.com"
KEY = "clave-de-prueba-" + "0" * 32
JOB = "3f2b8c1e-9d4a-4b6f-8e2d-1a2b3c4d5e6f"
REPO = Path(__file__).resolve().parent.parent


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def job_payload(status, **extra):
    return {"id": JOB, "status": status, "created_at": 1780000000.1, "updated_at": 1780000001.2, **extra}


class Server:
    """Servidor simulado: cada ruta devuelve la siguiente respuesta programada y se guardan las solicitudes."""

    def __init__(self, routes):
        self.routes = {key: list(value) for key, value in routes.items()}
        self.requests = []

    def __call__(self, request: httpx.Request):
        request.read()
        self.requests.append(request)
        key = (request.method, request.url.path)
        queue = self.routes.get(key) or self.routes.get((request.method, "*"))
        if not queue:
            return httpx.Response(599, json={"error": "ruta no programada"})
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item


def make_client(server, **options):
    clock = FakeClock()
    client = WhisperApiClient(BASE, KEY, transport=httpx.MockTransport(server), sleep=clock.sleep, clock=clock.now,
                              limiter=RateLimiter(28, clock=clock.now, sleep=clock.sleep), **options)
    return client, clock


def ok(payload, status=200, headers=None):
    return httpx.Response(status, json=payload, headers=headers)


class AudioFileMixin:
    def setUp(self):
        fd, name = tempfile.mkstemp(suffix=".mp3")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"ID3" + b"\x00" * 2048)
        self.audio = Path(name)

    def tearDown(self):
        self.audio.unlink(missing_ok=True)


class HeadersAndMultipartTests(AudioFileMixin, SimpleTestCase):
    def test_bearer_only_on_protected_routes_and_never_in_repr(self):
        server = Server({("GET", "/health/ready"): [ok({"status": "ready"})],
                         ("GET", f"/v1/transcriptions/{JOB}"): [ok(job_payload("queued"))]})
        client, _ = make_client(server)
        self.assertTrue(client.check_ready())
        client.get_transcription(JOB)
        health, protected = server.requests
        self.assertNotIn("authorization", health.headers)
        self.assertEqual(protected.headers["authorization"], f"Bearer {KEY}")
        self.assertNotIn(KEY, repr(client))
        self.assertEqual(protected.url.host, HOST)
        self.assertEqual(protected.url.scheme, "https")

    def test_multipart_has_exactly_one_file_and_allowed_fields(self):
        server = Server({("POST", "/v1/transcriptions"): [ok(job_payload("queued"), status=202,
                                                              headers={"Location": f"/v1/transcriptions/{JOB}"})]})
        client, _ = make_client(server)
        job = client.submit_transcription(self.audio, language="es", prompt="Clase de Fisiología\x07", response_format="json")
        self.assertEqual(job.id, JOB)
        body = server.requests[0].content.decode("latin-1")
        self.assertEqual(body.count('name="file"'), 1)
        self.assertIn("multipart/form-data; boundary=", server.requests[0].headers["content-type"])
        for name in ("model", "language", "prompt", "response_format"):
            self.assertEqual(body.count(f'name="{name}"'), 1)
        self.assertNotIn("\x07", body)  # caracteres de control fuera del prompt
        self.assertNotIn("base64", body)

    def test_language_is_omitted_for_autodetection(self):
        server = Server({("POST", "/v1/transcriptions"): [ok(job_payload("queued"), status=202)]})
        client, _ = make_client(server)
        client.submit_transcription(self.audio, language=None)
        body = server.requests[0].content.decode("latin-1")
        self.assertNotIn('name="language"', body)
        self.assertNotIn('name="prompt"', body)

    def test_invalid_parameters_are_rejected_locally(self):
        client, _ = make_client(Server({}))
        with self.assertRaises(whisper_api.WhisperApiConfigError):
            client.submit_transcription(self.audio, language="español")
        with self.assertRaises(whisper_api.WhisperApiConfigError):
            client.submit_transcription(self.audio, response_format="srt")
        with self.assertRaises(whisper_api.WhisperApiConfigError):
            make_client(Server({}), model="large")


class PollingAndResultTests(AudioFileMixin, SimpleTestCase):
    def test_polls_queued_processing_completed_every_three_to_five_seconds(self):
        server = Server({("GET", f"/v1/transcriptions/{JOB}"): [
            ok(job_payload("queued")), ok(job_payload("processing")), ok(job_payload("processing")),
            ok(job_payload("completed", result={"text": "Hola clase"})),
        ]})
        client, clock = make_client(server)
        seen = []
        result = client.wait_for_transcription(JOB, on_status=lambda job: seen.append(job.status))
        self.assertEqual(result.text, "Hola clase")
        self.assertEqual(seen, ["queued", "processing", "completed"])
        self.assertEqual(len(clock.sleeps), 3)
        self.assertTrue(all(3.0 <= s <= 5.0 for s in clock.sleeps), clock.sleeps)

    def test_failed_job_raises_with_service_code(self):
        server = Server({("GET", f"/v1/transcriptions/{JOB}"): [ok(job_payload("failed", error="decode_error"))]})
        client, _ = make_client(server)
        with self.assertRaises(whisper_api.WhisperApiJobFailed) as ctx:
            client.wait_for_transcription(JOB)
        self.assertEqual(ctx.exception.code, "decode_error")

    def test_result_formats_json_text_and_verbose(self):
        self.assertEqual(whisper_api.parse_result({"text": " hola "}).text, "hola")
        self.assertEqual(whisper_api.parse_result(" texto plano ").text, "texto plano")
        verbose = whisper_api.parse_result({
            "task": "transcribe", "language": "es", "duration": "12.34", "text": "Uno. Dos.",
            "segments": [{"id": 0, "start": 0.0, "end": 4.2, "text": " Uno. "}, {"start": "x", "text": "Dos."},
                         {"text": "   "}, "basura"],
        })
        self.assertEqual(verbose.language, "es")
        self.assertEqual(verbose.duration, 12.34)
        self.assertEqual([s["text"] for s in verbose.segments], ["Uno.", "Dos."])
        self.assertEqual(verbose.segments[1]["start"], 0.0)

    def test_local_wait_limit_stops_polling(self):
        server = Server({("GET", f"/v1/transcriptions/{JOB}"): [ok(job_payload("processing"))]})
        client, clock = make_client(server)
        with self.assertRaises(whisper_api.WhisperApiTimeout):
            client.wait_for_transcription(JOB, max_wait=20)
        self.assertLessEqual(clock.t, 20)
        self.assertLess(len(server.requests), 10)

    def test_cancellation_stops_polling(self):
        server = Server({("GET", f"/v1/transcriptions/{JOB}"): [ok(job_payload("processing"))]})
        client, _ = make_client(server)
        calls = iter([False, True])
        with self.assertRaises(whisper_api.WhisperApiCancelled):
            client.wait_for_transcription(JOB, should_cancel=lambda: next(calls, True))

    def test_resume_existing_job_does_not_upload_again(self):
        server = Server({("GET", f"/v1/transcriptions/{JOB}"): [
            ok(job_payload("processing")), ok(job_payload("completed", result={"text": "retomado"}))]})
        client, _ = make_client(server)
        result = client.transcribe(self.audio, resume_job_id=JOB)
        self.assertEqual(result.text, "retomado")
        self.assertFalse([r for r in server.requests if r.method == "POST"])

    def test_expired_job_is_submitted_again(self):
        server = Server({
            ("GET", f"/v1/transcriptions/{JOB}"): [ok({"detail": "not found"}, status=404),
                                                   ok(job_payload("completed", result={"text": "nuevo"}))],
            ("GET", "/health/ready"): [ok({"status": "ready"})],
            ("POST", "/v1/transcriptions"): [ok(job_payload("queued"), status=202)],
        })
        client, _ = make_client(server)
        submitted = []
        result = client.transcribe(self.audio, resume_job_id=JOB, on_submitted=submitted.append)
        self.assertEqual(result.text, "nuevo")
        self.assertEqual(submitted, [JOB])


class RetryTests(AudioFileMixin, SimpleTestCase):
    def test_retry_after_is_respected_on_get(self):
        server = Server({("GET", f"/v1/transcriptions/{JOB}"): [
            ok({"error": "rate_limited"}, status=429, headers={"Retry-After": "12"}), ok(job_payload("queued"))]})
        client, clock = make_client(server)
        self.assertEqual(client.get_transcription(JOB).status, "queued")
        self.assertGreaterEqual(clock.sleeps[0], 12)

    def test_retry_after_http_date(self):
        self.assertAlmostEqual(whisper_api.parse_retry_after("Wed, 21 Oct 2037 07:28:00 GMT", now=2139722880.0 - 30), 30, delta=1)
        self.assertIsNone(whisper_api.parse_retry_after("mañana"))

    def test_post_waits_and_retries_on_clear_503_and_429(self):
        server = Server({("POST", "/v1/transcriptions"): [
            ok({"status": "not_ready"}, status=503), ok({"error": "busy"}, status=429, headers={"Retry-After": "7"}),
            ok(job_payload("queued"), status=202)]})
        client, clock = make_client(server)
        self.assertEqual(client.submit_transcription(self.audio).id, JOB)
        self.assertEqual(len(server.requests), 3)
        self.assertGreaterEqual(clock.sleeps[0], 2)   # backoff exponencial
        self.assertGreaterEqual(clock.sleeps[1], 7)   # Retry-After

    def test_busy_gives_up_after_bounded_attempts(self):
        server = Server({("GET", f"/v1/transcriptions/{JOB}"): [ok({"status": "not_ready"}, status=503)]})
        client, _ = make_client(server)
        with self.assertRaises(whisper_api.WhisperApiBusy):
            client.get_transcription(JOB)
        self.assertLessEqual(len(server.requests), len(whisper_api.BACKOFF_SECONDS))

    def test_connection_cut_after_upload_is_not_retried(self):
        server = Server({("POST", "/v1/transcriptions"): [httpx.ReadError("conexion cortada")]})
        client, _ = make_client(server)
        with self.assertRaises(whisper_api.WhisperApiAmbiguousSubmit):
            client.submit_transcription(self.audio)
        self.assertEqual(len(server.requests), 1)

    def test_connection_never_opened_is_retried(self):
        attempts = []

        def handler(request):
            attempts.append(request)
            if len(attempts) == 1:
                raise httpx.ConnectError("sin red", request=request)
            return ok(job_payload("queued"), status=202)

        client, _ = make_client(handler)
        self.assertEqual(client.submit_transcription(self.audio).id, JOB)
        self.assertEqual(len(attempts), 2)

    def test_rate_limiter_blocks_above_the_window(self):
        clock = FakeClock()
        limiter = RateLimiter(2, period=60, clock=clock.now, sleep=clock.sleep)
        for _ in range(3):
            limiter.acquire()
        self.assertGreaterEqual(clock.t, 60)


class ErrorMappingTests(AudioFileMixin, SimpleTestCase):
    def test_status_codes_become_clear_internal_errors(self):
        expected = {
            401: whisper_api.WhisperApiAuthError, 403: whisper_api.WhisperApiForbidden,
            404: whisper_api.WhisperApiNotFound, 408: whisper_api.WhisperApiRejected,
            413: whisper_api.WhisperApiRejected, 422: whisper_api.WhisperApiRejected,
            429: whisper_api.WhisperApiBusy, 503: whisper_api.WhisperApiBusy, 504: whisper_api.WhisperApiRejected,
        }
        for status, error in expected.items():
            with self.subTest(status=status):
                server = Server({("GET", f"/v1/transcriptions/{JOB}"): [ok({"error": f"e{status}"}, status=status)]})
                client, _ = make_client(server)
                with self.assertRaises(error) as ctx:
                    client.get_transcription(JOB)
                self.assertEqual(ctx.exception.status, status)
        self.assertTrue(whisper_api.WhisperApiBusy.transient)
        self.assertFalse(whisper_api.WhisperApiAuthError.transient)

    def test_key_never_reaches_logs_or_error_messages(self):
        server = Server({("POST", "/v1/transcriptions"): [ok({"error": f"bad token {KEY}"}, status=401)]})
        client, _ = make_client(server)
        with self.assertLogs("learning.services.whisper_api", level="DEBUG") as logs:
            logging.getLogger("learning.services.whisper_api").debug("inicio de prueba")
            with self.assertRaises(whisper_api.WhisperApiAuthError) as ctx:
                client.submit_transcription(self.audio)
        self.assertNotIn(KEY, str(ctx.exception))
        self.assertNotIn(KEY, ctx.exception.code)
        self.assertNotIn(KEY, "\n".join(logs.output))

    def test_redirects_are_not_followed(self):
        server = Server({("GET", f"/v1/transcriptions/{JOB}"): [
            httpx.Response(307, headers={"Location": "https://otro-dominio.example/v1/robar"})]})
        client, _ = make_client(server)
        with self.assertRaises(whisper_api.WhisperApiRejected):
            client.get_transcription(JOB)
        self.assertEqual([r.url.host for r in server.requests], [HOST])

    def test_only_the_authorized_https_host_is_accepted(self):
        for url in ("http://whisper-api.aquelarredemujeres.com", "https://whisper.acueducto.com",
                    "https://evil.example", "https://whisper-api.aquelarredemujeres.com:8443",
                    "https://whisper-api.aquelarredemujeres.com/v1", "https://user:pw@whisper-api.aquelarredemujeres.com"):
            with self.subTest(url=url), self.assertRaises(whisper_api.WhisperApiConfigError):
                WhisperApiClient(url, KEY)
        with self.assertRaises(whisper_api.WhisperApiConfigError):
            WhisperApiClient(BASE, "")

    def test_local_file_validation(self):
        client, _ = make_client(Server({}))
        with self.assertRaisesMessage(whisper_api.WhisperApiFileError, "no existe"):
            client.submit_transcription(self.audio.with_name("no-existe.mp3"))
        empty = self.audio.with_name(self.audio.stem + "-vacio.mp3")
        empty.write_bytes(b"")
        big = self.audio.with_name(self.audio.stem + "-grande.mp3")
        with open(big, "wb") as fh:
            fh.truncate(whisper_api.MAX_FILE_BYTES + 1)
        try:
            with self.assertRaisesMessage(whisper_api.WhisperApiFileError, "vacio"):
                client.submit_transcription(empty)
            with self.assertRaisesMessage(whisper_api.WhisperApiFileError, "95 MiB"):
                client.submit_transcription(big)
        finally:
            empty.unlink(missing_ok=True)
            big.unlink(missing_ok=True)


class SecretHygieneTests(SimpleTestCase):
    def test_example_env_files_only_have_the_placeholder(self):
        for name in (".env.example", "deploy/env.production.example"):
            text = (REPO / name).read_text(encoding="utf-8")
            self.assertIn("WHISPER_API_KEY=REPLACE_WITH_SECRET", text)

    def test_configured_key_is_not_in_tracked_files(self):
        key = getattr(settings, "WHISPER_API_KEY", "")
        if not key or len(key) < 20:
            self.skipTest("sin clave configurada en este entorno")
        try:
            tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git no disponible")
        needle = key.encode()
        leaked = [path for path in tracked.decode(errors="ignore").split("\0")
                  if path and (REPO / path).is_file() and needle in (REPO / path).read_bytes()]
        self.assertEqual(leaked, [], "la clave aparece en archivos versionados (no se imprime)")

    def test_frontend_never_calls_the_api_or_sees_the_key(self):
        hits = []
        for folder in ("templates", "static"):
            for path in (REPO / folder).rglob("*"):
                if path.suffix.lower() in {".html", ".js", ".css", ".json"} and path.is_file():
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    if HOST in text or "WHISPER_API_KEY" in text or "/v1/transcriptions" in text:
                        hits.append(str(path.relative_to(REPO)))
        self.assertEqual(hits, [])


class TranscriptionBackendTests(AudioFileMixin, SimpleTestCase):
    @override_settings(TRANSCRIPTION_BACKEND="api", TRANSCRIPTION_FALLBACK="", WHISPER_LANGUAGE="es")
    def test_api_backend_returns_text_and_segments_and_reports_job(self):
        server = Server({
            ("GET", "/health/ready"): [ok({"status": "ready"})],
            ("POST", "/v1/transcriptions"): [ok(job_payload("queued"), status=202)],
            ("GET", f"/v1/transcriptions/{JOB}"): [ok(job_payload("completed", result={
                "text": "Hola clase. Hoy vemos priones.",
                "segments": [{"start": 0, "end": 2.5, "text": "Hola clase."}, {"start": 2.5, "end": 5, "text": "Hoy vemos priones."}],
            }))],
        })
        client, _ = make_client(server)
        submitted = []
        with mock.patch.object(whisper_api, "client_from_settings", return_value=client):
            text, segments = transcription.transcribe_audio_detailed(
                self.audio, prompt="Clase de Biología", on_submitted=submitted.append)
        self.assertEqual(text, "Hola clase. Hoy vemos priones.")
        self.assertEqual([s["text"] for s in segments], ["Hola clase.", "Hoy vemos priones."])
        self.assertEqual(submitted, [JOB])
        body = [r for r in server.requests if r.method == "POST"][0].content.decode("utf-8", errors="ignore")
        self.assertIn("verbose_json", body)
        self.assertIn("Clase de Biología", body)

    @override_settings(TRANSCRIPTION_BACKEND="api", TRANSCRIPTION_FALLBACK="")
    def test_api_errors_become_transcription_unavailable(self):
        server = Server({("GET", "/health/ready"): [ok({"status": "ready"})],
                         ("POST", "/v1/transcriptions"): [ok({"error": "invalid_audio"}, status=422)]})
        client, _ = make_client(server)
        with mock.patch.object(whisper_api, "client_from_settings", return_value=client):
            with self.assertRaisesMessage(transcription.TranscriptionUnavailable, "audio o parametros no validos"):
                transcription.transcribe_audio_detailed(self.audio)

    def test_service_status_uses_no_credentials(self):
        seen = []

        def handler(request):
            seen.append(request)
            return ok({"status": "ready" if request.url.path.endswith("ready") else "ok"})

        status = whisper_api.service_status(BASE, transport=httpx.MockTransport(handler))
        self.assertEqual(status, {"reachable": True, "ready": True})
        self.assertTrue(all("authorization" not in r.headers for r in seen))
        self.assertFalse(whisper_api.service_status("https://evil.example")["ready"])
