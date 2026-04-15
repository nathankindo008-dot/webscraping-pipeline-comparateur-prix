# =============================================================
# Dockerfile Airflow — Comparateur de Prix Jumia CI
# Orchestrateur visuel de pipeline (complement a Celery Beat)
# =============================================================

FROM apache/airflow:2.9.3-python3.12

USER airflow

RUN pip install --no-cache-dir \
    celery==5.4.0 \
    redis==5.2.0
