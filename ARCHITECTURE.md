# Architecture Technique

## Vue d'ensemble

```
              ┌────────────────────────────────────────────┐
              │   Sources Web                              │
              │   • Jumia CI (Cloudflare)                  │
              │   • DjokStore CI                           │
              │   • CoinAfrique CI                         │
              └───────────────────┬────────────────────────┘
                                  │
                                  │ HTTP (Scrapy / FlareSolverr)
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           DOCKER COMPOSE (12 services)                  │
│                                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                 │
│  │ FlareSolverr │──▶│    Scrapy    │──▶│   Cleaner    │                 │
│  │  (Jumia uniq)│   │ (3 spiders)  │   │   (pandas)   │                 │
│  └──────────────┘   └──────────────┘   └──────┬───────┘                 │
│                                               │                         │
│                                               ▼                         │
│                                        ┌──────────────┐                 │
│                                        │  PostgreSQL  │                 │
│                                        │  (8 tables)  │                 │
│                                        └──────┬───────┘                 │
│                                               │                         │
│   ┌──── ORCHESTRATION ────┐                   │                         │
│   │                       │                   │ SQLAlchemy              │
│   │  ┌─────────────────┐  │                   ▼                         │
│   │  │ Airflow         │  │          ┌────────────────────┐             │
│   │  │ (DAGs visuels)  │──┤          │    API Flask       │             │
│   │  │  - pipeline     │  │          │  (REST + JWT +     │             │
│   │  │  - weekly_digest│  │          │   Swagger + Chat)  │             │
│   │  └────────┬────────┘  │          └────────┬───────────┘             │
│   │           │           │                   │                         │
│   │           │ send_task │                   │ /metrics                │
│   │           │ via Redis │                   ▼                         │
│   └───────────┼───────────┘          ┌────────────────────┐             │
│               ▼                      │    Prometheus      │             │
│       ┌──────────────────┐           │    (scrape 30s)    │             │
│       │  Celery Worker   │           └────────┬───────────┘             │
│       │  (exécutant)     │                    │                         │
│       └──────────────────┘                    ▼                         │
│               │                      ┌──────────────────┐               │
│               │                      │     Grafana      │               │
│               ▼                      │   (dashboard)    │               │
│       ┌──────────────────┐           └──────────────────┘               │
│       │  Postgres + Redis│                                              │
│       └──────────────────┘                                              │
│                │                                                        │
│                                                                         │
│   Intelligence :                                                        │
│       ┌──────────────────────────────────────┐                          │
│       │  JumiBot (chatbot IA)                │                          │
│       │  Groq API + Llama 3.3 70B            │                          │
│       │  Appel depuis le navigateur          │                          │
│       └──────────────────────────────────────┘                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Répartition de l'orchestration

| Outil | Responsabilité | Exemples |
|-------|---------------|----------|
| **Airflow** | Orchestrateur unique (workflows, scheduling, UI visuelle) | Pipeline quotidien (scrape → clean → drops → alerts → matching), digest hebdomadaire |
| **Celery Worker** | Exécution effective de toutes les tâches | Reçoit les messages d'Airflow via Redis et lance Scrapy / clean / insert |
| **Redis** | Broker de messages entre Airflow et le worker | Queue Celery + backend de résultats |

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
| `celery_app.py` | Configuration Celery (broker Redis, sérialisation, retries) |
| `tasks.py` | Tâches Celery : scraping, nettoyage, insertion, détection baisses, alertes, matching, digest |

**Tâches Celery :**

| Tâche | Déclencheur | Description |
|-------|-------------|-------------|
| `scrape_jumia` | Airflow DAG (quotidien 2h) | Lance le spider Scrapy Jumia via FlareSolverr |
| `scrape_djokstore` | Airflow DAG (quotidien 2h) | Lance le spider DjokStore + clean + insert |
| `scrape_coinafrique` | Airflow DAG (quotidien 2h) | Lance le spider CoinAfrique + clean + insert |
| `clean_and_insert` | Airflow DAG (après scrape Jumia) | Nettoie et insère les données Jumia |
| `check_price_drops` | Airflow DAG (quotidien) | Détecte les baisses de prix > 10 % |
| `check_price_alerts` | Airflow DAG (quotidien) | Vérifie les alertes utilisateurs et envoie les emails |
| `match_cross_source` | Airflow DAG (quotidien) | Fuzzy-matching des produits entre sources |
| `send_weekly_digest` | Airflow DAG `weekly_digest` (lundi 8 h) | Envoie le digest hebdomadaire |

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
Services :
  postgres            → PostgreSQL 16 Alpine      (port 5433)
  redis               → Redis 7 Alpine            (port 6379)
  api                 → Flask API                  (port 5000)
  worker              → Celery Worker              (exécutant)
  flaresolverr        → Bypass Cloudflare Jumia   (port 8191)
  prometheus          → Prometheus                 (port 9090)
  grafana             → Grafana                    (port 3000)
  airflow-init        → Migration DB + user admin
  airflow-webserver   → UI Airflow                 (port 8080)
  airflow-scheduler   → Scheduler Airflow

Volumes :
  postgres_data, redis_data, prometheus_data, grafana_data
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
│   ├── celery_app.py       # Config Celery (worker exécutant)
│   └── tasks.py            # Tâches Celery
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
