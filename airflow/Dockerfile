# =============================================================
# Dockerfile Airflow — Comparateur de Prix Jumia CI
# Orchestrateur unique du pipeline (publie vers Celery worker via Redis)
# =============================================================

FROM apache/airflow:2.9.3-python3.12

USER airflow

RUN pip install --no-cache-dir \
    celery==5.4.0 \
    redis==5.2.0
