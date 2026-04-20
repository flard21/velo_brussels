#!/bin/bash
set -e

# Dossier de données
mkdir -p /data

echo "=== Collecte initiale ==="
python /app/collector.py

echo "=== Configuration du cron (toutes les 30 min) ==="
# Écriture du job cron — toutes les 30 minutes
echo "*/30 * * * * python /app/collector.py >> /var/log/collector.log 2>&1" \
    | crontab -

# Démarrage du démon cron en arrière-plan
service cron start

echo "=== Démarrage du serveur web ==="
exec python /app/app.py
