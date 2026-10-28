"""
Base Django settings shared by every environment for NexaMind.

Environment specific values are loaded from a .env file (see .env.example).
Never hard-code secrets here; read them from the environment.
"""
from pathlib import Path
import os

from celery.schedules import crontab
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    """Read an environment variable."""
    return os.environ.get(key, default)


def env_bool(key, default=False):
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key, default=None):
    value = os.environ.get(key)
    if not value:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "channels",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.dashboard",
    "apps.ai_assistant",
    "apps.tasks",
    "apps.calendar_manager",
    "apps.email_manager",
    "apps.workflow_automation",
    "apps.integrations",
    "apps.notifications",
    "apps.analytics",
    "apps.documents",
    "apps.audit_logs",
    "apps.subscriptions",
]

INSTALLED_APPS = ["daphne"] + DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.SessionSecurityMiddleware",
    "apps.accounts.middleware.TwoFactorMiddleware",
    "apps.audit_logs.middleware.AuditContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.notifications",
                "apps.subscriptions.context_processors.usage_limits",
                "apps.accounts.context_processors.site_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database (PostgreSQL in production, SQLite by default for a quick start)
# ---------------------------------------------------------------------------
DB_ENGINE = env("DB_ENGINE", "sqlite").lower()

if DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "nexamind"),
            "USER": env("DB_USER", "nexamind"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
elif DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME", "nexamind"),
            "USER": env("DB_USER", "nexamind"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / env("SQLITE_NAME", "db.sqlite3"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "landing:home"

# ---------------------------------------------------------------------------
# Sessions / cookies / security headers
# ---------------------------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = int(env("SESSION_COOKIE_AGE", "1209600"))  # 2 weeks
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Email (console by default; SMTP in production)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "NexaMind <no-reply@nexamind.local>")

# ---------------------------------------------------------------------------
# Celery / Redis
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = int(env("CELERY_TASK_TIME_LIMIT", "600"))
CELERY_TASK_SOFT_TIME_LIMIT = int(env("CELERY_TASK_SOFT_TIME_LIMIT", "540"))

# Periodic schedule executed by ``celery beat`` (see docker-compose "beat").
CELERY_BEAT_SCHEDULE = {
    # Fire scheduled workflows at their configured time-of-day.
    "scan-scheduled-workflows": {
        "task": "apps.workflow_automation.tasks.scan_scheduled_workflows",
        "schedule": 60.0,
    },
    # Trigger overdue-task notifications and overdue workflows.
    "scan-overdue-tasks": {
        "task": "apps.workflow_automation.tasks.scan_overdue_tasks",
        "schedule": crontab(minute="*/15"),
    },
    # Remind users about tasks due in the next 24 hours.
    "send-due-task-reminders": {
        "task": "apps.tasks.tasks.send_due_task_reminders",
        "schedule": crontab(minute="*/30"),
    },
    # Weekly in-app workspace digest.
    "send-weekly-digest": {
        "task": "apps.notifications.tasks.send_weekly_digest",
        "schedule": crontab(minute=0, hour=8, day_of_week="mon"),
    },
}

CACHES = {
    "default": {
        "BACKEND": env("CACHE_BACKEND", "django.core.cache.backends.locmem.LocMemCache"),
        "LOCATION": env("CACHE_LOCATION", "nexamind-cache"),
    }
}

# ---------------------------------------------------------------------------
# Django Channels (real-time notifications)
# ---------------------------------------------------------------------------
# Development defaults to the in-memory layer (single process, eager Celery).
# Production overrides this with ``channels_redis`` and a Redis URL.
CHANNEL_BACKEND = env(
    "CHANNEL_BACKEND", "channels.layers.InMemoryChannelLayer"
)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": CHANNEL_BACKEND,
        "CONFIG": (
            {"hosts": [env("CHANNEL_REDIS_URL", "redis://localhost:6379/1")]}
            if CHANNEL_BACKEND == "channels_redis.core.RedisChannelLayer"
            else {}
        ),
    }
}

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": env("API_USER_THROTTLE", "1000/hour"),
        "assistant": env("API_ASSISTANT_THROTTLE", "60/hour"),
        "sensitive": env("API_SENSITIVE_THROTTLE", "20/hour"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "NexaMind API",
    "DESCRIPTION": "REST API for the NexaMind AI personal assistant platform.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# NexaMind application settings
# ---------------------------------------------------------------------------
NEXAMIND = {
    "SITE_NAME": env("SITE_NAME", "NexaMind"),
    "AI_PROVIDER": env("AI_PROVIDER", ""),            # "", "local", "openai", "gemini", "mock"
    "AI_API_KEY": env("AI_API_KEY", ""),
    "AI_MODEL": env("AI_MODEL", ""),
    "AI_BASE_URL": env("AI_BASE_URL", ""),
    "AI_TIMEOUT": int(env("AI_TIMEOUT", "45")),
    "AI_MAX_TOKENS": int(env("AI_MAX_TOKENS", "1024")),
    "TOKEN_ENCRYPTION_KEY": env("TOKEN_ENCRYPTION_KEY", ""),
    "GOOGLE_CLIENT_ID": env("GOOGLE_CLIENT_ID", ""),
    "GOOGLE_CLIENT_SECRET": env("GOOGLE_CLIENT_SECRET", ""),
    "GITHUB_CLIENT_ID": env("GITHUB_CLIENT_ID", ""),
    "GITHUB_CLIENT_SECRET": env("GITHUB_CLIENT_SECRET", ""),
    "LINKEDIN_CLIENT_ID": env("LINKEDIN_CLIENT_ID", ""),
    "LINKEDIN_CLIENT_SECRET": env("LINKEDIN_CLIENT_SECRET", ""),
    "FACEBOOK_CLIENT_ID": env("FACEBOOK_CLIENT_ID", ""),
    "FACEBOOK_CLIENT_SECRET": env("FACEBOOK_CLIENT_SECRET", ""),
    "WHATSAPP_TOKEN": env("WHATSAPP_TOKEN", ""),
    "WHATSAPP_PHONE_NUMBER_ID": env("WHATSAPP_PHONE_NUMBER_ID", ""),
    "WHATSAPP_VERIFY_TOKEN": env("WHATSAPP_VERIFY_TOKEN", ""),
    "WHATSAPP_APP_SECRET": env("WHATSAPP_APP_SECRET", ""),
    "WHATSAPP_DISPLAY_NUMBER": env("WHATSAPP_DISPLAY_NUMBER", ""),
    "WHATSAPP_BRIDGE_URL": env("WHATSAPP_BRIDGE_URL", ""),
    "WHATSAPP_BRIDGE_SECRET": env("WHATSAPP_BRIDGE_SECRET", ""),
    "MAX_DOCUMENT_UPLOAD_MB": int(env("MAX_DOCUMENT_UPLOAD_MB", "10")),
    "LOGIN_MAX_ATTEMPTS": int(env("LOGIN_MAX_ATTEMPTS", "8")),
    "LOGIN_LOCKOUT_MINUTES": int(env("LOGIN_LOCKOUT_MINUTES", "15")),
    "SESSION_IDLE_MINUTES": int(env("SESSION_IDLE_MINUTES", "0")),  # 0 = disabled
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "nexamind": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
