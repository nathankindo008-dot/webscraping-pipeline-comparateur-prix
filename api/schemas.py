"""
schemas.py — Sérialiseurs JSON pour l'API Flask
Transforme les objets SQLAlchemy en dictionnaires Python propres.
"""

from decimal import Decimal


def _fmt_price(value) -> float | None:
    """Convertit Decimal/None en float ou None."""
    if value is None:
        return None
    return float(value)


def _fmt_date(value) -> str | None:
    """ISO 8601 pour les timestamps."""
    if value is None:
        return None
    return value.isoformat()


# ─────────────────────────────────────────────
# Schéma produit — liste / catégorie / recherche
# ─────────────────────────────────────────────
def product_schema(product, price_history) -> dict:
    """Représentation légère d'un produit + son dernier prix."""
    return {
        "id":           product.id,
        "name":         product.name,
        "category":     product.category,
        "price":        _fmt_price(price_history.price),
        "old_price":    _fmt_price(price_history.old_price),
        "discount_pct": _fmt_price(price_history.discount_pct),
        "currency":     product.currency,
        "reviews_count": price_history.reviews_count,
        "image_url":    product.image_url,
        "product_url":  product.product_url,
        "last_scraped_at": _fmt_date(price_history.scraped_at),
    }


# ─────────────────────────────────────────────
# Schéma produit — détail complet
# ─────────────────────────────────────────────
def product_detail_schema(product, price_history) -> dict:
    """Représentation complète avec métadonnées du produit."""
    base = product_schema(product, price_history)
    base.update({
        "page_url":   product.page_url,
        "created_at": _fmt_date(product.created_at),
        "updated_at": _fmt_date(product.updated_at),
    })
    return base


# ─────────────────────────────────────────────
# Schéma price_history — un snapshot
# ─────────────────────────────────────────────
def price_history_schema(snapshot) -> dict:
    """Un enregistrement d'historique de prix."""
    return {
        "id":           snapshot.id,
        "price":        _fmt_price(snapshot.price),
        "old_price":    _fmt_price(snapshot.old_price),
        "discount_pct": _fmt_price(snapshot.discount_pct),
        "reviews_count": snapshot.reviews_count,
        "scraped_at":   _fmt_date(snapshot.scraped_at),
    }


# ─────────────────────────────────────────────
# Schéma compare — comparaison côte à côte
# ─────────────────────────────────────────────
def compare_schema(product, price_history) -> dict:
    """Données d'un produit pour l'endpoint /compare."""
    savings = None
    if price_history.old_price and price_history.price:
        savings = float(price_history.old_price - price_history.price)

    return {
        "id":           product.id,
        "name":         product.name,
        "category":     product.category,
        "price":        _fmt_price(price_history.price),
        "old_price":    _fmt_price(price_history.old_price),
        "discount_pct": _fmt_price(price_history.discount_pct),
        "savings":      savings,          # économie en XOF
        "currency":     product.currency,
        "reviews_count": price_history.reviews_count,
        "image_url":    product.image_url,
        "product_url":  product.product_url,
        "last_scraped_at": _fmt_date(price_history.scraped_at),
    }


# ─────────────────────────────────────────────
# Schéma catégorie — stats agrégées
# ─────────────────────────────────────────────
def category_schema(row) -> dict:
    """Stats d'une catégorie (depuis une requête agrégée)."""
    return {
        "category":    row.category,
        "nb_products": row.nb_products,
        "avg_price":   round(float(row.avg_price), 0) if row.avg_price else None,
        "min_price":   _fmt_price(row.min_price),
        "max_price":   _fmt_price(row.max_price),
    }