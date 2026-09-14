"""Servicio HTTP de transcripcion con Whisper para que un servidor pequeno (VPS) no cargue Whisper.

Corre en la maquina que transcribe (p. ej. la PC del equipo) y escucha solo en 127.0.0.1. El VPS lo alcanza por un
tunel SSH inverso abierto desde esa maquina:

    python manage.py serve_whisper --port 9000
    ssh -N -R 127.0.0.1:9000:127.0.0.1:9000 sima-tunnel@IP_DEL_VPS

Endpoints:
    GET  /health       -> {"status": "ok", "model": "...", "busy": false}
    POST /transcribe   -> cuerpo = bytes del audio; cabecera X-Filename opcional.
                          Respuesta: {"text": "...", "segments": [{"start", "end", "text"}], "language": "..."}
Autenticacion: `Authorization: Bearer <WHISPER_REMOTE_TOKEN>` (obligatorio si el token esta configurado).
"""
from __future__ import annotations

import hmac
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
CHUNK = 1024 * 1024


def build_handler(transcriber, token: str, model_name: str, log=print):
    """transcriber(path) -> dict con text, segments y language. Se inyecta para poder probarlo sin Whisper."""
    lock = threading.Lock()
    state = {"busy": False, "served": 0}

    class Handler(BaseHTTPRequestHandler):
        server_version = "SIMAWhisper/1.0"

        def log_message(self, fmt, *args):  # silencia el log por defecto de http.server
            return

        def _json(self, code: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not token:
                return True
            header = self.headers.get("Authorization", "")
            return hmac.compare_digest(header, f"Bearer {token}")

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") != "/health":
                return self._json(404, {"error": "ruta no encontrada"})
            if not self._authorized():
                return self._json(401, {"error": "token invalido"})
            return self._json(200, {"status": "ok", "model": model_name, "busy": state["busy"], "served": state["served"]})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/transcribe":
                return self._json(404, {"error": "ruta no encontrada"})
            if not self._authorized():
                self._drain_small_body()
                return self._json(401, {"error": "token invalido"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            chunked = "chunked" in self.headers.get("Transfer-Encoding", "").lower()
            if not chunked and length <= 0:
                return self._json(400, {"error": "cuerpo vacio: envia los bytes del audio"})
            if length > MAX_UPLOAD_BYTES:
                return self._json(413, {"error": "audio demasiado grande"})
            suffix = os.path.splitext(self.headers.get("X-Filename", "audio"))[1][:10] or ".audio"
            fd, path = tempfile.mkstemp(prefix="sima_whisper_", suffix=suffix)
            try:
                with os.fdopen(fd, "wb") as out:
                    if chunked:
                        self._copy_chunked(out)
                    else:
                        remaining = length
                        while remaining > 0:
                            data = self.rfile.read(min(CHUNK, remaining))
                            if not data:
                                break
                            out.write(data)
                            remaining -= len(data)
                options = self._whisper_options()
                started = time.monotonic()
                with lock:  # una transcripcion a la vez: Whisper usa toda la CPU o GPU
                    state["busy"] = True
                    try:
                        result = transcriber(path, **options) if options else transcriber(path)
                    finally:
                        state["busy"] = False
                state["served"] += 1
                seconds = time.monotonic() - started
                segments = [
                    {"start": float(s.get("start") or 0.0), "end": float(s.get("end") or 0.0), "text": (s.get("text") or "").strip()}
                    for s in (result.get("segments") or [])
                ]
                log(f"Transcrito {self.headers.get('X-Filename', 'audio')}: {len(segments)} segmentos en {seconds:.1f} s")
                return self._json(200, {"text": (result.get("text") or "").strip(), "segments": segments,
                                        "language": result.get("language", ""), "model": model_name, "seconds": round(seconds, 1)})
            except Exception as exc:  # noqa: BLE001
                log(f"Error transcribiendo: {exc}")
                return self._json(500, {"error": str(exc)[:300]})
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

        def _drain_small_body(self, limit: int = 1024 * 1024):
            """Lee (y descarta) un cuerpo pequeno antes de rechazar: si queda sin leer, Windows corta la conexion
            y el cliente no alcanza a ver el 401."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if 0 < length <= limit:
                self.rfile.read(length)
            self.close_connection = True

        def _whisper_options(self) -> dict:
            """Idioma y contexto del curso enviados por el VPS (el prompt viaja en base64)."""
            import base64

            options = {}
            language = (self.headers.get("X-Whisper-Language") or "").strip().lower()
            if language.isalpha() and len(language) <= 8:
                options["language"] = language
            encoded = self.headers.get("X-Whisper-Prompt") or ""
            if encoded:
                try:
                    options["prompt"] = base64.b64decode(encoded, validate=True).decode("utf-8")[:1000]
                except (ValueError, UnicodeDecodeError):
                    pass
            return options

        def _copy_chunked(self, out):
            total = 0
            while True:
                size_line = self.rfile.readline().strip()
                size = int(size_line.split(b";")[0], 16) if size_line else 0
                if size == 0:
                    self.rfile.readline()
                    break
                total += size
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError("audio demasiado grande")
                out.write(self.rfile.read(size))
                self.rfile.readline()

    return Handler


class Command(BaseCommand):
    help = "Sirve Whisper por HTTP en 127.0.0.1 para que otro servidor (VPS) transcriba a traves de un tunel SSH."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1", help="Interfaz de escucha (por seguridad, 127.0.0.1).")
        parser.add_argument("--port", type=int, default=9000)
        parser.add_argument("--model", default="", help="Modelo de Whisper (por defecto WHISPER_MODEL).")
        parser.add_argument("--no-preload", action="store_true", help="No cargar el modelo al arrancar.")

    def handle(self, *args, **options):
        from learning.services.transcription import load_whisper_model

        token = getattr(settings, "WHISPER_REMOTE_TOKEN", "")
        if not token:
            raise CommandError("Configura WHISPER_REMOTE_TOKEN en .env (el mismo valor que en el VPS).")
        if options["host"] not in {"127.0.0.1", "localhost", "::1"}:
            self.stderr.write(self.style.WARNING("Escuchando fuera de 127.0.0.1: cualquiera en la red podra llamar al servicio."))
        model_name = options["model"] or settings.WHISPER_MODEL

        from learning.services.transcription import whisper_options

        def transcriber(path, prompt="", language=None):
            return load_whisper_model(model_name).transcribe(path, **whisper_options(prompt, language))

        if not options["no_preload"]:
            self.stdout.write(f"Cargando Whisper '{model_name}'...")
            load_whisper_model(model_name)
        handler = build_handler(transcriber, token, model_name, log=lambda msg: self.stdout.write(msg))
        server = ThreadingHTTPServer((options["host"], options["port"]), handler)
        self.stdout.write(self.style.SUCCESS(
            f"Servicio de transcripcion listo en http://{options['host']}:{options['port']} (modelo {model_name}). Ctrl+C para salir."))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            self.stdout.write("Deteniendo...")
        finally:
            server.server_close()
