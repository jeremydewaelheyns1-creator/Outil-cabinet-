# Image de l'application pour Google Cloud Run (région Belgique, europe-west1).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

WORKDIR /app

# Lecture des cartes d'identité (D-035, OCR local) et fabrication des PDF (D-039, WeasyPrint).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
       libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Dépendances d'abord : cette couche n'est reconstruite que si elles changent.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=construction-uniquement \
    DJANGO_ALLOWED_HOSTS=localhost \
    DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost \
    GS_DOCUMENTS_BUCKET=construction \
    .venv/bin/python manage.py collectstatic --noinput

RUN useradd --uid 10001 --no-create-home application
USER application

ENV PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8080

# Le même conteneur sert l'application web et, avec une autre commande, les tâches
# planifiées (Cloud Run Jobs) : `python manage.py run_jobs`, `python manage.py migrate`.
CMD exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" --workers 2 --threads 4 --timeout 120 \
    --access-logfile - --error-logfile -
