"""Production settings for NexaMind.

These enforce secure defaults. Provide real secrets through environment
variables; the application will raise if the insecure development key leaks
into production.
"""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env, env_bool, env_list

DEBUG = False

if SECRET_KEY == "dev-insecure-change-me":  # noqa: F405
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a strong, unique value in production."
    )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", [])
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")

# HTTPS / transport security
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

# Prefer real SMTP in production
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")

# Real-time notifications must use Redis across web/worker processes.
CHANNEL_BACKEND = env(
    "CHANNEL_BACKEND", "channels_redis.core.RedisChannelLayer"
)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": CHANNEL_BACKEND,
        "CONFIG": {
            "hosts": [env("CHANNEL_REDIS_URL", "redis://localhost:6379/1")],
        },
    }
}
