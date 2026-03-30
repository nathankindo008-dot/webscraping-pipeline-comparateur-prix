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
import sys
import os
os.environ.setdefault("PYTHONUTF8", "1")

import io
import csv
from flask import Flask, jsonify, request, abort, Response, send_file, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from flasgger import Swagger
from prometheus_flask_exporter import PrometheusMetrics

from models import Base, Product, PriceHistory
from schemas import (
    product_schema, product_detail_schema,
    price_history_schema, compare_schema, category_schema
)

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

db = SQLAlchemy(app, model_class=Base)

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


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

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
# 0. GET / — Frontend Web
# ─────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    """Page d'accueil — Dashboard interactif."""
    return render_template("index.html")


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
    except Exception as e:
        return jsonify({"status": "error", "database": str(e)}), 503


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
    if min_p := request.args.get("min_price"):
        query = query.filter(PriceHistory.price >= float(min_p))
    if max_p := request.args.get("max_price"):
        query = query.filter(PriceHistory.price <= float(max_p))
    if request.args.get("discount", "").lower() == "true":
        query = query.filter(PriceHistory.discount_pct.isnot(None))

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

    # Trier dans l'ordre demandé
    order_map = {p.id: i for i, p in enumerate([r[0] for r in results])}
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
        "product_url": product.product_url,
        "history":     history,
        "nb_snapshots": len(history),
        "price_variation_pct": variation,  # positif = hausse, négatif = baisse
    }), 200


# ─────────────────────────────────────────────
# 8. GET /search
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


# ─────────────────────────────────────────────
# 9. POST /scrape  (synchrone — Bronze)
# ─────────────────────────────────────────────
@app.route("/scrape", methods=["POST"])
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

        import json
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
    except Exception as e:
        return jsonify({"task_id": task_id, "status": "UNKNOWN", "error": str(e)}), 200


# ─────────────────────────────────────────────
# 12. GET /export  (Feature avancée — Or)
# ─────────────────────────────────────────────
@app.route("/export", methods=["GET"])
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