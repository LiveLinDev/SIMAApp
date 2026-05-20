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


SIMA_PC = env_text("SIMA_PC", "adrian").lower()
REMOTE_DUCKDNS_HOST = env_text("REMOTE_DUCKDNS_HOST", "bellamama.duckdns.org")


def resolve_local_api_base():
    local_base = env_text("LOCAL_API_BASE", "http://localhost:1234/v1")
    remote_base = env_text("REMOTE_LOCAL_API_BASE", f"http://{REMOTE_DUCKDNS_HOST}:8001/v1")
    if SIMA_PC == "erick":
        return remote_base
    return local_base


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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
REMOTE_LOCAL_API_BASE = env_text("REMOTE_LOCAL_API_BASE", f"http://{REMOTE_DUCKDNS_HOST}:8001/v1")
LOCAL_API_BASE = resolve_local_api_base()
LOCAL_API_KEY = os.getenv("LOCAL_API_KEY", "local")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", ANTHROPIC_MODEL)
CLOUD_BACKEND_SURCHARGE = env_int("CLOUD_BACKEND_SURCHARGE", 15)
LOCAL_ITEMS_REQUESTED = os.getenv("LOCAL_ITEMS_REQUESTED", "auto")
LOCAL_MIN_ITEMS = env_int("LOCAL_MIN_ITEMS", 5)
LOCAL_MAX_ITEMS = env_int("LOCAL_MAX_ITEMS", 150)
LOCAL_ITEMS_PER_CHUNK_MAX = env_int("LOCAL_ITEMS_PER_CHUNK_MAX", 22)
CLOUD_ITEMS_PER_CHUNK_MAX = env_int("CLOUD_ITEMS_PER_CHUNK_MAX", 32)
LOCAL_GENERATION_TEMPERATURE = env_float("LOCAL_GENERATION_TEMPERATURE", 0.4)
LOCAL_VERIFICATION_TEMPERATURE = env_float("LOCAL_VERIFICATION_TEMPERATURE", 0.3)
LOCAL_MAX_TOKENS = env_int("LOCAL_MAX_TOKENS", 8000)
LOCAL_CHUNK_WORDS = env_int("LOCAL_CHUNK_WORDS", 2000)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
LOCAL_TASK_QUEUE_MAXSIZE = env_int("LOCAL_TASK_QUEUE_MAXSIZE", 20)
LOCAL_TASK_WORKERS = env_int("LOCAL_TASK_WORKERS", 1)
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
VERIFICATION_SEARCH_QUERIES = env_int("VERIFICATION_SEARCH_QUERIES", 3)
VERIFICATION_SEARCH_RESULTS = env_int("VERIFICATION_SEARCH_RESULTS", 3)
