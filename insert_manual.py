# insert_manual.py — insertion manuelle pour tester
import os, sys, json, pandas as pd
import io
from datetime import datetime, timezone
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, "scraper")
sys.path.insert(0, "api")

from scraper.cleaner import load_raw_data, clean_dataframe
from api.models import Product, PriceHistory, Base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://jumia_user:jumia_pass@localhost:5433/jumia_db?client_encoding=utf8"
)
engine = create_engine(DATABASE_URL)

# Crée les tables si elles n'existent pas encore
Base.metadata.create_all(engine)

# Charge et nettoie les données
df = clean_dataframe(load_raw_data("scraper/raw_data.json"))
print(f"{len(df)} items à insérer...")

scraped_at = datetime.now(timezone.utc)
nb_new = nb_updated = 0

with Session(engine) as session:
    for _, row in df.iterrows():
        product = session.execute(
            select(Product).where(Product.product_url == row["product_url"])
        ).scalar_one_or_none()

        if product is None:
            product = Product(
                product_url=row["product_url"],
                name=row["name"],
                category=row["category"],
                currency="XOF",
                image_url=row.get("image_url"),
                page_url=row.get("page_url"),
            )
            session.add(product)
            session.flush()
            nb_new += 1
        else:
            nb_updated += 1

        session.add(PriceHistory(
            product_id    = product.id,
            price         = int(row["price"]),
            old_price     = int(row["old_price"]) if pd.notna(row["old_price"]) else None,
            discount_pct  = float(row["discount_pct"]) if pd.notna(row["discount_pct"]) else None,
            reviews_count = int(row["reviews_count"]) if pd.notna(row.get("reviews_count")) else 0,
            scraped_at    = scraped_at,
        ))

    session.commit()

print(f"Terminé — {nb_new} nouveaux produits, {nb_updated} mis à jour")