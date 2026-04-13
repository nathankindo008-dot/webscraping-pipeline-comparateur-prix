-- Cree la base airflow_db si elle n'existe pas encore.
-- Ce script est monte dans /docker-entrypoint-initdb.d/ de PostgreSQL
-- et s'execute automatiquement au premier demarrage du conteneur.

SELECT 'CREATE DATABASE airflow_db'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow_db')\gexec
