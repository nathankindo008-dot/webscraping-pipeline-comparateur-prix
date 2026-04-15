-- Migration : préférences utilisateur pour recommandations « Pour vous »
-- À exécuter une fois sur une base existante (après création de la table users).
-- Exemple Docker :
--   docker exec -i jumia_postgres psql -U jumia_user -d jumia_db < api/migrations/001_user_preferences.sql

CREATE TABLE IF NOT EXISTS user_preferences (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    categories   JSONB   NOT NULL DEFAULT '[]'::jsonb,
    budget_min   INTEGER,
    budget_max   INTEGER,
    sources      JSONB,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences(user_id);
