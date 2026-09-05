from pathlib import Path
import os
from urllib.parse import parse_qsl, urlparse


BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # setdefault no sobreescribe — usamos asignación directa para que
        # cambios en .env se apliquen al reiniciar el servidor
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_dotenv()


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_float(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_text(name, default=""):
    return os.getenv(name, default).strip()


def database_config():
    database_url = env_text("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise RuntimeError("DATABASE_URL debe usar postgres:// o postgresql:// para SIMA.")
        options = dict(parse_qsl(parsed.query))
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "OPTIONS": options,
        }

    engine = env_text("DB_ENGINE", "sqlite").lower()
    if engine in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env_text("POSTGRES_DB", "simaapp"),
            "USER": env_text("POSTGRES_USER", "simaapp"),
            "PASSWORD": env_text("POSTGRES_PASSWORD", ""),
            "HOST": env_text("POSTGRES_HOST", "127.0.0.1"),
            "PORT": env_text("POSTGRES_PORT", "5432"),
        }

    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / env_text("SQLITE_NAME", "db.sqlite3"),
    }


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "0.0.0.0,127.0.0.1,localhost").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "learning",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "sima.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "learning.context_processors.sidebar_data",
            ],
        },
    },
]

WSGI_APPLICATION = "sima.wsgi.application"

DATABASES = {"default": database_config()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-pe"
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

# ── Backend de IA en la nube ──────────────────────────────────────────────────
# Cualquier proveedor con API compatible con OpenAI Chat Completions (DeepSeek,
# OpenAI, Gemini, Qwen, Groq, Mistral...) o Anthropic con su SDK nativo.
# Las variables DEEPSEEK_* se siguen aceptando como alias heredado de CLOUD_*.
ANTHROPIC_API_KEY = env_text("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = env_text("ANTHROPIC_MODEL", "claude-opus-5")
DEEPSEEK_API_KEY = env_text("DEEPSEEK_API_KEY", "")
_PLACEHOLDER_KEYS = {"", "local", "none", "null", "false", "0", "change-me", "changeme", "sk-..."}
CLOUD_PROVIDER = env_text("CLOUD_PROVIDER", "").lower()
if not CLOUD_PROVIDER:
    _has_generic = (env_text("CLOUD_API_KEY", "") or DEEPSEEK_API_KEY).lower() not in _PLACEHOLDER_KEYS
    _has_anthropic = ANTHROPIC_API_KEY.lower() not in _PLACEHOLDER_KEYS
    CLOUD_PROVIDER = "anthropic" if (_has_anthropic and not _has_generic) else "openai_compatible"
if CLOUD_PROVIDER == "anthropic":
    CLOUD_API_KEY = env_text("CLOUD_API_KEY", "") or ANTHROPIC_API_KEY
    CLOUD_API_BASE = env_text("CLOUD_API_BASE", "")
    CLOUD_MODEL = env_text("CLOUD_MODEL", "") or ANTHROPIC_MODEL
else:
    CLOUD_API_KEY = env_text("CLOUD_API_KEY", "") or DEEPSEEK_API_KEY
    CLOUD_API_BASE = env_text("CLOUD_API_BASE", "") or env_text("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    CLOUD_MODEL = env_text("CLOUD_MODEL", "") or env_text("DEEPSEEK_MODEL", "deepseek-v4-flash")
_CLOUD_LABELS = {
    "deepseek": "DeepSeek", "openai": "OpenAI", "gemini": "Gemini", "qwen": "Qwen",
    "groq": "Groq", "mistral": "Mistral", "anthropic": "Claude", "openai_compatible": "Nube",
}
CLOUD_LABEL = env_text("CLOUD_LABEL", "") or _CLOUD_LABELS.get(CLOUD_PROVIDER, CLOUD_PROVIDER.title() or "Nube")
CLOUD_MAX_TOKENS = env_int("CLOUD_MAX_TOKENS", env_int("DEEPSEEK_MAX_TOKENS", 6000))
CLOUD_API_TIMEOUT = env_int("CLOUD_API_TIMEOUT", env_int("DEEPSEEK_API_TIMEOUT", 120))
CLOUD_GENERATION_TEMPERATURE = env_float("CLOUD_GENERATION_TEMPERATURE", env_float("DEEPSEEK_GENERATION_TEMPERATURE", 0.3))
CLOUD_VERIFICATION_TEMPERATURE = env_float("CLOUD_VERIFICATION_TEMPERATURE", env_float("DEEPSEEK_VERIFICATION_TEMPERATURE", 0.2))
# True: el proveedor cloud entrega el MINI final en una pasada y se OMITE la verificacion factual.
CLOUD_DIRECT_MINI = env_bool("CLOUD_DIRECT_MINI", env_bool("DEEPSEEK_DIRECT_MINI", False))

# ── Backend local (API compatible con OpenAI: Ollama, LM Studio, llama-server) ─
LOCAL_API_BASE = env_text("LOCAL_API_BASE", "http://127.0.0.1:8003/v1")
LOCAL_API_KEY = env_text("LOCAL_API_KEY", "local")
LOCAL_MODEL = env_text("LOCAL_MODEL", "") or CLOUD_MODEL
CLOUD_BACKEND_SURCHARGE = env_int("CLOUD_BACKEND_SURCHARGE", 15)
LOCAL_ITEMS_REQUESTED = os.getenv("LOCAL_ITEMS_REQUESTED", "auto")
LOCAL_MIN_ITEMS = env_int("LOCAL_MIN_ITEMS", 5)
LOCAL_MAX_ITEMS = env_int("LOCAL_MAX_ITEMS", 150)
LOCAL_ITEMS_PER_CHUNK_MAX = env_int("LOCAL_ITEMS_PER_CHUNK_MAX", 22)
CLOUD_ITEMS_PER_CHUNK_MAX = env_int("CLOUD_ITEMS_PER_CHUNK_MAX", 32)
LOCAL_GENERATION_TEMPERATURE = env_float("LOCAL_GENERATION_TEMPERATURE", 0.4)
LOCAL_VERIFICATION_TEMPERATURE = env_float("LOCAL_VERIFICATION_TEMPERATURE", 0.3)
LOCAL_MAX_TOKENS = env_int("LOCAL_MAX_TOKENS", 8000)
LOCAL_API_TIMEOUT = env_int("LOCAL_API_TIMEOUT", 7200)
LOCAL_TRANSCRIPT_REPAIR_CHUNK_WORDS = env_int("LOCAL_TRANSCRIPT_REPAIR_CHUNK_WORDS", 500)
LOCAL_CHUNK_WORDS = env_int("LOCAL_CHUNK_WORDS", 2000)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
LOCAL_TASK_QUEUE_MAXSIZE = env_int("LOCAL_TASK_QUEUE_MAXSIZE", 20)
LOCAL_TASK_WORKERS = env_int("LOCAL_TASK_WORKERS", 1)
# thread: worker en hilos dentro del proceso web (por defecto). db: proceso aparte `manage.py run_worker`.
SIMA_QUEUE_MODE = env_text("SIMA_QUEUE_MODE", "thread")
LOCAL_COHERENCE_MAX_ITEMS = env_int("LOCAL_COHERENCE_MAX_ITEMS", 60)
VERIFICATION_FETCH_SOURCES = env_bool("VERIFICATION_FETCH_SOURCES", True)
VERIFICATION_SOURCE_URLS = os.getenv("VERIFICATION_SOURCE_URLS", "")
VERIFICATION_MAX_SOURCES = env_int("VERIFICATION_MAX_SOURCES", 6)
VERIFICATION_SOURCE_TIMEOUT = env_int("VERIFICATION_SOURCE_TIMEOUT", 8)
VERIFICATION_SOURCE_CHARS = env_int("VERIFICATION_SOURCE_CHARS", 2200)
VERIFICATION_DEFAULT_MODE = os.getenv("VERIFICATION_DEFAULT_MODE", "web")
EDUQG_REFERENCE_PATH = os.getenv("EDUQG_REFERENCE_PATH", "")
EDUQG_SOURCE_CHARS = env_int("EDUQG_SOURCE_CHARS", 6000)
EDUQG_TOP_K = env_int("EDUQG_TOP_K", 5)
EDUQG_MAX_RECORDS = env_int("EDUQG_MAX_RECORDS", 6000)
VERIFICATION_DYNAMIC_WEB_SEARCH = env_bool("VERIFICATION_DYNAMIC_WEB_SEARCH", True)
VERIFICATION_ACADEMIC_SEARCH = env_bool("VERIFICATION_ACADEMIC_SEARCH", True)
VERIFICATION_SEARCH_QUERIES = env_int("VERIFICATION_SEARCH_QUERIES", 3)
VERIFICATION_SEARCH_RESULTS = env_int("VERIFICATION_SEARCH_RESULTS", 3)

# ── Correo (recordatorios de estudio) ────────────────────────────────────────
# Por defecto imprime en consola; para SMTP real usa django.core.mail.backends.smtp.EmailBackend
EMAIL_BACKEND = env_text("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env_text("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env_text("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env_text("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env_text("DEFAULT_FROM_EMAIL", "SIMA <no-reply@sima.local>")
# URL publica para los enlaces de los correos (sin barra final), p. ej. https://sima.midominio.pe
SIMA_SITE_URL = env_text("SIMA_SITE_URL", "")

# ── Seguridad en produccion (DJANGO_DEBUG=0) ─────────────────────────────────
if not DEBUG and SECRET_KEY == "dev-only-change-me":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Define DJANGO_SECRET_KEY en .env antes de correr con DJANGO_DEBUG=0.")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env_text("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", SECURE_SSL_REDIRECT)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", SECURE_SSL_REDIRECT)
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    if env_bool("BEHIND_PROXY", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ── Logging: consola + archivo rotativo logs/sima.log ────────────────────────
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "sima.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "encoding": "utf-8",
            "formatter": "std",
        },
    },
    "loggers": {
        "learning": {"handlers": ["console", "file"], "level": env_text("SIMA_LOG_LEVEL", "INFO"), "propagate": False},
        "django.request": {"handlers": ["console", "file"], "level": "WARNING", "propagate": False},
    },
}
