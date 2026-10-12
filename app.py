"""
Serveur Flask — Rapport journalier vélo Bruxelles
Expose :
  GET /           → dashboard HTML avec carte Leaflet
  GET /api/daily  → JSON  {date, device_id, location, lat, lon, day_cnt, hour_cnt}
  GET /api/dates  → liste des dates disponibles
"""

import os
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template_string, request

DB_PATH = os.environ.get("DB_PATH", "/data/velo.db")

# Les compteurs (day_cnt) sont remis à zéro à minuit heure de Bruxelles,
# alors que collected_at est stocké en UTC : une "journée" doit donc être
# découpée selon Europe/Brussels, pas selon la date UTC.
TZ = ZoneInfo("Europe/Brussels")
DB_FMT = "%Y-%m-%d %H:%M:%S"

app = Flask(__name__)


def today_brussels() -> str:
    return datetime.now(TZ).date().isoformat()


def day_bounds_utc(day: str) -> tuple[str, str]:
    """Bornes UTC [début, fin) de la journée `day` (YYYY-MM-DD) à Bruxelles."""
    d = date.fromisoformat(day)
    start = datetime.combine(d, time.min, TZ).astimezone(timezone.utc)
    end = datetime.combine(d + timedelta(days=1), time.min, TZ).astimezone(timezone.utc)
    return start.strftime(DB_FMT), end.strftime(DB_FMT)


def requested_day_bounds():
    """Lit ?date=YYYY-MM-DD (défaut : aujourd'hui à Bruxelles) → bornes UTC, ou None si invalide."""
    day = request.args.get("date") or today_brussels()
    try:
        return day_bounds_utc(day)
    except ValueError:
        return None


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- API ----------

@app.get("/api/dates")
def api_dates():
    """Retourne les dates (YYYY-MM-DD, heure de Bruxelles) pour lesquelles des données existent."""
    # SQLite ne gère pas les fuseaux : on récupère les heures UTC distinctes
    # (les décalages DST sont des heures entières, donc la conversion est exacte)
    # et on les ramène à la date locale en Python.
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT substr(collected_at, 1, 13) AS hour
            FROM counts
        """).fetchall()
    days = {
        datetime.strptime(r["hour"], "%Y-%m-%d %H")
        .replace(tzinfo=timezone.utc)
        .astimezone(TZ)
        .date()
        .isoformat()
        for r in rows
    }
    return jsonify(sorted(days, reverse=True)[:30])


@app.get("/api/daily")
def api_daily():
    """
    Retourne, pour une date donnée (param ?date=YYYY-MM-DD),
    le dernier relevé de chaque compteur ainsi que sa localisation,
    et le pic horaire (peak_hour_cnt) observé sur la journée.
    Par défaut : aujourd'hui (heure de Bruxelles).
    """
    bounds = requested_day_bounds()
    if bounds is None:
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400
    start, end = bounds

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                d.device_id,
                d.location,
                d.latitude  AS lat,
                d.longitude AS lon,
                c.collected_at,
                c.cnt_time,
                c.hour_cnt,
                c.day_cnt,
                c.year_cnt,
                (
                    SELECT MAX(c3.hour_cnt) FROM counts c3
                    WHERE c3.device_id = d.device_id
                      AND c3.collected_at >= :start AND c3.collected_at < :end
                ) AS peak_hour_cnt
            FROM devices d
            JOIN counts c ON c.device_id = d.device_id
            WHERE c.id = (
                SELECT id FROM counts c2
                WHERE c2.device_id = d.device_id
                  AND c2.collected_at >= :start AND c2.collected_at < :end
                ORDER BY c2.collected_at DESC
                LIMIT 1
            )
            ORDER BY c.day_cnt DESC
        """, {"start": start, "end": end}).fetchall()

    result = [dict(r) for r in rows]
    return jsonify(result)


@app.get("/api/history")
def api_history():
    """
    Retourne l'historique horaire des passages d'un compteur donné (?device_id=...)
    pour une date donnée (?date=YYYY-MM-DD, heure de Bruxelles).
    """
    device_id = request.args.get("device_id")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    bounds = requested_day_bounds()
    if bounds is None:
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400
    start, end = bounds

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                collected_at,
                cnt_time,
                hour_cnt,
                day_cnt,
                year_cnt
            FROM counts
            WHERE device_id = ?
              AND collected_at >= ? AND collected_at < ?
            ORDER BY collected_at ASC
        """, (device_id, start, end)).fetchall()

    result = [dict(r) for r in rows]
    return jsonify(result)


@app.post("/api/refresh")
def api_refresh():
    """
    Déclenche manuellement une collecte de données depuis l'API.
    """
    try:
        import collector
        with get_conn() as conn:
            collector.init_db(conn)
            inserted = collector.get_bike_data(conn)
        return jsonify({"status": "success", "inserted": inserted})
    except Exception as e:
        app.logger.error("Refresh failed: %s", e)
        return jsonify({"status": "error", "message": "Collection failed"}), 500


# ---------- DASHBOARD ----------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Compteurs Vélo · Bruxelles</title>

<!-- Fonts & Libraries -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js"
        integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"
        crossorigin="anonymous"></script>

<style>
  :root {
    --bg-main:      #0b0f19;
    --bg-card:      rgba(22, 30, 49, 0.65);
    --border-color: rgba(255, 255, 255, 0.08);
    --text-primary: #f8fafc;
    --text-muted:   #94a3b8;
    --accent-blue:  #3b82f6;
    --accent-green: #10b981;
    --accent-red:   #f43f5e;
    --accent-gold:  #f59e0b;
    --font-outfit:  'Outfit', sans-serif;
    --font-inter:   'Inter', sans-serif;
  }
  
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg-main);
    color: var(--text-primary);
    font-family: var(--font-inter);
    height: 100vh;
    display: grid;
    grid-template-rows: 70px 100px 1fr;
    grid-template-areas:
      "header"
      "stats"
      "main";
    overflow: hidden;
  }

  /* ── Header ── */
  header {
    grid-area: header;
    background: rgba(15, 23, 42, 0.8);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
    z-index: 10;
  }

  .logo-wrap {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .logo-icon {
    font-size: 28px;
    filter: drop-shadow(0 0 8px var(--accent-green));
  }

  header h1 {
    font-family: var(--font-outfit);
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.5px;
  }

  header h1 span { color: var(--accent-green); }

  .live-badge {
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid var(--accent-green);
    color: var(--accent-green);
    font-family: var(--font-outfit);
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 1px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .live-pulse {
    width: 6px;
    height: 6px;
    background-color: var(--accent-green);
    border-radius: 50%;
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
    animation: pulse 1.6s infinite;
  }

  @keyframes pulse {
    0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
    70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
    100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
  }

  .date-picker-wrap {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .date-picker-label {
    font-size: 13px;
    color: var(--text-muted);
  }

  #datePicker {
    background: rgba(30, 41, 59, 0.8);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    color: var(--text-primary);
    font-family: var(--font-inter);
    font-size: 13px;
    font-weight: 500;
    padding: 6px 12px;
    cursor: pointer;
    outline: none;
    transition: all 0.2s ease;
  }

  #datePicker:focus { border-color: var(--accent-blue); box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2); }

  /* ── Stats Banner ── */
  .stats-banner {
    grid-area: stats;
    background: rgba(11, 15, 25, 0.5);
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    padding: 12px 24px;
    border-bottom: 1px solid var(--border-color);
  }

  .stat-card {
    background: var(--bg-card);
    backdrop-filter: blur(8px);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 12px 18px;
    display: flex;
    align-items: center;
    gap: 16px;
    transition: transform 0.2s ease, border-color 0.2s ease;
  }

  .stat-card:hover {
    transform: translateY(-2px);
    border-color: rgba(255, 255, 255, 0.15);
  }

  .stat-icon {
    font-size: 24px;
    width: 44px;
    height: 44px;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .stat-details {
    display: flex;
    flex-direction: column;
  }

  .stat-card .label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    font-weight: 500;
    margin-bottom: 2px;
  }

  .stat-card .value {
    font-family: var(--font-outfit);
    font-size: 20px;
    font-weight: 700;
  }

  .stat-card .sub-value {
    font-size: 11px;
    color: var(--text-muted);
    white-space: nowrap;
    text-overflow: ellipsis;
    overflow: hidden;
    max-width: 170px;
  }

  /* ── Main Area ── */
  main {
    grid-area: main;
    display: grid;
    grid-template-columns: 360px 1fr;
    overflow: hidden;
    position: relative;
  }

  /* ── Sidebar ── */
  aside {
    background: rgba(15, 23, 42, 0.4);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .sidebar-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .sidebar-header .label {
    font-family: var(--font-outfit);
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }

  #totalBadge {
    font-size: 12px;
    background: rgba(59, 130, 246, 0.1);
    color: var(--accent-blue);
    border: 1px solid rgba(59, 130, 246, 0.2);
    padding: 2px 8px;
    border-radius: 12px;
    font-weight: 500;
  }

  .search-box {
    padding: 12px 20px;
    border-bottom: 1px solid var(--border-color);
    position: relative;
  }

  #searchInput {
    width: 100%;
    background: rgba(30, 41, 59, 0.6);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    color: var(--text-primary);
    font-family: var(--font-inter);
    font-size: 13px;
    padding: 8px 12px 8px 36px;
    outline: none;
    transition: all 0.2s ease;
  }

  #searchInput:focus {
    background: rgba(30, 41, 59, 0.9);
    border-color: var(--accent-blue);
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
  }

  .search-icon {
    position: absolute;
    left: 32px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 14px;
    color: var(--text-muted);
    pointer-events: none;
  }

  #counterList {
    overflow-y: auto;
    flex: 1;
    scrollbar-width: thin;
    scrollbar-color: rgba(255, 255, 255, 0.1) transparent;
  }

  .counter-item {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-color);
    cursor: pointer;
    transition: all 0.2s ease;
    position: relative;
  }

  .counter-item:hover {
    background: rgba(255, 255, 255, 0.02);
  }

  .counter-item.active {
    background: rgba(59, 130, 246, 0.06);
  }

  .counter-item.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    background: var(--accent-blue);
    border-radius: 0 4px 4px 0;
  }

  .counter-name {
    font-family: var(--font-outfit);
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 3px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .counter-location {
    font-size: 11px;
    color: var(--text-muted);
    margin-bottom: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .counter-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }

  .stat {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .stat-label {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
  }

  .stat-value {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .stat-value.day   { color: var(--accent-green); }
  .stat-value.hour  { color: var(--accent-gold); }

  .bar-wrap {
    margin-top: 10px;
    height: 4px;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 2px;
    overflow: hidden;
  }

  .bar-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent-blue), var(--accent-green));
    border-radius: 2px;
    transition: width 0.4s ease;
  }

  /* ── Map ── */
  #map {
    width: 100%;
    height: 100%;
    background: #0f172a;
  }

  /* ── Floating Detail Panel ── */
  .detail-panel {
    position: absolute;
    top: 20px;
    right: 20px;
    bottom: 20px;
    width: 420px;
    background: rgba(15, 23, 42, 0.85);
    backdrop-filter: blur(16px);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
    transform: translateX(460px);
    transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    overflow: hidden;
  }

  .detail-panel.open {
    transform: translateX(0);
  }

  .detail-header {
    padding: 20px;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
  }

  .detail-title-wrap {
    max-width: 320px;
  }

  .detail-title {
    font-family: var(--font-outfit);
    font-size: 18px;
    font-weight: 700;
    color: var(--accent-blue);
    margin-bottom: 4px;
  }

  .detail-subtitle {
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.4;
  }

  .close-btn {
    background: rgba(255, 255, 255, 0.05);
    border: none;
    color: var(--text-primary);
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background 0.2s ease;
  }

  .close-btn:hover {
    background: rgba(255, 255, 255, 0.15);
  }

  .detail-body {
    padding: 20px;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 20px;
    overflow-y: auto;
  }

  .detail-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }

  .detail-stat-card {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 12px 8px;
    text-align: center;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .detail-stat-card .v {
    font-family: var(--font-outfit);
    font-size: 18px;
    font-weight: 700;
  }

  .detail-stat-card .v.hour { color: var(--accent-gold); }
  .detail-stat-card .v.day  { color: var(--accent-green); }
  .detail-stat-card .v.year { color: var(--text-primary); }

  .detail-stat-card .l {
    font-size: 9px;
    text-transform: uppercase;
    color: var(--text-muted);
    font-weight: 500;
    letter-spacing: 0.5px;
  }

  .chart-section {
    flex: 1;
    min-height: 220px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .chart-title {
    font-family: var(--font-outfit);
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
  }

  .chart-container {
    flex: 1;
    position: relative;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 10px;
    padding: 10px;
    border: 1px solid var(--border-color);
  }

  .no-chart-data {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    color: var(--text-muted);
    text-align: center;
    padding: 20px;
  }

  /* ── Loading Overlay ── */
  #loader {
    position: fixed;
    inset: 0;
    background: var(--bg-main);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    z-index: 9999;
    transition: opacity 0.4s ease;
  }

  #loader.hidden { opacity: 0; pointer-events: none; }

  .spinner {
    width: 48px;
    height: 48px;
    border: 3px solid rgba(255, 255, 255, 0.05);
    border-top-color: var(--accent-green);
    border-radius: 50%;
    animation: spin 0.8s cubic-bezier(0.5, 0.1, 0.5, 0.9) infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .loader-text {
    font-family: var(--font-outfit);
    font-size: 14px;
    color: var(--text-muted);
    font-weight: 500;
    letter-spacing: 0.5px;
  }

  /* Custom map styling & controls */
  .leaflet-bar {
    border: 1px solid var(--border-color) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
  }
  .leaflet-bar a {
    background-color: rgba(15, 23, 42, 0.9) !important;
    color: var(--text-primary) !important;
    border-bottom: 1px solid var(--border-color) !important;
    transition: background-color 0.2s;
  }
  .leaflet-bar a:hover {
    background-color: rgba(30, 41, 59, 0.9) !important;
  }
</style>
</head>
<body>

<div id="loader">
  <div class="spinner"></div>
  <div class="loader-text">Chargement des données...</div>
</div>

<header>
  <div class="logo-wrap">
    <span class="logo-icon">🚲</span>
    <h1>Vélo <span>Bruxelles</span></h1>
  </div>
  <div style="display: flex; align-items: center; gap: 12px;">
    <div id="lastUpdate" style="font-size: 12px; color: var(--text-muted); background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); padding: 4px 12px; border-radius: 8px; display: none;"></div>
    <button id="refreshBtn" onclick="triggerRefresh()" style="background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.2); color: var(--accent-blue); font-family: var(--font-inter); font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: all 0.2s ease;">
      <span id="refreshIcon" style="display: inline-block; transition: transform 0.3s ease;">🔄</span>
      <span id="refreshText">Actualiser</span>
    </button>
  </div>
  <div class="date-picker-wrap">
    <span class="live-badge"><span class="live-pulse"></span>live</span>
    <span class="date-picker-label">Date :</span>
    <input type="date" id="datePicker">
  </div>
</header>

<section class="stats-banner">
  <div class="stat-card">
    <div class="stat-icon" style="color: var(--accent-green);">🚲</div>
    <div class="stat-details">
      <span class="label">Total Passages</span>
      <span class="value" id="statTotal">—</span>
    </div>
  </div>
  <div class="stat-card">
    <div class="stat-icon" style="color: var(--accent-gold);">⚡</div>
    <div class="stat-details">
      <span class="label">Pic Horaire</span>
      <span class="value" id="statPeakHour">—</span>
    </div>
  </div>
  <div class="stat-card">
    <div class="stat-icon" style="color: var(--accent-blue);">🏆</div>
    <div class="stat-details">
      <span class="label">Top Compteur</span>
      <span class="value" id="statBusiestCounter" style="font-size: 16px; line-height: 1.3; margin-top: 4px;">—</span>
      <span class="sub-value" id="statBusiestCount"></span>
    </div>
  </div>
  <div class="stat-card">
    <div class="stat-icon" style="color: var(--accent-red);">📡</div>
    <div class="stat-details">
      <span class="label">Compteurs Actifs</span>
      <span class="value" id="statActiveRatio">—</span>
    </div>
  </div>
</section>

<main>
  <aside>
    <div class="sidebar-header">
      <span class="label">Compteurs</span>
      <span id="totalBadge">—</span>
    </div>
    <div class="search-box">
      <span class="search-icon">🔍</span>
      <input type="text" id="searchInput" placeholder="Rechercher un compteur...">
    </div>
    <div id="counterList"></div>
  </aside>
  
  <div id="map"></div>

  <!-- Detail Floating Panel -->
  <div class="detail-panel" id="detailPanel">
    <div class="detail-header">
      <div class="detail-title-wrap">
        <div class="detail-title" id="panelTitle">—</div>
        <div class="detail-subtitle" id="panelSubtitle">—</div>
      </div>
      <button class="close-btn" onclick="closePanel()">✕</button>
    </div>
    <div class="detail-body">
      <div class="detail-grid">
        <div class="detail-stat-card">
          <span class="v hour" id="panelHourCount">—</span>
          <span class="l">/ heure</span>
        </div>
        <div class="detail-stat-card">
          <span class="v day" id="panelDayCount">—</span>
          <span class="l">/ jour</span>
        </div>
        <div class="detail-stat-card">
          <span class="v year" id="panelYearCount">—</span>
          <span class="l">/ an</span>
        </div>
      </div>
      
      <div class="chart-section">
        <span class="chart-title">Activité de la journée</span>
        <div class="chart-container">
          <div class="no-chart-data" id="chartPlaceholder">Chargement du graphique...</div>
          <canvas id="historyChart"></canvas>
        </div>
      </div>
    </div>
  </div>
</main>

<script>
// ---------- Helpers ----------
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ---------- Map init ----------
const map = L.map('map', {
  center: [50.845, 4.352],
  zoom: 13,
  zoomControl: true,
  attributionControl: true
});

L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png', {
  attribution: '© Stadia Maps © OpenStreetMap',
  subdomains: 'abcd',
  maxZoom: 19
}).addTo(map);

// ---------- State ----------
let allData      = [];
let markers      = {};
let activeId     = null;
let maxDay       = 1;
let chartInstance = null;

// ---------- Icon factory (custom styled glowing circles) ----------
function makeIcon(dayCount, isActive, isHovered = false) {
  const pct  = Math.min(dayCount / maxDay, 1);
  // Interpolate color from Neon Blue (low) to Vibrant Emerald (high)
  // Blue: rgb(59, 130, 246) -> Emerald: rgb(16, 185, 129)
  const r    = Math.round(59  + pct * (16 - 59));
  const g    = Math.round(130 + pct * (185 - 130));
  const b    = Math.round(246 + pct * (129 - 246));
  const fill = `rgb(${r},${g},${b})`;
  
  const size = isActive ? 18 : (isHovered ? 14 : 10);
  
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size+16}" height="${size+16}" style="overflow: visible;">
    <defs>
      <filter id="glow-${isActive ? 'active' : 'normal'}" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="${isActive ? 4 : 2}" result="blur" />
        <feComposite in="SourceGraphic" in2="blur" operator="over" />
      </filter>
    </defs>
    ${isActive ? `<circle cx="${(size+16)/2}" cy="${(size+16)/2}" r="${size/2 + 6}" fill="none" stroke="${fill}" stroke-width="1.5" opacity="0.5">
      <animate attributeName="r" values="${size/2 + 2};${size/2 + 10};${size/2 + 2}" dur="2s" repeatCount="indefinite" />
      <animate attributeName="opacity" values="0.6;0;0.6" dur="2s" repeatCount="indefinite" />
    </circle>` : ''}
    <circle cx="${(size+16)/2}" cy="${(size+16)/2}" r="${size/2}"
      fill="${fill}" fill-opacity="0.9"
      stroke="#ffffff"
      stroke-width="${isActive ? 2 : 1}"
      filter="url(#glow-${isActive ? 'active' : 'normal'})"
      style="transition: all 0.2s ease;"
    />
  </svg>`;
  
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [size+16, size+16],
    iconAnchor: [(size+16)/2, (size+16)/2]
  });
}

// ---------- Render UI ----------
function renderAll(data) {
  allData = data;
  maxDay  = Math.max(1, ...data.map(d => d.day_cnt || 0));

  // Display time of last collection (convert UTC to Brussels local time)
  if (data && data.length > 0) {
    // data est trié par day_cnt : on cherche le relevé le plus récent (format
    // "YYYY-MM-DD HH:MM:SS", donc comparable comme chaîne)
    const latestCollected = data.reduce(
      (max, d) => (d.collected_at && d.collected_at > max ? d.collected_at : max), '');
    if (latestCollected) {
      const utcDate = new Date(latestCollected.replace(' ', 'T') + 'Z');
      
      const formattedTime = utcDate.toLocaleTimeString('fr-BE', {
        timeZone: 'Europe/Brussels',
        hour: '2-digit',
        minute: '2-digit'
      });
      
      const formattedDate = utcDate.toLocaleDateString('fr-BE', {
        timeZone: 'Europe/Brussels',
        day: '2-digit',
        month: '2-digit'
      });
      
      const container = document.getElementById('lastUpdate');
      container.innerHTML = `Dernière collecte : <span style="color: var(--accent-green); font-weight: 600;">${formattedTime}</span> le ${formattedDate}`;
      container.style.display = 'block';
    }
  } else {
    document.getElementById('lastUpdate').style.display = 'none';
  }

  // Clear existing markers
  Object.values(markers).forEach(m => map.removeLayer(m));
  markers = {};

  // Build markers
  data.forEach(d => {
    if (!d.lat || !d.lon) return;
    const m = L.marker([d.lat, d.lon], { icon: makeIcon(d.day_cnt, false) })
      .addTo(map);

    m.on('click', () => selectDevice(d.device_id));
    
    // Hover effects
    m.on('mouseover', () => {
      if (d.device_id !== activeId) {
        m.setIcon(makeIcon(d.day_cnt, false, true));
      }
    });
    m.on('mouseout', () => {
      if (d.device_id !== activeId) {
        m.setIcon(makeIcon(d.day_cnt, false, false));
      }
    });

    markers[d.device_id] = m;
  });

  calculateStats(data);
  renderList(data);
  document.getElementById('loader').classList.add('hidden');
}

function calculateStats(data) {
  const total = data.reduce((sum, item) => sum + (item.day_cnt || 0), 0);
  const peak = Math.max(0, ...data.map(item => item.peak_hour_cnt || 0));
  
  let busiest = null;
  if (data.length > 0) {
    busiest = data.reduce((max, item) => (item.day_cnt || 0) > (max.day_cnt || 0) ? item : max, data[0]);
  }
  
  const activeCount = data.filter(item => (item.day_cnt || 0) > 0).length;
  const ratio = data.length > 0 ? Math.round((activeCount / data.length) * 100) : 0;

  document.getElementById('statTotal').textContent = total.toLocaleString('fr-BE');
  document.getElementById('statPeakHour').textContent = `${peak.toLocaleString('fr-BE')} /h`;
  
  if (busiest && busiest.day_cnt > 0) {
    document.getElementById('statBusiestCounter').textContent = busiest.device_id;
    document.getElementById('statBusiestCount').textContent = `${busiest.day_cnt.toLocaleString('fr-BE')} passages`;
  } else {
    document.getElementById('statBusiestCounter').textContent = "—";
    document.getElementById('statBusiestCount').textContent = "";
  }
  
  document.getElementById('statActiveRatio').textContent = `${activeCount} / ${data.length} (${ratio}%)`;
}

function renderList(data) {
  const list = document.getElementById('counterList');
  const q    = document.getElementById('searchInput').value.toLowerCase();
  
  const filtered = q
    ? data.filter(d => d.device_id.toLowerCase().includes(q) || (d.location||'').toLowerCase().includes(q))
    : data;

  document.getElementById('totalBadge').textContent = `${filtered.length}`;

  // Update map markers visibility based on search query
  data.forEach(d => {
    const marker = markers[d.device_id];
    if (!marker) return;
    
    const isVisible = filtered.some(fd => fd.device_id === d.device_id);
    if (isVisible) {
      if (!map.hasLayer(marker)) {
        marker.addTo(map);
      }
    } else {
      if (map.hasLayer(marker)) {
        map.removeLayer(marker);
      }
    }
  });

  list.innerHTML = filtered.map(d => {
    const pct = maxDay ? Math.round((d.day_cnt / maxDay) * 100) : 0;
    return `
    <div class="counter-item${d.device_id === activeId ? ' active' : ''}"
         data-device-id="${escapeHtml(d.device_id)}">
      <div class="counter-name">
        <span>${escapeHtml(d.device_id)}</span>
      </div>
      <div class="counter-location">${escapeHtml(d.location || '—')}</div>
      <div class="counter-stats">
        <div class="stat">
          <span class="stat-label">Journée</span>
          <span class="stat-value day">${(d.day_cnt||0).toLocaleString('fr-BE')}</span>
        </div>
        <div class="stat">
          <span class="stat-label">Heure</span>
          <span class="stat-value hour">${(d.hour_cnt||0).toLocaleString('fr-BE')}</span>
        </div>
        <div class="stat">
          <span class="stat-label">Année</span>
          <span class="stat-value">${(d.year_cnt||0).toLocaleString('fr-BE')}</span>
        </div>
      </div>
      <div class="bar-wrap"><div class="bar-fill" style="width:${pct}%"></div></div>
    </div>`;
  }).join('');
}

async function selectDevice(id) {
  // Reset previous active marker
  if (activeId && markers[activeId]) {
    const prev = allData.find(d => d.device_id === activeId);
    if (prev) markers[activeId].setIcon(makeIcon(prev.day_cnt, false));
  }
  
  activeId = id;
  const d = allData.find(x => x.device_id === id);
  if (!d) return;

  // Update active marker icon and pan
  if (markers[id]) {
    markers[id].setIcon(makeIcon(d.day_cnt, true));
    map.panTo([d.lat, d.lon], { animate: true, duration: 0.5 });
  }

  // Populate floating panel
  document.getElementById('panelTitle').textContent = d.device_id;
  document.getElementById('panelSubtitle').textContent = d.location || 'Position inconnue';
  document.getElementById('panelHourCount').textContent = (d.hour_cnt||0).toLocaleString('fr-BE');
  document.getElementById('panelDayCount').textContent = (d.day_cnt||0).toLocaleString('fr-BE');
  document.getElementById('panelYearCount').textContent = (d.year_cnt||0).toLocaleString('fr-BE');

  // Open the detail panel
  document.getElementById('detailPanel').classList.add('open');

  // Load history chart
  loadHistoryChart(id);

  // Redraw list to highlight the active element
  renderList(allData);

  // Scroll sidebar item into view
  setTimeout(() => {
    const el = document.querySelector(`.counter-item[data-device-id="${CSS.escape(id)}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, 100);
}

function closePanel() {
  document.getElementById('detailPanel').classList.remove('open');
  if (activeId && markers[activeId]) {
    const d = allData.find(x => x.device_id === activeId);
    if (d) markers[activeId].setIcon(makeIcon(d.day_cnt, false));
  }
  activeId = null;
  renderList(allData);
}

// ---------- Chart.js drawing ----------
async function loadHistoryChart(deviceId) {
  const dateVal = document.getElementById('datePicker').value;
  const placeholder = document.getElementById('chartPlaceholder');
  const canvas = document.getElementById('historyChart');
  
  placeholder.style.display = 'flex';
  placeholder.textContent = "Chargement des données historiques...";
  canvas.style.opacity = 0;

  try {
    const resp = await fetch(`/api/history?device_id=${encodeURIComponent(deviceId)}&date=${encodeURIComponent(dateVal)}`);
    if (!resp.ok) {
      placeholder.textContent = "Aucun historique disponible pour cette journée.";
      if (chartInstance) chartInstance.destroy();
      return;
    }
    const history = await resp.json();

    if (!history || history.length === 0) {
      placeholder.textContent = "Aucun historique disponible pour cette journée.";
      if (chartInstance) chartInstance.destroy();
      return;
    }

    placeholder.style.display = 'none';
    canvas.style.opacity = 1;

    // Parse times and counts (convert UTC to Brussels local time)
    const labels = history.map(item => {
      const utcDate = new Date(item.collected_at.replace(' ', 'T') + 'Z');
      return utcDate.toLocaleTimeString('fr-BE', {
        timeZone: 'Europe/Brussels',
        hour: '2-digit',
        minute: '2-digit'
      });
    });
    
    const hourData = history.map(item => item.hour_cnt || 0);

    const ctx = canvas.getContext('2d');
    if (chartInstance) {
      chartInstance.destroy();
    }

    // Gradient background under curve
    const gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.4)');
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

    chartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Passages / heure',
          data: hourData,
          borderColor: '#3b82f6',
          backgroundColor: gradient,
          borderWidth: 2,
          fill: true,
          tension: 0.35,
          pointBackgroundColor: '#3b82f6',
          pointBorderColor: '#ffffff',
          pointBorderWidth: 1,
          pointRadius: history.length > 20 ? 1 : 3,
          pointHoverRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(15, 23, 42, 0.9)',
            titleColor: '#f8fafc',
            bodyColor: '#f8fafc',
            borderColor: 'rgba(255, 255, 255, 0.1)',
            borderWidth: 1,
            padding: 8,
            titleFont: { family: 'Inter', weight: '600' },
            bodyFont: { family: 'Inter' },
            displayColors: false,
            callbacks: {
              label: function(context) {
                return `${context.parsed.y} cyclistes /h`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#94a3b8',
              font: { family: 'Inter', size: 10 },
              maxTicksLimit: 8
            }
          },
          y: {
            grid: { color: 'rgba(255, 255, 255, 0.04)' },
            ticks: {
              color: '#94a3b8',
              font: { family: 'Inter', size: 10 }
            },
            beginAtZero: true
          }
        }
      }
    });

  } catch (e) {
    console.error(e);
    placeholder.textContent = "Erreur lors du chargement des données.";
  }
}

// ---------- Data fetch ----------
async function loadData(day) {
  document.getElementById('loader').classList.remove('hidden');
  closePanel();
  
  const url = `/api/daily?date=${day}`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderAll(data);
  } catch (e) {
    console.error(e);
    document.getElementById('loader').classList.add('hidden');
  }
}

// Date du jour à Bruxelles au format YYYY-MM-DD (la locale sv-SE produit ce format)
function todayBrussels() {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Brussels' });
}

async function initDatePicker() {
  const picker = document.getElementById('datePicker');
  try {
    const resp  = await fetch('/api/dates');
    const dates = await resp.json();
    if (dates.length) {
      picker.value = dates[0];
      picker.min   = dates[dates.length - 1];
      picker.max   = dates[0];
    } else {
      picker.value = todayBrussels();
    }
  } catch {
    picker.value = todayBrussels();
  }
  
  picker.addEventListener('change', () => loadData(picker.value));
  loadData(picker.value);
}

// ---------- Refresh Button Logic ----------
async function triggerRefresh() {
  const btn = document.getElementById('refreshBtn');
  const icon = document.getElementById('refreshIcon');
  const text = document.getElementById('refreshText');
  const dateVal = document.getElementById('datePicker').value;

  // Disable button and animate icon
  btn.disabled = true;
  btn.style.opacity = '0.7';
  btn.style.cursor = 'not-allowed';
  icon.style.animation = 'spin 1s linear infinite';
  text.textContent = 'Actualisation...';

  try {
    const resp = await fetch('/api/refresh', { method: 'POST' });
    const res = await resp.json();
    
    if (res.status === 'success') {
      text.textContent = '✓ Fait !';
      btn.style.borderColor = 'var(--accent-green)';
      btn.style.color = 'var(--accent-green)';
      btn.style.background = 'rgba(16, 185, 129, 0.1)';
      
      // Reload current date data
      await loadData(dateVal);
    } else {
      text.textContent = 'Erreur';
    }
  } catch (e) {
    console.error(e);
    text.textContent = 'Erreur';
  }

  // Restore button state after 2 seconds
  setTimeout(() => {
    icon.style.animation = 'none';
    text.textContent = 'Actualiser';
    btn.disabled = false;
    btn.style.opacity = '1';
    btn.style.cursor = 'pointer';
    btn.style.borderColor = 'rgba(59, 130, 246, 0.2)';
    btn.style.color = 'var(--accent-blue)';
    btn.style.background = 'rgba(59, 130, 246, 0.1)';
  }, 2000);
}

// ---------- Search & Inputs ----------
document.getElementById('searchInput').addEventListener('input', () => renderList(allData));
document.getElementById('counterList').addEventListener('click', e => {
  const item = e.target.closest('.counter-item');
  if (item) selectDevice(item.dataset.deviceId);
});

// ---------- Boot ----------
initDatePicker();
</script>
</body>
</html>"""


@app.get("/")
def index():
    return render_template_string(DASHBOARD_HTML)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
