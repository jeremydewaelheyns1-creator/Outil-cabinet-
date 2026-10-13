"""Poste de développement : jamais utilisé en ligne."""

from .base import *

DEBUG = True
JOBS_MODE = env("JOBS_MODE", default="eager")
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = True
