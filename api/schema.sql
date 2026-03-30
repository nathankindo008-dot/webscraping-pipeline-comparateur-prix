DROP TABLE IF EXISTS price_history CASCADE;
DROP TABLE IF EXISTS products CASCADE;

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    product_url TEXT        NOT NULL UNIQUE,
    name        TEXT        NOT NULL,
    category    VARCHAR(60) NOT NULL,
    currency    CHAR(3)     NOT NULL DEFAULT 'XOF',
    image_url   TEXT,
    page_url    TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_products_category ON products(category);

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

CREATE VIEW v_latest_prices AS
SELECT
    p.id            AS product_id,
    p.name,
    p.category,
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
GROUP BY p.id, p.name, p.category, p.product_url;