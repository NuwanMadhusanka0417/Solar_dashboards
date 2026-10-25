# LEAP Solar Dashboards

React dashboards for every La Trobe solar site, built from the analysis in `../PV_analysis`.
They follow the two templates in `documents/` (*All meters dashboards.pdf*, *Individual dashboard.pdf*).

```
 download_data.py  ──►  data/raw/*.csv  ──►  process_data.py  ──►  data/processed/*.csv  ──►  api_server.py  ──►  React dashboard
  (SQL, Azure,                               (clean, PVLib, H,                              (FastAPI JSON,       (Vite + Recharts)
   Open-Meteo)                                soiling, forecast)                              serves the app)
```

| Step | File | What it does |
|---|---|---|
| 1 | `backend/download_data.py` | Incremental download of meter readings (SQL Server), Solcast weather for **all campuses** (Azure blobs) and PM2.5/PM10 (Open-Meteo) into `data/raw/`. |
| 2 | `backend/process_data.py` | Cleans meters, models expected generation with PVLib, and computes daily metrics, health ratio H, degradation, seasonal trends, HSU soiling and cleaning advice, and the forecast. Writes CSVs to `data/processed/`. |
| 3 | `backend/api_server.py` | FastAPI service that reads the processed CSVs and serves JSON under `/api`. It also serves the built React app at `/`. Interactive docs are at `/docs`. |
| UI | `frontend/` | React + TypeScript + Recharts. It has two pages: **Solar** (all sites) and **Individual Solar** (one site). |

Shared code lives in `backend/pvdash/` (`settings`, `sites`, `weather`, `cleaning`, `pvmodel`, `analytics`, `soiling`, `forecast`).

## Quick start (Windows, `solarazure` env)

```bash
conda activate solarazure
pip install -r requirements.txt
copy .env.example .env          # then fill in DB + Azure credentials

cd backend
python download_data.py --import-legacy ../../PV_analysis/data_raw   # one-off: reuse the old project's raw data
python download_data.py          # incremental top-up (meters, weather, air quality)
python process_data.py           # ~1.5 min for 49 sites
python api_server.py             # http://127.0.0.1:8000/docs
```

Dashboard in development (hot reload, proxies `/api` to port 8000):

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

Production: `npm run build` once, then `python api_server.py --host 0.0.0.0` serves both the API and the app on one port.

## Refreshing data (schedule this)

```bash
cd backend
python download_data.py && python process_data.py
```

The API reloads the CSVs by itself when `data/processed/pipeline_meta.json` changes, so it never needs a restart.
Schedule the two commands with Windows Task Scheduler or cron (for example every morning at 06:00).

Useful flags:

| Command | Flag | Effect |
|---|---|---|
| `download_data.py` | `--only meters\|weather\|air` | One source only (repeatable). |
| | `--all-meters` | Every `realenergyintotheload` meter in SQL, not just those in `sites.csv`. |
| | `--campus BUNDOORA` | Limit weather / PM to one campus. |
| | `--dry-run` | Show what would be fetched. |
| `process_data.py` | `--sites library dw` | Re-process only these sites; other sites keep their previous rows. |
| | `--skip-forecast` | Faster refresh. |
| | `--write-hourly` | Also write `processed/hourly/<site>.csv` for debugging. |
| `api_server.py` | `--host`, `--port`, `--reload` | Server options. |

## Configuration

* **`backend/config/sites.csv`** is the site registry. Each row is one dashboard site: meter ID(s), name, campus, kWp, inverter kW, tilt, azimuth, modules, commissioned date, design MWh, and `enabled`.
  * `meter_ids` can chain renamed meters with `|`. Library is chained to `library_intertrip` (renamed 2026-08-12), and Albury Wodonga Health to `health+carpark`.
  * If `kwp` is blank, capacity is estimated from peak output and shown as **est.** in the UI. That applies to all non-Bundoora sites today, because `panel_data.csv` only covers Bundoora. Fill in the real nameplates.
  * Tilt/azimuth default to **10° / north (azimuth 0)**, as in the template. The old pipeline used 180° (south) as a placeholder. Enter as-built values where you have them.
* **`backend/config/events.csv`** holds maintenance events (panel cleaning, etc.). The **+ Event** button on a site page appends to it. Events appear on the generation and soiling charts.
* **`.env`** holds credentials, plus optional tariff ($0.25/kWh), cleaning cost ($300), CO₂ factor (0.79 kg/kWh) and data folder.

## API

| Endpoint | Used by |
|---|---|
| `GET /api/meta` | Date bounds, campuses, tariff |
| `GET /api/sites` | Site selector |
| `GET /api/overview?start&end&campus` | All-sites page: KPIs, campus totals, attention list, sites table, degradation comparison |
| `GET /api/sites/{key}/summary?start&end` | Site details, data quality, period / peak / YTD / MTD / WTD / CO₂, loss breakdown |
| `GET /api/sites/{key}/generation?start&end&view=daily\|monthly\|yearly` | Generation chart + daily difference, outage spans, events |
| `GET /api/sites/{key}/seasonal` | Seasonal GHI and H scatter, annual medians, trends |
| `GET /api/sites/{key}/degradation` | Annual and monthly H with fits |
| `GET /api/sites/{key}/underperformance?threshold_pct&min_days&start&end` | Underperformance table |
| `GET /api/sites/{key}/soiling` | Soiling monitor + cleaning recommendation |
| `GET /api/sites/{key}/soiling/simulate?clean_date&cost` | 7-day cleaning simulator |
| `GET /api/sites/{key}/forecast?hours=72` | Generation forecast with 80% interval |
| `GET/POST /api/events` | Maintenance events |

## Docker

```bash
docker build -t leap-solar .
docker run -p 8000:8000 -v %cd%/data:/app/data -v %cd%/.env:/app/.env leap-solar
```

The image serves the API and the dashboard, and can run `process_data.py`. Downloading meters needs Microsoft's *ODBC Driver 18 for SQL Server*, which is not in the image. Run `download_data.py` on a machine that has it, or add the driver to the image.

## What changed from `PV_analysis` (and why numbers differ)

* **Solcast timestamps are now aligned.** The raw weather mixes two conventions: the archive is period-end UTC+9, and the live Azure feed is period-end Melbourne local time. The old pipeline read both as local time, which put expected power 1–2 h out of step with the meters and made night-masking cut real evening generation. `pvdash/weather.py` detects the convention per day from Solcast's own zenith column. Meter vs GHI correlation is now highest at 0 h shift on every campus (≈0.97–0.99).
* **No imputation.** Outages show as zero generation and are excluded from H, instead of being filled with XGBoost guesses. As a result, the absolute H level is lower than in the old dashboards (≈0.75–0.8 for healthy Bundoora sites, with north-facing panels).
* **Rain and PM for soiling are aligned in local time.** Previously rain was read as UTC. HSU soiling is now computed per campus.
* **Multi-campus.** Weather download covers every campus. Solar position, PVLib and PM use each campus's coordinates.
* **Credentials only from `.env`.** No fallback passwords or tokens in code.

## Known gaps

* Non-Bundoora weather in the imported data stops at 2025-08-13. Until `download_data.py` fetches all campuses from Azure, those sites have no expected / PR / forecast for recent dates.
* *Solar vs Building Consumption* is a placeholder because building load is not part of this pipeline.
* The roof layout is a generic drawing. Commissioned date, design MWh and module counts for non-Bundoora sites need filling in `sites.csv`.
