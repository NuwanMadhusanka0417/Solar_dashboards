"""
Paths, environment loading and analysis constants shared by the three entry scripts.

Every value that someone may want to tune lives here (or in ``.env``) so the
download / process / API scripts never hard-code credentials or magic numbers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
CONFIG_DIR = BACKEND_DIR / "config"
ENV_FILE = PROJECT_DIR / ".env"

SITES_CSV = CONFIG_DIR / "sites.csv"
EVENTS_CSV = CONFIG_DIR / "events.csv"


def _load_dotenv(path: Path) -> None:
    """Minimal KEY=VALUE loader (no python-dotenv dependency). Existing env vars win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        if key and not os.environ.get(key, "").strip():
            os.environ[key] = val


_load_dotenv(ENV_FILE)

_PLACEHOLDERS = {"", "your-server", "your-user", "your-password", "your-sas-token"}


def env(key: str, default: str = "") -> str:
    val = os.environ.get(key, "").strip()
    return default if val in _PLACEHOLDERS else val


def env_float(key: str, default: float) -> float:
    try:
        return float(env(key) or default)
    except ValueError:
        return default


DATA_DIR = Path(env("PVDASH_DATA_DIR") or (PROJECT_DIR / "data")).resolve()
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Raw files written by download_data.py
RAW_METERS_CSV = RAW_DIR / "meters_hourly.csv"
RAW_WEATHER_CSV = RAW_DIR / "solcast_weather.csv"
RAW_AIR_QUALITY_CSV = RAW_DIR / "air_quality.csv"

TIMEZONE = "Australia/Melbourne"


@dataclass(frozen=True)
class Campus:
    code: str  # Solcast campus code (upper case)
    name: str  # display name
    latitude: float
    longitude: float
    altitude_m: float


# Campus coordinates drive PVLib solar position and the Open-Meteo PM grid point.
CAMPUSES: dict[str, Campus] = {
    "BUNDOORA": Campus("BUNDOORA", "Bundoora", -37.7183, 145.0454, 85.0),
    "BENDIGO": Campus("BENDIGO", "Bendigo", -36.7790, 144.2990, 220.0),
    "WODONGA": Campus("WODONGA", "Wodonga", -36.1300, 146.8460, 160.0),
    "MILDURA": Campus("MILDURA", "Mildura", -34.1890, 142.1580, 50.0),
    "SHEPPARTON": Campus("SHEPPARTON", "Shepparton", -36.3800, 145.3990, 115.0),
}
CAMPUS_ORDER = ["BUNDOORA", "BENDIGO", "WODONGA", "MILDURA", "SHEPPARTON"]

# ── PVLib model ──────────────────────────────────────────────────────────────
GAMMA_PDC = -0.004  # PVWatts temperature coefficient (1/°C)
DEFAULT_TILT_DEG = 10.0
DEFAULT_AZIMUTH_DEG = 0.0  # PVLib convention: clockwise from north, 0 = north-facing
# Hourly kWh can never exceed inverter AC rating by more than this factor.
PHYSICAL_CAP_AC_MULT = 1.08
# Peak hourly kWh ÷ this ≈ kWp DC when a site has no catalogue capacity.
CAPACITY_ESTIMATE_PEAK_RATIO = 0.8

# ── Meter cleaning ───────────────────────────────────────────────────────────
ZERO_EPS = 1e-6
STUCK_MIN_HOURS = 4  # identical non-zero reading this long = frozen meter
DAYLIGHT_GHI_MIN = 5.0  # W/m² — "daylight" for H ratio (matches old dashboard)
OUTAGE_GHI_MIN = 50.0  # W/m² — zero reading with GHI above this is an outage hour
OUTAGE_DAY_FRACTION = 0.5  # day counts as an outage day when ≥50% of sunny hours are dead

# ── Soiling (pvlib HSU) ─────────────────────────────────────────────────────
HSU_CLEANING_THRESHOLD_MM = 0.5
HSU_SR_CLEAN_JUMP = 0.002
HSU_SR_FLOOR = 0.6563  # pvlib HSU mathematical minimum
PM_UGM3_TO_GM3 = 1e-6  # Open-Meteo returns µg/m³, pvlib wants g/m³
SOILING_FORECAST_DAYS = 7
SOILING_MONITOR_DAYS = 90
CLEAN_DECISION_MARGIN_AUD = 50.0

# ── Long-term analysis window ───────────────────────────────────────────────
# Degradation, yearly/monthly H, seasonal trends and the yearly generation view
# ignore data before this date (2020–2021 meter data has large gaps / zero runs).
# Daily charts can still browse earlier dates.
ANALYSIS_START = env("PVDASH_ANALYSIS_START", "2022-01-01")

# ── Money / emissions (override in .env) ───────────────────────────────────
TARIFF_AUD_PER_KWH = env_float("PVDASH_TARIFF_AUD_PER_KWH", 0.25)
CLEANING_COST_AUD = env_float("PVDASH_CLEANING_COST_AUD", 300.0)
# Victorian grid scope-2 factor (kg CO2-e per kWh) and one tree ≈ 21 kg CO2-e / yr
CO2_KG_PER_KWH = env_float("PVDASH_CO2_KG_PER_KWH", 0.79)
CO2_KG_PER_TREE = env_float("PVDASH_CO2_KG_PER_TREE", 21.0)

# ── Status thresholds for the All-sites table ────────────────────────────────
UNDERPERFORM_PCT = 10.0  # % below expected …
UNDERPERFORM_MIN_DAYS = 2  # … for this many consecutive days
SOILING_ALERT_LOSS_PCT = 3.0  # flag "Soiling" when current loss exceeds this
STALE_DATA_DAYS = 3  # site "not reporting" if no valid data in last N days of window


def ensure_dirs() -> None:
    for d in (RAW_DIR, PROCESSED_DIR):
        d.mkdir(parents=True, exist_ok=True)
