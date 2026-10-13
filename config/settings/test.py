"""Tests automatiques : rapides, isolés, sans réseau ni e-mail réel."""

from .base import *

DEBUG = False
SECRET_KEY = "tests-uniquement"  # noqa: S105
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
# Les fichiers statiques ne sont pas collectés en test.
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith("whitenoise")]
JOBS_MODE = "eager"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Aucune requête réseau réelle en test : les clients HTTP sont simulés.
VIES_API_URL = "https://vies.invalid/check-vat-number"
LOGGING["root"]["level"] = "WARNING"
