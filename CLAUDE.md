# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small containerized app that collects bike-counter data for Brussels from the `data.mobility.brussels` public API, stores it in SQLite, and serves a single-page dashboard (map + charts) over Flask. Three Python-adjacent files make up the whole app: `collector.py` (ingestion), `app.py` (Flask API + the entire dashboard as an inline HTML/CSS/JS string), and the container/cron plumbing (`Dockerfile`, `entrypoint.sh`, `docker-compose.yml`). Python dependencies are managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`, pinned to Python 3.14 via `.python-version`) — there is no `requirements.txt`.

## Running it

The app is only ever run in a container; there is no supported bare-metal dev workflow. Both Docker and Podman work against the same `Dockerfile`/`docker-compose.yml` — this environment has Podman only (no `docker` CLI), so `podman compose` (which shells out to `docker-compose.exe`) is what's actually been exercised here.

```bash
docker compose up -d --build   # or: podman compose up -d --build
```

That builds the image (Python 3.14 + `uv sync --locked` to create `/app/.venv` + cron), runs an immediate collection, then starts cron (every 30 min) and the Flask server. Dashboard: `http://localhost:8080` (maps to container port 5000). Wait ~20-30s after startup for the first collection to finish before data appears.

Common operational commands (see `README.md` §6-7 for the full Docker/Podman-parallel list):

```bash
docker compose logs -f                                          # follow app + collector logs
docker exec velo-brussels /app/.venv/bin/python /app/collector.py  # force an immediate collection (bypass cron)
docker exec velo-brussels cat /var/log/collector.log             # collector-only logs
docker exec -it velo-brussels sqlite3 /data/velo.db              # inspect the DB directly
docker compose down            # stop (keeps the velo_data volume)
docker compose down -v         # stop AND delete all collected history — destructive, confirm with user first
```

(Swap `docker` for `podman` in any of the above — same subcommands.) Note the container always runs `/app/.venv/bin/python`, not a bare `python` — cron's minimal PATH doesn't include the venv, so `entrypoint.sh` and any `exec`'d command must use the absolute venv path.

To change Python dependencies: edit `pyproject.toml`, run `uv lock` to refresh `uv.lock`, commit both, then rebuild the image — `uv sync --locked` in the `Dockerfile` will fail closed if the lockfile and pyproject.toml drift apart.

There is no test suite, linter, or CI config in this repo.

**Local caveat observed in this environment**: this machine's endpoint security blocks execution of (and even reading, during a build-context scan) the standalone `python.exe` binaries under `.venv/` and under the uv-managed Python install — `uv sync` itself succeeds, but running `.venv/Scripts/python.exe` directly fails with Windows "Access is denied", and including `.venv/` in a container build context fails the same way. `.dockerignore` excludes `.venv/` for this reason — don't remove it or switch the Dockerfile to `COPY . .` without re-checking this.

**Local caveat — corporate TLS-inspecting proxy**: this network (Paradigm/CIRB-CIBG) intercepts outbound HTTPS with its own CA (`inspection.paradigm.brussels`, chaining to root `CIRB_CIBG ROOT PKI - Services`), so both the Podman host VM and the build container need that root trusted or TLS pulls/downloads fail with "certificate signed by unknown authority" / "invalid peer certificate: UnknownIssuer". The Podman machine's own trust store was fixed once by importing the root into `podman-machine-default` (`podman machine ssh` → `update-ca-trust`) — that persists on the VM disk and shouldn't need repeating unless the VM is recreated. For the build container, the Dockerfile copies an optional local `certs/` directory into `/usr/local/share/ca-certificates/` and runs `update-ca-certificates`, plus sets `UV_SYSTEM_CERTS=1` so `uv sync` uses that trust store instead of its bundled webpki roots. `certs/` is gitignored (only `.gitkeep` is tracked) — it's a no-op for anyone building outside this network, and on this machine it holds a local copy of the corporate root CA (not committed).

## Architecture

Data flow: `API mobility.brussels → collector.py (cron, every 30 min) → /data/velo.db (SQLite) → app.py (Flask) → browser (Leaflet + Chart.js)`.

- **`collector.py`** — Standalone script, run both at container startup and via cron (see `entrypoint.sh`). Fetches the device list (`?request=devices`), then fetches live counts per device concurrently (`ThreadPoolExecutor`, max 10 workers) from `?request=live&featureID=...`. All SQLite writes happen sequentially in the main thread after the concurrent fetch completes — do not write to the `conn` from inside worker threads. `insert_count` dedupes via `INSERT OR IGNORE` against a UNIQUE index on `(device_id, cnt_time)` (created by a one-time migration in `init_db` that first purges pre-existing duplicates), so re-running the collector — even concurrently with `/api/refresh` — is safe. Empty `cnt_time` is stored as NULL and never deduped. `get_bike_data(conn)` is the reusable entry point (also imported and called directly by `app.py`'s `/api/refresh` endpoint) — `main()` is only the CLI/cron wrapper that opens the DB connection.
- **`app.py`** — Flask app with three read endpoints (`/api/dates`, `/api/daily`, `/api/history`) and one write endpoint (`/api/refresh`, which imports `collector` and calls `get_bike_data` on demand). `DASHBOARD_HTML` is a single large triple-quoted string rendered via `render_template_string` at `/` — the frontend (CSS + vanilla JS, Leaflet map + Chart.js line chart) lives entirely inside this string, not in separate static files. When editing dashboard behavior, you're editing Python-embedded HTML/JS, not a separate frontend project.
- **Schema** — two tables: `devices` (id, location, lat/lon — upserted on every collection) and `counts` (append-only time series keyed by `device_id` + `collected_at`; `cnt_time` is the API's own timestamp, `collected_at` is when we fetched it). Both `app.py` and `collector.py` connect independently via `DB_PATH` (env var, defaults to `/data/velo.db`); there's no shared connection or ORM.
- **Date handling** — the DB stores UTC (`collected_at`), but the API's `cnt_time` is Brussels local time and `day_cnt` resets at Brussels midnight. A "day" in the API/dashboard is therefore a **Brussels** day: `day_bounds_utc()` in `app.py` turns `?date=YYYY-MM-DD` into a UTC `[start, end)` range and `/api/daily`/`/api/history` filter with `collected_at >= ? AND collected_at < ?` (never `substr(collected_at, 1, 10)`, which would pick post-midnight readings for the previous day). `/api/dates` converts UTC hours to Brussels dates in Python. The image installs `tzdata` for `zoneinfo`. `cnt_time` is stored raw (`YYYY/MM/DD HH:MM:SS`; `clean_date` doesn't parse that format).
- **Deployment** — `entrypoint.sh` runs one collection synchronously, installs a crontab line (`*/30 * * * *`), starts the cron daemon, then execs the Flask server as PID 1. Changing collection frequency means editing the cron line in `entrypoint.sh` and rebuilding the image (see README §6.7), not a config value.
- The API is called with `verify=False` (TLS verification disabled) in `collector.py` — this is existing, intentional behavior for the mobility.brussels endpoint, not an oversight to silently "fix".
- **Architectural documentation** — `docs/architecture/workspace.dsl` holds a C4 model (Context + Container levels) in Structurizr DSL, viewable locally via `docker compose -f docs/architecture/docker-compose.structurizr.yml up` (Structurizr Lite on `http://localhost:8081`). No Component level — `app.py` and `collector.py` are each a single container, so a component diagram wouldn't add information. When the containers, external systems, or their relationships change (e.g. a new data source, a new service), update `workspace.dsl` alongside this file and the "Architecture" section of `README.md` — they describe the same system and should stay consistent.
