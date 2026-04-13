"""
celery_app.py — Configuration Celery
Broker  : Redis
Backend : Redis

Répartition des responsabilités entre Celery Beat et Airflow
------------------------------------------------------------
- Airflow (DAGs dans `dags/`) orchestre les **workflows complexes**
  avec dépendances entre tâches :
    * `scraping_pipeline`  (quotidien 2h)  : scrape → clean → drops → alerts → matching
    * `weekly_digest`      (lundi 8h)      : envoi du digest hebdomadaire

- Celery Beat (ici) gère uniquement les **tâches temps-réel**
  qui ne justifient pas un DAG Airflow :
    * `check-major-drops-every-5min` : détection des chutes majeures (>100%)
      toutes les 5 min (trop fréquent pour Airflow, pas de dépendances)

Cette séparation évite les double-exécutions et clarifie la responsabilité
de chaque outil : Beat pour les cron simples, Airflow pour les pipelines visuels.
"""

import os
from celery import Celery
from celery.schedules import crontab

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

    beat_schedule={
        # Tâches gérées par Airflow (cf. dags/) :
        #   - scrape_jumia + clean_and_insert   → DAG scraping_pipeline
        #   - scrape_djokstore, scrape_coinafrique → DAG scraping_pipeline
        #   - check_price_drops (quotidien)     → DAG scraping_pipeline
        #   - check_price_alerts (quotidien)    → DAG scraping_pipeline
        #   - match_cross_source (quotidien)    → DAG scraping_pipeline
        #   - send_weekly_digest (hebdo)        → DAG weekly_digest
        #
        # Beat ne garde ici QUE la veille temps-réel qui ne passe pas par Airflow :
        "check-major-drops-every-5min": {
            "task": "tasks.check_price_drops",
            "schedule": crontab(minute="*/5"),
            "kwargs": {"threshold_pct": 100.0},
            "options": {"expires": 290},
        },
    },
)
