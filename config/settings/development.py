"""Development settings for NexaMind."""
from .base import *  # noqa: F401,F403
from .base import env, env_bool

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Use a deterministic dev secret if none supplied so the app boots out of the box.
if SECRET_KEY == "dev-insecure-change-me":  # noqa: F405
    SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production-0123456789"  # noqa: F405

# Render email to the console during development.
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")

# Run background jobs inline unless a broker is explicitly configured.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)

# Relaxed cookie flags so login works over plain HTTP during local development.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

INTERNAL_IPS = ["127.0.0.1"]
