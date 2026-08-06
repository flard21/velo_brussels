#!/bin/bash
set -e

# Dossier de données
mkdir -p /data

# cron tourne avec un PATH minimal : on référence directement l'interpréteur
# du venv créé par `uv sync` au build plutôt que de dépendre de `uv run`
# (qui a besoin de retrouver la racine du projet depuis le cwd du job cron).
PYTHON=/app/.venv/bin/python

echo "=== Collecte initiale ==="
$PYTHON /app/collector.py

echo "=== Configuration du cron (toutes les 30 min) ==="
# Écriture du job cron — toutes les 30 minutes
echo "*/30 * * * * $PYTHON /app/collector.py >> /var/log/collector.log 2>&1" \
    | crontab -

# Démarrage du démon cron en arrière-plan
service cron start

echo "=== Démarrage du serveur web ==="
exec $PYTHON /app/app.py
