import os

from django.core.exceptions import ImproperlyConfigured

from .base import *


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off."
    )


def _env_list(name):
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} must be set in production.")
    return value


DEBUG = False

SECRET_KEY = _required_env("SECRET_KEY")
if (
    len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 5
    or SECRET_KEY.startswith("django-insecure-")
    or SECRET_KEY.casefold().startswith("replace-")
):
    raise ImproperlyConfigured(
        "SECRET_KEY must be at least 50 characters, contain at least 5 unique "
        "characters, and must not use Django's insecure development prefix."
    )

ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must contain a production hostname.")

CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS")
if any(not origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured(
        "Every CSRF_TRUSTED_ORIGINS entry must use https:// in production."
    )

# The production Nginx configuration overwrites this header, so Django can trust
# it without accepting a client-supplied value directly.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
if SECURE_HSTS_SECONDS < 0:
    raise ImproperlyConfigured("SECURE_HSTS_SECONDS cannot be negative.")
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    True,
)
SECURE_HSTS_PRELOAD = _env_bool("SECURE_HSTS_PRELOAD", True)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"

if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Production requires PostgreSQL with pgvector.")
_database_password = _required_env("DB_PASSWORD")
if _database_password.casefold().startswith("replace-"):
    raise ImproperlyConfigured("DB_PASSWORD must not use the example placeholder.")
DATABASES["default"]["PASSWORD"] = _database_password
DATABASES["default"]["CONN_MAX_AGE"] = int(os.getenv("DB_CONN_MAX_AGE", "60"))
if DATABASES["default"]["CONN_MAX_AGE"] < 0:
    raise ImproperlyConfigured("DB_CONN_MAX_AGE cannot be negative.")
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

CELERY_BROKER_URL = _required_env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = _required_env("CELERY_RESULT_BACKEND")
