"""Production et environnement d'essai en ligne (Google Cloud Run, région Belgique).

Toutes les valeurs sensibles sont obligatoires : l'application refuse de démarrer sans elles.
"""

from .base import *

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Cloud Run termine le HTTPS devant l'application.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=1)
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
# L'inscription à la liste de préchargement HSTS se décide avec le nom de domaine définitif.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LOGGING["handlers"]["console"]["formatter"] = "json"

# E-mails sortants (réinitialisation de mot de passe) : serveur SMTP du cabinet en attendant
# l'intégration Microsoft 365 (Graph) de l'épique « Communication ».
MAILERS = {
    "default": {
        "BACKEND": env(
            "DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
        ),
        "OPTIONS": {
            "host": env("EMAIL_HOST", default="smtp.office365.com"),
            "port": env.int("EMAIL_PORT", default=587),
            "username": env("EMAIL_HOST_USER", default=""),
            "password": env("EMAIL_HOST_PASSWORD", default=""),
            "use_tls": True,
            "timeout": 20,
        },
    },
}

# Les automatismes actuels sont de courts traitements en base : ils s'exécutent juste après
# la requête. Passer à "queue" quand arriveront les traitements longs (IA, e-mails).
JOBS_MODE = env("JOBS_MODE", default="eager")
