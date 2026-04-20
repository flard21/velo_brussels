# 🚲 Compteurs Vélo Bruxelles
*Guide de déploiement et d'exploitation*

---

## 1. Présentation

Cette application collecte automatiquement les données des compteurs vélo de Bruxelles (API `data.mobility.brussels`), les stocke dans une base SQLite légère, et expose un dashboard web interactif avec carte.

| Composant | Détail |
|---|---|
| `collector.py` | Collecte les données de l'API et écrit dans SQLite |
| `app.py` | Serveur Flask — dashboard + API REST |
| Base de données | SQLite dans `/data/velo.db` (volume Docker) |
| Fréquence | Toutes les 30 minutes via cron |
| Port web | http://localhost:8080 |

---

## 2. Pré-requis

- Docker Desktop installé et démarré
- Docker Compose (inclus dans Docker Desktop)
- Accès Internet (pour l'API mobility.brussels)

Vérifier que Docker fonctionne :

```bash
docker --version
docker compose version
```

---

## 3. Structure des fichiers

Placez tous les fichiers dans un même dossier, par exemple `velo_brussels/` :

```
velo_brussels/
├── collector.py
├── app.py
├── Dockerfile
├── entrypoint.sh
├── requirements.txt
└── docker-compose.yml
```

---

## 4. Premier lancement

### 4.1 Build et démarrage

Dans le dossier `velo_brussels/`, exécuter :

```bash
docker compose up -d --build
```

Cette commande :
- construit l'image Docker (Python + Flask + cron)
- lance le container en arrière-plan
- exécute une première collecte immédiatement
- active le cron pour les collectes suivantes

### 4.2 Accès au dashboard

Une fois le container démarré, ouvrir dans un navigateur :

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
docker exec velo-brussels python /app/collector.py
```

### 5.3 Rafraîchir l'interface web

L'interface ne se rafraîchit pas seule. Pour voir les nouvelles données :

- Changer la date dans le sélecteur en haut à droite (revenir sur la date du jour)
- Ou recharger la page (`F5` / `Cmd+R`)

> ⚠️ Si la date du jour n'apparaît pas dans le sélecteur, c'est que la collecte du jour n'a pas encore tourné. Forcer une collecte avec la commande ci-dessus.

---

## 6. Commandes utiles

### 6.1 Vérifier l'état du container
```bash
docker compose ps
```

### 6.2 Voir les logs en temps réel
```bash
docker compose logs -f
```

### 6.3 Voir uniquement les logs de collecte
```bash
docker exec velo-brussels cat /var/log/collector.log
```

### 6.4 Vérifier que le cron tourne
```bash
docker exec velo-brussels service cron status
docker exec velo-brussels crontab -l
```

### 6.5 Inspecter la base SQLite
```bash
docker exec -it velo-brussels sqlite3 /data/velo.db
```

Une fois dans sqlite3 :
```sql
.tables
SELECT * FROM counts ORDER BY collected_at DESC LIMIT 10;
.quit
```

### 6.6 Arrêter l'application
```bash
docker compose down
```

### 6.7 Arrêter et supprimer les données

> ⚠️ Cette commande supprime définitivement la base SQLite et tout l'historique.

```bash
docker compose down -v
```

---

## 7. Résolution de problèmes

### Je vois les données d'hier et pas d'aujourd'hui

Forcer une collecte manuelle :
```bash
docker exec velo-brussels python /app/collector.py
```

Vérifier les logs pour détecter une erreur API :
```bash
docker exec velo-brussels cat /var/log/collector.log
```

### Le dashboard ne charge pas (http://localhost:8080)

Vérifier que le container est bien démarré :
```bash
docker compose ps
```

Relancer si nécessaire :
```bash
docker compose up -d
```

### Changer la fréquence de collecte

Modifier la ligne cron dans `entrypoint.sh` :

```bash
# Toutes les 30 min (défaut)
*/30 * * * * python /app/collector.py >> /var/log/collector.log 2>&1

# Toutes les heures
0 * * * * python /app/collector.py >> /var/log/collector.log 2>&1

# Toutes les 15 min
*/15 * * * * python /app/collector.py >> /var/log/collector.log 2>&1
```

Puis reconstruire le container :
```bash
docker compose up -d --build
```

---

## 8. Architecture

Flux de données :

```
API mobility.brussels
        │
        ▼
  collector.py  (cron 30 min)
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

---

*— Fin du document —*
