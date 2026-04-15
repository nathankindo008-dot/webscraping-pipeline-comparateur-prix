"""
app.py — API Flask Comparateur de Prix Jumia CI
ENSEA — AS Data Science | Dr N'golo Konate

Endpoints :
  GET  /products                  → liste paginée avec filtres
  GET  /products/<id>             → détail d'un produit
  GET  /products/<id>/history     → historique des prix
  GET  /products/compare          → comparer N produits
  GET  /categories                → liste des catégories + stats
  GET  /categories/<cat>/products → produits d'une catégorie
  GET  /search?q=...              → recherche textuelle
  POST /scrape                    → lancer le scraping (synchrone)
  POST /scrape/async              → lancer le scraping (Celery)
  GET  /tasks/<id>/status         → statut d'une tâche Celery
  GET  /export                    → export CSV / Excel / JSON
  GET  /health                    → statut de l'API
  GET  /metrics                   → métriques Prometheus
"""
import os
os.environ.setdefault("PYTHONUTF8", "1")

import io
import csv
from datetime import datetime, timedelta, timezone
from functools import wraps
import bcrypt
import json
from flask import Flask, jsonify, request, abort, Response, send_file, render_template
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
)
from sqlalchemy import func, text, case
from flasgger import Swagger
from prometheus_flask_exporter import PrometheusMetrics

from models import Product, PriceHistory, User, UserFavorite, PriceAlert, ScrapeLog, UserPreference, ProductMatch
from extensions import db
from schemas import (
    product_schema, product_detail_schema,
    price_history_schema, compare_schema, category_schema
)
from assistant_routes import register_assistant_routes

# ─────────────────────────────────────────────
# App & Config
# ─────────────────────────────────────────────
app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "postgresql://jumia_user:jumia_pass@localhost:5433/jumia_db"
) + "?client_encoding=utf8"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JSON_SORT_KEYS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = 86400 * 7  # 7 jours

db.init_app(app)
jwt = JWTManager(app)

# ─────────────────────────────────────────────
# Swagger / OpenAPI
# ─────────────────────────────────────────────
swagger_config = {
    "headers": [],
    "specs": [{"endpoint": "apispec", "route": "/apispec.json"}],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs/",
}
swagger_template = {
    "info": {
        "title": "Comparateur de Prix Jumia CI",
        "description": "API de suivi des prix Jumia Côte d'Ivoire — ENSEA AS Data Science",
        "version": "1.0.0",
    },
    "basePath": "/",
}
swagger = Swagger(app, config=swagger_config, template=swagger_template)

# ─────────────────────────────────────────────
# Prometheus Metrics
# ─────────────────────────────────────────────
metrics = PrometheusMetrics(app, defaults_prefix="jumia_api")
metrics.info("app_info", "Comparateur de Prix Jumia CI", version="1.0.0")

register_assistant_routes(app)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _get_current_user_id() -> int:
    """Parse le JWT identity en int, abort 401 si invalide."""
    try:
        return int(get_jwt_identity())
    except (TypeError, ValueError):
        abort(401, description="Token JWT invalide.")


def admin_required(f):
    """JWT + utilisateur avec is_admin=True."""

    @wraps(f)
    def decorated(*args, **kwargs):
        verify_jwt_in_request()
        uid = _get_current_user_id()
        u = db.session.get(User, uid)
        if not u or not u.is_admin:
            abort(403, description="Accès administrateur requis.")
        return f(*args, **kwargs)

    return decorated


def paginate_args():
    """Extrait et valide les paramètres de pagination."""
    try:
        page     = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    except ValueError:
        abort(400, description="page et per_page doivent être des entiers positifs.")
    return page, per_page


def latest_price_subquery():
    """Sous-requête : dernier snapshot de prix par produit."""
    return (
        db.session.query(
            PriceHistory.product_id,
            func.max(PriceHistory.scraped_at).label("max_scraped_at")
        )
        .group_by(PriceHistory.product_id)
        .subquery()
    )


# ─────────────────────────────────────────────
# PAGES FRONTEND (templates multiples)
# ─────────────────────────────────────────────
@app.route("/login", methods=["GET"])
def page_login():
    return render_template("login.html")

@app.route("/", methods=["GET"])
def page_accueil():
    return render_template("accueil.html", active_page="accueil")

@app.route("/boutique", methods=["GET"])
def page_boutique():
    return render_template("boutique.html", active_page="boutique")

@app.route("/comparer", methods=["GET"])
def page_comparer():
    return render_template("comparer.html", active_page="comparer")

@app.route("/categories-view", methods=["GET"])
def page_categories():
    return render_template("categories_view.html", active_page="categories")

@app.route("/historique/<int:product_id>", methods=["GET"])
def page_historique(product_id):
    return render_template("historique.html", active_page="historique", product_id=product_id)

@app.route("/historique", methods=["GET"])
def page_historique_empty():
    return render_template("historique.html", active_page="historique", product_id=None)

@app.route("/mon-espace", methods=["GET"])
def page_espace():
    return render_template("mon_espace.html", active_page="espace")

@app.route("/admin", methods=["GET"])
def page_admin():
    return render_template("admin.html", active_page="admin")


# ─────────────────────────────────────────────
# ADMIN: GET /admin/scrape-logs
# ─────────────────────────────────────────────
@app.route("/admin/scrape-logs", methods=["GET"])
@admin_required
def scrape_logs():
    """
    Historique des scrapes avec stats.
    ---
    tags: [Admin]
    parameters:
      - name: limit
        in: query
        type: integer
        default: 30
    responses:
      200:
        description: Logs de scraping
    """
    try:
        limit = min(100, max(1, int(request.args.get("limit", 30))))
    except ValueError:
        limit = 30

    logs = (
        db.session.query(ScrapeLog)
        .order_by(ScrapeLog.started_at.desc())
        .limit(limit)
        .all()
    )

    data = []
    for l in logs:
        data.append({
            "id": l.id,
            "source": l.source,
            "status": l.status,
            "items_raw": l.items_raw,
            "items_clean": l.items_clean,
            "items_new": l.items_new,
            "items_updated": l.items_updated,
            "duration_sec": float(l.duration_sec) if l.duration_sec else None,
            "error_msg": l.error_msg,
            "started_at": l.started_at.isoformat() if l.started_at else None,
            "finished_at": l.finished_at.isoformat() if l.finished_at else None,
        })

    total_runs = db.session.query(func.count(ScrapeLog.id)).scalar() or 0
    success_runs = db.session.query(func.count(ScrapeLog.id)).filter(ScrapeLog.status == "success").scalar() or 0
    last_jumia = db.session.query(ScrapeLog).filter(ScrapeLog.source == "jumia_ci", ScrapeLog.status == "success").order_by(ScrapeLog.finished_at.desc()).first()
    last_djok = db.session.query(ScrapeLog).filter(ScrapeLog.source == "djokstore_ci", ScrapeLog.status == "success").order_by(ScrapeLog.finished_at.desc()).first()
    last_coin = db.session.query(ScrapeLog).filter(ScrapeLog.source == "coinafrique_ci", ScrapeLog.status == "success").order_by(ScrapeLog.finished_at.desc()).first()

    return jsonify({
        "logs": data,
        "summary": {
            "total_runs": total_runs,
            "success_runs": success_runs,
            "error_runs": total_runs - success_runs,
            "last_jumia": last_jumia.finished_at.isoformat() if last_jumia and last_jumia.finished_at else None,
            "last_djokstore": last_djok.finished_at.isoformat() if last_djok and last_djok.finished_at else None,
            "last_coinafrique": last_coin.finished_at.isoformat() if last_coin and last_coin.finished_at else None,
        },
        "schedule": {
            "full_pipeline": "Tous les jours a 2h00",
            "check_drops": "Tous les jours a 6h00",
            "check_alerts": "Tous les jours a 3h00",
            "health_check": "Toutes les 5 min",
        }
    }), 200


# ─────────────────────────────────────────────
# STATS: GET /stats/overview  (dashboard KPIs)
# ─────────────────────────────────────────────
@app.route("/stats/overview", methods=["GET"])
def stats_overview():
    """
    KPIs globaux pour le dashboard : produits, prix moyen/min/max, catégories, promotions.
    ---
    tags: [Statistiques]
    responses:
      200:
        description: KPIs du dashboard
    """
    sub = latest_price_subquery()
    base = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
    )
    row = base.with_entities(
        func.count(Product.id).label("total_products"),
        func.avg(PriceHistory.price).label("avg_price"),
        func.min(PriceHistory.price).label("min_price"),
        func.max(PriceHistory.price).label("max_price"),
    ).first()

    nb_promos = base.filter(
        PriceHistory.discount_pct.isnot(None), PriceHistory.discount_pct > 0
    ).count()

    nb_cats = db.session.query(func.count(func.distinct(Product.category))).scalar() or 0
    nb_snapshots = db.session.query(func.count(PriceHistory.id)).scalar() or 0

    return jsonify({
        "total_products": row.total_products or 0,
        "avg_price": round(float(row.avg_price)) if row.avg_price else 0,
        "min_price": round(float(row.min_price)) if row.min_price else 0,
        "max_price": round(float(row.max_price)) if row.max_price else 0,
        "nb_categories": nb_cats,
        "nb_promotions": nb_promos,
        "nb_snapshots": nb_snapshots,
    }), 200


# ─────────────────────────────────────────────
# STATS: GET /stats/price-trends
# ─────────────────────────────────────────────
@app.route("/stats/price-trends", methods=["GET"])
def price_trends():
    """
    Evolution du prix moyen par jour pour chaque source (Jumia CI vs DjokStore CI).
    ---
    tags: [Statistiques]
    parameters:
      - name: days
        in: query
        type: integer
        default: 30
        description: Nombre de jours d'historique (max 90)
    responses:
      200:
        description: Séries temporelles par source
    """
    try:
        days = min(90, max(7, int(request.args.get("days", 30))))
    except ValueError:
        days = 30

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.session.query(
            func.date(PriceHistory.scraped_at).label("day"),
            Product.source,
            func.avg(PriceHistory.price).label("avg_price"),
            func.count(PriceHistory.id).label("nb_snapshots"),
        )
        .join(Product, PriceHistory.product_id == Product.id)
        .filter(PriceHistory.scraped_at >= since)
        .group_by(func.date(PriceHistory.scraped_at), Product.source)
        .order_by(func.date(PriceHistory.scraped_at))
        .all()
    )

    sources = {}
    for day, source, avg_price, nb in rows:
        day_str = str(day)
        if source not in sources:
            sources[source] = []
        sources[source].append({
            "date": day_str,
            "avg_price": round(float(avg_price)),
            "nb_snapshots": nb,
        })

    return jsonify({"trends": sources, "days": days}), 200


# ─────────────────────────────────────────────
# 1. GET /health
# ─────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    """
    Statut de l'API et de la base de données.
    ---
    tags: [Monitoring]
    responses:
      200:
        description: API opérationnelle
      503:
        description: Base de données inaccessible
    """
    try:
        db.session.execute(text("SELECT 1"))
        nb_products = db.session.query(func.count(Product.id)).scalar()
        nb_snapshots = db.session.query(func.count(PriceHistory.id)).scalar()
        return jsonify({
            "status": "ok",
            "database": "connected",
            "stats": {
                "products": nb_products,
                "price_snapshots": nb_snapshots,
            }
        }), 200
    except Exception:
        return jsonify({"status": "error", "database": "unreachable"}), 503


# ─────────────────────────────────────────────
# 2. GET /categories
# ─────────────────────────────────────────────
@app.route("/categories", methods=["GET"])
def list_categories():
    """
    Liste toutes les catégories avec nombre de produits et prix moyen.
    ---
    tags: [Catégories]
    responses:
      200:
        description: Liste des catégories
    """
    sub = latest_price_subquery()
    rows = (
        db.session.query(
            Product.category,
            func.count(Product.id).label("nb_products"),
            func.avg(PriceHistory.price).label("avg_price"),
            func.min(PriceHistory.price).label("min_price"),
            func.max(PriceHistory.price).label("max_price"),
        )
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .group_by(Product.category)
        .order_by(func.count(Product.id).desc())
        .all()
    )
    data = [category_schema(r) for r in rows]
    return jsonify({"categories": data, "total": len(data)}), 200


# ─────────────────────────────────────────────
# 3. GET /categories/<category>/products
# ─────────────────────────────────────────────
@app.route("/categories/<string:category>/products", methods=["GET"])
def products_by_category(category):
    """
    Produits d'une catégorie, triés par prix croissant.
    ---
    tags: [Catégories]
    parameters:
      - name: category
        in: path
        type: string
        required: true
      - name: page
        in: query
        type: integer
        default: 1
      - name: per_page
        in: query
        type: integer
        default: 20
    responses:
      200:
        description: Liste de produits
      404:
        description: Catégorie introuvable
    """
    page, per_page = paginate_args()
    sub = latest_price_subquery()

    query = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(Product.category == category)
        .order_by(PriceHistory.price.asc())
    )
    total = query.count()
    if total == 0:
        abort(404, description=f"Catégorie '{category}' introuvable ou vide.")

    results = query.offset((page - 1) * per_page).limit(per_page).all()
    data = [product_schema(p, ph) for p, ph in results]
    return jsonify({
        "category": category,
        "products": data,
        "pagination": {"page": page, "per_page": per_page, "total": total,
                       "pages": -(-total // per_page)},
    }), 200


# ─────────────────────────────────────────────
# 4. GET /products
# ─────────────────────────────────────────────
@app.route("/products", methods=["GET"])
def list_products():
    """
    Liste paginée de produits avec filtres optionnels.
    ---
    tags: [Produits]
    parameters:
      - name: category
        in: query
        type: string
      - name: min_price
        in: query
        type: number
      - name: max_price
        in: query
        type: number
      - name: discount
        in: query
        type: boolean
        description: "true = uniquement les produits en promotion"
      - name: source
        in: query
        type: string
        description: "Filtrer par site (jumia_ci, djokstore_ci)"
      - name: sort
        in: query
        type: string
        enum: [price_asc, price_desc, discount_desc, reviews_desc]
        default: price_asc
      - name: page
        in: query
        type: integer
        default: 1
      - name: per_page
        in: query
        type: integer
        default: 20
    responses:
      200:
        description: Liste de produits
    """
    page, per_page = paginate_args()
    sub = latest_price_subquery()

    query = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
    )

    # Filtres
    if cat := request.args.get("category"):
        query = query.filter(Product.category == cat)
    if src := request.args.get("source"):
        query = query.filter(Product.source == src)
    if min_p := request.args.get("min_price"):
        try:
            query = query.filter(PriceHistory.price >= float(min_p))
        except ValueError:
            abort(400, description="min_price doit être un nombre.")
    if max_p := request.args.get("max_price"):
        try:
            query = query.filter(PriceHistory.price <= float(max_p))
        except ValueError:
            abort(400, description="max_price doit être un nombre.")
    if request.args.get("discount", "").lower() == "true":
        query = query.filter(PriceHistory.discount_pct.isnot(None), PriceHistory.discount_pct > 0)

    # Tri
    sort = request.args.get("sort", "price_asc")
    sort_map = {
        "price_asc":     PriceHistory.price.asc(),
        "price_desc":    PriceHistory.price.desc(),
        "discount_desc": PriceHistory.discount_pct.desc().nullslast(),
        "reviews_desc":  PriceHistory.reviews_count.desc(),
    }
    query = query.order_by(sort_map.get(sort, PriceHistory.price.asc()))

    total = query.count()
    results = query.offset((page - 1) * per_page).limit(per_page).all()
    data = [product_schema(p, ph) for p, ph in results]

    return jsonify({
        "products": data,
        "pagination": {"page": page, "per_page": per_page, "total": total,
                       "pages": -(-total // per_page)},
        "filters_applied": {
            "category":  request.args.get("category"),
            "source":    request.args.get("source"),
            "min_price": request.args.get("min_price"),
            "max_price": request.args.get("max_price"),
            "discount":  request.args.get("discount"),
            "sort":      sort,
        }
    }), 200


# ─────────────────────────────────────────────
# 5. GET /products/compare
# ─────────────────────────────────────────────
@app.route("/products/compare", methods=["GET"])
def compare_products():
    """
    Compare plusieurs produits côte à côte (prix, historique, remise).
    ---
    tags: [Produits]
    parameters:
      - name: ids
        in: query
        type: string
        required: true
        description: "IDs séparés par virgule, ex: 1,2,3 (max 5)"
    responses:
      200:
        description: Comparaison des produits
      400:
        description: Paramètre ids manquant ou invalide
      404:
        description: Un ou plusieurs produits introuvables
    """
    ids_param = request.args.get("ids", "")
    if not ids_param:
        abort(400, description="Paramètre 'ids' requis. Ex: /products/compare?ids=1,2,3")

    try:
        ids = [int(i.strip()) for i in ids_param.split(",") if i.strip()]
    except ValueError:
        abort(400, description="Les ids doivent être des entiers. Ex: ids=1,2,3")

    if len(ids) < 2:
        abort(400, description="Fournir au moins 2 ids pour une comparaison.")
    if len(ids) > 5:
        abort(400, description="Maximum 5 produits comparables à la fois.")

    sub = latest_price_subquery()
    results = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(Product.id.in_(ids))
        .all()
    )

    found_ids = {p.id for p, _ in results}
    missing = set(ids) - found_ids
    if missing:
        abort(404, description=f"Produits introuvables : {sorted(missing)}")

    results_sorted = sorted(results, key=lambda r: ids.index(r[0].id))

    compared = [compare_schema(p, ph) for p, ph in results_sorted]

    # Meilleure offre = prix le plus bas
    best = min(compared, key=lambda x: x["price"])

    return jsonify({
        "comparison": compared,
        "best_deal": {
            "product_id": best["id"],
            "name":       best["name"],
            "price":      best["price"],
            "currency":   "XOF",
        },
        "nb_products": len(compared),
    }), 200


# ─────────────────────────────────────────────
# 6. GET /products/<id>
# ─────────────────────────────────────────────
@app.route("/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    """
    Détail complet d'un produit avec son dernier prix.
    ---
    tags: [Produits]
    parameters:
      - name: product_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Détail du produit
      404:
        description: Produit introuvable
    """
    sub = latest_price_subquery()
    result = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(Product.id == product_id)
        .first()
    )
    if not result:
        abort(404, description=f"Produit #{product_id} introuvable.")

    product, ph = result
    return jsonify(product_detail_schema(product, ph)), 200


# ─────────────────────────────────────────────
# 7. GET /products/<id>/history
# ─────────────────────────────────────────────
@app.route("/products/<int:product_id>/history", methods=["GET"])
def get_price_history(product_id):
    """
    Historique complet des prix d'un produit (du plus récent au plus ancien).
    ---
    tags: [Produits]
    parameters:
      - name: product_id
        in: path
        type: integer
        required: true
      - name: limit
        in: query
        type: integer
        default: 30
        description: Nombre de snapshots retournés (max 365)
    responses:
      200:
        description: Historique des prix
      404:
        description: Produit introuvable
    """
    product = db.session.get(Product, product_id)
    if not product:
        abort(404, description=f"Produit #{product_id} introuvable.")

    try:
        limit = min(365, max(1, int(request.args.get("limit", 30))))
    except ValueError:
        limit = 30

    snapshots = (
        db.session.query(PriceHistory)
        .filter(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.scraped_at.desc())
        .limit(limit)
        .all()
    )

    history = [price_history_schema(s) for s in snapshots]

    # Calcul variation prix (premier vs dernier snapshot)
    variation = None
    if len(history) >= 2:
        first_price = history[-1]["price"]
        last_price  = history[0]["price"]
        if first_price > 0:
            variation = round((last_price - first_price) / first_price * 100, 2)

    return jsonify({
        "product_id":  product_id,
        "name":        product.name,
        "category":    product.category,
        "source":      product.source,
        "image_url":   product.image_url,
        "product_url": product.product_url,
        "history":     history,
        "nb_snapshots": len(history),
        "price_variation_pct": variation,  # positif = hausse, négatif = baisse
    }), 200


# ─────────────────────────────────────────────
# 7b. GET /products/<id>/price-insight
# ─────────────────────────────────────────────
@app.route("/products/<int:product_id>/price-insight", methods=["GET"])
def price_insight(product_id):
    """
    Analyse du prix actuel vs historique : bon moment pour acheter ?
    ---
    tags: [Produits]
    parameters:
      - name: product_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Insight prix
      404:
        description: Produit introuvable
    """
    product = db.session.get(Product, product_id)
    if not product:
        abort(404, description=f"Produit #{product_id} introuvable.")

    snapshots = (
        db.session.query(PriceHistory.price, PriceHistory.scraped_at)
        .filter(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.scraped_at.desc())
        .limit(365)
        .all()
    )

    if not snapshots:
        return jsonify({"product_id": product_id, "insight": None}), 200

    current_price = float(snapshots[0].price)
    all_prices = [float(s.price) for s in snapshots]

    price_min = min(all_prices)
    price_max = max(all_prices)
    price_avg = sum(all_prices) / len(all_prices)

    prices_30d = [float(s.price) for s in snapshots[:30]]
    avg_30d = sum(prices_30d) / len(prices_30d) if prices_30d else price_avg

    trend = "stable"
    if len(all_prices) >= 3:
        recent = sum(all_prices[:3]) / 3
        older = sum(all_prices[-3:]) / 3
        if older > 0:
            pct_change = (recent - older) / older * 100
            if pct_change < -5:
                trend = "baisse"
            elif pct_change > 5:
                trend = "hausse"

    if price_max > price_min:
        position = (current_price - price_min) / (price_max - price_min)
    else:
        position = 0.5

    if current_price <= price_min * 1.05:
        verdict = "prix_bas"
        label = "Prix au plus bas !"
        color = "green"
    elif current_price < avg_30d * 0.92:
        verdict = "bonne_affaire"
        label = "Bonne affaire"
        color = "green"
    elif current_price <= avg_30d * 1.05:
        verdict = "prix_moyen"
        label = "Prix dans la moyenne"
        color = "orange"
    else:
        verdict = "prix_eleve"
        label = "Prix eleve, attends une promo"
        color = "red"

    return jsonify({
        "product_id": product_id,
        "insight": {
            "current_price": int(current_price),
            "avg_all_time": int(price_avg),
            "avg_30d": int(avg_30d),
            "price_min": int(price_min),
            "price_max": int(price_max),
            "nb_snapshots": len(all_prices),
            "position_pct": round(position * 100),
            "trend": trend,
            "verdict": verdict,
            "label": label,
            "color": color,
        },
    }), 200


# ─────────────────────────────────────────────
# 7c. GET /products/<id>/matches (cross-source)
# ─────────────────────────────────────────────
@app.route("/products/<int:product_id>/matches", methods=["GET"])
def product_matches(product_id):
    """
    Produits similaires sur l'autre source (cross-source matching).
    ---
    tags: [Produits]
    parameters:
      - name: product_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Produits matchés
    """
    sub = (
        db.session.query(
            PriceHistory.product_id,
            func.max(PriceHistory.scraped_at).label("max_sa"),
        )
        .group_by(PriceHistory.product_id)
        .subquery()
    )

    from sqlalchemy import or_
    matches = (
        db.session.query(ProductMatch, Product, PriceHistory)
        .filter(or_(
            ProductMatch.product_id_a == product_id,
            ProductMatch.product_id_b == product_id,
        ))
        .join(Product, Product.id == case(
            (ProductMatch.product_id_a == product_id, ProductMatch.product_id_b),
            else_=ProductMatch.product_id_a,
        ))
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id)
              & (PriceHistory.scraped_at == sub.c.max_sa))
        .order_by(ProductMatch.similarity.desc())
        .limit(5)
        .all()
    )

    results = []
    for m, p, ph in matches:
        _labels = {"djokstore_ci": "DjokStore CI", "jumia_ci": "Jumia CI", "coinafrique_ci": "CoinAfrique CI"}
        source_label = _labels.get(p.source, p.source)
        results.append({
            "id": p.id,
            "name": p.name,
            "price": int(ph.price),
            "old_price": int(ph.old_price) if ph.old_price else None,
            "discount_pct": float(ph.discount_pct) if ph.discount_pct else None,
            "source": p.source,
            "source_label": source_label,
            "category": p.category,
            "image_url": p.image_url,
            "product_url": p.product_url,
            "similarity": float(m.similarity),
        })

    return jsonify({"product_id": product_id, "matches": results}), 200


# ─────────────────────────────────────────────
# 8a. POST /search/image (recherche par image IA)
# ─────────────────────────────────────────────
@app.route("/search/image", methods=["POST"])
def search_by_image():
    """
    Recherche par image : envoie une photo, l'IA identifie le produit
    et retourne des suggestions de la base de données.
    ---
    tags: [Recherche]
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [image]
          properties:
            image: {type: string, description: "Image en base64 (data:image/...;base64,...)"}
    responses:
      200:
        description: Description IA + suggestions produits
      400:
        description: Image manquante
      502:
        description: Erreur Groq Vision
    """
    import urllib.request
    import urllib.error

    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image", "")
    if not image_b64:
        abort(400, description="Le champ 'image' est requis (base64).")

    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        return jsonify({"error": "Clé Groq non configurée."}), 502

    vision_model = "meta-llama/llama-4-scout-17b-16e-instruct"
    prompt = (
        "Identifie ce produit. Réponds UNIQUEMENT avec : le nom du produit, "
        "la marque et le type (ex: 'Samsung Galaxy A15 smartphone' ou 'Nike Air Max chaussures'). "
        "Juste le nom, rien d'autre. Pas de phrase."
    )

    payload = json.dumps({
        "model": vision_model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_b64}},
            ],
        }],
        "max_tokens": 80,
        "temperature": 0.1,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        description = result["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, Exception) as e:
        return jsonify({"error": f"Erreur Groq Vision: {e}"}), 502

    q = description[:120]
    sub = latest_price_subquery()
    results = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id)
              & (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(func.lower(Product.name).op("%%")(q.lower()))
        .order_by(PriceHistory.price.asc())
        .limit(12)
        .all()
    )

    if not results:
        words = [w for w in q.split() if len(w) >= 3][:4]
        if words:
            filters = [Product.name.ilike(f"%{w}%") for w in words]
            from sqlalchemy import or_
            results = (
                db.session.query(Product, PriceHistory)
                .join(sub, Product.id == sub.c.product_id)
                .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id)
                      & (PriceHistory.scraped_at == sub.c.max_scraped_at))
                .filter(or_(*filters))
                .order_by(PriceHistory.price.asc())
                .limit(12)
                .all()
            )

    suggestions = []
    for p, ph in results:
        suggestions.append({
            "id": p.id,
            "name": p.name,
            "price": int(ph.price),
            "source": p.source,
            "image_url": p.image_url,
            "category": p.category,
        })

    return jsonify({"description": description, "suggestions": suggestions}), 200


# ─────────────────────────────────────────────
# 8a-bis. GET /search/brands (marques en base)
# ─────────────────────────────────────────────
@app.route("/search/brands", methods=["GET"])
def search_brands():
    try:
        rows = db.session.execute(
            text("""
                SELECT DISTINCT
                    split_part(lower(name), ' ', 1) AS brand
                FROM products
                GROUP BY brand
                HAVING COUNT(*) >= 3
                ORDER BY COUNT(*) DESC
                LIMIT 80
            """)
        ).fetchall()
        return jsonify([r[0] for r in rows]), 200
    except Exception:
        return jsonify([]), 200


# ─────────────────────────────────────────────
# 8b. GET /search/suggest (autocompletion)
# ─────────────────────────────────────────────
@app.route("/search/suggest", methods=["GET"])
def search_suggest():
    """
    Suggestions rapides pour l'autocompletion (leger, pas de pagination).
    ---
    tags: [Recherche]
    parameters:
      - name: q
        in: query
        type: string
        required: true
        description: "Min 2 caracteres"
      - name: source
        in: query
        type: string
        description: "Filtrer par source (jumia_ci, djokstore_ci)"
      - name: limit
        in: query
        type: integer
        default: 8
    responses:
      200:
        description: Liste de suggestions
    """
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([]), 200

    source = request.args.get("source", "").strip()

    try:
        limit = min(15, max(1, int(request.args.get("limit", 8))))
    except ValueError:
        limit = 8

    sub = latest_price_subquery()
    query = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id)
              & (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(Product.name.ilike(f"%{q}%"))
    )
    if source:
        query = query.filter(Product.source == source)
    results = query.order_by(PriceHistory.price.asc()).limit(limit).all()

    suggestions = []
    for p, ph in results:
        suggestions.append({
            "id": p.id,
            "name": p.name,
            "price": int(ph.price),
            "source": p.source,
            "image_url": p.image_url,
            "category": p.category,
        })

    return jsonify(suggestions), 200


# ─────────────────────────────────────────────
# 8b. GET /search
# ─────────────────────────────────────────────
@app.route("/search", methods=["GET"])
def search_products():
    """
    Recherche textuelle sur le nom des produits (insensible à la casse).
    ---
    tags: [Recherche]
    parameters:
      - name: q
        in: query
        type: string
        required: true
        description: "Mot-clé de recherche, ex: samsung galaxy"
      - name: category
        in: query
        type: string
      - name: page
        in: query
        type: integer
        default: 1
      - name: per_page
        in: query
        type: integer
        default: 20
    responses:
      200:
        description: Résultats de recherche
      400:
        description: Paramètre q manquant
    """
    q = request.args.get("q", "").strip()
    if not q:
        abort(400, description="Paramètre 'q' requis. Ex: /search?q=samsung")

    page, per_page = paginate_args()
    sub = latest_price_subquery()

    query = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(Product.name.ilike(f"%{q}%"))
    )

    if cat := request.args.get("category"):
        query = query.filter(Product.category == cat)
    if src := request.args.get("source"):
        query = query.filter(Product.source == src)

    query = query.order_by(PriceHistory.reviews_count.desc())
    total = query.count()
    results = query.offset((page - 1) * per_page).limit(per_page).all()
    data = [product_schema(p, ph) for p, ph in results]

    return jsonify({
        "query": q,
        "products": data,
        "pagination": {"page": page, "per_page": per_page, "total": total,
                       "pages": -(-total // per_page)},
    }), 200


# =============================================================
#  AUTHENTIFICATION & UTILISATEURS
# =============================================================

# ─────────────────────────────────────────────
# AUTH: POST /auth/signup
# ─────────────────────────────────────────────
@app.route("/auth/signup", methods=["POST"])
def signup():
    """
    Inscription d'un nouvel utilisateur.
    ---
    tags: [Authentification]
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [username, email, password, name]
          properties:
            username: {type: string}
            email: {type: string}
            password: {type: string}
            name: {type: string}
    responses:
      201:
        description: Compte créé
      400:
        description: Données invalides
      409:
        description: Username ou email déjà utilisé
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()

    if not username or not email or not password or not name:
        abort(400, description="username, email, password et name sont requis.")
    if len(username) < 3:
        abort(400, description="Le nom d'utilisateur doit contenir au moins 3 caractères.")
    if len(password) < 6:
        abort(400, description="Le mot de passe doit contenir au moins 6 caractères.")

    if db.session.query(User).filter(User.username == username).first():
        return jsonify({"error": "Conflict", "message": "Ce nom d'utilisateur est déjà pris."}), 409
    if db.session.query(User).filter(User.email == email).first():
        return jsonify({"error": "Conflict", "message": "Cet email est déjà utilisé."}), 409

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = User(username=username, email=email, password_hash=pw_hash, name=name, is_admin=False)
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return jsonify({
        "message": "Compte créé avec succès",
        "user": {"id": user.id, "username": user.username, "email": user.email, "name": user.name, "is_admin": bool(user.is_admin)},
        "access_token": token,
    }), 201


# ─────────────────────────────────────────────
# AUTH: POST /auth/login
# ─────────────────────────────────────────────
@app.route("/auth/login", methods=["POST"])
def login():
    """
    Connexion d'un utilisateur existant (par username).
    ---
    tags: [Authentification]
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [username, password]
          properties:
            username: {type: string}
            password: {type: string}
    responses:
      200:
        description: Connexion réussie + token JWT
      401:
        description: Username ou mot de passe incorrect
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    user = db.session.query(User).filter(User.username == username).first()
    if not user or not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        return jsonify({"error": "Unauthorized", "message": "Nom d'utilisateur ou mot de passe incorrect."}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({
        "message": "Connexion réussie",
        "user": {"id": user.id, "username": user.username, "email": user.email, "name": user.name, "is_admin": bool(user.is_admin)},
        "access_token": token,
    }), 200


# ─────────────────────────────────────────────
# AUTH: POST /auth/forgot-password
# ─────────────────────────────────────────────
@app.route("/auth/forgot-password", methods=["POST"])
def forgot_password():
    """
    Réinitialise le mot de passe via l'adresse email.
    ---
    tags: [Authentification]
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [email, new_password]
          properties:
            email: {type: string}
            new_password: {type: string}
    responses:
      200:
        description: Mot de passe réinitialisé
      400:
        description: Données invalides
      404:
        description: Email introuvable
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    new_password = data.get("new_password") or ""

    if not email or not new_password:
        abort(400, description="email et new_password sont requis.")
    if len(new_password) < 6:
        abort(400, description="Le mot de passe doit contenir au moins 6 caractères.")

    user = db.session.query(User).filter(User.email == email).first()
    if not user:
        return jsonify({"error": "Not Found", "message": "Aucun compte avec cet email."}), 404

    user.password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    db.session.commit()

    return jsonify({"message": "Mot de passe réinitialisé avec succès. Connectez-vous avec votre nouveau mot de passe."}), 200


# ─────────────────────────────────────────────
# AUTH: GET /auth/me
# ─────────────────────────────────────────────
@app.route("/auth/me", methods=["GET"])
@jwt_required()
def get_me():
    """
    Profil de l'utilisateur connecté.
    ---
    tags: [Authentification]
    security:
      - Bearer: []
    responses:
      200:
        description: Profil utilisateur
    """
    user = db.session.get(User, _get_current_user_id())
    if not user:
        abort(404, description="Utilisateur introuvable.")
    nb_favs = db.session.query(func.count(UserFavorite.id)).filter(UserFavorite.user_id == user.id).scalar()
    nb_alerts = db.session.query(func.count(PriceAlert.id)).filter(PriceAlert.user_id == user.id, PriceAlert.is_active).scalar()
    return jsonify({
        "id": user.id, "username": user.username, "email": user.email, "name": user.name,
        "is_admin": bool(user.is_admin),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "stats": {"favorites": nb_favs, "active_alerts": nb_alerts},
    }), 200


# =============================================================
#  FAVORIS
# =============================================================

@app.route("/me/favorites", methods=["GET"])
@jwt_required()
def list_favorites():
    """
    Liste des produits favoris de l'utilisateur connecté.
    ---
    tags: [Favoris]
    security:
      - Bearer: []
    responses:
      200:
        description: Liste des favoris avec prix actuels
    """
    uid = _get_current_user_id()
    sub = latest_price_subquery()
    results = (
        db.session.query(Product, PriceHistory)
        .join(UserFavorite, UserFavorite.product_id == Product.id)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(UserFavorite.user_id == uid)
        .order_by(Product.name)
        .all()
    )
    data = [product_schema(p, ph) for p, ph in results]
    return jsonify({"favorites": data, "total": len(data)}), 200


@app.route("/me/favorites", methods=["POST"])
@jwt_required()
def add_favorite():
    """
    Ajouter un produit aux favoris.
    ---
    tags: [Favoris]
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [product_id]
          properties:
            product_id: {type: integer}
    responses:
      201:
        description: Favori ajouté
      409:
        description: Déjà en favoris
    """
    uid = _get_current_user_id()
    data = request.get_json(silent=True) or {}
    pid = data.get("product_id")
    if not pid:
        abort(400, description="product_id requis.")
    if not db.session.get(Product, pid):
        abort(404, description=f"Produit #{pid} introuvable.")
    existing = db.session.query(UserFavorite).filter_by(user_id=uid, product_id=pid).first()
    if existing:
        return jsonify({"message": "Déjà en favoris"}), 409
    db.session.add(UserFavorite(user_id=uid, product_id=pid))
    db.session.commit()
    return jsonify({"message": "Favori ajouté", "product_id": pid}), 201


@app.route("/me/favorites/<int:product_id>", methods=["DELETE"])
@jwt_required()
def remove_favorite(product_id):
    """
    Retirer un produit des favoris.
    ---
    tags: [Favoris]
    security:
      - Bearer: []
    parameters:
      - name: product_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Favori supprimé
    """
    uid = _get_current_user_id()
    fav = db.session.query(UserFavorite).filter_by(user_id=uid, product_id=product_id).first()
    if not fav:
        abort(404, description="Ce produit n'est pas dans vos favoris.")
    db.session.delete(fav)
    db.session.commit()
    return jsonify({"message": "Favori supprimé", "product_id": product_id}), 200


# =============================================================
#  ALERTES DE PRIX
# =============================================================

@app.route("/me/alerts", methods=["GET"])
@jwt_required()
def list_alerts():
    """
    Liste des alertes de prix de l'utilisateur.
    ---
    tags: [Alertes]
    security:
      - Bearer: []
    responses:
      200:
        description: Liste des alertes
    """
    uid = _get_current_user_id()
    alerts = (
        db.session.query(PriceAlert, Product)
        .join(Product, PriceAlert.product_id == Product.id)
        .filter(PriceAlert.user_id == uid)
        .order_by(PriceAlert.created_at.desc())
        .all()
    )
    sub = latest_price_subquery()
    data = []
    for alert, product in alerts:
        current_price_row = (
            db.session.query(PriceHistory)
            .join(sub, (PriceHistory.product_id == sub.c.product_id) &
                       (PriceHistory.scraped_at == sub.c.max_scraped_at))
            .filter(PriceHistory.product_id == product.id)
            .first()
        )
        current_price = float(current_price_row.price) if current_price_row else None
        data.append({
            "id": alert.id,
            "product_id": product.id,
            "product_name": product.name,
            "product_image": product.image_url,
            "target_price": float(alert.target_price),
            "current_price": current_price,
            "is_active": alert.is_active,
            "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else None,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        })
    return jsonify({"alerts": data, "total": len(data)}), 200


@app.route("/me/alerts", methods=["POST"])
@jwt_required()
def create_alert():
    """
    Créer une alerte de prix sur un produit.
    ---
    tags: [Alertes]
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [product_id, target_price]
          properties:
            product_id: {type: integer}
            target_price: {type: number, description: "Prix seuil en XOF"}
    responses:
      201:
        description: Alerte créée
    """
    uid = _get_current_user_id()
    data = request.get_json(silent=True) or {}
    pid = data.get("product_id")
    target = data.get("target_price")
    if not pid or not target:
        abort(400, description="product_id et target_price requis.")
    if not db.session.get(Product, pid):
        abort(404, description=f"Produit #{pid} introuvable.")
    try:
        target_f = float(target)
    except (TypeError, ValueError):
        abort(400, description="target_price doit être un nombre.")
    if target_f <= 0:
        abort(400, description="target_price doit être positif.")

    alert = PriceAlert(user_id=uid, product_id=pid, target_price=int(target_f))
    db.session.add(alert)
    db.session.commit()
    return jsonify({
        "message": f"Alerte créée : notification quand le prix passe sous {int(target_f)} XOF",
        "alert_id": alert.id,
    }), 201


@app.route("/me/alerts/<int:alert_id>", methods=["DELETE"])
@jwt_required()
def delete_alert(alert_id):
    """
    Supprimer une alerte de prix.
    ---
    tags: [Alertes]
    security:
      - Bearer: []
    parameters:
      - name: alert_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Alerte supprimée
    """
    uid = _get_current_user_id()
    alert = db.session.query(PriceAlert).filter_by(id=alert_id, user_id=uid).first()
    if not alert:
        abort(404, description="Alerte introuvable.")
    db.session.delete(alert)
    db.session.commit()
    return jsonify({"message": "Alerte supprimée"}), 200


# =============================================================
#  DASHBOARD UTILISATEUR
# =============================================================

@app.route("/me/dashboard", methods=["GET"])
@jwt_required()
def user_dashboard():
    """
    Dashboard personnalisé : favoris, alertes actives, meilleures baisses de la semaine.
    ---
    tags: [Dashboard Utilisateur]
    security:
      - Bearer: []
    responses:
      200:
        description: Données du dashboard
    """
    uid = _get_current_user_id()
    sub = latest_price_subquery()

    # Favoris avec prix
    fav_results = (
        db.session.query(Product, PriceHistory)
        .join(UserFavorite, UserFavorite.product_id == Product.id)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(UserFavorite.user_id == uid)
        .all()
    )
    favorites = [product_schema(p, ph) for p, ph in fav_results]

    # Alertes actives
    active_alerts = (
        db.session.query(PriceAlert, Product)
        .join(Product, PriceAlert.product_id == Product.id)
        .filter(PriceAlert.user_id == uid, PriceAlert.is_active == True)
        .all()
    )
    alerts = []
    for alert, product in active_alerts:
        alerts.append({
            "id": alert.id,
            "product_name": product.name,
            "target_price": float(alert.target_price),
            "product_id": product.id,
        })

    # Top baisses de la semaine (tous produits)
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    drops = []
    products_with_history = (
        db.session.query(Product)
        .join(PriceHistory)
        .filter(PriceHistory.scraped_at >= one_week_ago)
        .group_by(Product.id)
        .having(func.count(PriceHistory.id) >= 2)
        .limit(50)
        .all()
    )
    for product in products_with_history:
        snapshots = (
            db.session.query(PriceHistory)
            .filter(PriceHistory.product_id == product.id)
            .order_by(PriceHistory.scraped_at.desc())
            .limit(2)
            .all()
        )
        if len(snapshots) >= 2:
            latest = float(snapshots[0].price)
            previous = float(snapshots[1].price)
            if previous > 0 and latest < previous:
                pct = round((latest - previous) / previous * 100, 1)
                drops.append({
                    "product_id": product.id,
                    "name": product.name,
                    "image_url": product.image_url,
                    "price_before": previous,
                    "price_after": latest,
                    "drop_pct": abs(pct),
                    "savings": round(previous - latest),
                })
    drops.sort(key=lambda x: x["drop_pct"], reverse=True)

    return jsonify({
        "favorites": favorites,
        "active_alerts": alerts,
        "weekly_drops": drops[:10],
        "stats": {
            "nb_favorites": len(favorites),
            "nb_active_alerts": len(alerts),
            "nb_weekly_drops": len(drops),
        },
    }), 200


# =============================================================
#  PRÉFÉRENCES & RECOMMANDATIONS « POUR VOUS »
# =============================================================

_ALLOWED_RECOMMENDATION_SOURCES = frozenset({"jumia_ci", "djokstore_ci"})


def _distinct_categories_in_db():
    return {r[0] for r in db.session.query(Product.category).distinct().all() if r[0]}


def _preference_payload(pref: UserPreference | None) -> dict:
    if not pref:
        return {
            "configured": False,
            "categories": [],
            "budget_min": None,
            "budget_max": None,
            "sources": None,
            "updated_at": None,
        }
    cats = pref.categories or []
    configured = bool(cats) and len(cats) > 0
    return {
        "configured": configured,
        "categories": cats,
        "budget_min": pref.budget_min,
        "budget_max": pref.budget_max,
        "sources": pref.sources,
        "updated_at": pref.updated_at.isoformat() if pref.updated_at else None,
    }


@app.route("/me/preferences", methods=["GET"])
@jwt_required()
def get_preferences():
    """
    Lit les préférences de recommandation (optionnel).
    ---
    tags: [Recommandations]
    security:
      - Bearer: []
    responses:
      200:
        description: Préférences courantes
    """
    uid = _get_current_user_id()
    pref = db.session.query(UserPreference).filter_by(user_id=uid).first()
    return jsonify(_preference_payload(pref)), 200


@app.route("/me/preferences", methods=["PUT"])
@jwt_required()
def put_preferences():
    """
    Enregistre les préférences pour « Pour vous » (remplace l'enregistrement existant).
    ---
    tags: [Recommandations]
    security:
      - Bearer: []
    """
    uid = _get_current_user_id()
    data = request.get_json(silent=True) or {}

    raw_cats = data.get("categories")
    if raw_cats is None:
        abort(400, description="categories requis (liste, peut être vide pour effacer).")
    if not isinstance(raw_cats, list):
        abort(400, description="categories doit être une liste de slugs.")
    if len(raw_cats) > 6:
        abort(400, description="Maximum 6 catégories.")

    known = _distinct_categories_in_db()
    cats_clean = []
    for c in raw_cats:
        if not isinstance(c, str):
            abort(400, description="Chaque catégorie doit être une chaîne.")
        s = c.strip()
        if not s:
            continue
        if len(s) > 60:
            abort(400, description="Slug de catégorie trop long.")
        if known and s not in known:
            abort(400, description=f"Catégorie inconnue : {s}")
        if s not in cats_clean:
            cats_clean.append(s)

    budget_min = data.get("budget_min")
    budget_max = data.get("budget_max")
    if budget_min is not None or budget_max is not None:
        try:
            bmin = int(budget_min) if budget_min is not None else None
            bmax = int(budget_max) if budget_max is not None else None
        except (TypeError, ValueError):
            abort(400, description="budget_min et budget_max doivent être des entiers.")
        if bmin is not None and bmin < 0:
            abort(400, description="budget_min invalide.")
        if bmax is not None and bmax < 0:
            abort(400, description="budget_max invalide.")
        if bmin is not None and bmax is not None and bmin > bmax:
            abort(400, description="budget_min ne peut pas dépasser budget_max.")
    else:
        bmin, bmax = None, None

    raw_sources = data.get("sources")
    src_clean = None
    if raw_sources is not None:
        if not isinstance(raw_sources, list):
            abort(400, description="sources doit être une liste (ex: [\"jumia_ci\"]) ou null.")
        src_clean = []
        for s in raw_sources:
            if s not in _ALLOWED_RECOMMENDATION_SOURCES:
                abort(400, description=f"Source inconnue : {s}")
            if s not in src_clean:
                src_clean.append(s)
        if not src_clean:
            src_clean = None

    pref = db.session.query(UserPreference).filter_by(user_id=uid).first()
    if not pref:
        pref = UserPreference(user_id=uid, categories=cats_clean, budget_min=bmin, budget_max=bmax, sources=src_clean)
        db.session.add(pref)
    else:
        pref.categories = cats_clean
        pref.budget_min = bmin
        pref.budget_max = bmax
        pref.sources = src_clean
    db.session.commit()
    db.session.refresh(pref)
    return jsonify({"message": "Préférences enregistrées.", **_preference_payload(pref)}), 200


@app.route("/me/recommendations", methods=["GET"])
@jwt_required()
def get_recommendations():
    """
    Produits recommandés selon les préférences (promotions d'abord, puis prix croissant).
    ---
    tags: [Recommandations]
    security:
      - Bearer: []
    parameters:
      - name: limit
        in: query
        type: integer
        default: 12
    responses:
      200:
        description: Liste de produits ou configured=false
    """
    uid = _get_current_user_id()
    try:
        limit = min(50, max(1, int(request.args.get("limit", 12))))
    except ValueError:
        limit = 12

    pref = db.session.query(UserPreference).filter_by(user_id=uid).first()
    if not pref or not (pref.categories or []):
        return jsonify({
            "configured": False,
            "products": [],
            "total": 0,
            "message": "Complétez vos préférences dans Mon espace pour voir des suggestions.",
        }), 200

    cats = pref.categories or []
    bmin = pref.budget_min if pref.budget_min is not None else 0
    bmax = pref.budget_max if pref.budget_max is not None else 9_999_999_999

    fav_ids = [
        r[0] for r in db.session.query(UserFavorite.product_id).filter(UserFavorite.user_id == uid).all()
    ]

    sub = latest_price_subquery()
    query = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
        .filter(Product.category.in_(cats))
        .filter(PriceHistory.price >= bmin, PriceHistory.price <= bmax)
    )
    if pref.sources:
        query = query.filter(Product.source.in_(pref.sources))
    if fav_ids:
        query = query.filter(~Product.id.in_(fav_ids))

    promo_rank = case((PriceHistory.discount_pct.isnot(None), 0), else_=1)
    query = query.order_by(
        promo_rank,
        PriceHistory.discount_pct.desc().nullslast(),
        PriceHistory.price.asc(),
    )

    total = query.count()
    results = query.limit(limit).all()
    products = [product_schema(p, ph) for p, ph in results]

    return jsonify({
        "configured": True,
        "products": products,
        "total": total,
        "limit": limit,
        "filters": {
            "categories": cats,
            "budget_min": pref.budget_min,
            "budget_max": pref.budget_max,
            "sources": pref.sources,
        },
    }), 200


# ─────────────────────────────────────────────
# 9. POST /scrape  (synchrone — Bronze)
# ─────────────────────────────────────────────
@app.route("/scrape", methods=["POST"])
@admin_required
def scrape_sync():
    """
    Lance le scraping de manière synchrone (bloquant).
    ---
    tags: [Scraping]
    responses:
      200:
        description: Scraping terminé avec succès
      500:
        description: Erreur pendant le scraping
    """
    import subprocess
    from pathlib import Path

    scraper_dir = Path(__file__).parent.parent / "scraper"
    raw_data_path = scraper_dir / "raw_data.json"

    try:
        result = subprocess.run(
            ["scrapy", "crawl", "jumia_ci"],
            cwd=str(scraper_dir),
            capture_output=True,
            text=True,
            timeout=3600,
        )

        if result.returncode != 0:
            return jsonify({
                "status": "error",
                "message": "Le scraping a échoué",
                "stderr": result.stderr[:500],
            }), 500

        nb_items = 0
        if raw_data_path.exists():
            with open(raw_data_path, encoding="utf-8") as f:
                nb_items = len(json.load(f))

        return jsonify({
            "status": "ok",
            "message": f"Scraping terminé : {nb_items} items récupérés",
            "raw_items": nb_items,
        }), 200

    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "Timeout dépassé (1h)"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────
# 10. POST /scrape/async  (Celery — Argent)
# ─────────────────────────────────────────────
@app.route("/scrape/async", methods=["POST"])
@admin_required
def scrape_async():
    """
    Lance le pipeline complet de scraping via Celery (non-bloquant).
    Retourne un task_id pour suivre l'avancement.
    ---
    tags: [Scraping]
    responses:
      202:
        description: Tâche lancée avec succès
        schema:
          properties:
            status:
              type: string
            task_id:
              type: string
            check_url:
              type: string
      500:
        description: Celery indisponible
    """
    try:
        from tasks.tasks import full_pipeline
        result = full_pipeline.delay()
        return jsonify({
            "status": "accepted",
            "message": "Pipeline de scraping lancé en arrière-plan",
            "task_id": result.id,
            "check_url": f"/tasks/{result.id}/status",
        }), 202
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Impossible de lancer la tâche Celery : {e}",
        }), 500


# ─────────────────────────────────────────────
# 11. GET /tasks/<task_id>/status  (Argent)
# ─────────────────────────────────────────────
@app.route("/tasks/<string:task_id>/status", methods=["GET"])
@admin_required
def task_status(task_id):
    """
    Vérifie le statut d'une tâche Celery.
    ---
    tags: [Scraping]
    parameters:
      - name: task_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Statut de la tâche
    """
    try:
        from tasks.celery_app import celery_app as celery
        result = celery.AsyncResult(task_id)

        response = {
            "task_id": task_id,
            "status": result.status,
            "ready": result.ready(),
        }

        if result.ready():
            if result.successful():
                response["result"] = result.result
            else:
                response["error"] = str(result.result)

        return jsonify(response), 200
    except Exception:
        return jsonify({"task_id": task_id, "status": "UNKNOWN", "error": "Celery indisponible"}), 503


# ─────────────────────────────────────────────
# 12. GET /export  (Feature avancée — Or)
# ─────────────────────────────────────────────
@app.route("/export", methods=["GET"])
@jwt_required()
def export_data():
    """
    Exporte les données en CSV, Excel ou JSON.
    ---
    tags: [Export]
    parameters:
      - name: format
        in: query
        type: string
        enum: [csv, excel, json]
        default: csv
      - name: category
        in: query
        type: string
        description: Filtrer par catégorie (optionnel)
    responses:
      200:
        description: Fichier téléchargeable
      400:
        description: Format non supporté
    """
    fmt = request.args.get("format", "csv").lower()
    if fmt not in ("csv", "excel", "json"):
        abort(400, description="Formats supportés : csv, excel, json")

    sub = latest_price_subquery()
    query = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(PriceHistory, (PriceHistory.product_id == sub.c.product_id) &
                            (PriceHistory.scraped_at == sub.c.max_scraped_at))
    )

    if cat := request.args.get("category"):
        query = query.filter(Product.category == cat)

    query = query.order_by(Product.category, PriceHistory.price.asc())
    results = query.all()

    rows = []
    for p, ph in results:
        rows.append({
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "price": float(ph.price) if ph.price else 0,
            "old_price": float(ph.old_price) if ph.old_price else "",
            "discount_pct": float(ph.discount_pct) if ph.discount_pct else "",
            "currency": p.currency,
            "reviews_count": ph.reviews_count,
            "product_url": p.product_url,
            "image_url": p.image_url or "",
            "scraped_at": ph.scraped_at.isoformat() if ph.scraped_at else "",
        })

    if fmt == "json":
        return jsonify({"products": rows, "total": len(rows)}), 200

    if fmt == "csv":
        if not rows:
            return Response("", mimetype="text/csv",
                            headers={"Content-Disposition": "attachment;filename=jumia_export.csv"})
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=jumia_export.csv"},
        )

    if fmt == "excel":
        try:
            import pandas as pd
            df = pd.DataFrame(rows)
            output = io.BytesIO()
            df.to_excel(output, index=False, sheet_name="Produits Jumia CI")
            output.seek(0)
            return send_file(
                output,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name="jumia_export.xlsx",
            )
        except ImportError:
            abort(400, description="openpyxl requis pour l'export Excel. Utilisez format=csv.")


# ─────────────────────────────────────────────
# Gestion des erreurs
# ─────────────────────────────────────────────
@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad Request", "message": str(e.description)}), 400

@app.errorhandler(403)
def forbidden(e):
    return jsonify({"error": "Forbidden", "message": str(e.description)}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not Found", "message": str(e.description)}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


# ─────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")