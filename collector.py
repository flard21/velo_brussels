"""
Collecteur de données vélo Bruxelles → SQLite
Appelé périodiquement par cron ou au démarrage du container.
"""

import requests
import sqlite3
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURATION ---
DB_PATH = os.environ.get("DB_PATH", "/data/velo.db")


def init_db(conn: sqlite3.Connection):
    """Crée les tables si elles n'existent pas encore."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id   TEXT PRIMARY KEY,
            location    TEXT,
            latitude    REAL,
            longitude   REAL
        );

        CREATE TABLE IF NOT EXISTS counts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id    TEXT NOT NULL,
            collected_at TEXT NOT NULL,          -- ISO‑8601 UTC
            cnt_time     TEXT,                   -- horodatage renvoyé par l'API
            hour_cnt     INTEGER,
            day_cnt      INTEGER,
            year_cnt     INTEGER,
            FOREIGN KEY (device_id) REFERENCES devices(device_id)
        );

        -- Index pour accélérer les requêtes par date
        CREATE INDEX IF NOT EXISTS idx_counts_device_date
            ON counts (device_id, collected_at);
    """)

    # Migration : unicité (device_id, cnt_time) pour une déduplication atomique
    # (cron et /api/refresh peuvent tourner en même temps). Les bases créées
    # avant cet index peuvent contenir des doublons et des cnt_time vides, à
    # nettoyer avant de pouvoir le créer. cnt_time NULL reste autorisé en
    # plusieurs exemplaires (NULL est distinct pour un index UNIQUE SQLite).
    has_unique = conn.execute("""
        SELECT 1 FROM sqlite_master
        WHERE type = 'index' AND name = 'idx_counts_device_cnt_time'
    """).fetchone()
    if not has_unique:
        conn.executescript("""
            UPDATE counts SET cnt_time = NULL WHERE cnt_time = '';
            DELETE FROM counts
            WHERE cnt_time IS NOT NULL
              AND id NOT IN (
                  SELECT MIN(id) FROM counts
                  WHERE cnt_time IS NOT NULL
                  GROUP BY device_id, cnt_time
              );
            CREATE UNIQUE INDEX idx_counts_device_cnt_time
                ON counts (device_id, cnt_time);
        """)
    conn.commit()


def clean_date(cdate: str) -> str:
    """Normalise le format de date renvoyé par l'API."""
    try:
        dt = datetime.fromisoformat(cdate.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return cdate


def upsert_device(conn: sqlite3.Connection, device_id: str, location: str,
                  lat: float, lon: float):
    conn.execute("""
        INSERT INTO devices (device_id, location, latitude, longitude)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            location  = excluded.location,
            latitude  = excluded.latitude,
            longitude = excluded.longitude
    """, (device_id, location, lat, lon))


def insert_count(conn: sqlite3.Connection, device_id: str, cnt_time: str,
                 hour_cnt, day_cnt, year_cnt):
    # L'index UNIQUE (device_id, cnt_time) ignore un relevé déjà enregistré ;
    # un cnt_time absent est stocké NULL et toujours inséré.
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute("""
        INSERT OR IGNORE INTO counts
            (device_id, collected_at, cnt_time, hour_cnt, day_cnt, year_cnt)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (device_id, now_utc, cnt_time or None, hour_cnt, day_cnt, year_cnt))
    return cursor.rowcount == 1


def fetch_device_live(device_id: str):
    """Fetch live counts for a single device from the API."""
    url_count = (
        f"https://data.mobility.brussels/bike/api/counts/"
        f"?request=live&featureID={device_id}"
    )
    try:
        r = requests.get(url_count, timeout=15, verify=False)
        r.raise_for_status()
        return device_id, r.json()
    except Exception as e:
        return device_id, e


def get_bike_data(conn: sqlite3.Connection):
    url_devices = "https://data.mobility.brussels/bike/api/counts/?request=devices"

    try:
        resp = requests.get(url_devices, timeout=30, verify=False)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"[ERROR] Récupération des appareils : {e}")
        return 0

    inserted = 0
    devices_to_fetch = []

    # Update devices metadata
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom  = feature.get("geometry", {})

        device_id = props.get("device_name", "")
        location  = props.get("road_fr", "")
        coords    = geom.get("coordinates", [0, 0])
        lon, lat  = coords[0], coords[1]

        upsert_device(conn, device_id, location, lat, lon)
        devices_to_fetch.append(device_id)

    # Commit avant les appels réseau : sinon le verrou d'écriture SQLite reste
    # tenu pendant toute la collecte et bloque une collecte concurrente.
    conn.commit()

    # Fetch live counts concurrently (max 10 threads)
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_device = {
            executor.submit(fetch_device_live, dev_id): dev_id
            for dev_id in devices_to_fetch
        }
        for future in future_to_device:
            dev_id = future_to_device[future]
            try:
                device_id, res = future.result()
                results[device_id] = res
            except Exception as e:
                results[dev_id] = e

    # Sequentially write counts to sqlite in the main thread
    for device_id in devices_to_fetch:
        res = results.get(device_id)
        if isinstance(res, Exception) or res is None:
            print(f"  ✗  {device_id} : {res}")
            continue

        try:
            cnt_time  = clean_date(res["data"].get("cnt_time", ""))
            hour_cnt  = res["data"].get("hour_cnt")
            day_cnt   = res["data"].get("day_cnt")
            year_cnt  = res["data"].get("year_cnt")

            is_new = insert_count(conn, device_id, cnt_time, hour_cnt, day_cnt, year_cnt)
            if is_new:
                print(f"  ✓  {device_id} (nouveau)")
                inserted += 1
            else:
                print(f"  ~  {device_id} (déjà à jour)")
        except Exception as e:
            print(f"  ✗  {device_id} (écriture base) : {e}")

    conn.commit()
    return inserted


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    print(f"[{datetime.now().isoformat()}] Collecte démarrée → {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        n = get_bike_data(conn)

    print(f"[{datetime.now().isoformat()}] Collecte terminée — {n} compteurs enregistrés.\n")


if __name__ == "__main__":
    main()
