"""
DAG Airflow — Pipeline de scraping quotidien
Comparateur de Prix Jumia CI — ENSEA AS Data Science

Orchestre visuellement le pipeline :
  scrape_jumia ──► clean_and_insert ──┐
                                      ├──► check_price_drops ──► check_alerts ──► match_cross_source
  scrape_djokstore ───────────────────┤
  scrape_coinafrique ─────────────────┘

Airflow dispatch les taches vers le Celery Worker existant via send_task().
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from celery import Celery

# ── Connexion au broker Redis (meme que le worker) ──
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("jumia_scraper", broker=REDIS_URL, backend=REDIS_URL.replace("/0", "/1"))


def trigger_celery_task(task_name, timeout=600, **kwargs):
    """Envoie une tache au Celery Worker et attend le resultat."""
    result = celery_app.send_task(task_name, kwargs=kwargs)
    return result.get(timeout=timeout, propagate=True)


def run_scrape_jumia(**ctx):
    trigger_celery_task("tasks.scrape_jumia", timeout=900)


def run_clean_and_insert(**ctx):
    trigger_celery_task("tasks.clean_and_insert", timeout=600)


def run_scrape_djokstore(**ctx):
    trigger_celery_task("tasks.scrape_djokstore", timeout=900)


def run_check_price_drops(**ctx):
    trigger_celery_task("tasks.check_price_drops", timeout=300, threshold_pct=10.0)


def run_check_price_alerts(**ctx):
    trigger_celery_task("tasks.check_price_alerts", timeout=300)


def run_scrape_coinafrique(**ctx):
    trigger_celery_task("tasks.scrape_coinafrique", timeout=900)


def run_match_cross_source(**ctx):
    trigger_celery_task("tasks.match_cross_source", timeout=600)


# ── Configuration du DAG ──
default_args = {
    "owner": "ensea-datascience",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="scraping_pipeline",
    default_args=default_args,
    description="Pipeline quotidien : scraping Jumia + DjokStore + CoinAfrique, nettoyage, alertes, matching",
    schedule_interval="0 2 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["scraping", "pipeline", "production"],
) as dag:

    scrape_jumia = PythonOperator(
        task_id="scrape_jumia",
        python_callable=run_scrape_jumia,
    )

    clean_and_insert = PythonOperator(
        task_id="clean_and_insert",
        python_callable=run_clean_and_insert,
    )

    scrape_djokstore = PythonOperator(
        task_id="scrape_djokstore",
        python_callable=run_scrape_djokstore,
    )

    check_price_drops = PythonOperator(
        task_id="check_price_drops",
        python_callable=run_check_price_drops,
    )

    check_price_alerts = PythonOperator(
        task_id="check_price_alerts",
        python_callable=run_check_price_alerts,
    )

    scrape_coinafrique = PythonOperator(
        task_id="scrape_coinafrique",
        python_callable=run_scrape_coinafrique,
    )

    match_cross_source = PythonOperator(
        task_id="match_cross_source",
        python_callable=run_match_cross_source,
    )

    # ── Dependances (le coeur du DAG visuel) ──
    # Jumia : scrape → clean → ...
    # DjokStore + CoinAfrique : scrape seul (nettoyage integre)
    # Les trois convergent vers check_price_drops
    scrape_jumia >> clean_and_insert
    [clean_and_insert, scrape_djokstore, scrape_coinafrique] >> check_price_drops
    check_price_drops >> check_price_alerts >> match_cross_source
