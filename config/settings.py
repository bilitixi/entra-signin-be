"""
Django settings for the Entra ID sign-in project.

See BACKEND_API_FLOW.md and AUTHENTICATION.md for the rationale behind
the Entra-related settings below.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "entra-signin-cache",
    }
}

# --- Entra ID (AUTHENTICATION.md §7 / ENTRA_PORTAL_SETUP.md A2-A3) ---
ENTRA_TENANT_ID = env("ENTRA_TENANT_ID", default="")
ENTRA_CLIENT_ID = env("ENTRA_CLIENT_ID", default="")
ENTRA_CLIENT_SECRET = env("ENTRA_CLIENT_SECRET", default="")
ENTRA_AUTHORITY = env("ENTRA_AUTHORITY", default="")
ENTRA_REDIRECT_URI = env(
    "ENTRA_REDIRECT_URI", default="http://localhost:8000/api/v1/auth/callback"
)
# MSAL's get_authorization_request_url() adds "openid", "profile", and
# "offline_access" itself and raises ValueError if they're also passed
# here — only list scopes beyond that reserved set (see accounts/views.py).
ENTRA_SCOPES = ["email"]
FRONTEND_POST_LOGIN_URL = env("FRONTEND_POST_LOGIN_URL", default="http://localhost:3000/")
FRONTEND_POST_LOGOUT_URL = env("FRONTEND_POST_LOGOUT_URL", default="http://localhost:3000/")

# Issuer for Graph-created "local account" identities (accounts/graph.py) —
# your tenant's default domain, e.g. "contoso.onmicrosoft.com". Only needed
# if provisioning users from /admin should also create their Entra identity;
# see ENTRA_PORTAL_SETUP.md §A5b.
ENTRA_CIAM_DOMAIN = env("ENTRA_CIAM_DOMAIN", default="")

# Base URL of *this* backend (not the frontend) — used to build the sign-in
# link sent in the account-setup email (accounts/emails.py).
BACKEND_BASE_URL = env("BACKEND_BASE_URL", default="http://localhost:8000")

# Account-setup emails (accounts/emails.py). Falls back to printing emails
# to the console when EMAIL_HOST isn't set, so local dev works with no SMTP
# server — set real values before go-live.
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@example.com")
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)

# External ID (CIAM) tenants: the dedicated app
# registration's Application (client) ID for the "custom authentication
# extension" Entra calls at the OnAttributeCollectionSubmit event. Entra
# authenticates itself to POST /auth/entra-connector/attribute-collection-submit
# with a bearer token audience-scoped to this app ID — see
# accounts/entra_auth.py and ENTRA_PORTAL_SETUP.md Part B.
ENTRA_CUSTOM_EXTENSION_APP_ID = env("ENTRA_CUSTOM_EXTENSION_APP_ID", default="")

# Session/cookie config — required for the React SPA to work cross-request
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG

# React dev server origin — needed only if frontend/backend run on different ports locally
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"]
)
CORS_ALLOW_CREDENTIALS = True
