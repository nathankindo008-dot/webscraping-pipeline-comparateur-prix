-- =============================================================
-- Schema SQL — Comparateur de Prix Jumia CI
-- ENSEA — AS Data Science | Dr N'golo Konate
--
-- Tables : users, products, price_history, user_favorites,
--          price_alerts, user_preferences, scrape_logs
-- =============================================================

DROP TABLE IF EXISTS scrape_logs CASCADE;
DROP TABLE IF EXISTS user_preferences CASCADE;
DROP TABLE IF EXISTS price_alerts CASCADE;
DROP TABLE IF EXISTS user_favorites CASCADE;
DROP TABLE IF EXISTS price_history CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- ─────────────────────────────────────────────
-- Users
-- ─────────────────────────────────────────────
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(60)  NOT NULL UNIQUE,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    name          VARCHAR(120) NOT NULL,
    is_active     BOOLEAN      DEFAULT TRUE,
    is_admin      BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);

-- ─────────────────────────────────────────────
-- Products
-- ─────────────────────────────────────────────
CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    product_url TEXT        NOT NULL UNIQUE,
    name        TEXT        NOT NULL,
    category    VARCHAR(60) NOT NULL,
    source      VARCHAR(30) NOT NULL DEFAULT 'jumia_ci',
    currency    CHAR(3)     NOT NULL DEFAULT 'XOF',
    image_url   TEXT,
    page_url    TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_source   ON products(source);

-- ─────────────────────────────────────────────
-- Price History
-- ─────────────────────────────────────────────
CREATE TABLE price_history (
    id            SERIAL PRIMARY KEY,
    product_id    INTEGER     NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price         NUMERIC(12, 0) NOT NULL,
    old_price     NUMERIC(12, 0),
    discount_pct  NUMERIC(5, 2),
    reviews_count INTEGER     NOT NULL DEFAULT 0,
    scraped_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT chk_price_positive CHECK (price > 0),
    CONSTRAINT chk_old_price_coherent CHECK (old_price IS NULL OR old_price > price),
    CONSTRAINT chk_discount_range CHECK (discount_pct IS NULL OR (discount_pct >= 0 AND discount_pct <= 100))
);

CREATE INDEX idx_price_history_product_id   ON price_history(product_id);
CREATE INDEX idx_price_history_scraped_at   ON price_history(scraped_at DESC);
CREATE INDEX idx_price_history_product_date ON price_history(product_id, scraped_at DESC);

-- ─────────────────────────────────────────────
-- User Favorites
-- ─────────────────────────────────────────────
CREATE TABLE user_favorites (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_user_product_fav UNIQUE (user_id, product_id)
);

CREATE INDEX idx_user_favorites_user_id    ON user_favorites(user_id);
CREATE INDEX idx_user_favorites_product_id ON user_favorites(product_id);

-- ─────────────────────────────────────────────
-- Price Alerts
-- ─────────────────────────────────────────────
CREATE TABLE price_alerts (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id   INTEGER      NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    target_price NUMERIC(12, 0) NOT NULL,
    is_active    BOOLEAN      DEFAULT TRUE,
    triggered_at TIMESTAMP WITH TIME ZONE,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_price_alerts_user_id    ON price_alerts(user_id);
CREATE INDEX idx_price_alerts_product_id ON price_alerts(product_id);

-- ─────────────────────────────────────────────
-- User Preferences (recommandations)
-- ─────────────────────────────────────────────
CREATE TABLE user_preferences (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    categories JSONB   NOT NULL DEFAULT '[]'::jsonb,
    budget_min INTEGER,
    budget_max INTEGER,
    sources    JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_user_preferences_user_id ON user_preferences(user_id);

-- ─────────────────────────────────────────────
-- Scrape Logs
-- ─────────────────────────────────────────────
CREATE TABLE scrape_logs (
    id            SERIAL PRIMARY KEY,
    source        VARCHAR(30) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'running',
    items_raw     INTEGER     DEFAULT 0,
    items_clean   INTEGER     DEFAULT 0,
    items_new     INTEGER     DEFAULT 0,
    items_updated INTEGER     DEFAULT 0,
    duration_sec  NUMERIC(8, 1),
    error_msg     TEXT,
    started_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    finished_at   TIMESTAMP WITH TIME ZONE
);

-- ─────────────────────────────────────────────
-- Product Matches (cross-source)
-- ─────────────────────────────────────────────
CREATE TABLE product_matches (
    id             SERIAL PRIMARY KEY,
    product_id_a   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_id_b   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    similarity     NUMERIC(5, 2) NOT NULL DEFAULT 0,
    created_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_match_pair UNIQUE (product_id_a, product_id_b),
    CONSTRAINT chk_diff_products CHECK (product_id_a <> product_id_b)
);

CREATE INDEX idx_matches_a ON product_matches(product_id_a);
CREATE INDEX idx_matches_b ON product_matches(product_id_b);

-- ─────────────────────────────────────────────
-- Trigger : updated_at automatique sur products
-- ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_user_preferences_updated_at
    BEFORE UPDATE ON user_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─────────────────────────────────────────────
-- Views
-- ─────────────────────────────────────────────
CREATE VIEW v_latest_prices AS
SELECT
    p.id            AS product_id,
    p.name,
    p.category,
    p.source,
    p.product_url,
    p.image_url,
    ph.price,
    ph.old_price,
    ph.discount_pct,
    ph.reviews_count,
    ph.scraped_at   AS last_scraped_at
FROM products p
JOIN LATERAL (
    SELECT *
    FROM price_history
    WHERE product_id = p.id
    ORDER BY scraped_at DESC
    LIMIT 1
) ph ON TRUE;

CREATE VIEW v_price_evolution AS
SELECT
    p.id            AS product_id,
    p.name,
    p.category,
    p.source,
    p.product_url,
    MIN(ph.price)   AS price_min,
    MAX(ph.price)   AS price_max,
    (
        SELECT price FROM price_history
        WHERE product_id = p.id
        ORDER BY scraped_at DESC LIMIT 1
    )               AS price_current,
    COUNT(ph.id)    AS nb_snapshots,
    MIN(ph.scraped_at) AS first_seen,
    MAX(ph.scraped_at) AS last_seen
FROM products p
JOIN price_history ph ON ph.product_id = p.id
GROUP BY p.id, p.name, p.category, p.source, p.product_url;
