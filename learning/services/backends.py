"""Proveedores de IA: resolucion de backend (nube compatible OpenAI / Anthropic / local), llamada y errores."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import re
import threading
import time

from django.conf import settings



class LocalAITimeoutError(RuntimeError):
    """El servidor de IA local no respondio dentro del timeout configurado."""


BACKEND_ALIASES = {
    "cloud": "cloud", "nube": "cloud", "anthropic": "cloud", "claude": "cloud", "deepseek": "cloud",
    "local": "local", "qwen": "local", "local_qwen": "local", "ollama": "local",
}


def normalize_backend(value) -> str:
    """Normaliza nombres de backend, incluidos los heredados ("anthropic", "deepseek", "qwen")."""
    key = (value or "auto").strip().lower()
    if key == "auto":
        return "auto"
    return BACKEND_ALIASES.get(key, key)


def cloud_backend_available() -> bool:
    provider = getattr(settings, "CLOUD_PROVIDER", "openai_compatible")
    if provider == "anthropic":
        return is_real_cloud_key(getattr(settings, "ANTHROPIC_API_KEY", "")) or is_real_cloud_key(
            getattr(settings, "CLOUD_API_KEY", "")
        )
    return is_real_cloud_key(getattr(settings, "CLOUD_API_KEY", ""))


def get_available_backends() -> dict:
    """
    Backends de IA disponibles.
    - cloud: proveedor externo configurado con CLOUD_* (o el alias heredado DEEPSEEK_*).
    - local: siempre se ofrece; asume una API compatible con OpenAI en LOCAL_API_BASE.
    """
    cloud_ok = cloud_backend_available()
    provider = getattr(settings, "CLOUD_PROVIDER", "openai_compatible")
    return {
        "cloud": cloud_ok,
        "local": True,
        "default": "cloud" if cloud_ok else "local",
        "cloud_provider": provider if cloud_ok else "",
        "cloud_label": getattr(settings, "CLOUD_LABEL", "Nube"),
        "cloud_model": getattr(settings, "CLOUD_MODEL", ""),
        # nombre antiguo, por si alguna plantilla o script externo aun lo consulta
        "anthropic": cloud_ok,
    }


def is_real_anthropic_key(key: str | None) -> bool:
    return is_real_cloud_key(key)


def is_real_cloud_key(key: str | None) -> bool:
    value = (key or "").strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered in {"local", "none", "null", "false", "0", "change-me", "changeme"}:
        return False
    placeholder_markers = ("tu_clave", "your_", "example", "placeholder", "sk-...")
    return not any(marker in lowered for marker in placeholder_markers)


def resolve_backend(backend: str = "auto") -> str:
    backend = normalize_backend(backend)
    if backend == "auto":
        return get_available_backends()["default"]
    return backend


def use_direct_cloud_mini(backend: str) -> bool:
    """
    Con CLOUD_DIRECT_MINI el proveedor cloud entrega el MINI final en una sola
    pasada y el pipeline solo aplica filtros deterministas (sin verificacion).
    """
    if normalize_backend(backend) != "cloud":
        return False
    return bool(getattr(settings, "CLOUD_DIRECT_MINI", False))


def call_ai(prompt: str, backend: str = "auto", role: str = "generation", max_tokens: int | None = None) -> str:
    """
    max_tokens: tope de salida para ESTA llamada (se recorta a CLOUD_MAX_TOKENS si esta definido).
    Los proveedores con limite de tokens por peticion cuentan la salida reservada, asi que cada
    llamada pide solo lo que necesita.
    """
    backend = resolve_backend(backend)
    if backend == "cloud":
        if not cloud_backend_available():
            raise RuntimeError(
                "No hay un proveedor de IA en la nube configurado (CLOUD_API_KEY en .env). Usa el backend local."
            )
        return _call_cloud_model(prompt, role=role, max_tokens=max_tokens)
    if backend == "local":
        return _call_local(prompt, role=role)
    raise RuntimeError(f"Backend desconocido: {backend}")


def clean_ai_error(exc) -> str:
    err_str = str(exc)
    if "<!DOCTYPE" in err_str or "<html" in err_str.lower():
        return "No se pudo conectar al servidor de IA. Verifica que el modelo local esté corriendo y que LOCAL_API_BASE en .env sea correcto."
    return err_str


VERIFICATION_ROLES = {"verification", "coherence", "transcript"}


def model_for_role(role: str) -> str:
    """
    CLOUD_MODEL genera; CLOUD_VERIFICATION_MODEL (opcional) verifica, repara coherencia y
    transcripcion. Permite combinar un modelo que respeta bien el formato .mini con otro
    que razona mejor sobre hechos (p. ej. Qwen 3.8 para generar y GPT-OSS 120B para verificar).
    """
    if role in VERIFICATION_ROLES:
        return getattr(settings, "CLOUD_VERIFICATION_MODEL", "") or getattr(settings, "CLOUD_MODEL", "")
    return getattr(settings, "CLOUD_MODEL", "")


def _cloud_temperature(role: str) -> float:
    if role in {"verification", "coherence", "transcript"}:
        return getattr(settings, "CLOUD_VERIFICATION_TEMPERATURE", 0.2)
    return getattr(settings, "CLOUD_GENERATION_TEMPERATURE", 0.3)


def _call_cloud_model(prompt: str, role: str = "generation", max_tokens: int | None = None) -> str:
    """Enruta al proveedor cloud configurado en CLOUD_PROVIDER."""
    if getattr(settings, "CLOUD_PROVIDER", "openai_compatible") == "anthropic":
        return _call_anthropic(prompt, role=role, max_tokens=max_tokens)
    return _call_openai_compatible(prompt, role=role, max_tokens=max_tokens)


REASONING_MARKERS = ("gpt-oss", "thinking", "reasoner", "/o1", "/o3", "-r1")
REASONING_EXTRA_TOKENS = 2500   # los modelos con razonamiento gastan salida "pensando" antes de responder


def is_reasoning_model(model: str) -> bool:
    name = (model or "").lower()
    return any(marker in name for marker in REASONING_MARKERS)


def effective_max_tokens(requested: int | None, model: str = "") -> int:
    """
    Tope de salida: lo que pide la llamada (mas un margen si el modelo razona antes de
    responder), recortado al CLOUD_MAX_TOKENS global (0 = sin tope).
    """
    cap = int(getattr(settings, "CLOUD_MAX_TOKENS", 6000) or 0)
    if requested and requested > 0:
        wanted = int(requested) + (REASONING_EXTRA_TOKENS if is_reasoning_model(model) else 0)
        return min(cap, wanted) if cap > 0 else wanted
    return cap


def _call_anthropic(prompt: str, role: str = "generation", max_tokens: int | None = None) -> str:
    try:
        from anthropic import (
            Anthropic,
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            RateLimitError,
        )
    except ImportError as exc:
        raise RuntimeError("Instala el paquete anthropic: pip install anthropic") from exc

    model = getattr(settings, "CLOUD_MODEL", "") or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-5")
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or getattr(settings, "CLOUD_API_KEY", "")
    timeout = getattr(settings, "CLOUD_API_TIMEOUT", 120)
    client = Anthropic(api_key=api_key, timeout=timeout, max_retries=0)
    try:
        # Sin temperature: los modelos Claude 4.6+ rechazan parametros de muestreo.
        message = client.messages.create(
            model=model,
            max_tokens=effective_max_tokens(max_tokens, model) or 6000,
            messages=[{"role": "user", "content": prompt}],
        )
    except AuthenticationError as exc:
        raise RuntimeError(
            "Anthropic rechazo la API key configurada. Revisa ANTHROPIC_API_KEY / CLOUD_API_KEY en .env."
        ) from exc
    except RateLimitError as exc:
        raise RuntimeError("Anthropic devolvio limite de tasa (429). Reintenta en unos segundos.") from exc
    except APIConnectionError as exc:
        raise RuntimeError(f"No se pudo conectar a Anthropic (timeout {timeout}s): {exc}") from exc
    except APIStatusError as exc:
        raise RuntimeError(f"Error de Anthropic ({exc.status_code}): {exc.message}") from exc

    if message.stop_reason == "refusal":
        raise RuntimeError("Claude rechazo la solicitud (stop_reason=refusal).")
    text = "\n".join(block.text for block in message.content if getattr(block, "type", "") == "text").strip()
    if not text:
        raise RuntimeError(f"Claude devolvio una respuesta vacia (stop_reason={message.stop_reason}).")
    return text.replace("\x00", "")


def _call_openai_compatible(prompt: str, role: str = "generation", max_tokens: int | None = None) -> str:
    """Proveedor cloud con API compatible con OpenAI Chat Completions (DeepSeek, OpenAI, Gemini, Qwen, Groq...)."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Instala openai para usar el backend cloud: pip install openai") from exc

    label = getattr(settings, "CLOUD_LABEL", "Nube")
    base_url = normalize_openai_base_url(getattr(settings, "CLOUD_API_BASE", "") or "https://api.deepseek.com")
    model = model_for_role(role)
    timeout = getattr(settings, "CLOUD_API_TIMEOUT", 120)
    if not model:
        raise RuntimeError("CLOUD_MODEL no esta configurado en .env.")

    client = _chat_client(OpenAI, base_url, timeout)
    request = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=_cloud_temperature(role),
        stream=False,
        timeout=timeout,
    )
    # Algunos endpoints compatibles (Gemini) no aceptan max_tokens: CLOUD_MAX_TOKENS=0 lo omite.
    budget = effective_max_tokens(max_tokens, model)
    if budget > 0:
        request["max_tokens"] = budget
    if "gpt-oss" in model.lower():
        # Groq/OpenAI: menos razonamiento = menos tokens de salida consumidos antes de la respuesta.
        request["extra_body"] = {"reasoning_effort": getattr(settings, "CLOUD_REASONING_EFFORT", "low")}
    if getattr(settings, "CLOUD_PROVIDER", "") == "qwen":
        # Los modelos Qwen3 pueden traer "razonamiento" que rompe el bloque .mini y, en algunos
        # modelos, obliga a streaming; se pide la respuesta directa.
        request["extra_body"] = {"enable_thinking": False}
    limit_per_minute = int(getattr(settings, "CLOUD_TOKENS_PER_MINUTE", 0) or 0)
    if limit_per_minute > 0:
        _limiter.acquire(estimate_tokens(prompt) + (budget or 0), limit_per_minute)
    retries = max(0, int(getattr(settings, "CLOUD_RATE_LIMIT_RETRIES", 5)))
    max_wait = float(getattr(settings, "CLOUD_RATE_LIMIT_MAX_WAIT", 90))
    attempt = 0
    while True:
        try:
            response = client.chat.completions.create(**request)
            break
        except Exception as exc:
            # Niveles gratuitos (Groq, Gemini) limitan tokens por minuto: se espera lo que
            # sugiere el proveedor y se reintenta en vez de tumbar el pipeline.
            if _is_rate_limit_error(exc) and attempt < retries:
                attempt += 1
                wait = _suggested_wait_seconds(str(exc)) or min(max_wait, 5.0 * 2 ** (attempt - 1))
                time.sleep(min(max_wait, wait + 0.5))
                continue
            _raise_cloud_error(exc, label, model, base_url, timeout, attempt)

    return _extract_chat_completion_text(response, label)


class TokenRateLimiter:
    """
    Ventana deslizante de 60 s: antes de cada llamada se estima su costo (entrada + salida
    reservada) y, si la ventana ya no lo admite, se espera. Evita el 429 en vez de sufrirlo.
    Vive en el proceso: en modo thread cubre a los workers en hilos; con varios procesos
    `run_worker`, cada uno respeta su propia cuota (usa un valor por worker).
    """

    def __init__(self, clock=time.monotonic, sleeper=time.sleep):
        self._events: list[tuple[float, int]] = []
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.Lock()

    def acquire(self, tokens: int, limit_per_minute: int) -> float:
        if limit_per_minute <= 0 or tokens <= 0:
            return 0.0
        waited = 0.0
        with self._lock:
            while True:
                now = self._clock()
                self._events = [(t, n) for t, n in self._events if now - t < 60.0]
                used = sum(n for _, n in self._events)
                if used + tokens <= limit_per_minute or not self._events:
                    self._events.append((now, min(tokens, limit_per_minute)))
                    return waited
                oldest = self._events[0][0]
                pause = max(0.5, 60.0 - (now - oldest) + 0.2)
                self._sleep(pause)
                waited += pause


_limiter = TokenRateLimiter()


def estimate_tokens(text: str) -> int:
    """Estimacion barata (~3.5 caracteres por token en espanol)."""
    return int(len(text or "") / 3.5) + 1


def _chat_client(OpenAI, base_url: str, timeout: int):
    return OpenAI(api_key=getattr(settings, "CLOUD_API_KEY", ""), base_url=base_url, max_retries=0, timeout=timeout)


def _is_rate_limit_error(exc) -> bool:
    try:
        from openai import RateLimitError
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, RateLimitError) or getattr(exc, "status_code", None) == 429


_WAIT_RE = re.compile(r"try again in\s*(?:(\d+)m)?([\d.]+)s", re.I)


def _suggested_wait_seconds(message: str):
    """Groq y otros escriben 'Please try again in 14.2s' (o '2m3.5s') en el mensaje del 429."""
    m = _WAIT_RE.search(message or "")
    if not m:
        return None
    minutes = int(m.group(1) or 0)
    return minutes * 60 + float(m.group(2))


def _raise_cloud_error(exc, label, model, base_url, timeout, attempts):
    from openai import APIConnectionError, APITimeoutError, AuthenticationError, NotFoundError

    if getattr(exc, "status_code", None) == 413:
        raise RuntimeError(
            f"{label} rechazo la peticion por tamano (413): baja CLOUD_CHUNK_WORDS (p. ej. 1200) y "
            "CLOUD_ITEMS_PER_CHUNK_MAX (p. ej. 12) en .env para el nivel gratuito."
        ) from exc
    if _is_rate_limit_error(exc):
        detail = re.sub(r"\s+", " ", str(exc))
        detail = detail[detail.find("Rate limit"):][:220] if "Rate limit" in detail else detail[:220]
        raise RuntimeError(
            f"{label} alcanzo el limite de uso del nivel actual (429) tras {attempts} reintento(s): {detail} "
            "Ajusta CLOUD_TOKENS_PER_MINUTE en .env al limite del modelo o espera."
        ) from exc
    if True:
        if isinstance(exc, AuthenticationError):
            raise RuntimeError(f"{label} rechazo la API key configurada. Revisa CLOUD_API_KEY en .env.") from exc
        if isinstance(exc, NotFoundError):
            raise RuntimeError(
                f"{label} no reconoce el modelo '{model}'. Revisa CLOUD_MODEL en .env "
                "(por ejemplo, DeepSeek retiro deepseek-chat en julio de 2026)."
            ) from exc
        if isinstance(exc, APITimeoutError):
            raise RuntimeError(f"{label} no respondio dentro del timeout de {timeout} segundos.") from exc
        if isinstance(exc, APIConnectionError):
            raise RuntimeError(f"No se pudo conectar a {label} en {base_url}. Revisa CLOUD_API_BASE en .env.") from exc
        raise RuntimeError(f"Error llamando a {label}: {exc}") from exc


_call_deepseek = _call_openai_compatible


def _extract_chat_completion_text(response, model_label: str) -> str:
    choice = response.choices[0]
    msg = choice.message
    text = (msg.content or "").strip()
    if not text:
        text = (getattr(msg, "reasoning_content", None) or "").strip()
    if not text:
        raise RuntimeError(
            f"{model_label} devolvio una respuesta vacia (finish_reason={choice.finish_reason})."
        )

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return text.replace("\x00", "")


def _call_local(prompt: str, role: str = "generation") -> str:
    """
    Llama a un modelo local compatible con OpenAI Chat Completions.
    Maneja modelos con thinking (Qwen3) donde content puede venir vacío
    y el texto real está en reasoning_content o en el primer choice.
    """
    local_base = normalize_openai_base_url(getattr(settings, "LOCAL_API_BASE", "http://localhost:1234/v1"))
    model = getattr(settings, "LOCAL_MODEL", None) or settings.CLOUD_MODEL
    temperature = (
        getattr(settings, "LOCAL_VERIFICATION_TEMPERATURE", 0.3)
        if role in {"verification", "coherence", "transcript"}
        else getattr(settings, "LOCAL_GENERATION_TEMPERATURE", 0.4)
    )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Instala openai para usar el backend local: pip install openai") from exc

    client = OpenAI(
        api_key=getattr(settings, "LOCAL_API_KEY", "local"),
        base_url=local_base,
        max_retries=0,
        timeout=getattr(settings, "LOCAL_API_TIMEOUT", 120),
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=getattr(settings, "LOCAL_MAX_TOKENS", 6000),
            temperature=temperature,
            stream=False,
            timeout=getattr(settings, "LOCAL_API_TIMEOUT", 120),
        )
    except Exception as exc:
        from openai import APIConnectionError, APITimeoutError
        if isinstance(exc, APITimeoutError):
            raise LocalAITimeoutError(
                f"El servidor de IA local en {local_base} no respondio dentro del timeout de "
                f"{getattr(settings, 'LOCAL_API_TIMEOUT', 120)} segundos. "
                "Reduce el tamano del texto, sube LOCAL_API_TIMEOUT en .env, o revisa que el modelo local tenga recursos suficientes."
            ) from exc
        if isinstance(exc, APIConnectionError):
            raise RuntimeError(
                f"No se pudo conectar al servidor de IA en {local_base}. "
                "Verifica que llama-server este corriendo y que LOCAL_API_BASE apunte al endpoint /v1."
            ) from exc
        raise RuntimeError(
            f"Error inesperado llamando al servidor de IA en {local_base}: {exc}"
        ) from exc

    choice = response.choices[0]
    msg = choice.message

    # Qwen3 y otros modelos con thinking devuelven el texto en content
    # pero a veces lo ponen en reasoning_content cuando thinking está activo.
    # Intentamos content primero, luego reasoning_content como fallback.
    text = (msg.content or "").strip()
    if not text:
        text = (getattr(msg, "reasoning_content", None) or "").strip()
    if not text:
        raise RuntimeError(
            f"El modelo devolvió una respuesta vacía (finish_reason={choice.finish_reason}). "
            f"Verifica que el servidor local esté corriendo en {local_base}."
        )

    # Qwen3 con --jinja incluye <think>...</think> antes del output real — lo removemos
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Algunos servidores locales (Ollama) pueden devolver bytes NUL que PostgreSQL rechaza
    text = text.replace("\x00", "")

    return text


def normalize_openai_base_url(base_url: str) -> str:
    """
    llama-server expone la API compatible con OpenAI bajo /v1.
    Permite configurar http://127.0.0.1:8001 o http://127.0.0.1:8001/v1.
    """
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        return "http://127.0.0.1:8001/v1"

    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


def call_claude(prompt: str, backend: str = "auto") -> str:
    return call_ai(prompt, backend=backend)
