#!/usr/bin/env python3
"""
STEP 1 — Download raw data into ``data/raw/`` (incremental; safe to re-run).

  meters_hourly.csv   SQL Server [dbo].[SolarMeterReadings] → hourly kWh per meter
  solcast_weather.csv Azure blob Solcast live + forecast CSVs, every campus
  air_quality.csv     Open-Meteo CAMS PM2.5 / PM10 per campus (drives HSU soiling)

Credentials come only from ``.env`` (see ``.env.example``).

Usage (from ``backend/``)::

  python download_data.py                       # everything, incremental
  python download_data.py --only meters         # one source: meters | weather | air
  python download_data.py --all-meters          # every 'realenergyintotheload' meter in SQL
  python download_data.py --import-legacy ../../PV_analysis/data_raw   # bootstrap from old project
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

from pvdash import settings
from pvdash.sites import all_meter_ids, load_sites

METER_COLS = ["timestamp", "meter", "meter_reading"]
WEATHER_REFRESH_DAYS = 14  # live Solcast replaces stale forecast rows in this window
AIR_REFRESH_DAYS = 5  # PM forecast hours are replaced by analysis values later
OPENMETEO_AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
CAMS_GLOBAL_START = pd.Timestamp("2022-08-01")


def log(msg: str) -> None:
    print(msg, flush=True)


# ── Meters (SQL Server) ─────────────────────────────────────────────────────


def sql_engine():
    from sqlalchemy import create_engine

    server, user, pwd = settings.env("LEAP_DB_SERVER"), settings.env("LEAP_DB_USER"), settings.env("LEAP_DB_PASSWORD")
    if not (server and user and pwd):
        raise SystemExit("Set LEAP_DB_SERVER / LEAP_DB_USER / LEAP_DB_PASSWORD in .env to download meters.")
    driver = settings.env("LEAP_DB_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    database = settings.env("LEAP_DB_DATABASE", "leap")
    odbc = (
        f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
        f"UID={user};PWD={pwd};TrustServerCertificate=yes"
    )
    return create_engine("mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc))


def readings_to_hourly_kwh(df: pd.DataFrame, meter_id: str) -> pd.DataFrame:
    """Cumulative register → interval energy → 30-min sum → hourly sum (same as the old pipeline)."""
    if df.empty:
        return pd.DataFrame(columns=METER_COLS)
    work = df.drop_duplicates(subset=["ReadingTimestamp"]).copy()
    work["MeterReading"] = pd.to_numeric(work["MeterReading"], errors="coerce").interpolate()
    diff = work["MeterReading"].diff()
    valid = diff.dropna()
    if not valid.empty:
        hi = float(np.nanquantile(valid, 0.999))
        diff = diff.where((diff >= 0) & (diff <= hi))
    work["meter_reading"] = diff.interpolate(method="linear")
    work["timestamp"] = pd.to_datetime(work["ReadingTimestamp"], errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").set_index("timestamp")
    half_hour = work["meter_reading"].resample("30min").sum()
    hourly = half_hour.resample("h", label="right", closed="right").sum(min_count=1).reset_index()
    hourly["meter"] = meter_id
    return hourly[METER_COLS]


def download_meters(meter_ids: list[str], *, all_meters: bool, dry_run: bool) -> None:
    from sqlalchemy import text

    path = settings.RAW_METERS_CSV
    existing = pd.read_csv(path, parse_dates=["timestamp"]) if path.is_file() else pd.DataFrame(columns=METER_COLS)
    last_by_meter = existing.groupby("meter")["timestamp"].max().to_dict() if not existing.empty else {}

    engine = sql_engine()
    try:
        if all_meters:
            q = text(
                "SELECT DISTINCT [MeterKeyString] AS meter FROM [dbo].[SolarMeterReadings] "
                "WHERE [MeterKeyString] LIKE '%realenergyintotheload%'"
            )
            meter_ids = sorted(pd.read_sql_query(q, engine)["meter"].astype(str).str.strip().unique())
        log(f"  {len(meter_ids)} meter(s)")

        new_parts = []
        for meter_id in meter_ids:
            since = last_by_meter.get(meter_id)
            params = {"meter": meter_id}
            sql = (
                "SELECT [ReadingTimestamp], [MeterReading] FROM [dbo].[SolarMeterReadings] "
                "WHERE [MeterKeyString] = :meter"
            )
            if since is not None:
                # Re-read from one hour before the last stored hour so the first diff has an anchor.
                sql += " AND [ReadingTimestamp] > :since"
                params["since"] = since - pd.Timedelta(hours=1)
            raw = pd.read_sql_query(text(sql + " ORDER BY [ReadingTimestamp]"), engine, params=params)
            hourly = readings_to_hourly_kwh(raw, meter_id)
            if since is not None:
                hourly = hourly[hourly["timestamp"] > since]
            log(f"  {meter_id}: +{len(hourly):,} h" + (f" after {since}" if since is not None else " (full history)"))
            if not hourly.empty:
                new_parts.append(hourly)
    finally:
        engine.dispose()

    if dry_run or not new_parts:
        log("  nothing written" + (" (dry run)" if dry_run else ""))
        return
    merged = pd.concat([existing, *new_parts], ignore_index=True)
    merged["timestamp"] = pd.to_datetime(merged["timestamp"]).dt.floor("h")
    merged = merged.sort_values(["meter", "timestamp"]).drop_duplicates(["meter", "timestamp"], keep="last")
    merged.to_csv(path, index=False)
    log(f"  wrote {path} ({len(merged):,} rows)")


# ── Weather (Azure Solcast blobs) ───────────────────────────────────────────


def normalize_weather(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    if "timestamp" not in out.columns and "period_end" in out.columns:
        out["timestamp"] = out["period_end"]
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out = out.dropna(subset=["timestamp"])
    out["campus"] = out["campus"].astype(str).str.strip().str.upper()
    if "accessed_on" in out.columns:
        out["accessed_on"] = pd.to_datetime(out["accessed_on"], errors="coerce")
        out = out.sort_values("accessed_on").drop_duplicates(["timestamp", "campus"], keep="last")
    return out.drop(columns=[c for c in ("accessed_on", "source_file", "timestamp_utc") if c in out.columns])


def merge_weather(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    out = pd.concat([existing, new], ignore_index=True, sort=False)
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    return out.sort_values(["campus", "timestamp"]).drop_duplicates(["campus", "timestamp"], keep="last")


def download_weather(campuses: list[str] | None, *, dry_run: bool) -> None:
    from azure.storage.blob import BlobServiceClient

    sas = settings.env("AZURE_STORAGE_SAS_TOKEN")
    if not sas:
        raise SystemExit("Set AZURE_STORAGE_SAS_TOKEN in .env to download Solcast weather.")
    account = settings.env("AZURE_STORAGE_ACCOUNT_URL", "https://leapdata.blob.core.windows.net").rstrip("/")
    container = settings.env("AZURE_STORAGE_CONTAINER", "solar-forecasts-solcast")
    client = BlobServiceClient(account_url=account, credential=sas).get_container_client(container)

    frames = []
    for blob in client.list_blobs():
        if blob.name.endswith(".csv") and ("live" in blob.name or "forecast" in blob.name):
            data = client.get_blob_client(blob.name).download_blob().readall()
            frames.append(pd.read_csv(StringIO(data.decode("utf-8", errors="replace"))))
    if not frames:
        raise RuntimeError(f"No Solcast live/forecast blobs in container {container!r}")
    live = normalize_weather(pd.concat(frames, ignore_index=True))
    log(f"  {len(frames)} blob(s), {len(live):,} rows, campuses {sorted(live['campus'].unique())}")
    if campuses:
        live = live[live["campus"].isin(campuses)]

    path = settings.RAW_WEATHER_CSV
    existing = pd.read_csv(path, parse_dates=["timestamp"]) if path.is_file() else pd.DataFrame()
    if not existing.empty:
        last = existing.groupby("campus")["timestamp"].max()
        cutoff = live["campus"].map(last) - pd.Timedelta(days=WEATHER_REFRESH_DAYS)
        live = live[cutoff.isna() | (live["timestamp"] >= cutoff)]
    log(f"  merging {len(live):,} rows")
    if dry_run or live.empty:
        return
    merge_weather(existing, live).to_csv(path, index=False)
    log(f"  wrote {path}")


# ── Air quality (Open-Meteo CAMS) ───────────────────────────────────────────


def fetch_pm(campus: settings.Campus, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    import requests

    frames = []
    for year in range(start.year, end.year + 1):
        s = max(start, pd.Timestamp(f"{year}-01-01"))
        e = min(end, pd.Timestamp(f"{year}-12-31"))
        r = requests.get(
            OPENMETEO_AIR_URL,
            params={
                "latitude": campus.latitude,
                "longitude": campus.longitude,
                "hourly": "pm2_5,pm10",
                "start_date": s.strftime("%Y-%m-%d"),
                "end_date": e.strftime("%Y-%m-%d"),
                "timezone": "GMT",
                "domains": "cams_global",
            },
            timeout=120,
        )
        r.raise_for_status()
        hourly = r.json().get("hourly", {})
        if hourly.get("time"):
            frames.append(pd.DataFrame(hourly).rename(columns={"time": "timestamp_utc"}))
    if not frames:
        return pd.DataFrame(columns=["timestamp_utc", "campus", "pm2_5", "pm10"])
    out = pd.concat(frames, ignore_index=True)
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"])
    out["campus"] = campus.code
    return out.dropna(subset=["pm2_5", "pm10"], how="all")


def download_air_quality(campuses: list[str], *, dry_run: bool) -> None:
    path = settings.RAW_AIR_QUALITY_CSV
    existing = pd.read_csv(path, parse_dates=["timestamp_utc"]) if path.is_file() else pd.DataFrame()
    # CAMS forecasts reach ~4 days ahead; useful for the 7-day soiling simulator.
    end = pd.Timestamp.utcnow().tz_localize(None).normalize() + pd.Timedelta(days=4)
    parts = []
    for code in campuses:
        campus = settings.CAMPUSES[code]
        have = existing[existing["campus"] == code] if not existing.empty else existing
        start = (
            have["timestamp_utc"].max() - pd.Timedelta(days=AIR_REFRESH_DAYS)
            if not have.empty
            else CAMS_GLOBAL_START
        ).normalize()
        log(f"  {code}: PM {start.date()} -> {end.date()}")
        if dry_run:
            continue
        try:
            parts.append(fetch_pm(campus, start, end))
        except Exception as exc:  # one campus failing should not stop the others
            log(f"    WARNING: {exc}")
    if dry_run or not parts:
        return
    merged = pd.concat([existing, *parts], ignore_index=True)
    merged = merged.sort_values(["campus", "timestamp_utc"]).drop_duplicates(["campus", "timestamp_utc"], keep="last")
    merged.to_csv(path, index=False)
    log(f"  wrote {path} ({len(merged):,} rows)")


# ── One-off migration from the old PV_analysis/data_raw folder ──────────────


def import_legacy(legacy_dir: Path) -> None:
    legacy_dir = legacy_dir.resolve()
    log(f"Importing legacy raw data from {legacy_dir}")

    for name in ("SolarMeterReadings1hour.csv", "SolarMeterReadings1hour_2020_2025.csv"):
        src = legacy_dir / name
        if src.is_file():
            meters = pd.read_csv(src, usecols=METER_COLS, parse_dates=["timestamp"])
            meters.to_csv(settings.RAW_METERS_CSV, index=False)
            log(f"  meters: {src.name} -> {settings.RAW_METERS_CSV.name} ({len(meters):,} rows)")
            break

    weather = pd.DataFrame()
    # Archive first, then the live file so live rows win on overlap.
    for name in ("solcast_df.csv", "solcast_df_2020_2025.csv"):
        src = legacy_dir / name
        if src.is_file():
            weather = merge_weather(weather, normalize_weather(pd.read_csv(src)))
            log(f"  weather: + {src.name}")
    if not weather.empty:
        weather.to_csv(settings.RAW_WEATHER_CSV, index=False)
        log(f"  weather -> {settings.RAW_WEATHER_CSV.name} ({len(weather):,} rows)")

    src = legacy_dir / "hsu_soiling_output.csv"
    if src.is_file():
        hsu = pd.read_csv(src, index_col=0)
        ts = pd.to_datetime(hsu.index, utc=True).tz_localize(None)
        air = pd.DataFrame({"timestamp_utc": ts, "campus": "BUNDOORA", "pm2_5": hsu["pm2_5"].values, "pm10": hsu["pm10"].values})
        # Old file filled pre-CAMS hours with climatology; keep only real CAMS hours.
        air = air[air["timestamp_utc"] >= CAMS_GLOBAL_START]
        air.to_csv(settings.RAW_AIR_QUALITY_CSV, index=False)
        log(f"  air quality (Bundoora PM) -> {settings.RAW_AIR_QUALITY_CSV.name} ({len(air):,} rows)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=("meters", "weather", "air"), action="append")
    ap.add_argument("--all-meters", action="store_true", help="Download every realenergyintotheload meter.")
    ap.add_argument("--campus", action="append", help="Limit weather / air quality to these campus codes.")
    ap.add_argument("--import-legacy", type=Path, help="Copy raw CSVs from the old PV_analysis/data_raw folder first.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings.ensure_dirs()
    if args.import_legacy:
        import_legacy(args.import_legacy)
        if not args.only:
            return 0

    sources = set(args.only or ("meters", "weather", "air"))
    campuses = [c.upper() for c in args.campus] if args.campus else list(settings.CAMPUS_ORDER)

    if "weather" in sources:
        log("\n[weather] Azure Solcast")
        download_weather(campuses if args.campus else None, dry_run=args.dry_run)
    if "air" in sources:
        log("\n[air] Open-Meteo PM2.5/PM10")
        download_air_quality(campuses, dry_run=args.dry_run)
    if "meters" in sources:
        log("\n[meters] SQL Server")
        download_meters(all_meter_ids(load_sites()), all_meters=args.all_meters, dry_run=args.dry_run)
    log("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
