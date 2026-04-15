"""
tasks.py — Tâches Celery
Comparateur de Prix Jumia CI — ENSEA AS Data Science

Tâches disponibles :
  scrape_jumia          → lance le spider Scrapy
  clean_and_insert      → nettoie raw_data.json et insère en base
  full_pipeline         → scrape + clean + insert (tâche principale)
  check_price_drops     → détecte les baisses de prix > seuil
"""

import math
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

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.cleaner import load_raw_data, clean_dataframe
from api.models import Product, PriceHistory, User, PriceAlert, ScrapeLog, ProductMatch

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
logger = logging.getLogger(__name__)

DATABASE_URL  = os.getenv("DATABASE_URL", "postgresql://jumia_user:jumia_pass@localhost:5433/jumia_db")
SCRAPER_DIR   = Path(__file__).parent.parent / "scraper"
RAW_DATA_PATH = SCRAPER_DIR / "raw_data.json"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def _safe_int(val, default=0):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return int(val)


def _safe_float(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return float(val)


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
    t0 = datetime.now(timezone.utc)

    try:
        result = subprocess.run(
            ["scrapy", "crawl", "jumia_ci"],
            cwd=str(SCRAPER_DIR),
            capture_output=True,
            text=True,
            timeout=3600,
        )

        if result.returncode != 0:
            logger.error(f"[scrape_jumia] Erreur Scrapy :\n{result.stderr}")
            raise RuntimeError(f"Scrapy a échoué (code {result.returncode})")

        if not RAW_DATA_PATH.exists():
            raise FileNotFoundError(f"raw_data.json introuvable après scraping : {RAW_DATA_PATH}")

        with open(RAW_DATA_PATH, encoding="utf-8") as f:
            nb_items = len(json.load(f))

        logger.info(f"[scrape_jumia] Scraping terminé : {nb_items} items dans raw_data.json")
        return {"status": "ok", "raw_items": nb_items, "path": str(RAW_DATA_PATH), "_t0": t0.isoformat()}

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

        if len(df_clean) == 0:
            logger.warning("[clean_and_insert] Aucun item à insérer — scraping probablement vide")
            return {"status": "empty", "new": 0, "updated": 0, "total": 0}

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
                        source      = row.get("source", "jumia_ci"),
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

                snapshot = PriceHistory(
                    product_id    = product.id,
                    price         = _safe_int(row["price"]),
                    old_price     = _safe_int(row["old_price"], default=None) if _safe_float(row["old_price"]) else None,
                    discount_pct  = _safe_float(row["discount_pct"]),
                    reviews_count = _safe_int(row.get("reviews_count", 0)),
                    scraped_at    = scraped_at,
                )
                session.add(snapshot)

            session.commit()

        logger.info(
            f"[clean_and_insert] Insertion terminée — "
            f"{nb_new} nouveaux produits, {nb_updated} mis à jour"
        )

        t1 = datetime.now(timezone.utc)
        t0 = datetime.fromisoformat(scrape_result.get("_t0", t1.isoformat())) if scrape_result else t1
        duration = round((t1 - t0).total_seconds(), 1)

        with Session(engine) as session:
            log = ScrapeLog(
                source="jumia_ci", status="success",
                items_raw=scrape_result.get("raw_items", 0) if scrape_result else len(df_raw),
                items_clean=len(df_clean), items_new=nb_new, items_updated=nb_updated,
                duration_sec=duration, started_at=t0, finished_at=t1,
            )
            session.add(log)
            session.commit()

        return {
            "status":     "ok",
            "new":        nb_new,
            "updated":    nb_updated,
            "total":      nb_new + nb_updated,
            "scraped_at": scraped_at.isoformat(),
        }

    except Exception as exc:
        logger.error(f"[clean_and_insert] Erreur : {exc}")
        try:
            with Session(engine) as session:
                session.add(ScrapeLog(source="jumia_ci", status="error", error_msg=str(exc)[:500]))
                session.commit()
        except Exception:
            pass
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
    logger.info("[full_pipeline] Lancement du pipeline complet (Jumia + DjokStore + CoinAfrique)...")
    pipeline = chain(scrape_jumia.s(), clean_and_insert.s())
    result   = pipeline.apply_async()
    scrape_djokstore.delay()
    scrape_coinafrique.delay()
    logger.info(f"[full_pipeline] Pipelines lancés — jumia_task={result.id}")
    return {"status": "started", "task_id": result.id}


# ─────────────────────────────────────────────
# TÂCHE 3b : Scraping DjokStore.ci
# ─────────────────────────────────────────────
DJOKSTORE_RAW_PATH = SCRAPER_DIR / "raw_data_djokstore.json"


@celery_app.task(
    bind=True,
    name="tasks.scrape_djokstore",
    max_retries=2,
    default_retry_delay=300,
)
def scrape_djokstore(self):
    """Lance le spider DjokStore.ci → raw_data_djokstore.json → clean → insert."""
    logger.info("[scrape_djokstore] Démarrage du scraping DjokStore.ci...")
    t0 = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            ["scrapy", "crawl", "djokstore_ci"],
            cwd=str(SCRAPER_DIR),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0:
            logger.error(f"[scrape_djokstore] Erreur Scrapy :\n{result.stderr}")
            raise RuntimeError(f"Scrapy DjokStore a échoué (code {result.returncode})")

        if not DJOKSTORE_RAW_PATH.exists():
            raise FileNotFoundError(f"raw_data_djokstore.json introuvable : {DJOKSTORE_RAW_PATH}")

        with open(DJOKSTORE_RAW_PATH, encoding="utf-8") as f:
            nb_items = len(json.load(f))

        logger.info(f"[scrape_djokstore] Scraping terminé : {nb_items} items")

        df_raw = load_raw_data(str(DJOKSTORE_RAW_PATH))
        df_clean = clean_dataframe(df_raw)
        logger.info(f"[scrape_djokstore] {len(df_clean)} items nettoyés à insérer")

        scraped_at = datetime.now(timezone.utc)
        nb_new = 0
        nb_updated = 0

        with Session(engine) as session:
            for _, row in df_clean.iterrows():
                product = session.execute(
                    select(Product).where(Product.product_url == row["product_url"])
                ).scalar_one_or_none()

                if product is None:
                    product = Product(
                        product_url=row["product_url"],
                        name=row["name"],
                        category=row["category"],
                        source=row.get("source", "djokstore_ci"),
                        currency=row.get("currency", "XOF"),
                        image_url=row.get("image_url"),
                        page_url=row.get("page_url"),
                    )
                    session.add(product)
                    session.flush()
                    nb_new += 1
                else:
                    product.name = row["name"]
                    nb_updated += 1

                snapshot = PriceHistory(
                    product_id=product.id,
                    price=_safe_int(row["price"]),
                    old_price=_safe_int(row["old_price"], default=None) if _safe_float(row["old_price"]) else None,
                    discount_pct=_safe_float(row["discount_pct"]),
                    reviews_count=_safe_int(row.get("reviews_count", 0)),
                    scraped_at=scraped_at,
                )
                session.add(snapshot)
            session.commit()

        t1 = datetime.now(timezone.utc)
        duration = round((t1 - t0).total_seconds(), 1)

        with Session(engine) as ses:
            ses.add(ScrapeLog(
                source="djokstore_ci", status="success",
                items_raw=nb_items, items_clean=len(df_clean),
                items_new=nb_new, items_updated=nb_updated,
                duration_sec=duration, started_at=t0, finished_at=t1,
            ))
            ses.commit()

        logger.info(f"[scrape_djokstore] {nb_new} nouveaux, {nb_updated} mis à jour")
        return {"status": "ok", "source": "djokstore_ci", "new": nb_new, "updated": nb_updated}

    except Exception as exc:
        logger.error(f"[scrape_djokstore] Erreur : {exc}")
        try:
            with Session(engine) as ses:
                ses.add(ScrapeLog(source="djokstore_ci", status="error", error_msg=str(exc)[:500]))
                ses.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=300)


# ─────────────────────────────────────────────
# TÂCHE 3c : Scraping CoinAfrique.com CI
# ─────────────────────────────────────────────
COINAFRIQUE_RAW_PATH = SCRAPER_DIR / "raw_data_coinafrique.json"


@celery_app.task(
    bind=True,
    name="tasks.scrape_coinafrique",
    max_retries=2,
    default_retry_delay=300,
)
def scrape_coinafrique(self):
    """Lance le spider CoinAfrique CI → raw_data_coinafrique.json → clean → insert."""
    logger.info("[scrape_coinafrique] Démarrage du scraping CoinAfrique CI...")
    t0 = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            ["scrapy", "crawl", "coinafrique_ci"],
            cwd=str(SCRAPER_DIR),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0:
            logger.error(f"[scrape_coinafrique] Erreur Scrapy :\n{result.stderr}")
            raise RuntimeError(f"Scrapy CoinAfrique a échoué (code {result.returncode})")

        if not COINAFRIQUE_RAW_PATH.exists():
            raise FileNotFoundError(f"raw_data_coinafrique.json introuvable : {COINAFRIQUE_RAW_PATH}")

        with open(COINAFRIQUE_RAW_PATH, encoding="utf-8") as f:
            nb_items = len(json.load(f))

        logger.info(f"[scrape_coinafrique] Scraping terminé : {nb_items} items")

        df_raw = load_raw_data(str(COINAFRIQUE_RAW_PATH))
        df_clean = clean_dataframe(df_raw)
        logger.info(f"[scrape_coinafrique] {len(df_clean)} items nettoyés à insérer")

        scraped_at = datetime.now(timezone.utc)
        nb_new = 0
        nb_updated = 0

        with Session(engine) as session:
            for _, row in df_clean.iterrows():
                product = session.execute(
                    select(Product).where(Product.product_url == row["product_url"])
                ).scalar_one_or_none()

                if product is None:
                    product = Product(
                        product_url=row["product_url"],
                        name=row["name"],
                        category=row["category"],
                        source=row.get("source", "coinafrique_ci"),
                        currency=row.get("currency", "XOF"),
                        image_url=row.get("image_url"),
                        page_url=row.get("page_url"),
                    )
                    session.add(product)
                    session.flush()
                    nb_new += 1
                else:
                    product.name = row["name"]
                    nb_updated += 1

                snapshot = PriceHistory(
                    product_id=product.id,
                    price=_safe_int(row["price"]),
                    old_price=_safe_int(row["old_price"], default=None) if _safe_float(row["old_price"]) else None,
                    discount_pct=_safe_float(row["discount_pct"]),
                    reviews_count=_safe_int(row.get("reviews_count", 0)),
                    scraped_at=scraped_at,
                )
                session.add(snapshot)
            session.commit()

        t1 = datetime.now(timezone.utc)
        duration = round((t1 - t0).total_seconds(), 1)

        with Session(engine) as ses:
            ses.add(ScrapeLog(
                source="coinafrique_ci", status="success",
                items_raw=nb_items, items_clean=len(df_clean),
                items_new=nb_new, items_updated=nb_updated,
                duration_sec=duration, started_at=t0, finished_at=t1,
            ))
            ses.commit()

        logger.info(f"[scrape_coinafrique] {nb_new} nouveaux, {nb_updated} mis à jour")
        return {"status": "ok", "source": "coinafrique_ci", "new": nb_new, "updated": nb_updated}

    except Exception as exc:
        logger.error(f"[scrape_coinafrique] Erreur : {exc}")
        try:
            with Session(engine) as ses:
                ses.add(ScrapeLog(source="coinafrique_ci", status="error", error_msg=str(exc)[:500]))
                ses.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=300)


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

    drops.sort(key=lambda x: x["drop_pct"], reverse=True)
    logger.info(f"[check_price_drops] {len(drops)} produits avec baisse > {threshold_pct}%")
    return {"drops": drops, "count": len(drops), "threshold_pct": threshold_pct}


# ─────────────────────────────────────────────
# TÂCHE 5 : Vérification des alertes prix utilisateurs
# ─────────────────────────────────────────────
@celery_app.task(name="tasks.check_price_alerts")
def check_price_alerts():
    """
    Parcourt toutes les alertes actives.
    Si le prix actuel d'un produit est <= target_price, envoie un email
    à l'utilisateur et marque l'alerte comme triggered.
    """
    logger.info("[check_price_alerts] Vérification des alertes utilisateurs...")
    triggered_count = 0

    with Session(engine) as session:
        active_alerts = (
            session.execute(
                select(PriceAlert)
                .where(PriceAlert.is_active == True)
            )
            .scalars()
            .all()
        )

        for alert in active_alerts:
            latest_snapshot = (
                session.execute(
                    select(PriceHistory)
                    .where(PriceHistory.product_id == alert.product_id)
                    .order_by(PriceHistory.scraped_at.desc())
                    .limit(1)
                )
                .scalar_one_or_none()
            )

            if not latest_snapshot:
                continue

            current_price = float(latest_snapshot.price)
            target = float(alert.target_price)

            if current_price <= target:
                product = session.execute(
                    select(Product).where(Product.id == alert.product_id)
                ).scalar_one_or_none()
                user = session.execute(
                    select(User).where(User.id == alert.user_id)
                ).scalar_one_or_none()

                if user and product:
                    try:
                        send_alert_email(
                            to_email=user.email,
                            user_name=user.name,
                            product_name=product.name,
                            product_url=product.product_url,
                            current_price=current_price,
                            target_price=target,
                            image_url=product.image_url,
                            source=getattr(product, "source", "jumia_ci"),
                        )
                        alert.is_active = False
                        alert.triggered_at = datetime.now(timezone.utc)
                        triggered_count += 1
                        logger.info(
                            f"[check_price_alerts] Alerte déclenchée : "
                            f"{product.name} à {current_price} XOF → {user.email}"
                        )
                    except Exception as e:
                        logger.error(f"[check_price_alerts] Erreur envoi email {user.email}: {e}")

        session.commit()

    logger.info(f"[check_price_alerts] {triggered_count} alertes déclenchées")
    return {"triggered": triggered_count, "total_active": len(active_alerts)}


# ─────────────────────────────────────────────
# TÂCHE 6 : Matching cross-source
# ─────────────────────────────────────────────
@celery_app.task(name="tasks.match_cross_source")
def match_cross_source(min_similarity: float = 0.45):
    """
    Fuzzy-match des produits entre toutes les sources (Jumia, DjokStore, CoinAfrique).
    Compare les noms des produits après normalisation.
    """
    from difflib import SequenceMatcher
    import re as _re
    logger.info("[match_cross_source] Démarrage du matching cross-source...")

    def _normalize(name):
        name = name.lower().strip()
        name = _re.sub(r"[^a-z0-9àâéèêëïîôùûüç\s]", " ", name)
        noise = {"pour", "avec", "les", "des", "une", "le", "la", "de", "du", "en", "et"}
        return " ".join(w for w in name.split() if w not in noise and len(w) > 1)

    sources = ["jumia_ci", "djokstore_ci", "coinafrique_ci"]
    source_pairs = []
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            source_pairs.append((sources[i], sources[j]))

    nb_new = 0
    with Session(engine) as session:
        for src_a, src_b in source_pairs:
            products_a = session.execute(
                select(Product).where(Product.source == src_a)
            ).scalars().all()
            products_b = session.execute(
                select(Product).where(Product.source == src_b)
            ).scalars().all()

            if not products_a or not products_b:
                logger.info(f"[match_cross_source] Pas assez de produits pour {src_a} vs {src_b}")
                continue

            norm_a = [(p, _normalize(p.name)) for p in products_a]
            norm_b = [(p, _normalize(p.name)) for p in products_b]

            logger.info(f"[match_cross_source] Matching {src_a}({len(norm_a)}) vs {src_b}({len(norm_b)})")

            for pa, na in norm_a:
                for pb, nb_name in norm_b:
                    ratio = SequenceMatcher(None, na, nb_name).ratio()
                    if ratio < min_similarity:
                        continue

                    existing = session.execute(
                        select(ProductMatch).where(
                            ((ProductMatch.product_id_a == pa.id) & (ProductMatch.product_id_b == pb.id))
                            | ((ProductMatch.product_id_a == pb.id) & (ProductMatch.product_id_b == pa.id))
                        )
                    ).scalar_one_or_none()

                    if existing:
                        existing.similarity = round(ratio * 100, 2)
                    else:
                        session.add(ProductMatch(
                            product_id_a=pa.id,
                            product_id_b=pb.id,
                            similarity=round(ratio * 100, 2),
                        ))
                        nb_new += 1

        session.commit()

    logger.info(f"[match_cross_source] {nb_new} nouveaux matchs trouvés")
    return {"new_matches": nb_new}


# ─────────────────────────────────────────────
# TÂCHE 7 : Digest hebdomadaire
# ─────────────────────────────────────────────
@celery_app.task(name="tasks.send_weekly_digest")
def send_weekly_digest():
    """Envoie un email récapitulatif hebdo aux utilisateurs avec préférences."""
    logger.info("[send_weekly_digest] Préparation du digest hebdomadaire...")
    sent = 0

    with Session(engine) as session:
        from api.models import UserPreference
        users_with_prefs = session.execute(
            select(User, UserPreference).join(UserPreference, User.id == UserPreference.user_id)
        ).all()

        for user, pref in users_with_prefs:
            categories = pref.categories or []
            if not categories:
                continue

            top_deals = (
                session.execute(
                    select(Product, PriceHistory)
                    .join(PriceHistory, Product.id == PriceHistory.product_id)
                    .where(
                        Product.category.in_(categories),
                        PriceHistory.discount_pct.isnot(None),
                        PriceHistory.discount_pct >= 20,
                    )
                    .order_by(PriceHistory.discount_pct.desc())
                    .limit(8)
                ).all()
            )

            if not top_deals:
                continue

            rows_html = ""
            for p, ph in top_deals:
                src = {"djokstore_ci": "DjokStore", "coinafrique_ci": "CoinAfrique"}.get(p.source, "Jumia")
                disc = f"-{int(ph.discount_pct)}%" if ph.discount_pct else ""
                rows_html += f"""
                <tr>
                  <td style="padding:8px;border-bottom:1px solid #333">{p.name[:55]}</td>
                  <td style="padding:8px;border-bottom:1px solid #333;font-weight:bold;color:#00b894">{int(ph.price)} XOF</td>
                  <td style="padding:8px;border-bottom:1px solid #333;color:#fdcb6e">{disc}</td>
                  <td style="padding:8px;border-bottom:1px solid #333">{src}</td>
                </tr>"""

            html = f"""
            <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#1a1d2e;color:#e2e8f0;border-radius:12px;overflow:hidden">
              <div style="background:linear-gradient(135deg,#F68B1E,#e67e22);padding:20px 30px">
                <h1 style="margin:0;color:#fff;font-size:20px">Ton recap hebdo JumiaPrix 🔥</h1>
              </div>
              <div style="padding:20px 30px">
                <p>Salut <strong>{user.name}</strong>,</p>
                <p>Voici les meilleures promos de la semaine dans tes categories :</p>
                <table style="width:100%;border-collapse:collapse;margin:15px 0;font-size:13px">
                  <tr style="color:#8892b0"><th style="text-align:left;padding:8px">Produit</th><th style="padding:8px">Prix</th><th style="padding:8px">Promo</th><th style="padding:8px">Source</th></tr>
                  {rows_html}
                </table>
                <a href="http://localhost:5000/boutique" style="display:inline-block;background:#F68B1E;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:10px">Voir sur JumiaPrix</a>
                <p style="margin-top:20px;font-size:12px;color:#8892b0">— Comparateur de Prix Jumia CI</p>
              </div>
            </div>"""

            try:
                _send_email(
                    to_email=user.email,
                    subject=f"Tes promos de la semaine - JumiaPrix CI",
                    html_body=html,
                )
                sent += 1
            except Exception as e:
                logger.error(f"[send_weekly_digest] Erreur email {user.email}: {e}")

    logger.info(f"[send_weekly_digest] {sent} digests envoyés")
    return {"sent": sent}


def _send_email(to_email, subject, html_body):
    """Helper: envoie un email HTML via Gmail SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    gmail_user = os.getenv("GMAIL_USER")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_app_password:
        logger.warning("[_send_email] GMAIL_USER / GMAIL_APP_PASSWORD non configurés")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"JumiaPrix CI <{gmail_user}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_app_password)
        server.send_message(msg)


def send_alert_email(to_email, user_name, product_name, product_url,
                     current_price, target_price, image_url=None, source="jumia_ci"):
    """Envoie une notification par email via Gmail SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    gmail_user = os.getenv("GMAIL_USER")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_app_password:
        logger.warning("[send_alert_email] GMAIL_USER / GMAIL_APP_PASSWORD non configurés, skip email")
        return

    savings = round(target_price - current_price)
    subject = f"Alerte prix : {product_name[:50]} est a {int(current_price)} XOF !"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#1a1d2e;color:#e2e8f0;border-radius:12px;overflow:hidden">
      <div style="background:linear-gradient(135deg,#6c5ce7,#a29bfe);padding:20px 30px">
        <h1 style="margin:0;color:#fff;font-size:22px">Alerte Prix Declenchee !</h1>
      </div>
      <div style="padding:25px 30px">
        <p>Bonjour <strong>{user_name}</strong>,</p>
        <p>Le produit que vous surveillez a atteint votre prix cible :</p>
        <div style="background:#232640;border-radius:8px;padding:20px;margin:15px 0;text-align:center">
          {"<img src='" + image_url + "' style='width:120px;height:120px;object-fit:contain;background:#fff;border-radius:8px;margin-bottom:10px' /><br>" if image_url else ""}
          <h2 style="margin:5px 0;font-size:16px">{product_name}</h2>
          <p style="font-size:28px;font-weight:bold;color:#00b894;margin:10px 0">{int(current_price)} XOF</p>
          <p style="color:#8892b0">Votre seuil : {int(target_price)} XOF</p>
          {f"<p style='color:#fdcb6e'>Economie : {savings} XOF</p>" if savings > 0 else ""}
        </div>
        <a href="{product_url}" style="display:inline-block;background:#6c5ce7;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:10px">
          Voir sur {"DjokStore CI" if source == "djokstore_ci" else "CoinAfrique CI" if source == "coinafrique_ci" else "Jumia CI"}
        </a>
        <p style="margin-top:20px;font-size:13px;color:#8892b0">
          — Comparateur de Prix Jumia CI | ENSEA AS Data Science
        </p>
      </div>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"JumiaPrix CI <{gmail_user}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_app_password)
        server.send_message(msg)

    logger.info(f"[send_alert_email] Email envoyé à {to_email}")