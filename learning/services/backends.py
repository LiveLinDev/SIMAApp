"""Proveedores de IA: resolucion de backend (nube compatible OpenAI / Anthropic / local), llamada y errores."""
from __future__ import annotations

import re
from urllib.parse import urlparse

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


def call_ai(prompt: str, backend: str = "auto", role: str = "generation") -> str:
    backend = resolve_backend(backend)
    if backend == "cloud":
        if not cloud_backend_available():
            raise RuntimeError(
                "No hay un proveedor de IA en la nube configurado (CLOUD_API_KEY en .env). Usa el backend local."
            )
        return _call_cloud_model(prompt, role=role)
    if backend == "local":
        return _call_local(prompt, role=role)
    raise RuntimeError(f"Backend desconocido: {backend}")


def clean_ai_error(exc) -> str:
    err_str = str(exc)
    if "<!DOCTYPE" in err_str or "<html" in err_str.lower():
        return "No se pudo conectar al servidor de IA. Verifica que el modelo local esté corriendo y que LOCAL_API_BASE en .env sea correcto."
    return err_str


def _cloud_temperature(role: str) -> float:
    if role in {"verification", "coherence", "transcript"}:
        return getattr(settings, "CLOUD_VERIFICATION_TEMPERATURE", 0.2)
    return getattr(settings, "CLOUD_GENERATION_TEMPERATURE", 0.3)


def _call_cloud_model(prompt: str, role: str = "generation") -> str:
    """Enruta al proveedor cloud configurado en CLOUD_PROVIDER."""
    if getattr(settings, "CLOUD_PROVIDER", "openai_compatible") == "anthropic":
        return _call_anthropic(prompt, role=role)
    return _call_openai_compatible(prompt, role=role)


def _call_anthropic(prompt: str, role: str = "generation") -> str:
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
            max_tokens=getattr(settings, "CLOUD_MAX_TOKENS", 6000),
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


def _call_openai_compatible(prompt: str, role: str = "generation") -> str:
    """Proveedor cloud con API compatible con OpenAI Chat Completions (DeepSeek, OpenAI, Gemini, Qwen, Groq...)."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Instala openai para usar el backend cloud: pip install openai") from exc

    label = getattr(settings, "CLOUD_LABEL", "Nube")
    base_url = normalize_openai_base_url(getattr(settings, "CLOUD_API_BASE", "") or "https://api.deepseek.com")
    model = getattr(settings, "CLOUD_MODEL", "")
    timeout = getattr(settings, "CLOUD_API_TIMEOUT", 120)
    if not model:
        raise RuntimeError("CLOUD_MODEL no esta configurado en .env.")

    client = OpenAI(
        api_key=getattr(settings, "CLOUD_API_KEY", ""),
        base_url=base_url,
        max_retries=0,
        timeout=timeout,
    )
    request = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=_cloud_temperature(role),
        stream=False,
        timeout=timeout,
    )
    # Algunos endpoints compatibles (Gemini) no aceptan max_tokens: CLOUD_MAX_TOKENS=0 lo omite.
    max_tokens = int(getattr(settings, "CLOUD_MAX_TOKENS", 6000) or 0)
    if max_tokens > 0:
        request["max_tokens"] = max_tokens
    try:
        response = client.chat.completions.create(**request)
    except Exception as exc:
        from openai import APIConnectionError, APITimeoutError, AuthenticationError, NotFoundError
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

    return _extract_chat_completion_text(response, label)


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
