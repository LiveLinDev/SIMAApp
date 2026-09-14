"""Prueba real de Whisper API con un audio corto y no sensible.

    python manage.py check_whisper_api ruta/al/audio.mp3

Orden: /health/live -> /health/ready -> POST /v1/transcriptions (202) -> consulta cada 3-5 s -> estado final.
No imprime la credencial ni el texto transcrito (solo su longitud).
"""
from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verifica Whisper API: salud, creacion del trabajo (HTTP 202) y estado terminal, sin mostrar secretos."

    def add_arguments(self, parser):
        parser.add_argument("audio", help="Audio corto y no sensible (mp3, wav, m4a, ogg, webm o flac).")
        parser.add_argument("--language", default="es")

    def handle(self, *args, **options):
        from learning.services.whisper_api import WhisperApiError, client_from_settings

        audio = Path(options["audio"])
        if not audio.is_file():
            raise CommandError("El audio no existe.")
        if not getattr(settings, "WHISPER_API_KEY", ""):
            raise CommandError("Falta WHISPER_API_KEY en el .env privado del backend.")

        try:
            with client_from_settings() as client:
                self.stdout.write(f"Servicio: {client.base_url}")
                live = client.check_live()
                self.stdout.write(f"1. /health/live  -> {'200' if live else 'no disponible'}")
                if not live:
                    raise CommandError("El servicio no esta vivo (la PC anfitriona puede estar apagada o sin Internet).")
                ready = client.check_ready()
                self.stdout.write(f"2. /health/ready -> {'200' if ready else '503 not_ready'}")
                if not ready:
                    raise CommandError("El servicio no esta listo; intenta en unos minutos.")

                started = time.monotonic()
                job = client.submit_transcription(audio, language=options["language"], response_format="json")
                self.stdout.write(f"3. POST /v1/transcriptions -> 202, trabajo {job.id} ({job.status})")

                def status(remote):
                    self.stdout.write(f"   {time.monotonic() - started:5.1f} s  {remote.status}")

                result = client.wait_for_transcription(job.id, on_status=status)
                self.stdout.write(self.style.SUCCESS(
                    f"4. Estado final: completed en {time.monotonic() - started:.1f} s; "
                    f"result.text presente ({len(result.text)} caracteres)."))
        except WhisperApiError as exc:
            raise CommandError(f"Whisper API: {exc}") from None
