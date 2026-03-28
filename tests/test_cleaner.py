"""
test_cleaner.py — Tests unitaires du cleaner
ENSEA — AS Data Science | Dr N'golo Konate

Couvre :
  - clean_price()       : validation des prix par catégorie
  - clean_discount()    : extraction du pourcentage
  - clean_name()        : nettoyage des noms
  - clean_dataframe()   : pipeline complet
  - remove_duplicates() : déduplication
  - get_stats()         : statistiques post-nettoyage
"""

import pytest
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))

from cleaner import (
    clean_price,
    clean_discount,
    clean_name,
    clean_dataframe,
    remove_duplicates,
    get_stats,
)


# ─────────────────────────────────────────────
# Fixtures — données de test réutilisables
# ─────────────────────────────────────────────

@pytest.fixture
def sample_raw_data():
    """Jeu de données brutes représentatif des vraies données Jumia CI."""
    return [
        {
            "name": "Samsung Galaxy A06 - 4G - 2 SIM - 6.7\" - 4/64Go - Noir",
            "category": "telephones-tablettes",
            "price": 45700,
            "old_price": 60000,
            "discount": "24%",
            "currency": "XOF",
            "reviews_count": 854,
            "product_url": "https://www.jumia.ci/samsung-galaxy-a06-31825552.html",
            "image_url": "https://ci.jumia.is/product/25/552813/1.jpg",
            "page_url": "https://www.jumia.ci/telephone-tablette/",
            "scraped_at": "2026-03-13T10:58:49.667136",
        },
        {
            "name": "Nasco TV LED Slim 32\" - HD - Noir",
            "category": "tv-electronique",
            "price": 43900,
            "old_price": 56900,
            "discount": "23%",
            "currency": "XOF",
            "reviews_count": 16091,
            "product_url": "https://www.jumia.ci/nasco-slim-tv-led-32-13905321.html",
            "image_url": "https://ci.jumia.is/product/12/350931/1.jpg",
            "page_url": "https://www.jumia.ci/electronique/",
            "scraped_at": "2026-03-13T10:58:53.799901",
        },
        {
            "name": "Roch Sardines à l'huile Végétale 125G",
            "category": "supermarche",
            "price": 345,
            "old_price": 400,
            "discount": "14%",
            "currency": "XOF",
            "reviews_count": 113,
            "product_url": "https://www.jumia.ci/roch-sardines-125g-30146420.html",
            "image_url": "https://ci.jumia.is/product/02/464103/1.jpg",
            "page_url": "https://www.jumia.ci/epicerie/",
            "scraped_at": "2026-03-13T10:59:18.853788",
        },
        {
            # Prix aberrant — bug du spider (concaténation de chiffres)
            "name": "Cerave Gel Nettoyant Moussant",
            "category": "beaute-hygiene",
            "price": 760017850,
            "old_price": 800018800,
            "discount": "5%",
            "currency": "XOF",
            "reviews_count": 12,
            "product_url": "https://www.jumia.ci/cerave-gel-nettoyant-27420279.html",
            "image_url": "https://ci.jumia.is/product/97/202472/1.jpg",
            "page_url": "https://www.jumia.ci/beaute-hygiene-sante/",
            "scraped_at": "2026-03-13T10:59:23.009168",
        },
        {
            # Doublon — même URL, catégorie différente
            "name": "Samsung Galaxy A06 - 4G - 2 SIM - 6.7\" - 4/64Go - Noir",
            "category": "electromenager",
            "price": 45700,
            "old_price": 60000,
            "discount": "24%",
            "currency": "XOF",
            "reviews_count": 854,
            "product_url": "https://www.jumia.ci/samsung-galaxy-a06-31825552.html",
            "image_url": "https://ci.jumia.is/product/25/552813/1.jpg",
            "page_url": "https://www.jumia.ci/mlp-electromenager/",
            "scraped_at": "2026-03-13T10:59:03.216550",
        },
        {
            # old_price incohérent (inférieur au price)
            "name": "Produit avec prix incohérent",
            "category": "mode",
            "price": 10000,
            "old_price": 5000,   # ← old_price < price : incohérent
            "discount": "10%",
            "currency": "XOF",
            "reviews_count": 5,
            "product_url": "https://www.jumia.ci/produit-incoherent-99999.html",
            "image_url": "https://ci.jumia.is/product/99/999999/1.jpg",
            "page_url": "https://www.jumia.ci/fashion-mode/",
            "scraped_at": "2026-03-13T10:59:12.800000",
        },
        {
            # Prix null
            "name": "Produit sans prix",
            "category": "mode",
            "price": None,
            "old_price": None,
            "discount": None,
            "currency": "XOF",
            "reviews_count": 0,
            "product_url": "https://www.jumia.ci/produit-sans-prix-88888.html",
            "image_url": "",
            "page_url": "https://www.jumia.ci/fashion-mode/",
            "scraped_at": "2026-03-13T10:59:12.900000",
        },
    ]


@pytest.fixture
def sample_df(sample_raw_data):
    """DataFrame brut à partir du jeu de données."""
    return pd.DataFrame(sample_raw_data)


# ─────────────────────────────────────────────
# Tests : clean_price()
# ─────────────────────────────────────────────

class TestCleanPrice:

    def test_prix_valide_telephones(self):
        """Un prix normal de téléphone doit passer."""
        assert clean_price(45700, "telephones-tablettes") == 45700.0

    def test_prix_valide_supermarche(self):
        """Un petit prix d'épicerie doit passer."""
        assert clean_price(345, "supermarche") == 345.0

    def test_prix_aberrant_trop_grand(self):
        """Un prix de 760 millions est aberrant → None."""
        assert clean_price(760017850, "beaute-hygiene") is None

    def test_prix_aberrant_mode(self):
        """Un old_price de 840 millions est aberrant → None."""
        assert clean_price(840010500, "mode") is None

    def test_prix_zero(self):
        """Un prix à 0 est invalide → None."""
        assert clean_price(0, "telephones-tablettes") is None

    def test_prix_negatif(self):
        """Un prix négatif est invalide → None."""
        assert clean_price(-500, "supermarche") is None

    def test_prix_none(self):
        """None en entrée → None en sortie."""
        assert clean_price(None, "electromenager") is None

    def test_prix_trop_petit_pour_categorie(self):
        """50 XOF pour un téléphone est impossible → None."""
        assert clean_price(50, "telephones-tablettes") is None

    def test_categorie_inconnue_utilise_default(self):
        """Une catégorie inconnue utilise les seuils par défaut."""
        assert clean_price(5000, "categorie-inconnue") == 5000.0

    def test_prix_float_valide(self):
        """Un float valide doit être accepté."""
        assert clean_price(45700.0, "telephones-tablettes") == 45700.0


# ─────────────────────────────────────────────
# Tests : clean_discount()
# ─────────────────────────────────────────────

class TestCleanDiscount:

    def test_discount_classique(self):
        """'24%' → 24.0"""
        assert clean_discount("24%") == 24.0

    def test_discount_sans_symbole(self):
        """'58' → 58.0"""
        assert clean_discount("58") == 58.0

    def test_discount_none(self):
        """None → None"""
        assert clean_discount(None) is None

    def test_discount_vide(self):
        """Chaîne vide → None"""
        assert clean_discount("") is None

    def test_discount_avec_texte(self):
        """'-24% de réduction' → 24.0 (extrait le premier nombre)"""
        assert clean_discount("-24% de réduction") == 24.0

    def test_discount_grand(self):
        """'85%' → 85.0"""
        assert clean_discount("85%") == 85.0


# ─────────────────────────────────────────────
# Tests : clean_name()
# ─────────────────────────────────────────────

class TestCleanName:

    def test_nom_normal(self):
        """Un nom normal reste inchangé (espaces normalisés)."""
        assert clean_name("Samsung Galaxy A06") == "Samsung Galaxy A06"

    def test_espaces_multiples(self):
        """Les espaces multiples sont réduits à un seul."""
        assert clean_name("Samsung   Galaxy   A06") == "Samsung Galaxy A06"

    def test_espaces_debut_fin(self):
        """Les espaces en début/fin sont supprimés."""
        assert clean_name("  Samsung Galaxy A06  ") == "Samsung Galaxy A06"

    def test_nom_vide(self):
        """Un nom vide retourne une chaîne vide."""
        assert clean_name("") == ""

    def test_nom_none(self):
        """None retourne une chaîne vide."""
        assert clean_name(None) == ""

    def test_nom_trop_long(self):
        """Un nom de plus de 500 caractères est tronqué."""
        long_name = "A" * 600
        result = clean_name(long_name)
        assert len(result) == 500

    def test_nom_avec_caracteres_speciaux(self):
        """Les caractères spéciaux (accents, guillemets) sont conservés."""
        name = "Nasco TV LED 32\" - Décodeur Intégré"
        assert clean_name(name) == name


# ─────────────────────────────────────────────
# Tests : remove_duplicates()
# ─────────────────────────────────────────────

class TestRemoveDuplicates:

    def test_supprime_doublons_url(self, sample_df):
        """Deux items avec la même product_url → un seul gardé."""
        before = len(sample_df)
        df_dedup = remove_duplicates(sample_df)
        # Le Samsung A06 apparaît 2 fois → doit être réduit à 1
        assert len(df_dedup) == before - 1

    def test_garde_le_premier(self, sample_df):
        """En cas de doublon, le premier item est conservé."""
        df_dedup = remove_duplicates(sample_df)
        samsung = df_dedup[df_dedup["product_url"].str.contains("samsung-galaxy-a06")]
        assert len(samsung) == 1
        assert samsung.iloc[0]["category"] == "telephones-tablettes"

    def test_sans_doublons_inchange(self):
        """Un DataFrame sans doublons n'est pas modifié."""
        df = pd.DataFrame([
            {"product_url": "https://jumia.ci/produit-1.html", "name": "Produit 1"},
            {"product_url": "https://jumia.ci/produit-2.html", "name": "Produit 2"},
        ])
        df_dedup = remove_duplicates(df)
        assert len(df_dedup) == 2


# ─────────────────────────────────────────────
# Tests : clean_dataframe() — pipeline complet
# ─────────────────────────────────────────────

class TestCleanDataframe:

    def test_supprime_prix_aberrants(self, sample_df):
        """Les items avec prix aberrant (Cerave 760M) sont supprimés."""
        df_clean = clean_dataframe(sample_df)
        cerave = df_clean[df_clean["name"].str.contains("Cerave", case=False)]
        assert len(cerave) == 0

    def test_supprime_prix_null(self, sample_df):
        """Les items sans prix sont supprimés."""
        df_clean = clean_dataframe(sample_df)
        sans_prix = df_clean[df_clean["name"].str.contains("sans prix", case=False)]
        assert len(sans_prix) == 0

    def test_supprime_doublons(self, sample_df):
        """Les doublons cross-catégories sont supprimés."""
        df_clean = clean_dataframe(sample_df)
        samsung = df_clean[df_clean["product_url"].str.contains("samsung-galaxy-a06")]
        assert len(samsung) == 1

    def test_corrige_old_price_incoherent(self, sample_df):
        """Un old_price < price est mis à None."""
        df_clean = clean_dataframe(sample_df)
        incoherent = df_clean[df_clean["name"].str.contains("incohérent", case=False)]
        if len(incoherent) > 0:
            assert incoherent.iloc[0]["old_price"] is None or \
                   pd.isna(incoherent.iloc[0]["old_price"])

    def test_colonne_discount_pct_creee(self, sample_df):
        """La colonne discount_pct doit exister après nettoyage."""
        df_clean = clean_dataframe(sample_df)
        assert "discount_pct" in df_clean.columns

    def test_discount_pct_est_float(self, sample_df):
        """Les valeurs de discount_pct sont des floats."""
        df_clean = clean_dataframe(sample_df)
        valeurs = df_clean["discount_pct"].dropna()
        for val in valeurs:
            assert isinstance(val, float)

    def test_colonnes_finales_presentes(self, sample_df):
        """Toutes les colonnes attendues sont présentes."""
        df_clean = clean_dataframe(sample_df)
        colonnes_attendues = [
            "name", "category", "price", "old_price", "discount_pct",
            "currency", "reviews_count", "product_url", "image_url",
            "page_url", "scraped_at"
        ]
        for col in colonnes_attendues:
            assert col in df_clean.columns, f"Colonne manquante : {col}"

    def test_currency_toujours_xof(self, sample_df):
        """La devise est toujours XOF après nettoyage."""
        df_clean = clean_dataframe(sample_df)
        assert (df_clean["currency"] == "XOF").all()

    def test_scraped_at_est_datetime(self, sample_df):
        """scraped_at est converti en datetime."""
        df_clean = clean_dataframe(sample_df)
        assert pd.api.types.is_datetime64_any_dtype(df_clean["scraped_at"])

    def test_dataframe_non_vide(self, sample_df):
        """Le DataFrame nettoyé contient au moins un item valide."""
        df_clean = clean_dataframe(sample_df)
        assert len(df_clean) > 0

    def test_index_reinitialise(self, sample_df):
        """L'index repart de 0 après nettoyage."""
        df_clean = clean_dataframe(sample_df)
        assert list(df_clean.index) == list(range(len(df_clean)))


# ─────────────────────────────────────────────
# Tests : get_stats()
# ─────────────────────────────────────────────

class TestGetStats:

    def test_total_items(self, sample_df):
        """total_items correspond au nombre de lignes."""
        df_clean = clean_dataframe(sample_df)
        stats = get_stats(df_clean)
        assert stats["total_items"] == len(df_clean)

    def test_categories_presentes(self, sample_df):
        """Les catégories sont bien comptées."""
        df_clean = clean_dataframe(sample_df)
        stats = get_stats(df_clean)
        assert isinstance(stats["categories"], dict)
        assert len(stats["categories"]) > 0

    def test_price_range_coherent(self, sample_df):
        """Le prix min est inférieur ou égal au prix max."""
        df_clean = clean_dataframe(sample_df)
        stats = get_stats(df_clean)
        assert stats["price_range"]["min"] <= stats["price_range"]["max"]

    def test_items_with_discount(self, sample_df):
        """Le nombre d'items avec remise est cohérent."""
        df_clean = clean_dataframe(sample_df)
        stats = get_stats(df_clean)
        assert 0 <= stats["items_with_discount"] <= stats["total_items"]

    def test_avg_reviews_positif(self, sample_df):
        """La moyenne des reviews est positive."""
        df_clean = clean_dataframe(sample_df)
        stats = get_stats(df_clean)
        assert stats["avg_reviews"] >= 0