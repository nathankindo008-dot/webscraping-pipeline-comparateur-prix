"""
beat_schedule.py — Planificateur Celery Beat
Comparateur de Prix Jumia CI — ENSEA AS Data Science

Le beat_schedule est défini dans celery_app.py (centralisé).
Ce fichier documente les tâches planifiées.

Tâches planifiées :
  1. scrape-jumia-daily        → Pipeline complet tous les jours à 2h
  2. check-price-drops-daily   → Détection baisses de prix à 6h
  3. health-check-every-5min   → Vérification santé toutes les 5 min

Comment ça marche :
  1. Celery Beat tourne en permanence (comme une horloge)
  2. À l'heure programmée, il envoie un message à Redis
  3. Le Celery Worker reçoit le message et exécute la tâche
"""

from tasks.celery_app import celery_app  # noqa: F401
