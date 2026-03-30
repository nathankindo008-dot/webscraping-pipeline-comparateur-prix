# Comparateur de Prix — Jumia CI

![Niveau visé](https://img.shields.io/badge/Niveau-OR%20🥇-gold)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![Flask](https://img.shields.io/badge/API-Flask-lightgrey)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![Scrapy](https://img.shields.io/badge/Scraping-Scrapy-green)
![PostgreSQL](https://img.shields.io/badge/DB-PostgreSQL%2016-336791)
![Celery](https://img.shields.io/badge/Async-Celery%20%2B%20Redis-red)
![Prometheus](https://img.shields.io/badge/Monitoring-Prometheus%20%2B%20Grafana-orange)

> Pipeline complet de web scraping, nettoyage, stockage et exposition des prix
> de produits Jumia Côte d'Ivoire — **ENSEA AS Data Science**

---

## Equipe

| Membre | Rôle | Responsabilités |
|--------|------|-----------------|
| KABAMBA Dolly | Data Engineer + DevOps | Scraping, nettoyage, Docker, monitoring |
| KINDO Nathan | Backend Developer + Data Analyst | API REST, base de données, tests |

**Enseignant :** Dr N'golo Konate — ENSEA

---

## Description du projet

Ce projet implémente un **pipeline de production complet** pour la collecte et l'analyse des prix sur Jumia Côte d'Ivoire :

1. **Scraping automatisé** de 17 catégories de produits (max 500 items)
2. **Nettoyage intelligent** avec détection des prix aberrants par catégorie
3. **Stockage** dans PostgreSQL avec historique des prix
4. **API REST** complète avec pagination, recherche, filtres et comparaison
5. **Tâches planifiées** via Celery Beat (scraping quotidien à 2h)
6. **Monitoring** avec Prometheus + Grafana (dashboard préconfiguré)
7. **Export** des données en CSV, Excel et JSON

---

## Architecture

```
Jumia CI ──▶ Scrapy ──▶ pandas (nettoyage) ──▶ PostgreSQL
                 ▲                                    │
           Celery Beat                           API Flask
           (planification)                     (REST + Swagger)
                                                      │
                                               Prometheus ──▶ Grafana
```

> Voir [ARCHITECTURE.md](./ARCHITECTURE.md) pour le détail complet.

---

## Technologies

| Composant | Technologie | Version |
|-----------|-------------|---------|
| Scraping | Scrapy | 2.11 |
| Nettoyage | pandas | 2.2 |
| API | Flask + SQLAlchemy + Flasgger | 3.1 |
| Base de données | PostgreSQL | 16 |
| Tâches async | Celery + Redis | 5.4 |
| Conteneurisation | Docker Compose | 3.9 |
| Monitoring | Prometheus + Grafana | 2.53 / 11.0 |
| Tests | pytest | 8.3 |
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

| Service | URL |
|---------|-----|
| API Flask | http://localhost:5000 |
| Swagger UI | http://localhost:5000/docs/ |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin123) |

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

Ce projet respecte scrupuleusement la charte éthique :

- `robots.txt` respecté (`ROBOTSTXT_OBEY = True`)
- Délai de 2 secondes entre chaque requête + randomisation
- 1 seule requête concurrente par domaine
- Maximum 50 items par catégorie, 500 items au total
- User-Agent identifiable : `ENSEA-Educational-Bot/1.0`
- Aucune donnée personnelle collectée
- Site pré-validé auprès de l'enseignant

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
├── api/                    # API Flask REST
│   ├── app.py
│   ├── models.py
│   ├── schemas.py
│   └── schema.sql
├── scraper/                # Spider Scrapy + nettoyage
│   ├── cleaner.py
│   └── jumia_scraper/
│       └── spiders/
│           └── spider_jumia.py
├── tasks/                  # Celery (worker + beat)
│   ├── celery_app.py
│   ├── tasks.py
│   └── beat_schedule.py
├── tests/                  # Tests unitaires
│   └── test_cleaner.py
├── monitoring/             # Prometheus + Grafana
│   ├── prometheus.yml
│   └── grafana/provisioning/
├── docker-compose.yml      # Orchestration 7 services
├── Dockerfile              # Image Python multi-stage
├── requirements.txt
├── INSTALLATION.md
├── API_DOCUMENTATION.md
├── ARCHITECTURE.md
└── README.md
```

---

## Licence

MIT — Projet éducatif ENSEA 2026
