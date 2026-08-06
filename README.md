# 🚲 Compteurs Vélo Bruxelles
*Guide de déploiement et d'exploitation*

---

## 1. Présentation

Cette application collecte automatiquement les données des compteurs vélo de Bruxelles (API `data.mobility.brussels`), les stocke dans une base SQLite légère, et expose un dashboard web interactif avec carte.

| Composant | Détail |
|---|---|
| `collector.py` | Collecte les données de l'API et écrit dans SQLite |
| `app.py` | Serveur Flask — dashboard + API REST |
| `pyproject.toml` / `uv.lock` | Dépendances Python, gérées avec [uv](https://docs.astral.sh/uv/) |
| Base de données | SQLite dans `/data/velo.db` (volume du conteneur) |
| Fréquence | Toutes les 30 minutes via cron |
| Port web | http://localhost:8080 |

L'image est construite avec [uv](https://docs.astral.sh/uv/) (résolution et installation des dépendances Python) et peut être lancée aussi bien avec **Docker** qu'avec **Podman** — les deux moteurs sont compatibles avec le `Dockerfile` et le `docker-compose.yml` fournis. Les exemples ci‑dessous donnent la commande équivalente pour chacun ; utilisez celle qui correspond à votre installation.

---

## 2. Pré-requis

Un des deux moteurs de conteneurs suivants :

- **Docker** : Docker Desktop installé et démarré (Docker Compose est inclus)
- **Podman** : Podman Desktop / `podman` CLI, avec une machine démarrée sur Windows/macOS (`podman machine init` puis `podman machine start`) et le plugin compose (`podman compose`, qui s'appuie sur `docker-compose` s'il est présent, ou sur `podman-compose`)

Ainsi qu'un accès Internet (pour l'API mobility.brussels).

Vérifier que l'un des deux fonctionne :

```bash
# Docker
docker --version
docker compose version

# Podman
podman --version
podman machine list      # doit afficher une machine "Currently running" (Windows/macOS)
podman compose version
```

---

## 3. Structure des fichiers

Placez tous les fichiers dans un même dossier, par exemple `velo_brussels/` :

```
velo_brussels/
├── collector.py
├── app.py
├── Dockerfile
├── .dockerignore
├── entrypoint.sh
├── pyproject.toml
├── uv.lock
├── .python-version
└── docker-compose.yml
```

`pyproject.toml` et `uv.lock` remplacent l'ancien `requirements.txt` : ils définissent et verrouillent les dépendances Python (`flask`, `requests`) résolues par `uv`. Le `Dockerfile` copie ces deux fichiers et exécute `uv sync --locked` pour construire un environnement reproductible au moment du build — inutile d'installer quoi que ce soit manuellement.

---

## 4. Premier lancement

### 4.1 Build et démarrage

Dans le dossier `velo_brussels/`, exécuter :

```bash
# Docker
docker compose up -d --build

# Podman
podman compose up -d --build
```

Cette commande :

- construit l'image du conteneur (Python 3.14 + uv + Flask + cron)
- lance le conteneur en arrière-plan
- exécute une première collecte immédiatement
- active le cron pour les collectes suivantes

### 4.2 Accès au dashboard

Une fois le conteneur démarré, ouvrir dans un navigateur :

```
http://localhost:8080
```

> ✅ Attendre 20–30 secondes après le démarrage pour que la première collecte se termine.

---

## 5. Rafraîchir les données

### 5.1 Collecte automatique (cron)

La collecte se déclenche automatiquement toutes les **30 minutes**. Aucune action manuelle n'est nécessaire en utilisation normale.

### 5.2 Forcer une collecte immédiate

Pour déclencher manuellement une collecte sans attendre le cron :

```bash
# Docker
docker exec velo-brussels /app/.venv/bin/python /app/collector.py

# Podman
podman exec velo-brussels /app/.venv/bin/python /app/collector.py
```

> Le conteneur exécute Python depuis l'environnement virtuel géré par `uv` (`/app/.venv`), et non depuis un `python` installé globalement — utilisez ce chemin plutôt que `python` seul.

Il est aussi possible de déclencher une collecte depuis le dashboard lui‑même via le bouton **Actualiser**, qui appelle l'endpoint `POST /api/refresh`.

### 5.3 Rafraîchir l'interface web

L'interface ne se rafraîchit pas seule. Pour voir les nouvelles données :

- Changer la date dans le sélecteur en haut à droite (revenir sur la date du jour)
- Ou recharger la page (`F5` / `Cmd+R`)

> ⚠️ Si la date du jour n'apparaît pas dans le sélecteur, c'est que la collecte du jour n'a pas encore tourné. Forcer une collecte avec la commande ci-dessus.

---

## 6. Commandes utiles

### 6.1 Vérifier l'état du conteneur
```bash
docker compose ps      # Docker
podman compose ps      # Podman
```

### 6.2 Voir les logs en temps réel
```bash
docker compose logs -f      # Docker
podman compose logs -f      # Podman
```

### 6.3 Voir uniquement les logs de collecte
```bash
docker exec velo-brussels cat /var/log/collector.log      # Docker
podman exec velo-brussels cat /var/log/collector.log      # Podman
```

### 6.4 Vérifier que le cron tourne
```bash
# Docker
docker exec velo-brussels service cron status
docker exec velo-brussels crontab -l

# Podman
podman exec velo-brussels service cron status
podman exec velo-brussels crontab -l
```

### 6.5 Inspecter la base SQLite
```bash
docker exec -it velo-brussels sqlite3 /data/velo.db      # Docker
podman exec -it velo-brussels sqlite3 /data/velo.db      # Podman
```

Une fois dans sqlite3 :
```sql
.tables
SELECT * FROM counts ORDER BY collected_at DESC LIMIT 10;
.quit
```

### 6.6 Arrêter l'application
```bash
docker compose down      # Docker
podman compose down      # Podman
```

### 6.7 Arrêter et supprimer les données

> ⚠️ Cette commande supprime définitivement la base SQLite et tout l'historique.

```bash
docker compose down -v      # Docker
podman compose down -v      # Podman
```

---

## 7. Résolution de problèmes

### Je vois les données d'hier et pas d'aujourd'hui

Forcer une collecte manuelle :
```bash
docker exec velo-brussels /app/.venv/bin/python /app/collector.py      # Docker
podman exec velo-brussels /app/.venv/bin/python /app/collector.py      # Podman
```

Vérifier les logs pour détecter une erreur API :
```bash
docker exec velo-brussels cat /var/log/collector.log      # Docker
podman exec velo-brussels cat /var/log/collector.log      # Podman
```

### Le dashboard ne charge pas (http://localhost:8080)

Vérifier que le conteneur est bien démarré :
```bash
docker compose ps      # Docker
podman compose ps      # Podman
```

Sous Podman sur Windows/macOS, vérifier aussi que la machine tourne :
```bash
podman machine list
podman machine start     # si elle n'est pas "Currently running"
```

Relancer si nécessaire :
```bash
docker compose up -d      # Docker
podman compose up -d      # Podman
```

### Changer la fréquence de collecte

Modifier la ligne cron dans `entrypoint.sh` :

```bash
# Toutes les 30 min (défaut)
*/30 * * * * $PYTHON /app/collector.py >> /var/log/collector.log 2>&1

# Toutes les heures
0 * * * * $PYTHON /app/collector.py >> /var/log/collector.log 2>&1

# Toutes les 15 min
*/15 * * * * $PYTHON /app/collector.py >> /var/log/collector.log 2>&1
```

Puis reconstruire le conteneur :
```bash
docker compose up -d --build      # Docker
podman compose up -d --build      # Podman
```

### Mettre à jour les dépendances Python

Les dépendances sont verrouillées dans `uv.lock`. Pour changer une version, éditer `pyproject.toml` puis régénérer le lock avec `uv` (installé localement, ou via `uvx`) :

```bash
uv lock
```

Committer le nouveau `uv.lock`, puis reconstruire l'image (voir ci-dessus) pour que `uv sync --locked` installe les versions mises à jour.

---

## 8. Architecture

Flux de données :

```
API mobility.brussels
        │
        ▼
  collector.py  (cron 30 min, exécuté par /app/.venv/bin/python)
        │
        ▼
   /data/velo.db  (SQLite)
        │
        ▼
     app.py  (Flask)
        │
        ▼
http://localhost:8080  (Leaflet + JS)
```

Au build de l'image, `uv sync --locked` lit `pyproject.toml` et `uv.lock` pour créer l'environnement virtuel `/app/.venv` utilisé ensuite par `entrypoint.sh` pour lancer aussi bien la collecte initiale, le job cron, que le serveur Flask.

---

*— Fin du document —*
