"""Réglages communs à tous les environnements.

Les valeurs propres à un environnement (secrets, base de données, domaines) viennent
de variables d'environnement, jamais du code. Voir `.env.example`.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import django_stubs_ext
import environ

# Permet d'écrire ModelAdmin[Client], ModelForm[Client]... (typage vérifié par mypy).
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-uniquement-ne-pas-utiliser-en-production")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --- Applications ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
    "django.forms",  # gabarits des widgets, pour le rendu de formulaires personnalisé
    # Tiers
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "django_htmx",
    "simple_history",
    # Doit précéder nos applications : elles y déclarent leurs travaux de fond.
    "procrastinate.contrib.django",
    # Nos modules
    "apps.core",
    "apps.clients",
    "apps.bce",
    "apps.integrations",
    "apps.reprise",
    "apps.tasks",
    "apps.documents",
    "apps.vat",
]

MIDDLEWARE = [
    "apps.core.health.HealthCheckMiddleware",  # en premier : sondes Cloud Run (voir module)
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Tout écran exige une connexion, sauf ceux marqués explicitement (`login_not_required`).
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.core.middleware.RequireMFAMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"
FORM_RENDERER = "apps.core.forms.FormRenderer"
WSGI_APPLICATION = "config.wsgi.application"

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
                "apps.core.context_processors.app_context",
                "apps.clients.context_processors.current_dossier",
            ],
            # Disponibles dans tous les gabarits sans {% load %}.
            "builtins": ["apps.core.templatetags.app_tags"],
        },
    },
]

# --- Base de données ------------------------------------------------------------------------
# PostgreSQL uniquement : c'est la seule source de vérité (voir docs/DECISIONS.md, D-004).

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://outil:outil@localhost:5432/outil"),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Comptes et authentification -------------------------------------------------------------

AUTH_USER_MODEL = "core.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "core:home"

# allauth : connexion par e-mail, pas d'inscription libre (les comptes sont créés par l'admin).
ACCOUNT_ADAPTER = "apps.core.adapters.AccountAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_SESSION_REMEMBER = False
ACCOUNT_PASSWORD_RESET_BY_CODE_ENABLED = False

# Double authentification : obligatoire pour tous (voir apps.core.middleware).
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes", "webauthn"]
MFA_PASSKEY_LOGIN_ENABLED = True
MFA_TOTP_ISSUER = env("MFA_TOTP_ISSUER", default="Outil cabinet")
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = False

# Sessions : coupées à la fermeture du navigateur et après 8 heures au maximum.
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --- Langue et fuseau horaire -----------------------------------------------------------------

LANGUAGE_CODE = "fr-be"
LANGUAGES = [("fr", "Français")]
TIME_ZONE = "Europe/Brussels"
USE_I18N = True
USE_TZ = True

# --- Fichiers ---------------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    # Documents des clients (D-034) : jamais servis directement, toujours par une vue qui
    # vérifie les droits et journalise. Hors de MEDIA_ROOT, qui n'est pas publié non plus.
    "documents": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(BASE_DIR / "var" / "documents")},
    },
}
DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
# Relances automatiques d'une demande « À recevoir » : après N jours, au plus N fois.
REQUEST_REMINDER_DAYS = env.int("REQUEST_REMINDER_DAYS", default=7)
REQUEST_MAX_REMINDERS = env.int("REQUEST_MAX_REMINDERS", default=2)
# Pièces d'identité (D-035) : lecture locale des lignes « machine » (Tesseract, sur le serveur
# du cabinet) et demande de la nouvelle carte N jours avant expiration.
IDENTITY_OCR_ENABLED = env.bool("IDENTITY_OCR_ENABLED", default=True)
IDENTITY_RENEWAL_DAYS = env.int("IDENTITY_RENEWAL_DAYS", default=30)
# D-041 : un fichier du dépôt unique non classé est effacé après ce délai.
INBOX_RETENTION_DAYS = env.int("INBOX_RETENTION_DAYS", default=30)
# D-042 : vrai seulement quand la messagerie du cabinet est branchée (sinon : enregistré).
OUTGOING_EMAIL_ENABLED = env.bool("OUTGOING_EMAIL_ENABLED", default=False)

DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# --- E-mail -----------------------------------------------------------------------------------

# Envoi via Microsoft 365 (Graph) prévu à l'épique « Communication » ; d'ici là, la console.
MAILERS = {
    "default": {
        "BACKEND": env(
            "DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
        ),
    },
}
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="outil@cabinet.invalid")

# --- Travaux de fond (procrastinate, stockés dans PostgreSQL) ---------------------------------
# "queue" : les travaux passent par la file et un worker les exécute.
# "eager" : exécution immédiate après la transaction (tests, poste de développement).
JOBS_MODE = env("JOBS_MODE", default="queue")

# --- Journalisation ---------------------------------------------------------------------------

LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "apps.core.logging.JsonFormatter"},
        "simple": {"format": "%(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": env("LOG_FORMAT", default="simple"),
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "procrastinate": {"level": "WARNING"},
    },
}

# --- Règles métier paramétrables --------------------------------------------------------------
# Bénéficiaires effectifs : seuil légal belge actuel « plus de 25 % ». La réforme européenne
# (10 juillet 2027) passe à « au moins 25 % » : il suffira de mettre UBO_THRESHOLD_INCLUSIVE à True.
UBO_THRESHOLD_PERCENT = Decimal(env("UBO_THRESHOLD_PERCENT", default="25"))
UBO_THRESHOLD_INCLUSIVE = env.bool("UBO_THRESHOLD_INCLUSIVE", default=False)

# Données publiques
BCE_DATA_DIR = Path(env("BCE_DATA_DIR", default=str(BASE_DIR / "var" / "bce")))
VIES_API_URL = env(
    "VIES_API_URL",
    default="https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number",
)
VIES_TIMEOUT_SECONDS = env.float("VIES_TIMEOUT_SECONDS", default=10.0)
# Numéro de TVA du cabinet (ex. BE0123456789) : VIES renvoie alors un identifiant de
# consultation qui sert de preuve. Facultatif.
VIES_REQUESTER_VAT = env("VIES_REQUESTER_VAT", default="")

# Sites officiels consultés pour chaque société (D-024) : BCE (fonctions), Moniteur belge,
# Banque Nationale (comptes annuels). Une consultation par client et par source, au plus une
# fois par OFFICIAL_REFRESH_DAYS jours en automatique, ou à la demande.
KBO_PUBLIC_URL = env(
    "KBO_PUBLIC_URL", default="https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html"
)
MONITEUR_URL = env("MONITEUR_URL", default="https://www.ejustice.just.fgov.be/cgi_tsv/list.pl")
# API officielle de la Banque Nationale (CBSO) : clé gratuite à demander par le cabinet sur
# https://developer.cbso.nbb.be/ (produit « Authentic Query »). Sans clé : lien vers le site.
NBB_CBSO_API_URL = env("NBB_CBSO_API_URL", default="https://ws.cbso.nbb.be")
NBB_CBSO_KEY = env("NBB_CBSO_KEY", default="")
OFFICIAL_TIMEOUT_SECONDS = env.float("OFFICIAL_TIMEOUT_SECONDS", default=15.0)
OFFICIAL_AUTO_REFRESH = env.bool("OFFICIAL_AUTO_REFRESH", default=True)
OFFICIAL_REFRESH_DAYS = env.int("OFFICIAL_REFRESH_DAYS", default=7)
OFFICIAL_REFRESH_BATCH = env.int("OFFICIAL_REFRESH_BATCH", default=10)

# Nombre de relais de confiance (répartiteur de charge Google) qui ajoutent l'adresse IP du
# visiteur dans l'en-tête X-Forwarded-For. 0 = on se fie à l'adresse de connexion directe.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)

# Nom affiché du cabinet
CABINET_NAME = env("CABINET_NAME", default="Cabinet")
