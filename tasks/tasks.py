"""
tasks.py — Tâches Celery
Comparateur de Prix Jumia CI — ENSEA AS Data Science

Tâches disponibles :
  scrape_jumia          → lance le spider Scrapy
  clean_and_insert      → nettoie raw_data.json et insère en base
  full_pipeline         → scrape + clean + insert (tâche principale)
  check_price_drops     → détecte les baisses de prix > seuil
"""

import os
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from celery import chain
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tasks.celery_app import celery_app

# Import du cleaner et des modèles
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.cleaner import load_raw_data, clean_dataframe
from api.models import Product, PriceHistory

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
logger = logging.getLogger(__name__)

DATABASE_URL  = os.getenv("DATABASE_URL", "postgresql://jumia_user:jumia_pass@localhost:5432/jumia_db")
SCRAPER_DIR   = Path(__file__).parent.parent / "scraper"
RAW_DATA_PATH = SCRAPER_DIR / "raw_data.json"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# ─────────────────────────────────────────────
# TÂCHE 1 : Scraping Scrapy
# ─────────────────────────────────────────────
@celery_app.task(
    bind=True,
    name="tasks.scrape_jumia",
    max_retries=2,
    default_retry_delay=300,   # réessaie après 5 min si ça plante
)
def scrape_jumia(self):
    """
    Lance le spider Scrapy et produit raw_data.json.
    Retourne le chemin du fichier généré.
    """
    logger.info("[scrape_jumia] Démarrage du scraping Jumia CI...")

    try:
        result = subprocess.run(
            ["scrapy", "crawl", "jumia_ci"],
            cwd=str(SCRAPER_DIR),
            capture_output=True,
            text=True,
            timeout=3600,    # max 1h
        )

        if result.returncode != 0:
            logger.error(f"[scrape_jumia] Erreur Scrapy :\n{result.stderr}")
            raise RuntimeError(f"Scrapy a échoué (code {result.returncode})")

        if not RAW_DATA_PATH.exists():
            raise FileNotFoundError(f"raw_data.json introuvable après scraping : {RAW_DATA_PATH}")

        # Compte le nombre d'items récupérés
        with open(RAW_DATA_PATH, encoding="utf-8") as f:
            nb_items = len(json.load(f))

        logger.info(f"[scrape_jumia] Scraping terminé : {nb_items} items dans raw_data.json")
        return {"status": "ok", "raw_items": nb_items, "path": str(RAW_DATA_PATH)}

    except subprocess.TimeoutExpired:
        logger.error("[scrape_jumia] Timeout dépassé (1h)")
        raise self.retry(countdown=600)

    except Exception as exc:
        logger.error(f"[scrape_jumia] Erreur inattendue : {exc}")
        raise self.retry(exc=exc, countdown=300)


# ─────────────────────────────────────────────
# TÂCHE 2 : Nettoyage + Insertion en base
# ─────────────────────────────────────────────
@celery_app.task(
    bind=True,
    name="tasks.clean_and_insert",
    max_retries=3,
    default_retry_delay=60,
)
def clean_and_insert(self, scrape_result=None):
    """
    1. Charge raw_data.json
    2. Nettoie avec cleaner.py
    3. Insère/met à jour la base PostgreSQL

    Stratégie d'insertion :
      - Si le produit (product_url) existe déjà → on ajoute juste un snapshot prix
      - Si le produit est nouveau → on l'insère + premier snapshot prix
    """
    logger.info("[clean_and_insert] Démarrage nettoyage et insertion...")

    try:
        # 1. Chargement et nettoyage
        df_raw   = load_raw_data(str(RAW_DATA_PATH))
        df_clean = clean_dataframe(df_raw)
        logger.info(f"[clean_and_insert] {len(df_clean)} items propres à insérer")

        scraped_at = datetime.now(timezone.utc)
        nb_new     = 0
        nb_updated = 0

        # 2. Insertion en base
        with Session(engine) as session:
            for _, row in df_clean.iterrows():
                # Cherche si le produit existe déjà
                product = session.execute(
                    select(Product).where(Product.product_url == row["product_url"])
                ).scalar_one_or_none()

                # Nouveau produit → insertion
                if product is None:
                    product = Product(
                        product_url = row["product_url"],
                        name        = row["name"],
                        category    = row["category"],
                        currency    = row.get("currency", "XOF"),
                        image_url   = row.get("image_url"),
                        page_url    = row.get("page_url"),
                    )
                    session.add(product)
                    session.flush()   # génère l'id avant d'insérer le snapshot
                    nb_new += 1
                else:
                    # Produit existant → met à jour le nom si changé
                    product.name = row["name"]
                    nb_updated += 1

                # Snapshot de prix (toujours inséré, même si le produit existait)
                snapshot = PriceHistory(
                    product_id    = product.id,
                    price         = int(row["price"]),
                    old_price     = int(row["old_price"]) if row["old_price"] else None,
                    discount_pct  = float(row["discount_pct"]) if row["discount_pct"] else None,
                    reviews_count = int(row.get("reviews_count", 0)),
                    scraped_at    = scraped_at,
                )
                session.add(snapshot)

            session.commit()

        logger.info(
            f"[clean_and_insert] Insertion terminée — "
            f"{nb_new} nouveaux produits, {nb_updated} mis à jour"
        )
        return {
            "status":     "ok",
            "new":        nb_new,
            "updated":    nb_updated,
            "total":      nb_new + nb_updated,
            "scraped_at": scraped_at.isoformat(),
        }

    except Exception as exc:
        logger.error(f"[clean_and_insert] Erreur : {exc}")
        raise self.retry(exc=exc, countdown=60)


# ─────────────────────────────────────────────
# TÂCHE 3 : Pipeline complet (scrape → clean → insert)
# ─────────────────────────────────────────────
@celery_app.task(name="tasks.full_pipeline")
def full_pipeline():
    """
    Lance le pipeline complet dans l'ordre :
      scrape_jumia → clean_and_insert

    Utilise chain() de Celery pour chaîner les tâches :
    le résultat de scrape_jumia est passé à clean_and_insert.
    """
    logger.info("[full_pipeline] Lancement du pipeline complet...")
    pipeline = chain(scrape_jumia.s(), clean_and_insert.s())
    result   = pipeline.apply_async()
    logger.info(f"[full_pipeline] Pipeline lancé — task_id={result.id}")
    return {"status": "started", "task_id": result.id}


# ─────────────────────────────────────────────
# TÂCHE 4 : Détection des baisses de prix
# ─────────────────────────────────────────────
@celery_app.task(name="tasks.check_price_drops")
def check_price_drops(threshold_pct: float = 10.0):
    """
    Détecte les produits dont le prix a baissé de plus de `threshold_pct` %
    entre l'avant-dernier et le dernier scrape.

    Utile pour : alertes, dashboard, mise en avant des bonnes affaires.
    Retourne la liste des produits concernés.
    """
    logger.info(f"[check_price_drops] Recherche des baisses > {threshold_pct}%...")
    drops = []

    with Session(engine) as session:
        # Récupère tous les produits qui ont au moins 2 snapshots
        products = session.execute(select(Product)).scalars().all()

        for product in products:
            # 2 derniers snapshots triés par date décroissante
            snapshots = (
                session.execute(
                    select(PriceHistory)
                    .where(PriceHistory.product_id == product.id)
                    .order_by(PriceHistory.scraped_at.desc())
                    .limit(2)
                )
                .scalars()
                .all()
            )

            if len(snapshots) < 2:
                continue

            last_price = float(snapshots[0].price)
            prev_price = float(snapshots[1].price)

            if prev_price <= 0:
                continue

            variation_pct = (last_price - prev_price) / prev_price * 100

            if variation_pct <= -threshold_pct:
                drops.append({
                    "product_id":    product.id,
                    "name":          product.name,
                    "category":      product.category,
                    "product_url":   product.product_url,
                    "price_before":  prev_price,
                    "price_after":   last_price,
                    "drop_pct":      round(abs(variation_pct), 2),
                    "scraped_at":    snapshots[0].scraped_at.isoformat(),
                })

    # Trie par baisse décroissante (les plus grosses baisses en premier)
    drops.sort(key=lambda x: x["drop_pct"], reverse=True)
    logger.info(f"[check_price_drops] {len(drops)} produits avec baisse > {threshold_pct}%")
    return {"drops": drops, "count": len(drops), "threshold_pct": threshold_pct}