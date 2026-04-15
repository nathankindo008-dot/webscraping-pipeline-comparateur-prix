-- Rôle administrateur (scraping, logs Celery). Les comptes restent non-admin par défaut.
-- Promouvoir un compte : UPDATE users SET is_admin = TRUE WHERE email = 'votre@email';

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
