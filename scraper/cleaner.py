import pandas as pd
import json
import re
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Seuils de prix valides par catégorie (XOF)
# ─────────────────────────────────────────────
PRICE_LIMITS = {
    "telephones-tablettes": (500,    2_000_000),
    "tv-electronique":      (500,  2_000_000),
    "electromenager":       (500,  2_000_000),
    "informatique":         (500, 2_000_000),
    "maison-bureau":        (500,    2_000_000),
    "mode":                 (500,    2_000_000),
    "supermarche":          (200,    2_000_000),
    "beaute-hygiene":       (300,    2_000_000),
    "produits-bebes":       (500,    2_000_000),
    "agriculture-elevage":  (500,    2_000_000),
    "Articles-sportifs":    (500,    2_000_000),
    "Automobile":           (500,    2_000_000),
    "default":              (200,    2_000_000),
}


# ─────────────────────────────────────────────
# Fonctions de nettoyage
# ─────────────────────────────────────────────

def load_raw_data(filepath: str) -> pd.DataFrame:
    """Charge le fichier JSON brut."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {filepath}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    logger.info(f"Données chargées : {len(df)} items bruts")
    return df


def clean_price(value, category: str = "default") -> float | None:
    """
    Valide un prix selon les seuils de la catégorie.
    Retourne None si aberrant (ex: 840010500 = concaténation de 2 prix).
    """
    if pd.isna(value) or value is None:
        return None
    try:
        price = float(value)
    except (ValueError, TypeError):
        return None
    if price <= 0:
        return None
    min_p, max_p = PRICE_LIMITS.get(category, PRICE_LIMITS["default"])
    if price < min_p or price > max_p:
        return None
    return price


def clean_discount(value) -> float | None:
    """Extrait le pourcentage de réduction (ex: '24%' → 24.0)."""
    if pd.isna(value) or value is None:
        return None
    match = re.search(r'(\d+)', str(value))
    return float(match.group(1)) if match else None


def clean_name(value) -> str:
    """Nettoie le nom du produit."""
    if pd.isna(value) or not value:
        return ""
    name = str(value).strip()
    name = re.sub(r'\s+', ' ', name)
    return name[:500]


def remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Supprime les doublons cross-catégories basés sur product_url."""
    before = len(df)
    df = df.drop_duplicates(subset=['product_url'], keep='first')
    after = len(df)
    removed = before - after
    if removed:
        logger.info(f"Doublons supprimés : {removed} (déduplication sur product_url)")
    return df


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline de nettoyage complet."""
    logger.info("=" * 55)
    logger.info("=== Début du pipeline de nettoyage ===")
    logger.info("=" * 55)
    initial_count = len(df)

    # 1. Nettoyage des noms
    df['name'] = df['name'].apply(clean_name)
    empty_names = (df['name'] == '').sum()
    if empty_names:
        logger.warning(f"Noms vides détectés : {empty_names}")

    # 2. Nettoyage & validation des prix par catégorie
    df['price'] = df.apply(
        lambda row: clean_price(row['price'], row.get('category', 'default')), axis=1
    )
    df['old_price'] = df.apply(
        lambda row: clean_price(row['old_price'], row.get('category', 'default')), axis=1
    )
    prix_aberrants = df['price'].isna().sum()
    logger.info(f"Prix aberrants/invalides détectés : {prix_aberrants}")

    # 3. Nettoyage du discount → colonne discount_pct (float)
    df['discount_pct'] = df['discount'].apply(clean_discount)

    # 4. Cohérence prix : old_price doit être strictement > price
    mask_incoherent = (
        df['old_price'].notna() &
        df['price'].notna() &
        (df['old_price'] <= df['price'])
    )
    df.loc[mask_incoherent, 'old_price'] = None
    df.loc[mask_incoherent, 'discount_pct'] = None
    if mask_incoherent.sum():
        logger.info(f"Prix incohérents corrigés (old_price ≤ price) : {mask_incoherent.sum()}")

    # 5. Suppression des lignes sans prix valide
    df = df[df['price'].notna()].copy()
    supprimés = initial_count - len(df)
    logger.info(f"Items supprimés (prix invalide/absent) : {supprimés}")

    # 6. Suppression des doublons (même URL dans plusieurs catégories)
    df = remove_duplicates(df)

    # 7. Nettoyage des URLs
    df['product_url'] = df['product_url'].str.strip()
    df['image_url']   = df['image_url'].str.strip()

    # 8. Conversion du timestamp scraped_at
    df['scraped_at'] = pd.to_datetime(df['scraped_at'], errors='coerce')

    # 9. Standardisation de la devise
    df['currency'] = 'XOF'

    # 10. Réinitialisation de l'index
    df = df.reset_index(drop=True)

    # 11. Colonnes finales ordonnées (supprime la colonne 'discount' brute)
    cols = [
        'name', 'category', 'price', 'old_price', 'discount_pct',
        'currency', 'reviews_count', 'product_url', 'image_url',
        'page_url', 'scraped_at'
    ]
    df = df[cols]

    logger.info("=" * 55)
    logger.info(f"=== Nettoyage terminé : {len(df)} items valides / {initial_count} bruts ===")
    logger.info("=" * 55)
    return df


def save_clean_data(df: pd.DataFrame, output_path: str = "clean_data.json"):
    """Sauvegarde les données nettoyées en JSON."""
    path = Path(output_path)
    records = df.copy()
    records['scraped_at'] = records['scraped_at'].astype(str)
    records.to_json(path, orient='records', force_ascii=False, indent=2)
    logger.info(f"Fichier sauvegardé : {path} ({len(df)} items)")


def get_stats(df: pd.DataFrame) -> dict:
    """Génère des statistiques post-nettoyage."""
    stats = {
        "total_items": len(df),
        "categories": df['category'].value_counts().to_dict(),
        "items_with_discount": int(df['discount_pct'].notna().sum()),
        "items_with_old_price": int(df['old_price'].notna().sum()),
        "avg_price_by_category": (
            df.groupby('category')['price'].mean().round(0).astype(int).to_dict()
        ),
        "price_range": {
            "min": float(df['price'].min()),
            "max": float(df['price'].max()),
        },
        "avg_reviews": float(round(df['reviews_count'].mean(), 1)),
        "zero_reviews": int((df['reviews_count'] == 0).sum()),
    }
    return stats


# ─────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────
if __name__ == "__main__":
    INPUT_FILE  = "raw_data.json"
    OUTPUT_FILE = "clean_data.json"

    # Chargement
    df_raw = load_raw_data(INPUT_FILE)

    # Nettoyage
    df_clean = clean_dataframe(df_raw)

    # Sauvegarde
    save_clean_data(df_clean, OUTPUT_FILE)

    # Statistiques
    stats = get_stats(df_clean)
    logger.info("\n📊 STATISTIQUES POST-NETTOYAGE :\n" +
                json.dumps(stats, indent=2, ensure_ascii=False))