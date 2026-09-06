"""Transcripcion de audio con Whisper local (texto y segmentos con tiempo)."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings



def transcribe_audio(audio_path):
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("Instala Whisper local para transcribir: pip install openai-whisper") from exc

    configure_local_ffmpeg(whisper)
    model = whisper.load_model(settings.WHISPER_MODEL)
    result = model.transcribe(str(audio_path))
    return result.get("text", "").strip()


def transcribe_audio_detailed(audio_path) -> tuple[str, list[dict]]:
    """Texto completo y segmentos con marcas de tiempo (start, end, text)."""
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("Instala Whisper local para transcribir: pip install openai-whisper") from exc
    from ..segments import normalize_whisper_result

    configure_local_ffmpeg(whisper)
    model = whisper.load_model(settings.WHISPER_MODEL)
    return normalize_whisper_result(model.transcribe(str(audio_path)))


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
