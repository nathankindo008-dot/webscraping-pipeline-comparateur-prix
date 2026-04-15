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
# Mapping de normalisation des catégories
# Unifie Jumia + DjokStore vers un référentiel commun
# ─────────────────────────────────────────────
CATEGORY_MAPPING = {
    # --- Jumia : correction de casse (clés en lowercase) ---
    "articles-sportifs":    "articles-sportifs",
    "automobile":           "automobile",
    "livres-films-musique": "livres-films-musique",
    "jouets et jeux":       "jouets-et-jeux",

    # --- DjokStore → catégories unifiées ---
    "smartphone":           "telephones-tablettes",
    "tablette":             "telephones-tablettes",
    "tablette-educative":   "telephones-tablettes",
    "chargeur":             "telephones-tablettes",
    "powerbank":            "telephones-tablettes",
    "power-bank":           "telephones-tablettes",

    "ecouteurs":            "tv-electronique",
    "woofer":               "tv-electronique",
    "speaker":              "tv-electronique",
    "televiseur":           "tv-electronique",
    "tv":                   "tv-electronique",
    "tv-uhd-4k":            "tv-electronique",
    "montre-connectée":     "tv-electronique",
    "clavier-filaire":      "informatique",

    "ventilateur":          "electromenager",
    "bouilloire-electrique":"electromenager",
    "friteuse":             "electromenager",
    "extracteur":           "electromenager",
    "aspirateur-a-main":    "electromenager",
    "congélateur":          "electromenager",
    "congélateur-horizontal":"electromenager",
    "congélateur-vertical": "electromenager",
    "réfrigérateur-2-battants":"electromenager",
    "support-de-refrigerateur":"electromenager",

    "pc-portable":                  "informatique",
    "lenovo-pc-ordinateur-portable":"informatique",
    "hp-ordinateur-portable-hp":    "informatique",
    "imprimante-jet-d'encre-couleur":"informatique",
    "souris":                       "informatique",

    "tondeuse":                 "beaute-hygiene",
    "lame-de-rechange":         "beaute-hygiene",
    "brosse-a-dent-électrique": "beaute-hygiene",
    "massage":                  "beaute-hygiene",

    # --- CoinAfrique → catégories unifiées ---
    "telephones-tablettes":     "telephones-tablettes",
    "telephones-et-tablettes":  "telephones-tablettes",
    "tv-box-et-video-projecteurs": "tv-electronique",
    "son-hifi-et-casques":      "tv-electronique",
    "jeux-video-et-consoles":   "tv-electronique",
    "accessoires-informatiques":"informatique",
    "ordinateurs":              "informatique",
    "mode-et-beaute":           "mode",
    "vetements-homme":          "mode",
    "vetements-femme":          "mode",
    "chaussures-homme":         "mode",
    "chaussures-femme":         "mode",
    "pour-la-maison":           "maison-bureau",
    "meubles":                  "maison-bureau",
    "literie-et-matelas":       "maison-bureau",
    "sports-et-loisirs":        "articles-sportifs",
    "refrigerateurs-et-congelateurs": "electromenager",
    "climatiseurs-et-ventilateurs":   "electromenager",
    "cuisinieres-gazinieres-et-fours":"electromenager",
    "petit-electromenager":           "electromenager",
    "pour-l-enfant":            "produits-bebes",
}

KEYWORD_CATEGORY_RULES = [
    (["tv", "televiseur", "écran", "led", "smart-tv"],          "tv-electronique"),
    (["haut-parleur", "speaker", "barre-de-son", "super-power"],"tv-electronique"),
    (["congélateur", "congelateur", "réfrigérateur", "frigo"],  "electromenager"),
    (["matelas", "thermos", "cuisine"],                         "maison-bureau"),
    (["pc", "ordinateur", "imprimante", "laptop"],              "informatique"),
    (["tablette", "phone", "powerbank"],                        "telephones-tablettes"),
]

NAME_KEYWORD_RULES = [
    (["smartphone", "galaxy", "iphone", "redmi", "infinix", "tecno",
      "itel ", "samsung", "xiaomi", "zte ", "villaon", "sim", "mah",
      "tablette", "powerbank", "power bank", "câble", "chargeur",
      "support de téléphone"], "telephones-tablettes"),
    (["écouteur", "headphone", "casque", "montre", "watch",
      "haut-parleur", "haut parleur", "speaker", "woofer",
      "drone", "game controller"], "tv-electronique"),
    (["congélateur", "congelateur", "réfrigérateur", "refrigerateur",
      "ventilateur", "friteuse", "bouilloire", "pompe",
      "aspirateur", "extracteur", "lave-"], "electromenager"),
    (["ordinateur", "laptop", "pc portable", "imprimante",
      "écran hp", "ecran hp", "hp 250", "souris", "clavier"], "informatique"),
    (["tv ", "télé", "google tv", "qled", "smart tv", "uhd"], "tv-electronique"),
    (["thermos", "matelas"], "maison-bureau"),
]


def normalize_category(category: str) -> str:
    """Normalise une catégorie vers le référentiel commun."""
    if not category or category == "general":
        return "general"

    cat = category.strip().lower()

    if cat in CATEGORY_MAPPING:
        return CATEGORY_MAPPING[cat]

    for keywords, unified in KEYWORD_CATEGORY_RULES:
        if any(kw in cat for kw in keywords):
            return unified

    if len(cat) > 40:
        return "general"

    return cat


def classify_by_name(name: str) -> str:
    """Tente de deviner la catégorie d'un produit 'general' via son nom."""
    name_lower = name.strip().lower()
    for keywords, unified in NAME_KEYWORD_RULES:
        if any(kw in name_lower for kw in keywords):
            return unified
    return "general"


# ─────────────────────────────────────────────
# Seuils de prix valides par catégorie (XOF)
# ─────────────────────────────────────────────
PRICE_LIMITS = {
    "telephones-tablettes": (500,    2_000_000),
    "tv-electronique":      (500,    2_000_000),
    "electromenager":       (500,    2_000_000),
    "informatique":         (500,    2_000_000),
    "maison-bureau":        (500,    2_000_000),
    "mode":                 (500,    2_000_000),
    "supermarche":          (200,    2_000_000),
    "beaute-hygiene":       (300,    2_000_000),
    "produits-bebes":       (500,    2_000_000),
    "agriculture-elevage":  (500,    2_000_000),
    "articles-sportifs":    (500,    2_000_000),
    "automobile":           (500,    2_000_000),
    "livres-films-musique": (500,    2_000_000),
    "instruments-musique":  (500,    2_000_000),
    "jouets-et-jeux":       (500,    2_000_000),
    "animalerie":           (500,    2_000_000),
    "jardin-plein-air":     (500,    2_000_000),
    "general":              (200,    2_000_000),
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

    if initial_count == 0:
        logger.warning("DataFrame vide — rien à nettoyer")
        return pd.DataFrame(columns=[
            'name', 'category', 'price', 'old_price', 'discount_pct',
            'currency', 'reviews_count', 'product_url', 'image_url',
            'page_url', 'source', 'scraped_at'
        ])

    # 1. Normalisation des catégories (Jumia + DjokStore → référentiel commun)
    df['category'] = df['category'].apply(normalize_category)
    general_before = (df['category'] == 'general').sum()

    # 1b. Classification des "general" restants par analyse du nom du produit
    mask_general = df['category'] == 'general'
    df.loc[mask_general, 'category'] = df.loc[mask_general, 'name'].apply(classify_by_name)
    general_after = (df['category'] == 'general').sum()
    logger.info(
        f"Catégories après normalisation : {df['category'].nunique()} uniques "
        f"({general_before - general_after} produits 'general' reclassés)"
    )

    # 2. Nettoyage des noms
    df['name'] = df['name'].apply(clean_name)
    empty_names = (df['name'] == '').sum()
    if empty_names:
        logger.warning(f"Noms vides détectés : {empty_names}")

    # 3. Nettoyage & validation des prix par catégorie
    df['price'] = df.apply(
        lambda row: clean_price(row['price'], row.get('category', 'default')), axis=1
    )
    df['old_price'] = df.apply(
        lambda row: clean_price(row['old_price'], row.get('category', 'default')), axis=1
    )
    prix_aberrants = df['price'].isna().sum()
    logger.info(f"Prix aberrants/invalides détectés : {prix_aberrants}")

    # 4. Nettoyage du discount → colonne discount_pct (float)
    df['discount_pct'] = df['discount'].apply(clean_discount)

    # 5. Cohérence prix : old_price doit être strictement > price
    mask_incoherent = (
        df['old_price'].notna() &
        df['price'].notna() &
        (df['old_price'] <= df['price'])
    )
    df.loc[mask_incoherent, 'old_price'] = None
    df.loc[mask_incoherent, 'discount_pct'] = None
    if mask_incoherent.sum():
        logger.info(f"Prix incohérents corrigés (old_price ≤ price) : {mask_incoherent.sum()}")

    # 6. Suppression des lignes sans prix valide
    df = df[df['price'].notna()].copy()
    supprimés = initial_count - len(df)
    logger.info(f"Items supprimés (prix invalide/absent) : {supprimés}")

    # 7. Suppression des doublons (même URL dans plusieurs catégories)
    df = remove_duplicates(df)

    # 8. Nettoyage des URLs
    df['product_url'] = df['product_url'].str.strip()
    df['image_url']   = df['image_url'].str.strip()

    # 9. Conversion du timestamp scraped_at
    df['scraped_at'] = pd.to_datetime(df['scraped_at'], errors='coerce')

    # 10. Standardisation de la devise
    df['currency'] = 'XOF'

    # 11. Réinitialisation de l'index
    df = df.reset_index(drop=True)

    # 12. Colonnes finales ordonnées (supprime la colonne 'discount' brute)
    if 'source' not in df.columns:
        df['source'] = 'jumia_ci'

    cols = [
        'name', 'category', 'price', 'old_price', 'discount_pct',
        'currency', 'reviews_count', 'product_url', 'image_url',
        'page_url', 'source', 'scraped_at'
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