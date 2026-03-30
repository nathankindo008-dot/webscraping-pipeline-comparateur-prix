# Architecture Technique

## Vue d'ensemble

```
                          ┌─────────────────────────────────┐
                          │        Jumia CI (Web)            │
                          └──────────────┬──────────────────┘
                                         │ HTTP (Scrapy)
                                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        DOCKER COMPOSE                               │
│                                                                     │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────┐    │
│  │   Scrapy      │────▶│   Cleaner    │────▶│   PostgreSQL     │    │
│  │  (Spider)     │     │  (pandas)    │     │   (Stockage)     │    │
│  └──────────────┘     └──────────────┘     └────────┬─────────┘    │
│         ▲                                           │              │
│         │ lance                                     │ lit          │
│  ┌──────┴──────────┐                     ┌──────────▼─────────┐    │
│  │  Celery Worker   │◀── messages ──────│    API Flask        │    │
│  │  (exécution)     │                    │  (REST + Swagger)  │    │
│  └──────┬──────────┘                     └──────────┬─────────┘    │
│         ▲                                           │              │
│         │ planifie                                   │ /metrics     │
│  ┌──────┴──────────┐                     ┌──────────▼─────────┐    │
│  │  Celery Beat     │                    │    Prometheus       │    │
│  │  (cron)          │                    │  (métriques)        │    │
│  └─────────────────┘                     └──────────┬─────────┘    │
│                                                     │              │
│         ┌──────────────┐                 ┌──────────▼─────────┐    │
│         │    Redis      │                │    Grafana          │    │
│         │  (broker)     │                │  (dashboard)        │    │
│         └──────────────┘                 └────────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Composants

### 1. Scraper (`scraper/`)

| Fichier | Rôle |
|---------|------|
| `jumia_scraper/spiders/spider_jumia.py` | Spider Scrapy — parcourt 17 catégories Jumia CI |
| `jumia_scraper/settings.py` | Configuration Scrapy (délais, concurrence, robots.txt) |
| `jumia_scraper/items.py` | Définition des items Scrapy |
| `jumia_scraper/middlewares.py` | Middlewares personnalisés |
| `jumia_scraper/pipelines.py` | Pipelines de traitement |
| `cleaner.py` | Nettoyage des données brutes avec pandas |
| `scrapy.cfg` | Configuration du projet Scrapy |

**Flux de données :**
```
Jumia CI → spider_jumia.py → raw_data.json → cleaner.py → clean_data.json
```

**Règles éthiques respectées :**
- `ROBOTSTXT_OBEY = True`
- `DOWNLOAD_DELAY = 2` secondes + randomisation
- `CONCURRENT_REQUESTS = 1`
- `MAX_PER_CATEGORY = 50` (max 500 items total)
- User-Agent : `ENSEA-Educational-Bot/1.0`

---

### 2. API REST (`api/`)

| Fichier | Rôle |
|---------|------|
| `app.py` | Application Flask — routes, endpoints, configuration |
| `models.py` | Modèles SQLAlchemy (Product, PriceHistory) |
| `schemas.py` | Sérialiseurs JSON pour les réponses API |
| `schema.sql` | Schéma SQL initial (tables, index, vues, triggers) |

**Endpoints principaux :** 14 endpoints (voir `API_DOCUMENTATION.md`)

---

### 3. Tâches asynchrones (`tasks/`)

| Fichier | Rôle |
|---------|------|
| `celery_app.py` | Configuration Celery (broker Redis, sérialisation, beat_schedule) |
| `tasks.py` | Tâches Celery : scraping, nettoyage, insertion, détection baisses |
| `beat_schedule.py` | Documentation du planificateur |

**Tâches Celery :**

| Tâche | Déclencheur | Description |
|-------|-------------|-------------|
| `scrape_jumia` | Manuel / Pipeline | Lance le spider Scrapy |
| `clean_and_insert` | Après scraping | Nettoie et insère en base |
| `full_pipeline` | Beat (2h/jour) | Pipeline complet scrape → clean → insert |
| `check_price_drops` | Beat (6h/jour) | Détecte les baisses de prix > 10% |

---

### 4. Monitoring (`monitoring/`)

| Fichier | Rôle |
|---------|------|
| `prometheus.yml` | Configuration Prometheus (scrape API Flask) |
| `grafana/provisioning/datasources/` | Source de données Prometheus pour Grafana |
| `grafana/provisioning/dashboards/` | Dashboard pré-configuré |

**Métriques collectées :**
- Nombre de requêtes par endpoint et code HTTP
- Latence des requêtes (histogramme, p95)
- Mémoire du processus Python
- Statut de l'API (up/down)

---

### 5. Base de données

**PostgreSQL 16** avec le schéma suivant :

```
┌─────────────────────┐       ┌─────────────────────────┐
│      products        │       │     price_history        │
├─────────────────────┤       ├─────────────────────────┤
│ id (PK)             │──1:N─▶│ id (PK)                 │
│ product_url (UNIQUE)│       │ product_id (FK)          │
│ name                │       │ price                    │
│ category            │       │ old_price                │
│ currency            │       │ discount_pct             │
│ image_url           │       │ reviews_count            │
│ page_url            │       │ scraped_at               │
│ created_at          │       │ created_at               │
│ updated_at          │       └─────────────────────────┘
└─────────────────────┘

Vues SQL :
  - v_latest_prices    → dernier prix de chaque produit
  - v_price_evolution   → évolution min/max/actuel par produit
```

**Contraintes :**
- `price > 0`
- `old_price IS NULL OR old_price > price`
- `discount_pct BETWEEN 0 AND 100`

---

## Infrastructure Docker

```yaml
Services (7) :
  postgres   → PostgreSQL 16 Alpine      (port 5433)
  redis      → Redis 7 Alpine            (port 6379)
  api        → Flask API                  (port 5000)
  worker     → Celery Worker
  beat       → Celery Beat
  prometheus → Prometheus                 (port 9090)
  grafana    → Grafana                    (port 3000)

Volumes (6) :
  postgres_data, redis_data, scraper_data,
  beat_data, prometheus_data, grafana_data
```

---

## Arborescence du projet

```
webscraping-pipeline-comparateur-prix/
├── api/
│   ├── app.py              # API Flask
│   ├── models.py           # Modèles SQLAlchemy
│   ├── schemas.py          # Sérialiseurs JSON
│   └── schema.sql          # Schéma SQL
├── scraper/
│   ├── cleaner.py          # Nettoyage pandas
│   ├── scrapy.cfg
│   └── jumia_scraper/
│       ├── settings.py
│       ├── items.py
│       ├── middlewares.py
│       ├── pipelines.py
│       └── spiders/
│           └── spider_jumia.py
├── tasks/
│   ├── celery_app.py       # Config Celery
│   ├── tasks.py            # Tâches Celery
│   └── beat_schedule.py    # Planificateur
├── tests/
│   └── test_cleaner.py     # Tests unitaires
├── monitoring/
│   ├── prometheus.yml
│   └── grafana/
│       └── provisioning/
│           ├── datasources/
│           └── dashboards/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env / env.example
├── README.md
├── INSTALLATION.md
├── API_DOCUMENTATION.md
├── ARCHITECTURE.md
└── .gitignore
```
