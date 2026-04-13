"""
DAG Airflow — Digest hebdomadaire
Comparateur de Prix Jumia CI — ENSEA AS Data Science

Envoie un email recapitulatif chaque lundi a 8h aux utilisateurs inscrits.
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("jumia_scraper", broker=REDIS_URL, backend=REDIS_URL.replace("/0", "/1"))


def run_weekly_digest(**ctx):
    result = celery_app.send_task("tasks.send_weekly_digest")
    return result.get(timeout=300, propagate=True)


default_args = {
    "owner": "ensea-datascience",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="weekly_digest",
    default_args=default_args,
    description="Envoi du digest hebdomadaire chaque lundi",
    schedule_interval="0 8 * * 1",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["email", "digest", "hebdomadaire"],
) as dag:

    send_digest = PythonOperator(
        task_id="send_weekly_digest",
        python_callable=run_weekly_digest,
    )
