"""
celery_app.py — Configuration Celery
Broker : Redis
Backend : Redis
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
        "scrape-jumia-daily": {
            "task": "tasks.full_pipeline",
            "schedule": crontab(hour=2, minute=0),
            "options": {"expires": 3600},
        },
        "check-price-drops-daily": {
            "task": "tasks.check_price_drops",
            "schedule": crontab(hour=6, minute=0),
            "kwargs": {"threshold_pct": 10.0},
        },
        "health-check-every-5min": {
            "task": "tasks.check_price_drops",
            "schedule": crontab(minute="*/5"),
            "kwargs": {"threshold_pct": 100.0},
        },
    },
)