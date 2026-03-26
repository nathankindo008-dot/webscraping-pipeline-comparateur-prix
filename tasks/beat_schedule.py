"""
beat_schedule.py — Planificateur Celery Beat
Comparateur de Prix Jumia CI — ENSEA AS Data Science

Celery Beat = le "cron" de Celery.
Il lit ce fichier et déclenche les tâches automatiquement aux horaires définis.

Comment ça marche :
  1. Celery Beat tourne en permanence (comme une horloge)
  2. À l'heure programmée, il envoie un message à Redis
  3. Le Celery Worker reçoit le message et exécute la tâche
"""

from celery.schedules import crontab
from tasks.celery_app import celery_app

celery_app.conf.beat_schedule = {

    # ─────────────────────────────────────────
    # Pipeline complet : tous les jours à 2h du matin
    # → scrape Jumia CI + nettoyage + insertion PostgreSQL
    # ─────────────────────────────────────────
    "scrape-jumia-daily": {
        "task":     "tasks.full_pipeline",
        "schedule": crontab(hour=2, minute=0),
        "options":  {"expires": 3600},   # expire si pas exécuté dans l'heure
    },

    # ─────────────────────────────────────────
    # Détection des baisses de prix : tous les jours à 6h
    # → après le scrape de 2h, on cherche les bonnes affaires
    # ─────────────────────────────────────────
    "check-price-drops-daily": {
        "task":     "tasks.check_price_drops",
        "schedule": crontab(hour=6, minute=0),
        "kwargs":   {"threshold_pct": 10.0},  # baisse > 10%
    },

    # ─────────────────────────────────────────
    # Health check API : toutes les 5 minutes
    # → vérifie que l'API répond (pour Prometheus/Grafana)
    # ─────────────────────────────────────────
    "health-check-every-5min": {
        "task":     "tasks.check_price_drops",   # tâche légère comme proxy
        "schedule": crontab(minute="*/5"),
        "kwargs":   {"threshold_pct": 100.0},    # seuil à 100% = ne remonte rien, juste un ping
    },
}

celery_app.conf.timezone = "Africa/Abidjan"