"""Cliente de Whisper API: servicio privado de transcripcion (una PC con GPU publicada con Cloudflare Tunnel).

Contrato del servicio:
    GET  /health/live                    (publica)  -> 200 {"status": "ok"}
    GET  /health/ready                   (publica)  -> 200 {"status": "ready"} | 503 {"status": "not_ready"}
    POST /v1/transcriptions              (Bearer)   -> 202 {"id", "status": "queued", ...}   modo asincrono
    GET  /v1/transcriptions/{job_id}     (Bearer)   -> {"status": queued|processing|completed|failed, ...}
    POST /v1/audio/transcriptions        (Bearer)   -> 200 {"text": ...}                     modo sincrono

Reglas de seguridad y de uso que este modulo hace cumplir:
- La URL base solo puede apuntar a un hostname autorizado (AUTHORIZED_HOSTS), por HTTPS y con TLS verificado.
  No hay URL por llamada. Las redirecciones no se siguen: el Bearer nunca viaja a otro host.
- La clave sale de la configuracion (WHISPER_API_KEY) y no aparece en repr, errores ni logs (ver `redact`).
- Las rutas de salud se consultan SIN clave.
- Limite global de solicitudes protegidas (por defecto 28 por minuto, bajo el tope de 30 del servidor).
- GET se reintenta con backoff acotado. POST solo se reintenta ante 429/503 claros o si la conexion ni se abrio;
  si la conexion se corta despues de enviar, el trabajo pudo haberse creado: se informa como ambiguo y no se
  reenvia (la API no tiene clave de idempotencia).
- El audio se sube por streaming desde el archivo (sin base64 ni lecturas completas en memoria).
"""
from __future__ import annotations

import email.utils
import logging
import random
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Hostnames a los que se permite enviar la clave. whisper.acueducto.com NO esta activo todavia: agregarlo solo
# cuando el administrador confirme el cambio.
AUTHORIZED_HOSTS = frozenset({"whisper-api.aquelarredemujeres.com"})

MAX_FILE_BYTES = 99_614_720          # 95 MiB
MAX_PROMPT_CHARS = 1000
MODELS = frozenset({"whisper-1", "base"})
RESPONSE_FORMATS = frozenset({"json", "text", "verbose_json"})
PENDING_STATES = frozenset({"queued", "processing"})
TERMINAL_STATES = frozenset({"completed", "failed"})
BACKOFF_SECONDS = (2, 4, 8, 15, 30)
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}$")


# ------------------------------------------------------------------------------------------------ errores
class WhisperApiError(RuntimeError):
    """Error del servicio convertido a un mensaje entendible. `transient` indica si tiene sentido reintentar."""

    transient = False

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None, code: str = ""):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.code = code


class WhisperApiConfigError(WhisperApiError):
    pass


class WhisperApiFileError(WhisperApiError):
    pass


class WhisperApiAuthError(WhisperApiError):
    pass


class WhisperApiForbidden(WhisperApiError):
    pass


class WhisperApiNotFound(WhisperApiError):
    pass


class WhisperApiRejected(WhisperApiError):
    """400, 408, 413, 422 o 504: la solicitud no se acepto y repetirla igual no cambiaria el resultado."""


class WhisperApiBusy(WhisperApiError):
    """429 o 503: el servicio esta ocupado o no esta listo."""

    transient = True


class WhisperApiUnavailable(WhisperApiError):
    """No se pudo conectar (PC apagada, sin Internet, reiniciando) o no quedo listo a tiempo."""

    transient = True


class WhisperApiAmbiguousSubmit(WhisperApiError):
    """La conexion se corto despues de enviar el audio: el trabajo pudo crearse. No se reenvia."""


class WhisperApiJobFailed(WhisperApiError):
    pass


class WhisperApiTimeout(WhisperApiError):
    """El trabajo no termino dentro del plazo local (WHISPER_API_MAX_WAIT_SECONDS)."""


class WhisperApiCancelled(WhisperApiError):
    pass


STATUS_MESSAGES = {
    400: (WhisperApiRejected, "solicitud rechazada por el servicio (host o formato de la solicitud)"),
    401: (WhisperApiAuthError, "credencial rechazada: revisa WHISPER_API_KEY o pide una rotacion al administrador"),
    403: (WhisperApiForbidden, "acceso denegado: la IP publica de salida no esta autorizada en el servicio"),
    404: (WhisperApiNotFound, "trabajo inexistente, expirado o creado con otra credencial"),
    408: (WhisperApiRejected, "la subida del audio supero el tiempo del servidor"),
    413: (WhisperApiRejected, "audio demasiado grande: maximo 95 MiB y 2 horas"),
    422: (WhisperApiRejected, "audio o parametros no validos (formato, archivo vacio, idioma o prompt)"),
    429: (WhisperApiBusy, "demasiadas solicitudes al servicio de transcripcion"),
    503: (WhisperApiBusy, "el servicio de transcripcion esta ocupado o no esta listo"),
    504: (WhisperApiRejected, "el servicio no pudo decodificar el audio a tiempo"),
}


def redact(text: object, secret: str) -> str:
    value = str(text)
    return value.replace(secret, "[REDACTADO]") if secret else value


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Retry-After en segundos o como fecha HTTP."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - (time.time() if now is None else now))


# ------------------------------------------------------------------------------------------------ modelos
@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str = ""
    duration: float | None = None
    segments: list[dict] = field(default_factory=list)

    def as_whisper_dict(self) -> dict:
        return {"text": self.text, "language": self.language, "segments": self.segments}


@dataclass(frozen=True)
class TranscriptionJob:
    id: str
    status: str
    created_at: float | None = None
    updated_at: float | None = None
    result: TranscriptionResult | None = None
    error: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES


def parse_result(raw) -> TranscriptionResult:
    """Tolera los tres formatos: json {"text"}, text (cadena) y verbose_json (con segmentos opcionales)."""
    if isinstance(raw, str):
        return TranscriptionResult(text=raw.strip())
    if not isinstance(raw, dict):
        raise WhisperApiError("respuesta de transcripcion con formato inesperado")
    segments = []
    for order, seg in enumerate(raw.get("segments") or []):
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        try:
            start, end = float(seg.get("start") or 0.0), float(seg.get("end") or 0.0)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        segments.append({"start": start, "end": end, "text": text, "order": order})
    duration = raw.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    return TranscriptionResult(text=str(raw.get("text") or "").strip(), language=str(raw.get("language") or ""),
                               duration=duration, segments=segments)


def parse_job(payload) -> TranscriptionJob:
    if not isinstance(payload, dict):
        raise WhisperApiError("respuesta de trabajo con formato inesperado")
    job_id = str(payload.get("id") or "")
    status = str(payload.get("status") or "")
    if not job_id or status not in PENDING_STATES | TERMINAL_STATES:
        raise WhisperApiError(f"estado de trabajo inesperado: {status or 'vacio'}")
    result = parse_result(payload["result"]) if status == "completed" and "result" in payload else None
    if status == "completed" and result is None:
        raise WhisperApiError("trabajo completado sin resultado")

    def as_float(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return TranscriptionJob(id=job_id, status=status, created_at=as_float(payload.get("created_at")),
                            updated_at=as_float(payload.get("updated_at")), result=result,
                            error=str(payload.get("error") or "")[:120])


# ------------------------------------------------------------------------------------------------ limitador
class RateLimiter:
    """Ventana deslizante compartida por todos los clientes del proceso (el polling tambien cuenta)."""

    def __init__(self, max_calls: int, period: float = 60.0, clock=time.monotonic, sleep=time.sleep):
        self.max_calls = max(1, int(max_calls))
        self.period = period
        self.clock = clock
        self.sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, should_cancel: Callable[[], bool] | None = None):
        while True:
            with self._lock:
                now = self.clock()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                wait = self.period - (now - self._calls[0]) + 0.05
            if should_cancel and should_cancel():
                raise WhisperApiCancelled("transcripcion cancelada")
            self.sleep(min(wait, 5.0))


_SHARED_LIMITERS: dict[int, RateLimiter] = {}
_SHARED_LOCK = threading.Lock()


def shared_limiter(max_calls: int) -> RateLimiter:
    with _SHARED_LOCK:
        if max_calls not in _SHARED_LIMITERS:
            _SHARED_LIMITERS[max_calls] = RateLimiter(max_calls)
        return _SHARED_LIMITERS[max_calls]


# ------------------------------------------------------------------------------------------------ cliente
class WhisperApiClient:
    def __init__(self, base_url: str, api_key: str, *, poll_interval: float = 4.0, request_timeout: float = 620.0,
                 max_wait: float = 9000.0, ready_wait: float = 180.0, model: str = "whisper-1",
                 max_calls_per_minute: int = 28, transport=None, sleep=time.sleep, clock=time.monotonic,
                 limiter: RateLimiter | None = None):
        import httpx

        self.base_url = self._validate_base_url(base_url)
        if not api_key or not api_key.strip():
            raise WhisperApiConfigError("falta WHISPER_API_KEY en la configuracion privada del backend")
        if model not in MODELS:
            raise WhisperApiConfigError("modelo no admitido por el servicio (usa whisper-1 o base)")
        self._api_key = api_key.strip()
        self.poll_interval = max(3.0, float(poll_interval))
        self.max_wait = float(max_wait)
        self.ready_wait = float(ready_wait)
        self.model = model
        self.sleep = sleep
        self.clock = clock
        self.limiter = limiter or shared_limiter(max_calls_per_minute)
        timeout = httpx.Timeout(connect=10.0, read=float(request_timeout), write=float(request_timeout), pool=10.0)
        self._http = httpx.Client(timeout=timeout, follow_redirects=False, verify=True, transport=transport,
                                  headers={"User-Agent": "SIMA-whisper-client/1"})

    # -- ciclo de vida
    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f"WhisperApiClient(base_url={self.base_url!r}, api_key=[REDACTADO])"

    # -- configuracion
    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        parts = urlsplit((base_url or "").strip())
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or host not in AUTHORIZED_HOSTS or parts.username or parts.password or parts.port:
            raise WhisperApiConfigError("WHISPER_API_BASE_URL debe ser https:// y apuntar al hostname autorizado")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise WhisperApiConfigError("WHISPER_API_BASE_URL no debe llevar ruta ni parametros")
        return f"https://{host}"

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    # -- utilidades HTTP
    def _raise_for(self, response, context: str):
        status = response.status_code
        if 300 <= status < 400:
            raise WhisperApiRejected(f"{context}: el servicio respondio con una redireccion ({status}); no se sigue",
                                     status=status)
        if status < 400:
            return
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
        cls, message = STATUS_MESSAGES.get(status, (WhisperApiBusy if status >= 500 else WhisperApiRejected,
                                                   f"respuesta HTTP {status}"))
        code = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                code = str(body.get("error") or body.get("detail") or body.get("status") or "")[:80]
        except ValueError:
            pass
        raise cls(f"{context}: {message}" + (f" ({redact(code, self._api_key)})" if code else ""),
                  status=status, retry_after=retry_after, code=redact(code, self._api_key))

    def _pause(self, attempt: int, retry_after: float | None, deadline: float | None, should_cancel=None):
        base = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        delay = max(base, retry_after or 0.0) + random.uniform(0, 1.0)
        if deadline is not None and self.clock() + delay > deadline:
            raise WhisperApiTimeout("se agoto el plazo local esperando al servicio de transcripcion")
        if should_cancel and should_cancel():
            raise WhisperApiCancelled("transcripcion cancelada")
        logger.info("Whisper API ocupada o no disponible; nuevo intento en %.1f s", delay)
        self.sleep(delay)

    def _get_with_retry(self, path: str, *, auth: bool, context: str, deadline: float | None = None,
                        should_cancel=None, retry_statuses=(429, 503)):
        import httpx

        attempt = 0
        while True:
            if should_cancel and should_cancel():
                raise WhisperApiCancelled("transcripcion cancelada")
            if auth:
                self.limiter.acquire(should_cancel)
            try:
                response = self._http.get(self._url(path), headers=self._auth() if auth else None)
            except httpx.TransportError as exc:
                logger.warning("Whisper API sin conexion en %s: %s", context, exc.__class__.__name__)
                if attempt >= len(BACKOFF_SECONDS) - 1:
                    raise WhisperApiUnavailable(f"{context}: el servicio de transcripcion no responde") from None
                self._pause(attempt, None, deadline, should_cancel)
                attempt += 1
                continue
            if response.status_code in retry_statuses and attempt < len(BACKOFF_SECONDS) - 1:
                self._pause(attempt, parse_retry_after(response.headers.get("Retry-After")), deadline, should_cancel)
                attempt += 1
                continue
            return response

    # -- salud (sin clave)
    def check_live(self) -> bool:
        response = self._get_with_retry("/health/live", auth=False, context="salud", retry_statuses=())
        return response.status_code == 200

    def check_ready(self) -> bool:
        response = self._get_with_retry("/health/ready", auth=False, context="salud", retry_statuses=())
        return response.status_code == 200

    def wait_until_ready(self, should_cancel=None):
        deadline = self.clock() + self.ready_wait
        attempt = 0
        while True:
            try:
                if self.check_ready():
                    return
            except WhisperApiUnavailable:
                pass
            if self.clock() >= deadline:
                raise WhisperApiUnavailable("el servicio de transcripcion no esta listo; reintenta mas tarde")
            try:
                self._pause(attempt, None, deadline, should_cancel)
            except WhisperApiTimeout:
                raise WhisperApiUnavailable("el servicio de transcripcion no esta listo; reintenta mas tarde") from None
            attempt += 1

    # -- validaciones locales
    @staticmethod
    def _check_file(path) -> Path:
        audio = Path(path)
        if not audio.is_file():
            raise WhisperApiFileError("el archivo de audio no existe")
        size = audio.stat().st_size
        if size <= 0:
            raise WhisperApiFileError("el archivo de audio esta vacio")
        if size > MAX_FILE_BYTES:
            raise WhisperApiFileError("el archivo de audio supera el maximo de 95 MiB")
        return audio

    def _fields(self, language: str | None, prompt: str | None, response_format: str) -> dict:
        if response_format not in RESPONSE_FORMATS:
            raise WhisperApiConfigError("response_format no admitido (json, text o verbose_json)")
        fields = {"model": self.model, "response_format": response_format}
        if language:
            language = language.strip().lower()
            if not _LANGUAGE_RE.match(language):
                raise WhisperApiConfigError("codigo de idioma no valido")
            fields["language"] = language
        if prompt:
            prompt = _CONTROL_RE.sub(" ", prompt).strip()[:MAX_PROMPT_CHARS]
            if prompt:
                fields["prompt"] = prompt
        return fields

    def _post_audio(self, path: str, audio: Path, fields: dict, context: str, should_cancel=None):
        """POST multipart por streaming. Reintenta solo 429/503 claros o conexiones que no llegaron a abrirse."""
        import httpx

        attempt = 0
        while True:
            if should_cancel and should_cancel():
                raise WhisperApiCancelled("transcripcion cancelada")
            self.limiter.acquire(should_cancel)
            try:
                with audio.open("rb") as stream:
                    response = self._http.post(
                        self._url(path), headers=self._auth(), data=fields,
                        files={"file": (audio.name.encode("ascii", "ignore").decode() or "audio", stream,
                                        "application/octet-stream")},
                    )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                logger.warning("Whisper API sin conexion al enviar audio: %s", exc.__class__.__name__)
                if attempt >= 3:
                    raise WhisperApiUnavailable(f"{context}: el servicio de transcripcion no responde") from None
                self._pause(attempt, None, None, should_cancel)
                attempt += 1
                continue
            except httpx.TransportError as exc:
                logger.warning("Whisper API corto la conexion tras enviar audio: %s", exc.__class__.__name__)
                raise WhisperApiAmbiguousSubmit(
                    f"{context}: la conexion se corto despues de enviar el audio; el servicio pudo haberlo recibido. "
                    "No se reenvia para no duplicar el trabajo") from None
            if response.status_code in (429, 503) and attempt < 4:
                self._pause(attempt, parse_retry_after(response.headers.get("Retry-After")), None, should_cancel)
                attempt += 1
                continue
            return response

    # -- modo asincrono
    def submit_transcription(self, path, *, language: str | None = "es", prompt: str | None = None,
                             response_format: str = "verbose_json", should_cancel=None) -> TranscriptionJob:
        audio = self._check_file(path)
        fields = self._fields(language, prompt, response_format)
        response = self._post_audio("/v1/transcriptions", audio, fields, "crear transcripcion", should_cancel)
        self._raise_for(response, "crear transcripcion")
        if response.status_code != 202:
            raise WhisperApiError(f"crear transcripcion: respuesta inesperada HTTP {response.status_code}")
        try:
            job = parse_job(response.json())
        except ValueError:
            raise WhisperApiError("crear transcripcion: respuesta no es JSON") from None
        logger.info("Whisper API: trabajo %s creado (%s)", job.id, job.status)
        return job

    def get_transcription(self, job_id: str, *, deadline: float | None = None, should_cancel=None) -> TranscriptionJob:
        if not _UUID_RE.match(job_id or ""):
            raise WhisperApiNotFound("identificador de trabajo no valido")
        response = self._get_with_retry(f"/v1/transcriptions/{job_id}", auth=True, context="consultar transcripcion",
                                        deadline=deadline, should_cancel=should_cancel)
        self._raise_for(response, "consultar transcripcion")
        try:
            return parse_job(response.json())
        except ValueError:
            raise WhisperApiError("consultar transcripcion: respuesta no es JSON") from None

    def wait_for_transcription(self, job_id: str, *, max_wait: float | None = None, should_cancel=None,
                               on_status: Callable[[TranscriptionJob], None] | None = None) -> TranscriptionResult:
        deadline = self.clock() + (self.max_wait if max_wait is None else float(max_wait))
        last_status = ""
        while True:
            job = self.get_transcription(job_id, deadline=deadline, should_cancel=should_cancel)
            if job.status != last_status:
                last_status = job.status
                logger.info("Whisper API: trabajo %s %s", job.id, job.status)
                if on_status:
                    on_status(job)
            if job.status == "completed":
                return job.result
            if job.status == "failed":
                raise WhisperApiJobFailed(f"la transcripcion fallo en el servicio ({job.error or 'sin detalle'})",
                                          code=job.error)
            delay = self.poll_interval + random.uniform(-0.5, 1.0)
            if self.clock() + delay > deadline:
                raise WhisperApiTimeout("la transcripcion no termino dentro del plazo local")
            if should_cancel and should_cancel():
                raise WhisperApiCancelled("transcripcion cancelada")
            self.sleep(max(3.0, delay))

    # -- modo sincrono (solo audios cortos)
    def transcribe_sync(self, path, *, language: str | None = "es", prompt: str | None = None,
                        response_format: str = "verbose_json") -> TranscriptionResult:
        audio = self._check_file(path)
        fields = self._fields(language, prompt, response_format)
        response = self._post_audio("/v1/audio/transcriptions", audio, fields, "transcribir")
        self._raise_for(response, "transcribir")
        if response_format == "text":
            return TranscriptionResult(text=response.text.strip())
        try:
            return parse_result(response.json())
        except ValueError:
            raise WhisperApiError("transcribir: respuesta no es JSON") from None

    # -- camino principal
    def transcribe(self, path, *, language: str | None = "es", prompt: str | None = None,
                   response_format: str = "verbose_json", resume_job_id: str | None = None,
                   on_submitted: Callable[[str], None] | None = None, should_cancel=None,
                   on_status: Callable[[TranscriptionJob], None] | None = None) -> TranscriptionResult:
        """Asincrono: espera a que el servicio este listo, crea el trabajo y consulta hasta terminar.

        resume_job_id: trabajo creado antes para esta misma operacion; si sigue consultable se retoma en vez de
        subir el audio otra vez (evita duplicados tras un corte o un reinicio del worker).
        """
        if resume_job_id:
            try:
                self.get_transcription(resume_job_id, should_cancel=should_cancel)
                return self.wait_for_transcription(resume_job_id, should_cancel=should_cancel, on_status=on_status)
            except WhisperApiNotFound:
                logger.info("Whisper API: el trabajo anterior ya no existe; se crea uno nuevo")
        self.wait_until_ready(should_cancel)
        job = self.submit_transcription(path, language=language, prompt=prompt, response_format=response_format,
                                        should_cancel=should_cancel)
        if on_submitted:
            on_submitted(job.id)
        return self.wait_for_transcription(job.id, should_cancel=should_cancel, on_status=on_status)


def client_from_settings(**overrides) -> WhisperApiClient:
    from django.conf import settings

    options = dict(
        base_url=getattr(settings, "WHISPER_API_BASE_URL", ""),
        api_key=getattr(settings, "WHISPER_API_KEY", ""),
        poll_interval=getattr(settings, "WHISPER_API_POLL_INTERVAL_SECONDS", 4),
        request_timeout=getattr(settings, "WHISPER_API_REQUEST_TIMEOUT_SECONDS", 620),
        max_wait=getattr(settings, "WHISPER_API_MAX_WAIT_SECONDS", 9000),
        ready_wait=getattr(settings, "WHISPER_API_READY_WAIT_SECONDS", 180),
        model=getattr(settings, "WHISPER_API_MODEL", "whisper-1"),
        max_calls_per_minute=getattr(settings, "WHISPER_API_MAX_CALLS_PER_MINUTE", 28),
    )
    options.update(overrides)
    return WhisperApiClient(**options)


def service_status(base_url: str, timeout: float = 5.0, transport=None) -> dict:
    """live y ready del servicio, sin credencial (para /salud/ y check_ai)."""
    import httpx

    try:
        base = WhisperApiClient._validate_base_url(base_url)
    except WhisperApiConfigError as exc:
        return {"reachable": False, "ready": False, "error": str(exc)}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, verify=True, transport=transport) as http:
            live = http.get(f"{base}/health/live").status_code == 200
            ready = live and http.get(f"{base}/health/ready").status_code == 200
        return {"reachable": live, "ready": ready}
    except httpx.TransportError as exc:
        return {"reachable": False, "ready": False, "error": exc.__class__.__name__}
