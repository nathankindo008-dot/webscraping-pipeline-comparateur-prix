"""
celery_app.py — Configuration Celery
Broker  : Redis
Backend : Redis

Rôle
----
Celery est utilisé ici UNIQUEMENT comme **exécutant de tâches** (worker).
L'orchestration (quand lancer quoi) est assurée exclusivement par **Airflow**
via ses DAGs dans `dags/` :

- `scraping_pipeline` (quotidien 2h) : scrape Jumia + DjokStore + CoinAfrique
  → clean → check_drops → check_alerts → match_cross_source
- `weekly_digest` (lundi 8h) : envoi du digest hebdomadaire

Airflow publie chaque tâche sur la queue Redis via `send_task(...)`, et le
worker Celery la consomme. Pas de Celery Beat : un seul orchestrateur (Airflow)
pour éviter la duplication de responsabilités.
"""

import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "jumia_scraper",
    broker=REDIS_URL,
    backend=REDIS_URL.replace("/0", "/1"),
    include=["tasks.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    timezone="Africa/Abidjan",
    enable_utc=True,

    task_acks_late=True,
    task_reject_on_worker_lost=True,

    result_expires=86_400,
    task_max_retries=3,
)
