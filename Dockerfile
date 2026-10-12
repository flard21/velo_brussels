FROM python:3.14-slim

# Pas de fichiers .pyc, logs non bufferisés
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Binaire uv (statique, copié depuis l'image officielle — pas d'installation via pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Dépendances système minimales (sqlite3 inclus dans python:slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
        cron ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# CA supplémentaires (ex. proxy d'inspection TLS d'entreprise) — dossier vide par
# défaut (voir .gitignore), no-op si aucun certificat n'y est déposé localement.
COPY certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV UV_SYSTEM_CERTS=1

# Dépendances Python — couche mise en cache séparément du code applicatif
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

# Code applicatif
COPY collector.py .
COPY app.py .
COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

# Volume pour la base SQLite
VOLUME ["/data"]

EXPOSE 5000

ENTRYPOINT ["./entrypoint.sh"]
