# Image de production de Billio : web (gunicorn) ou worker (tâches planifiées), selon la commande.
FROM python:3.12-slim-bookworm

ARG RELEASE=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000 \
    RELEASE=${RELEASE}

# Bibliothèques système : WeasyPrint (PDF des factures), polices, client PostgreSQL 18 (sauvegardes ; doit être ≥ la version du serveur).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-client-18 \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 shared-mime-info \
      fonts-dejavu-core fonts-liberation \
 && apt-get purge -y gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Fichiers statiques compressés (WhiteNoise). Clé factice : uniquement pour cette étape de build.
RUN SECRET_KEY=build-only-collectstatic-key-0000000000000000000000 \
    python manage.py collectstatic --noinput \
 && useradd --create-home --uid 10001 billio \
 && mkdir -p /data/media \
 && chown -R billio:billio /app /data \
 && chmod +x docker/entrypoint.sh

USER billio
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz/" || exit 1

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["web"]
