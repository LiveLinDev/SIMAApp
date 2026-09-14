"""Transcripcion de audio con Whisper (texto y segmentos con tiempo).

Backends (TRANSCRIPTION_BACKEND):
- local:  Whisper se carga en este mismo proceso.
- remote: el audio se envia a `manage.py serve_whisper`, que corre en otra maquina (por ejemplo la PC del
          equipo, alcanzada desde el VPS por un tunel SSH inverso en 127.0.0.1:9000).
TRANSCRIPTION_FALLBACK (opcional) define que hacer si el backend principal falla: local o cloud.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

BACKEND_LABELS = {
    "local": "Whisper en este servidor",
    "remote": "Whisper en el equipo de transcripcion (tunel SSH)",
    "cloud": "API de Whisper del proveedor en la nube",
}


class TranscriptionUnavailable(RuntimeError):
    """El servicio de transcripcion configurado no esta disponible."""


def transcription_backend() -> str:
    backend = (getattr(settings, "TRANSCRIPTION_BACKEND", "local") or "local").strip().lower()
    return backend if backend in BACKEND_LABELS else "local"


def transcription_label(backend: str | None = None) -> str:
    return BACKEND_LABELS.get(backend or transcription_backend(), BACKEND_LABELS["local"])


def transcribe_audio(audio_path):
    text, _segments = transcribe_audio_detailed(audio_path)
    return text


def transcribe_audio_detailed(audio_path) -> tuple[str, list[dict]]:
    """Texto completo y segmentos con marcas de tiempo (start, end, text) segun el backend configurado."""
    primary = transcription_backend()
    fallback = (getattr(settings, "TRANSCRIPTION_FALLBACK", "") or "").strip().lower()
    try:
        return _run_backend(primary, audio_path)
    except Exception as exc:  # noqa: BLE001
        if not fallback or fallback == primary or fallback not in BACKEND_LABELS:
            raise
        logger.warning("Transcripcion %s fallo (%s); usando respaldo %s", primary, exc, fallback)
        return _run_backend(fallback, audio_path)


def _run_backend(backend: str, audio_path) -> tuple[str, list[dict]]:
    if backend == "remote":
        return transcribe_remote(audio_path)
    if backend == "cloud":
        return transcribe_cloud(audio_path)
    return transcribe_local(audio_path)


# ---------------------------------------------------------------------------------------------- local
_MODEL_CACHE: dict[str, object] = {}


def load_whisper_model(model_name: str | None = None):
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("Instala Whisper local para transcribir: pip install openai-whisper") from exc
    name = model_name or settings.WHISPER_MODEL
    if name not in _MODEL_CACHE:
        configure_local_ffmpeg(whisper)
        _MODEL_CACHE[name] = whisper.load_model(name)
    return _MODEL_CACHE[name]


def transcribe_local(audio_path, model_name: str | None = None) -> tuple[str, list[dict]]:
    from ..segments import normalize_whisper_result

    model = load_whisper_model(model_name)
    return normalize_whisper_result(model.transcribe(str(audio_path)))


# ---------------------------------------------------------------------------------------------- remote
def _remote_base() -> str:
    return (getattr(settings, "WHISPER_REMOTE_URL", "") or "http://127.0.0.1:9000").rstrip("/")


def _remote_headers(filename: str = "") -> dict:
    headers = {}
    token = getattr(settings, "WHISPER_REMOTE_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if filename:
        headers["X-Filename"] = Path(filename).name.encode("ascii", "ignore").decode() or "audio"
        headers["Content-Type"] = "application/octet-stream"
    return headers


def transcribe_remote(audio_path) -> tuple[str, list[dict]]:
    import httpx

    from ..segments import normalize_whisper_result

    url = f"{_remote_base()}/transcribe"
    timeout = httpx.Timeout(float(getattr(settings, "WHISPER_REMOTE_TIMEOUT", 3600)), connect=10.0)
    try:
        with open(audio_path, "rb") as fh:
            response = httpx.post(url, content=fh, headers=_remote_headers(str(audio_path)), timeout=timeout)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
        raise TranscriptionUnavailable(
            "El equipo de transcripcion no responde. Verifica que la PC este encendida con "
            "`iniciar-transcripcion-remota.bat` y el tunel SSH activo, y luego usa Reintentar."
        ) from exc
    except httpx.TimeoutException as exc:
        raise TranscriptionUnavailable("La transcripcion remota supero el tiempo maximo (WHISPER_REMOTE_TIMEOUT).") from exc
    if response.status_code == 401:
        raise TranscriptionUnavailable("El equipo de transcripcion rechazo el token (WHISPER_REMOTE_TOKEN no coincide).")
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("error", "")
        except Exception:  # noqa: BLE001
            detail = response.text[:200]
        raise TranscriptionUnavailable(f"El equipo de transcripcion devolvio {response.status_code}: {detail}")
    return normalize_whisper_result(response.json())


def remote_status(timeout: float = 2.0) -> dict:
    """Estado del servicio remoto para /salud/ (sin datos sensibles)."""
    import httpx

    try:
        response = httpx.get(f"{_remote_base()}/health", headers=_remote_headers(), timeout=timeout)
        data = response.json() if response.status_code == 200 else {}
        return {"reachable": response.status_code == 200, "model": data.get("model", ""), "busy": data.get("busy", False)}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": exc.__class__.__name__}


# ---------------------------------------------------------------------------------------------- cloud
def transcribe_cloud(audio_path) -> tuple[str, list[dict]]:
    """API de transcripcion compatible con OpenAI (Groq: whisper-large-v3-turbo). El audio sale a un tercero."""
    from openai import OpenAI

    from ..segments import normalize_whisper_result
    from .backends import cloud_backend_available, normalize_openai_base_url

    if not cloud_backend_available():
        raise TranscriptionUnavailable("No hay proveedor en la nube configurado para transcribir (CLOUD_API_KEY).")
    client = OpenAI(api_key=settings.CLOUD_API_KEY, base_url=normalize_openai_base_url(settings.CLOUD_API_BASE) or None)
    with open(audio_path, "rb") as fh:
        result = client.audio.transcriptions.create(
            model=getattr(settings, "CLOUD_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo"),
            file=fh,
            response_format="verbose_json",
        )
    data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    return normalize_whisper_result(data)


# ---------------------------------------------------------------------------------------------- ffmpeg
def configure_local_ffmpeg(whisper_module=None):
    try:
        import imageio_ffmpeg
    except ImportError:
        return None

    ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if whisper_module is not None:
        patch_whisper_loader(whisper_module, ffmpeg_path)
    return ffmpeg_path


def patch_whisper_loader(whisper_module, ffmpeg_path):
    import numpy as np
    from subprocess import CalledProcessError, run

    def load_audio(file, sr=16000):
        cmd = [
            str(ffmpeg_path),
            "-nostdin",
            "-threads",
            "0",
            "-i",
            file,
            "-f",
            "s16le",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sr),
            "-",
        ]
        try:
            out = run(cmd, capture_output=True, check=True).stdout
        except CalledProcessError as exc:
            raise RuntimeError(f"Failed to load audio: {exc.stderr.decode(errors='ignore')}") from exc
        return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0

    whisper_module.audio.load_audio = load_audio
