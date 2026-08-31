import os
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))

INSTRUMENT_API_KEY = os.getenv("INSTRUMENT_API_KEY", "")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
CHANNEL_REDIS_URL = os.getenv("CHANNEL_REDIS_URL", "redis://redis:6379/2")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.pubsub.RedisPubSubChannelLayer",
        "CONFIG": {
            "hosts": [CHANNEL_REDIS_URL],
            "prefix": "openlims_ws",
        },
    },
}
if os.getenv("CHANNEL_LAYERS_BACKEND", "").lower() == "inmemory":
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }

CELERY_TASK_ALWAYS_EAGER = os.getenv(
    "CELERY_TASK_ALWAYS_EAGER", "false"
).lower() in {"1", "true", "yes", "on"}
CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER

DEBUG = env.bool("DJANGO_DEBUG", default=True)
SECRET_KEY = env("DJANGO_SECRET_KEY", default="change-me")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"] if DEBUG else [],
)

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "samples",
    "notebook",
    "inventory",
    "events",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "custom_fields",
    "core",
    "results",
    "projects",
    "imports",
    "notifications",
    "sequences",
    "alignments",
    "settings_app",
    "django.contrib.postgres",
    "blast",
    "mass_spec",
    "migration_toolkit",
    "assistant",
    "pipelines",
    "registry",
    "workflow_requests",
    "drf_spectacular",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "core.authentication.CookieJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.OpenLIMSPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "OpenLIMS API",
    "DESCRIPTION": "Versioned OpenLIMS laboratory information management API.",
    "VERSION": "1.0.0",
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SERVE_INCLUDE_SCHEMA": False,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(hours=2),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

JWT_ACCESS_COOKIE_NAME = env("JWT_ACCESS_COOKIE_NAME", default="openlims_access")
JWT_REFRESH_COOKIE_NAME = env("JWT_REFRESH_COOKIE_NAME", default="openlims_refresh")
JWT_COOKIE_SECURE = env.bool("JWT_COOKIE_SECURE", default=not DEBUG)
JWT_COOKIE_SAMESITE = env("JWT_COOKIE_SAMESITE", default="Lax")
JWT_ACCESS_COOKIE_MAX_AGE = int(SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
JWT_REFRESH_COOKIE_MAX_AGE = int(SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.feature_flags.FeatureFlagAPIMiddleware",
    "core.security.SecurityHeadersMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3")
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int(
    "DB_CONN_MAX_AGE",
    default=0 if DEBUG else 60,
)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

CACHE_URL = env("CACHE_URL", default="")
if CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
            "TIMEOUT": 60,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "openlims-default",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Browser and proxy security. Production deployments should set
# JWT_COOKIE_SECURE=true and normally terminate TLS at the web proxy/Caddy.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)

# Read-only legacy database migration sources. Remote hosts must be explicitly
# allowed; SQLite files must stay below the configured source directory.
MIGRATION_DB_ALLOWED_HOSTS = env.list(
    "MIGRATION_DB_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", "db", "host.docker.internal"],
)
MIGRATION_DB_CONNECT_TIMEOUT = env.int("MIGRATION_DB_CONNECT_TIMEOUT", default=10)
MIGRATION_DB_MAX_ROWS = env.int("MIGRATION_DB_MAX_ROWS", default=50000)
MIGRATION_SQLITE_ROOT = Path(
    os.getenv("MIGRATION_SQLITE_ROOT", str(BASE_DIR / "migration_sources"))
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Optional LLM support for the OpenLIMS Assistant. Models can classify or explain,
# but validated OpenLIMS routes remain authoritative for reads and confirmed writes.
OPENLIMS_ASSISTANT_LLM_PROVIDER = os.getenv("OPENLIMS_ASSISTANT_LLM_PROVIDER", "openai")
OPENLIMS_ASSISTANT_LLM_ENABLED = os.getenv(
    "OPENLIMS_ASSISTANT_LLM_ENABLED",
    "false",
).lower() in ["1", "true", "yes", "on"]
OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED = os.getenv(
    "OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED",
    "true",
).lower() in ["1", "true", "yes", "on"]
OPENLIMS_ASSISTANT_LLM_ROUTING_MIN_CONFIDENCE = float(
    os.getenv("OPENLIMS_ASSISTANT_LLM_ROUTING_MIN_CONFIDENCE", "0.65")
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
