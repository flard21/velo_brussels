FROM python:3.12-slim

# Pas de fichiers .pyc, logs non bufferisés
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dépendances système minimales (sqlite3 inclus dans python:slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY collector.py .
COPY app.py .
COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

# Volume pour la base SQLite
VOLUME ["/data"]

EXPOSE 5000

ENTRYPOINT ["./entrypoint.sh"]
