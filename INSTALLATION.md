# Installation

## Prérequis

| Outil | Version minimale | Vérification |
|-------|-----------------|--------------|
| Python | 3.10+ | `python --version` |
| Docker | 20.10+ | `docker --version` |
| Docker Compose | 2.0+ | `docker compose version` |
| Git | 2.30+ | `git --version` |

---

## Option 1 — Lancement avec Docker (recommandé)

### 1. Cloner le repository

```bash
git clone https://github.com/votre-username/webscraping-pipeline-comparateur-prix.git
cd webscraping-pipeline-comparateur-prix
```

### 2. Configurer les variables d'environnement

```bash
cp env.example .env
```

Modifier `.env` si nécessaire (les valeurs par défaut fonctionnent pour le développement).

### 3. Lancer tous les services

```bash
docker compose up --build -d
```

### 4. Vérifier que tout fonctionne

```bash
# Vérifier les containers
docker compose ps

# Tester l'API
curl http://localhost:5000/health
```

### Services accessibles

| Service | URL | Description |
|---------|-----|-------------|
| API Flask | http://localhost:5000 | API REST principale |
| Swagger UI | http://localhost:5000/docs/ | Documentation interactive |
| Prometheus | http://localhost:9090 | Métriques |
| Grafana | http://localhost:3000 | Dashboard monitoring |
| PostgreSQL | localhost:5433 | Base de données |
| Redis | localhost:6379 | Broker Celery |

**Grafana** : login par défaut `admin` / `admin123`

### 5. Lancer un premier scraping

```bash
# Via l'API (synchrone)
curl -X POST http://localhost:5000/scrape

# Via Celery (asynchrone)
curl -X POST http://localhost:5000/scrape/async
```

### 6. Arrêter les services

```bash
docker compose down

# Pour supprimer aussi les volumes (données)
docker compose down -v
```

---

## Option 2 — Installation locale (développement)

### 1. Créer un environnement virtuel

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Lancer PostgreSQL et Redis

Vous avez besoin d'une instance PostgreSQL et Redis. Avec Docker :

```bash
docker compose up postgres redis -d
```

### 4. Configurer les variables d'environnement

```bash
cp env.example .env
```

Ajuster `DATABASE_URL` si votre PostgreSQL n'est pas sur le port 5433.

### 5. Lancer le scraping manuellement

```bash
cd scraper
scrapy crawl jumia_ci
cd ..
```

### 6. Insérer les données en base

```bash
python insert_manual.py
```

### 7. Lancer l'API

```bash
cd api
python app.py
```

L'API est accessible sur http://localhost:5000

### 8. Lancer Celery (optionnel)

```bash
# Worker (dans un terminal séparé)
celery -A tasks.celery_app worker --loglevel=info

# Beat — planificateur (dans un autre terminal)
celery -A tasks.celery_app beat --loglevel=info
```

---

## Dépannage

| Problème | Solution |
|----------|----------|
| `connection refused` sur PostgreSQL | Vérifier que le container postgres tourne : `docker compose ps` |
| `ModuleNotFoundError` | Activer le venv : `venv\Scripts\activate` |
| Scraping retourne 0 items | Jumia CI peut bloquer les requêtes — vérifier `robots.txt` |
| Grafana sans dashboard | Accéder à http://localhost:3000, le dashboard est provisionné automatiquement |
| Port 5000 déjà utilisé | Modifier le port dans `docker-compose.yml` (section `api.ports`) |

---

## Structure des données

Après un scraping réussi :

1. `scraper/raw_data.json` — Données brutes extraites
2. `scraper/clean_data.json` — Données nettoyées
3. PostgreSQL — Tables `products` et `price_history` alimentées
