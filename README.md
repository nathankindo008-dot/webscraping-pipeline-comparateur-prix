# Comparateur de Prix — Jumia CI

![Niveau visé](https://img.shields.io/badge/Niveau-OR%20🥇-gold)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![Flask](https://img.shields.io/badge/API-Flask-lightgrey)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![Scrapy](https://img.shields.io/badge/Scraping-Scrapy-green)
![PostgreSQL](https://img.shields.io/badge/DB-PostgreSQL%2016-336791)
![Celery](https://img.shields.io/badge/Async-Celery%20%2B%20Redis-red)
![Airflow](https://img.shields.io/badge/Orchestration-Airflow%202.9-017CEE)
![Prometheus](https://img.shields.io/badge/Monitoring-Prometheus%20%2B%20Grafana-orange)
![Tests](https://img.shields.io/badge/Tests-42%20passing-brightgreen)

> Pipeline complet de web scraping, nettoyage, stockage et exposition des prix
> **multi-sources** (Jumia CI, DjokStore CI, CoinAfrique CI) — **ENSEA AS Data Science**

---

## Equipe

| Membre | Rôle | Responsabilités |
|--------|------|-----------------|
| KABAMBA Dolly | Data Engineer + DevOps | Scraping, nettoyage, Docker, monitoring |
| KINDO Nathan | Backend Developer + Data Analyst | API REST, base de données, tests |

**Enseignant :** Dr N'golo Konate — ENSEA

---

## Description du projet

Ce projet implémente un **pipeline de production complet** pour la collecte et l'analyse des prix sur 3 sources ivoiriennes :

1. **Scraping multi-sources** :
   - **Jumia CI** (17 catégories, max 500 items, via FlareSolverr pour contourner Cloudflare)
   - **DjokStore CI** (boutique e-commerce locale)
   - **CoinAfrique CI** (petites annonces neuf + occasion)
2. **Nettoyage intelligent** (pandas) avec détection des prix aberrants par catégorie
3. **Stockage** PostgreSQL avec **historique des prix** (`price_history`) et **matching cross-source** (produits identiques entre sources)
4. **API REST** complète avec pagination, recherche, filtres, comparaison, auth JWT
5. **Orchestration** :
   - **Airflow** est l'orchestrateur unique des workflows (pipeline quotidien, digest hebdo)
   - **Celery worker** exécute les tâches publiées par Airflow via Redis
6. **Monitoring** : Prometheus + Grafana (dashboard préconfiguré)
7. **Chatbot IA** (JumiBot) basé sur Llama 3.3 70B via Groq
8. **Alertes email** de baisse de prix + digest hebdomadaire
9. **Export** des données en CSV, Excel et JSON

---

## Architecture

```
 Jumia CI ──▶ FlareSolverr ──┐
 DjokStore CI ───────────────┤──▶ Scrapy ──▶ pandas ──▶ PostgreSQL
 CoinAfrique CI ─────────────┘        (nettoyage)           │
                                                            │
         ┌───────────────────────────────────────┐          │
         │       ORCHESTRATION                   │          ▼
         │       Airflow (DAGs + scheduler)      │   ┌──────────────┐
         └──────────────┬────────────────────────┘   │  API Flask   │
                        │                            │ (REST+Swagger│
                        ▼                            │   + Chatbot) │
                 Celery Worker                       └──────┬───────┘
                 (Redis broker)                             │
                                                   Prometheus ──▶ Grafana
```

> Voir [ARCHITECTURE.md](./ARCHITECTURE.md) pour le détail complet.

---

## Technologies

| Composant | Technologie | Version |
|-----------|-------------|---------|
| Scraping | Scrapy | 2.12+ |
| Anti-Cloudflare | FlareSolverr | latest |
| Nettoyage | pandas | 2.2.3 |
| API | Flask + SQLAlchemy + Flasgger | 3.1.0 |
| Auth | Flask-JWT-Extended + bcrypt | 4.7 |
| Base de données | PostgreSQL | 16 |
| Tâches async | Celery + Redis | 5.4 |
| Orchestration | Apache Airflow | 2.9.3 |
| Conteneurisation | Docker Compose | 3.9 |
| Monitoring | Prometheus + Grafana | 2.53 / 11.0 |
| Chatbot LLM | Groq API (Llama 3.3 70B) | - |
| Tests | pytest | 8.3.4 |
| Documentation API | Swagger / OpenAPI | via Flasgger |

---

## Installation rapide

### Avec Docker (recommandé)

```bash
git clone https://github.com/votre-username/webscraping-pipeline-comparateur-prix.git
cd webscraping-pipeline-comparateur-prix
cp env.example .env
docker compose up --build -d
```

Tous les services démarrent automatiquement :

| Service | URL | Identifiants |
|---------|-----|--------------|
| API Flask | http://localhost:5000 | - |
| Swagger UI | http://localhost:5000/docs/ | - |
| Chatbot JumiBot | http://localhost:5000/assistant | - |
| Airflow UI | http://localhost:8080 | admin / admin123 |
| Prometheus | http://localhost:9090 | - |
| Grafana | http://localhost:3000 | admin / admin123 |
| FlareSolverr | http://localhost:8191 | - |

> Voir [INSTALLATION.md](./INSTALLATION.md) pour l'installation complète et le mode développement local.

---

## Utilisation

### Lancer un scraping

```bash
# Synchrone (bloquant)
curl -X POST http://localhost:5000/scrape

# Asynchrone via Celery
curl -X POST http://localhost:5000/scrape/async

# Vérifier le statut d'une tâche
curl http://localhost:5000/tasks/{task_id}/status
```

### Consulter les données

```bash
# Liste des produits (paginée)
curl "http://localhost:5000/products?page=1&per_page=10"

# Recherche
curl "http://localhost:5000/search?q=samsung"

# Détail d'un produit
curl http://localhost:5000/products/1

# Historique des prix
curl http://localhost:5000/products/1/history

# Comparer des produits
curl "http://localhost:5000/products/compare?ids=1,5,12"

# Catégories
curl http://localhost:5000/categories
```

### Exporter les données

```bash
# CSV
curl -o export.csv "http://localhost:5000/export?format=csv"

# Excel
curl -o export.xlsx "http://localhost:5000/export?format=excel"

# JSON
curl "http://localhost:5000/export?format=json"
```

> Voir [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) pour la documentation complète de tous les endpoints.

---

## Ethique du scraping

Ce projet respecte scrupuleusement la charte éthique sur les **3 sources** (Jumia CI, DjokStore CI, CoinAfrique CI) :

- **`robots.txt` respecté** :
  - DjokStore et CoinAfrique : `ROBOTSTXT_OBEY = True` (Scrapy vérifie automatiquement)
  - Jumia : vérification **manuelle** (`DISALLOWED_PATTERNS`) car Cloudflare bloque l'accès direct au `robots.txt`
- **Délais** : 2 secondes entre chaque requête + randomisation (`RANDOMIZE_DOWNLOAD_DELAY = True`)
- **Concurrence limitée** : 1 seule requête concurrente par domaine
- **Limite d'items** : max 50 items par catégorie, **500 items au total** (`CLOSESPIDER_ITEMCOUNT = 500`)
- **User-Agent identifiable** : `ENSEA-Bot/1.0 (+https://ensea.ed.ci; educational project)`
- **Aucune donnée personnelle** collectée (seulement nom, prix, catégorie, URL)
- **Sites pré-validés** auprès de l'enseignant
- **Scraping en heures creuses** : pipeline quotidien à 2h du matin (Africa/Abidjan)

---

## Tests

```bash
# Lancer les tests
pytest tests/ -v

# Avec couverture
pytest tests/ -v --cov=scraper --cov-report=term-missing
```

Les tests couvrent :
- `clean_price()` — validation des prix par catégorie (10 cas)
- `clean_discount()` — extraction du pourcentage (6 cas)
- `clean_name()` — nettoyage des noms (7 cas)
- `remove_duplicates()` — déduplication cross-catégories (3 cas)
- `clean_dataframe()` — pipeline complet (11 cas)
- `get_stats()` — statistiques post-nettoyage (5 cas)

---

## Structure du projet

```
webscraping-pipeline-comparateur-prix/
├── api/                    # API Flask REST + chatbot IA
│   ├── app.py              # Routes REST, auth JWT, Swagger
│   ├── assistant_routes.py # Endpoints du chatbot JumiBot
│   ├── models.py           # Schéma ORM SQLAlchemy (8 tables)
│   ├── schema.sql          # Schéma SQL brut (fallback)
│   └── templates/          # Frontend HTML (accueil, boutique, ...)
├── scraper/                # Spiders Scrapy + nettoyage
│   ├── cleaner.py          # 12 étapes de nettoyage pandas
│   └── jumia_scraper/
│       └── spiders/
│           ├── spider_jumia.py         # via FlareSolverr
│           ├── spider_djokstore.py     # direct
│           └── spider_coinafrique.py   # direct
├── tasks/                  # Celery (worker exécutant)
│   ├── celery_app.py       # Config du worker
│   └── tasks.py            # Tâches (scrape, clean, alerts, match)
├── dags/                   # Airflow
│   ├── scraping_pipeline.py  # Pipeline quotidien (scrape → clean → drops → alerts → match)
│   └── weekly_digest.py      # Digest hebdomadaire
├── airflow/                # Dockerfile Airflow
├── tests/                  # Tests unitaires (42 tests)
│   └── test_cleaner.py
├── monitoring/             # Prometheus + Grafana
│   ├── prometheus.yml
│   └── grafana/provisioning/
├── docker-compose.yml      # Orchestration des services
├── Dockerfile              # Image Python multi-stage (api/worker)
├── .dockerignore           # Exclusions du contexte de build
├── requirements.txt
├── env.example             # Template de configuration
├── INSTALLATION.md
├── API_DOCUMENTATION.md
├── ARCHITECTURE.md
└── README.md
```

---

## Licence

MIT — Projet éducatif ENSEA 2026
