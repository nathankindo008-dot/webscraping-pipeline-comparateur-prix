# Documentation API — Comparateur de Prix Jumia CI

**Base URL :** `http://localhost:5000`
**Documentation interactive (Swagger) :** http://localhost:5000/docs/

---

## Endpoints

### Monitoring

#### `GET /health`

Vérifie le statut de l'API et de la base de données.

**Réponse 200 :**
```json
{
  "status": "ok",
  "database": "connected",
  "stats": {
    "products": 245,
    "price_snapshots": 490
  }
}
```

**Réponse 503 :** Base de données inaccessible.

---

### Produits

#### `GET /products`

Liste paginée de tous les produits avec filtres optionnels.

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `page` | int | 1 | Numéro de page |
| `per_page` | int | 20 | Éléments par page (max 100) |
| `category` | string | — | Filtrer par catégorie |
| `min_price` | float | — | Prix minimum (XOF) |
| `max_price` | float | — | Prix maximum (XOF) |
| `discount` | bool | — | `true` = uniquement les promotions |
| `sort` | string | `price_asc` | Tri : `price_asc`, `price_desc`, `discount_desc`, `reviews_desc` |

**Exemple :**
```
GET /products?category=telephones-tablettes&min_price=10000&sort=price_asc&page=1&per_page=10
```

**Réponse 200 :**
```json
{
  "products": [
    {
      "id": 1,
      "name": "Samsung Galaxy A06 - 4G - 2 SIM - 6.7\" - 4/64Go",
      "category": "telephones-tablettes",
      "price": 45700.0,
      "old_price": 60000.0,
      "discount_pct": 24.0,
      "currency": "XOF",
      "reviews_count": 854,
      "image_url": "https://ci.jumia.is/product/25/552813/1.jpg",
      "product_url": "https://www.jumia.ci/samsung-galaxy-a06-31825552.html",
      "last_scraped_at": "2026-03-13T10:58:49+00:00"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 10,
    "total": 50,
    "pages": 5
  },
  "filters_applied": {
    "category": "telephones-tablettes",
    "min_price": "10000",
    "max_price": null,
    "discount": null,
    "sort": "price_asc"
  }
}
```

---

#### `GET /products/<id>`

Détail complet d'un produit avec son dernier prix.

**Réponse 200 :**
```json
{
  "id": 1,
  "name": "Samsung Galaxy A06 - 4G",
  "category": "telephones-tablettes",
  "price": 45700.0,
  "old_price": 60000.0,
  "discount_pct": 24.0,
  "currency": "XOF",
  "reviews_count": 854,
  "image_url": "...",
  "product_url": "...",
  "page_url": "...",
  "created_at": "2026-03-13T10:58:49+00:00",
  "updated_at": "2026-03-13T10:58:49+00:00",
  "last_scraped_at": "2026-03-13T10:58:49+00:00"
}
```

**Réponse 404 :** Produit introuvable.

---

#### `GET /products/<id>/history`

Historique complet des prix d'un produit.

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `limit` | int | 30 | Nombre de snapshots (max 365) |

**Réponse 200 :**
```json
{
  "product_id": 1,
  "name": "Samsung Galaxy A06",
  "category": "telephones-tablettes",
  "product_url": "...",
  "history": [
    {
      "id": 42,
      "price": 45700.0,
      "old_price": 60000.0,
      "discount_pct": 24.0,
      "reviews_count": 854,
      "scraped_at": "2026-03-14T02:00:00+00:00"
    },
    {
      "id": 12,
      "price": 48000.0,
      "old_price": 60000.0,
      "discount_pct": 20.0,
      "reviews_count": 830,
      "scraped_at": "2026-03-13T02:00:00+00:00"
    }
  ],
  "nb_snapshots": 2,
  "price_variation_pct": -4.79
}
```

---

#### `GET /products/compare`

Compare plusieurs produits côte à côte.

| Paramètre | Type | Requis | Description |
|-----------|------|--------|-------------|
| `ids` | string | oui | IDs séparés par virgule (2-5 produits) |

**Exemple :**
```
GET /products/compare?ids=1,5,12
```

**Réponse 200 :**
```json
{
  "comparison": [
    { "id": 1, "name": "...", "price": 45700.0, "savings": 14300.0, "..." : "..." },
    { "id": 5, "name": "...", "price": 52000.0, "savings": null, "..." : "..." },
    { "id": 12, "name": "...", "price": 38900.0, "savings": 11100.0, "..." : "..." }
  ],
  "best_deal": {
    "product_id": 12,
    "name": "...",
    "price": 38900.0,
    "currency": "XOF"
  },
  "nb_products": 3
}
```

---

### Catégories

#### `GET /categories`

Liste de toutes les catégories avec statistiques.

**Réponse 200 :**
```json
{
  "categories": [
    {
      "category": "telephones-tablettes",
      "nb_products": 50,
      "avg_price": 125000.0,
      "min_price": 15900.0,
      "max_price": 890000.0
    }
  ],
  "total": 17
}
```

---

#### `GET /categories/<category>/products`

Produits d'une catégorie, triés par prix croissant.

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `page` | int | 1 | Numéro de page |
| `per_page` | int | 20 | Éléments par page |

---

### Recherche

#### `GET /search`

Recherche textuelle sur le nom des produits (insensible à la casse).

| Paramètre | Type | Requis | Description |
|-----------|------|--------|-------------|
| `q` | string | oui | Mot-clé de recherche |
| `category` | string | non | Filtrer par catégorie |
| `page` | int | non | Numéro de page |
| `per_page` | int | non | Éléments par page |

**Exemple :**
```
GET /search?q=samsung&category=telephones-tablettes
```

---

### Scraping

#### `POST /scrape`

Lance le scraping de manière synchrone (bloquant — peut prendre plusieurs minutes).

**Réponse 200 :**
```json
{
  "status": "ok",
  "message": "Scraping terminé : 245 items récupérés",
  "raw_items": 245
}
```

---

#### `POST /scrape/async`

Lance le pipeline complet via Celery (non-bloquant).

**Réponse 202 :**
```json
{
  "status": "accepted",
  "message": "Pipeline de scraping lancé en arrière-plan",
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "check_url": "/tasks/a1b2c3d4-e5f6-7890-abcd-ef1234567890/status"
}
```

---

#### `GET /tasks/<task_id>/status`

Vérifie le statut d'une tâche Celery.

**Réponse 200 (en cours) :**
```json
{
  "task_id": "a1b2c3d4-...",
  "status": "PENDING",
  "ready": false
}
```

**Réponse 200 (terminé) :**
```json
{
  "task_id": "a1b2c3d4-...",
  "status": "SUCCESS",
  "ready": true,
  "result": {
    "status": "ok",
    "new": 45,
    "updated": 200,
    "total": 245
  }
}
```

---

### Export

#### `GET /export`

Exporte les données en CSV, Excel ou JSON.

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `format` | string | `csv` | Format : `csv`, `excel`, `json` |
| `category` | string | — | Filtrer par catégorie |

**Exemples :**
```
GET /export?format=csv
GET /export?format=excel&category=telephones-tablettes
GET /export?format=json
```

---

## Codes d'erreur

| Code | Signification | Exemple |
|------|---------------|---------|
| 200 | Succès | Données retournées |
| 202 | Accepté | Tâche async lancée |
| 400 | Mauvaise requête | Paramètre manquant ou invalide |
| 404 | Non trouvé | Produit ou catégorie inexistant |
| 500 | Erreur serveur | Erreur interne |
| 503 | Service indisponible | Base de données down |

Toutes les erreurs retournent un JSON structuré :
```json
{
  "error": "Not Found",
  "message": "Produit #999 introuvable."
}
```

---

## Métriques Prometheus

L'endpoint `GET /metrics` expose les métriques au format Prometheus :

- `jumia_api_http_request_total` — Nombre total de requêtes par endpoint et code HTTP
- `jumia_api_http_request_duration_seconds` — Latence des requêtes (histogramme)
- `jumia_api_app_info` — Métadonnées de l'application
