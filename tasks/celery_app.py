"""
celery_app.py — Configuration Celery
Broker : Redis
Backend : Redis
"""

import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "jumia_scraper",
    broker=REDIS_URL,
    backend=REDIS_URL.replace("/0", "/1"),   # résultats sur DB 1, tâches sur DB 0
    include=["tasks.tasks"],                  # fichier qui contient les tâches
)

celery_app.conf.update(
    # Sérialisation JSON (lisible, sécurisé)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Fuseau horaire Abidjan (UTC+0, pas de changement d'heure)
    timezone="Africa/Abidjan",
    enable_utc=True,

    # Retry automatique si la tâche plante
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Résultats conservés 24h
    result_expires=86_400,

    # Max 3 tentatives par tâche avant abandon
    task_max_retries=3,
)