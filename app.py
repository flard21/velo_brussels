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
from datetime import datetime, date
from flask import Flask, jsonify, render_template_string, request

DB_PATH = os.environ.get("DB_PATH", "/data/velo.db")

app = Flask(__name__)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- API ----------

@app.get("/api/dates")
def api_dates():
    """Retourne les dates (YYYY-MM-DD) pour lesquelles des données existent."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT substr(collected_at, 1, 10) AS day
            FROM counts
            ORDER BY day DESC
            LIMIT 30
        """).fetchall()
    return jsonify([r["day"] for r in rows])


@app.get("/api/daily")
def api_daily():
    """
    Retourne, pour une date donnée (param ?date=YYYY-MM-DD),
    le dernier relevé de chaque compteur ainsi que sa localisation.
    Par défaut : aujourd'hui.
    """
    day = request.args.get("date", date.today().isoformat())

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
                c.year_cnt
            FROM devices d
            JOIN counts c ON c.device_id = d.device_id
            WHERE c.id = (
                SELECT id FROM counts c2
                WHERE c2.device_id = d.device_id
                  AND substr(c2.collected_at, 1, 10) = ?
                ORDER BY c2.collected_at DESC
                LIMIT 1
            )
            ORDER BY c.day_cnt DESC
        """, (day,)).fetchall()

    result = [dict(r) for r in rows]
    return jsonify(result)


# ---------- DASHBOARD ----------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Compteurs Vélo · Bruxelles</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<style>
  :root {
    --bg:      #f0f2f5;
    --surface: #ffffff;
    --border:  #d0d7de;
    --text:    #24292f;
    --muted:   #656d76;
    --accent:  #cf4024;
    --accent2: #0969da;
    --green:   #1a7f37;
  }
  
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Mono', monospace;
    height: 100vh;
    display: grid;
    grid-template-rows: 56px 1fr;
    grid-template-columns: 340px 1fr;
    grid-template-areas:
      "header header"
      "sidebar map";
    overflow: hidden;
  }

  /* ── Header ── */
  header {
    grid-area: header;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 24px;
  }

  header h1 {
    font-family: 'Syne', sans-serif;
    font-size: 18px;
    font-weight: 800;
    letter-spacing: -0.5px;
  }

  header h1 span { color: var(--accent); }

  .date-picker-wrap {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12px;
    color: var(--muted);
  }

  #datePicker {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    padding: 4px 10px;
    cursor: pointer;
  }

  #datePicker:focus { outline: none; border-color: var(--accent2); }

  .badge {
    background: var(--accent);
    color: #000;
    font-size: 10px;
    font-weight: 500;
    padding: 2px 8px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  /* ── Sidebar ── */
  aside {
    grid-area: sidebar;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .sidebar-header {
    padding: 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .sidebar-header .label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
  }

  #totalBadge {
    font-size: 11px;
    color: var(--accent2);
  }

  .search-box {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
  }

  #searchInput {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    padding: 6px 12px;
  }

  #searchInput:focus { outline: none; border-color: var(--accent2); }

  #counterList {
    overflow-y: auto;
    flex: 1;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }

  .counter-item {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.15s;
    position: relative;
  }

  .counter-item:hover,
  .counter-item.active {
    background: rgba(121, 192, 255, 0.06);
  }

  .counter-item.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
    background: var(--accent2);
    border-radius: 0 2px 2px 0;
  }

  .counter-name {
    font-size: 11px;
    font-weight: 500;
    color: var(--accent2);
    margin-bottom: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .counter-location {
    font-size: 10px;
    color: var(--muted);
    margin-bottom: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .counter-stats {
    display: flex;
    gap: 12px;
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
    color: var(--muted);
  }

  .stat-value {
    font-size: 14px;
    font-weight: 500;
    color: var(--text);
  }

  .stat-value.day   { color: var(--green); }
  .stat-value.hour  { color: var(--accent); }

  /* bar sparkline */
  .bar-wrap {
    margin-top: 8px;
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }

  .bar-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent2), var(--green));
    border-radius: 2px;
    transition: width 0.4s ease;
  }

  /* ── Map ── */
  #map {
    grid-area: map;
    background: #0d1117;
  }

  /* ── Loading overlay ── */
  #loader {
    position: fixed;
    inset: 0;
    background: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    transition: opacity 0.4s;
  }

  #loader.hidden { opacity: 0; pointer-events: none; }

  .spinner {
    width: 36px;
    height: 36px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Leaflet popup custom ── */
  .leaflet-popup-content-wrapper {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 12px !important;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5) !important;
  }

  .leaflet-popup-tip { background: var(--surface) !important; }

  .popup-title {
    font-family: 'Syne', sans-serif;
    font-size: 14px;
    font-weight: 700;
    color: var(--accent2);
    margin-bottom: 4px;
  }

  .popup-loc {
    color: var(--muted);
    font-size: 10px;
    margin-bottom: 10px;
  }

  .popup-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }

  .popup-stat { text-align: center; }
  .popup-stat .v { font-size: 18px; font-weight: 500; color: var(--green); }
  .popup-stat .l { font-size: 9px; text-transform: uppercase; color: var(--muted); }
  .popup-stat:first-child .v { color: var(--accent); }
  .popup-stat:last-child .v  { color: var(--muted); }
</style>
</head>
<body>

<div id="loader"><div class="spinner"></div></div>

<header>
  <h1>🚲 Vélo <span>Bruxelles</span></h1>
  <span class="badge" id="liveBadge">live</span>
  <div class="date-picker-wrap">
    <span>Rapport du</span>
    <input type="date" id="datePicker">
  </div>
</header>

<aside>
  <div class="sidebar-header">
    <span class="label">Compteurs</span>
    <span id="totalBadge">—</span>
  </div>
  <div class="search-box">
    <input type="text" id="searchInput" placeholder="Filtrer…">
  </div>
  <div id="counterList"></div>
</aside>

<div id="map"></div>

<script>
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
let allData   = [];
let markers   = {};
let activeId  = null;
let maxDay    = 1;

// ---------- Icon factory ----------
function makeIcon(dayCount, isActive) {
  const pct  = Math.min(dayCount / maxDay, 1);
  const r    = Math.round(88  + pct * (86 - 88));
  const g    = Math.round(129 + pct * (211 - 129));
  const b    = Math.round(245 + pct * (100 - 245));
  const fill = `rgb(${r},${g},${b})`;
  const size = isActive ? 16 : 11;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size+8}" height="${size+8}">
    <circle cx="${(size+8)/2}" cy="${(size+8)/2}" r="${size/2}"
      fill="${fill}" fill-opacity="0.9"
      stroke="${isActive ? '#fff' : 'rgba(0,0,0,0.4)'}"
      stroke-width="${isActive ? 2 : 1}"/>
  </svg>`;
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [size+8, size+8],
    iconAnchor: [(size+8)/2, (size+8)/2]
  });
}

// ---------- Render ----------
function renderAll(data) {
  allData = data;
  maxDay  = Math.max(1, ...data.map(d => d.day_cnt || 0));

  // clear markers
  Object.values(markers).forEach(m => map.removeLayer(m));
  markers = {};

  data.forEach(d => {
    if (!d.lat || !d.lon) return;
    const m = L.marker([d.lat, d.lon], { icon: makeIcon(d.day_cnt, false) })
      .addTo(map);

    m.on('click', () => selectDevice(d.device_id));
    markers[d.device_id] = m;
  });

  renderList(data);
  document.getElementById('loader').classList.add('hidden');
}

function renderList(data) {
  const list = document.getElementById('counterList');
  const q    = document.getElementById('searchInput').value.toLowerCase();
  const filtered = q
    ? data.filter(d => d.device_id.toLowerCase().includes(q) || (d.location||'').toLowerCase().includes(q))
    : data;

  document.getElementById('totalBadge').textContent = `${filtered.length} compteur${filtered.length>1?'s':''}`;

  list.innerHTML = filtered.map(d => {
    const pct = maxDay ? Math.round((d.day_cnt / maxDay) * 100) : 0;
    return `
    <div class="counter-item${d.device_id === activeId ? ' active' : ''}"
         onclick="selectDevice('${d.device_id}')">
      <div class="counter-name">${d.device_id}</div>
      <div class="counter-location">${d.location || '—'}</div>
      <div class="counter-stats">
        <div class="stat">
          <span class="stat-label">Journée</span>
          <span class="stat-value day">${(d.day_cnt||0).toLocaleString('fr')}</span>
        </div>
        <div class="stat">
          <span class="stat-label">Heure</span>
          <span class="stat-value hour">${(d.hour_cnt||0).toLocaleString('fr')}</span>
        </div>
        <div class="stat">
          <span class="stat-label">Année</span>
          <span class="stat-value">${(d.year_cnt||0).toLocaleString('fr')}</span>
        </div>
      </div>
      <div class="bar-wrap"><div class="bar-fill" style="width:${pct}%"></div></div>
    </div>`;
  }).join('');
}

function selectDevice(id) {
  // reset previous
  if (activeId && markers[activeId]) {
    const prev = allData.find(d => d.device_id === activeId);
    if (prev) markers[activeId].setIcon(makeIcon(prev.day_cnt, false));
  }
  activeId = id;
  const d = allData.find(x => x.device_id === id);
  if (!d) return;

  // update marker
  if (markers[id]) {
    markers[id].setIcon(makeIcon(d.day_cnt, true));
    map.panTo([d.lat, d.lon], { animate: true, duration: 0.5 });
    markers[id].openPopup();
  }

  // open popup
  if (markers[id]) {
    const popup = L.popup({
      closeButton: false,
      offset: [0, -6]
    }).setContent(`
      <div class="popup-title">${d.device_id}</div>
      <div class="popup-loc">${d.location || 'Position inconnue'}</div>
      <div class="popup-grid">
        <div class="popup-stat">
          <div class="v">${(d.hour_cnt||0).toLocaleString('fr')}</div>
          <div class="l">/ heure</div>
        </div>
        <div class="popup-stat">
          <div class="v">${(d.day_cnt||0).toLocaleString('fr')}</div>
          <div class="l">/ jour</div>
        </div>
        <div class="popup-stat">
          <div class="v">${(d.year_cnt||0).toLocaleString('fr')}</div>
          <div class="l">/ an</div>
        </div>
      </div>
    `);
    markers[id].bindPopup(popup).openPopup();
  }

  renderList(allData);

  // scroll sidebar item
  document.querySelectorAll('.counter-item').forEach(el => {
    if (el.querySelector('.counter-name')?.textContent === id) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

// ---------- Data fetch ----------
async function loadData(day) {
  document.getElementById('loader').classList.remove('hidden');
  const url = `/api/daily?date=${day}`;
  try {
    const resp = await fetch(url);
    const data = await resp.json();
    renderAll(data);
  } catch (e) {
    console.error(e);
    document.getElementById('loader').classList.add('hidden');
  }
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
    }
  } catch {}
  picker.addEventListener('change', () => loadData(picker.value));
  loadData(picker.value || new Date().toISOString().slice(0, 10));
}

// ---------- Search ----------
document.getElementById('searchInput').addEventListener('input', () => renderList(allData));

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
