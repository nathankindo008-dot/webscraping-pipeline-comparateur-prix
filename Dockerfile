# =============================================================
# Dockerfile — Comparateur de Prix Jumia CI
# Utilisé par : api, worker, beat
# =============================================================

FROM python:3.12-slim AS base

# Métadonnées
LABEL maintainer="ENSEA AS Data Science"
LABEL description="Comparateur de prix Jumia CI"

# Variables d'environnement Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ─────────────────────────────────────────────
# Stage : dépendances Python
# ─────────────────────────────────────────────
FROM base AS dependencies

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# ─────────────────────────────────────────────
# Stage : image finale
# ─────────────────────────────────────────────
FROM dependencies AS final

# Copie du code source
COPY api/     ./api/
COPY tasks/   ./tasks/
COPY scraper/ ./scraper/

# Utilisateur non-root pour la sécurité
RUN useradd -m -u 1001 appuser \
 && chown -R appuser:appuser /app
USER appuser

# Port exposé par l'API Flask
EXPOSE 5000

# Commande par défaut → API Flask
# (override dans docker-compose pour worker/beat)
CMD ["python", "api/app.py"]