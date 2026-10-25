#!/usr/bin/env python3
"""
STEP 2 — Turn ``data/raw/`` into dashboard-ready CSVs in ``data/processed/``.

For every enabled site in ``config/sites.csv``:
  clean meter data (flags, no imputation) → PVLib expected → daily metrics →
  health ratio / degradation / seasons → soiling loss + cleaning advice → forecast.

Outputs (all CSV, long format with a ``site_key`` column):
  sites.csv                     registry + capacity source + data coverage
  daily.csv                     one row per site per day (energy, H, weather, data quality)
  health_yearly.csv / health_monthly.csv
  degradation.csv               year- and month-based H trend per site
  seasonal_points.csv / seasonal_annual.csv / seasonal_summary.csv
  soiling_campus_daily.csv      HSU soiling ratio per campus per day
  soiling_site_daily.csv        soiling energy loss per site per day
  soiling_week.csv              7 forward days per site (expected kWh + forecast rain)
  soiling_recommendation.csv    current cleaning advice per site
  forecast_hourly.csv / forecast_meta.csv
  pipeline_meta.json

Usage (from ``backend/``)::

  python process_data.py
  python process_data.py --sites library dw    # just these sites (others keep previous output)
  python process_data.py --skip-forecast        # faster refresh
  python process_data.py --write-hourly         # also write hourly/<site>.csv for debugging
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings

import numpy as np
import pandas as pd

from pvdash import analytics, cleaning, forecast, pvmodel, settings, soiling
from pvdash import weather as wx
from pvdash.sites import Site, load_sites

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
OUT = settings.PROCESSED_DIR


def log(msg: str) -> None:
    print(msg, flush=True)


def campus_soiling(weather: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    air = pd.read_csv(settings.RAW_AIR_QUALITY_CSV, parse_dates=["timestamp_utc"]) if settings.RAW_AIR_QUALITY_CSV.is_file() else pd.DataFrame(columns=["timestamp_utc", "campus", "pm2_5", "pm10"])
    out = {}
    for campus, w in weather.items():
        if "rain_mm" not in w:
            continue
        pm = soiling.pm_local_hourly(air, campus)
        hourly = soiling.hsu_campus(w["rain_mm"], pm)
        out[campus] = soiling.daily_soiling(hourly)
        log(f"  HSU {campus}: mean SR {hourly['soiling_ratio'].mean():.4f}, PM hours observed {len(pm):,}")
    return out


def forward_week(site_hourly_exp: pd.Series, anchor: pd.Timestamp, soil_daily: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Seven days after the last reading: expected kWh from forecast weather, rain from Solcast forecast."""
    days = pd.date_range(anchor + pd.Timedelta(days=1), periods=settings.SOILING_FORECAST_DAYS, freq="D")
    exp_daily = site_hourly_exp.groupby(site_hourly_exp.index.normalize()).sum(min_count=12)
    fallback = daily["expected_kwh"].tail(30).mean()
    rain = soil_daily.set_index("date")
    week = pd.DataFrame({"date": days})
    week["expected_kwh"] = exp_daily.reindex(days).fillna(fallback if np.isfinite(fallback) else 0).to_numpy()
    week["rain_mm"] = rain["rain_mm"].reindex(days).fillna(0).to_numpy()
    week["rain_max_mm"] = rain["rain_max_mm"].reindex(days).fillna(0).to_numpy()
    week["has_weather"] = exp_daily.reindex(days).notna().to_numpy()
    return week


def process_site(site: Site, readings: pd.Series, weather: pd.DataFrame, soil_daily: pd.DataFrame | None, args) -> dict | None:
    t0 = time.time()
    hourly = cleaning.clean_site(site, readings, weather)
    if hourly.empty or not site.kwp:
        log(f"  [{site.key}] skipped (no usable readings)")
        return None

    exp = pvmodel.expected_generation(
        weather.reset_index(), campus=site.campus, system_dc_kw=site.kwp, inverter_ac_kw=site.inverter_ac_kw,
        tilt_deg=site.tilt_deg, azimuth_deg=site.azimuth_deg,
    ).set_index("timestamp")
    hourly = hourly.join(exp)
    daily = analytics.daily_from_hourly(hourly)
    if args.write_hourly:
        (OUT / "hourly").mkdir(exist_ok=True)
        hourly.to_csv(OUT / "hourly" / f"{site.key}.csv")

    res: dict = {"site": site, "daily": daily}
    # Long-term trends only use data from ANALYSIS_START (early meter data is unreliable).
    hist = daily[daily["date"] >= pd.Timestamp(settings.ANALYSIS_START)]
    res["deg"] = {"site_key": site.key, **analytics.degradation(hist)}
    res["yearly"] = analytics.health_by_period(hist, "Y").assign(site_key=site.key)
    res["monthly"] = analytics.health_by_period(hist, "M").assign(site_key=site.key)
    pts, annual, summary = analytics.seasonal(hist)
    res["season_pts"], res["season_annual"], res["season_summary"] = (x.assign(site_key=site.key) for x in (pts, annual, summary))

    has_reading = hourly["raw_kwh"].notna() & (hourly["actual_kwh"] > 0)
    last_ts = hourly.index[has_reading][-1] if has_reading.any() else hourly.index[-1]
    anchor = last_ts.normalize()

    if soil_daily is not None and not soil_daily.empty:
        hist_soil = soil_daily[soil_daily["date"] <= anchor]
        sd = soiling.site_soiling_daily(hist_soil, daily)
        res["soil_site"] = sd.assign(site_key=site.key)
        week = forward_week(exp["expected_kwh"], anchor, soil_daily, daily)
        res["soil_week"] = week.assign(site_key=site.key)
        if len(sd):
            res["soil_rec"] = {"site_key": site.key, **soiling.recommendation(sd, week)}

    if not args.skip_forecast:
        feats = hourly.join(weather[[c for c in ("ghi", "dni", "dhi", "air_temp", "wind_speed_10m") if c in weather]], rsuffix="_w")
        hist = feats.drop(columns=[c for c in feats.columns if c.endswith("_w")])
        fut_idx = exp.index[(exp.index >= anchor + pd.Timedelta(days=1))][: forecast.FORECAST_HOURS_MAX]
        future = exp.loc[fut_idx].join(weather.drop(columns=["rain_mm"], errors="ignore"))
        future["zenith"] = cleaning.solar_zenith(future.index, site.campus) if len(future) else []
        fc, meta = forecast.forecast_site(hist, future)
        res["forecast"] = fc.assign(site_key=site.key) if len(fc) else fc
        res["forecast_meta"] = {"site_key": site.key, "forecast_start": str(fut_idx[0]) if len(fut_idx) else "", "forecast_hours": len(fut_idx), **meta}

    valid_days = daily[daily["valid_hours"] > 0]
    res["coverage"] = {
        "first_date": str(daily["date"].min().date()),
        "last_reading": str(last_ts),
        "last_valid_date": str(valid_days["date"].max().date()) if len(valid_days) else "",
        "weather_until": str(weather.index.max()),
    }
    log(
        f"  [{site.key}] {site.kwp:.0f} kWp ({site.capacity_source}) H={res['deg']['mean_h']:.3f} "
        f"trend={res['deg']['yearly_pct_per_year']:+.2f}%/yr  {time.time() - t0:.1f}s"
    )
    return res


def write(name: str, frames: list[pd.DataFrame], keys: list[str], previous_keep: bool) -> None:
    """Write a long CSV; when only some sites were processed, keep other sites' old rows."""
    frames = [f for f in frames if f is not None and len(f)]
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    path = OUT / name
    if previous_keep and path.is_file():
        old = pd.read_csv(path)
        if "site_key" in old.columns:
            df = pd.concat([old[~old["site_key"].isin(keys)], df], ignore_index=True)
    if "site_key" in df.columns:
        df = df[["site_key"] + [c for c in df.columns if c != "site_key"]]
    df.to_csv(path, index=False, float_format="%.6g")
    log(f"  wrote {name} ({len(df):,} rows)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", nargs="*", help="Only process these site keys.")
    ap.add_argument("--skip-forecast", action="store_true")
    ap.add_argument("--write-hourly", action="store_true")
    args = ap.parse_args()

    settings.ensure_dirs()
    t0 = time.time()
    sites = load_sites()
    if args.sites:
        wanted = {s.lower() for s in args.sites}
        sites = [s for s in sites if s.key in wanted]
    log(f"Processing {len(sites)} site(s)")

    log("\nLoading weather")
    weather = wx.load_all(log=log)
    log("\nHSU soiling per campus")
    soil = campus_soiling(weather)

    log("\nLoading meters")
    needed = {m for s in sites for m in s.meter_ids}
    meters = pd.read_csv(settings.RAW_METERS_CSV, parse_dates=["timestamp"])
    meters = meters[meters["meter"].isin(needed)]
    by_meter = {k: g for k, g in meters.groupby("meter")}
    log(f"  {len(meters):,} rows for {len(by_meter)} meter(s)")

    log("\nSites")
    results = []
    for site in sites:
        if site.campus not in weather:
            log(f"  [{site.key}] skipped: no weather for campus {site.campus}")
            continue
        parts = pd.concat([by_meter[m] for m in site.meter_ids if m in by_meter]) if any(m in by_meter for m in site.meter_ids) else pd.DataFrame(columns=["timestamp", "meter", "meter_reading"])
        readings = cleaning.chain_meters(parts, site.meter_ids)
        try:
            r = process_site(site, readings, weather[site.campus], soil.get(site.campus), args)
        except Exception as exc:
            log(f"  [{site.key}] ERROR: {exc}")
            continue
        if r:
            results.append(r)

    log("\nWriting outputs")
    keys = [r["site"].key for r in results]
    partial = bool(args.sites)
    sites_rows = [{**r["site"].to_record(), **r["coverage"]} for r in results]
    write("sites.csv", [pd.DataFrame(sites_rows)], keys, partial)
    write("daily.csv", [r["daily"].assign(site_key=r["site"].key) for r in results], keys, partial)
    write("health_yearly.csv", [r["yearly"] for r in results], keys, partial)
    write("health_monthly.csv", [r["monthly"] for r in results], keys, partial)
    write("degradation.csv", [pd.DataFrame([r["deg"] for r in results])], keys, partial)
    write("seasonal_points.csv", [r["season_pts"] for r in results], keys, partial)
    write("seasonal_annual.csv", [r["season_annual"] for r in results], keys, partial)
    write("seasonal_summary.csv", [r["season_summary"] for r in results], keys, partial)
    write("soiling_site_daily.csv", [r.get("soil_site") for r in results], keys, partial)
    write("soiling_week.csv", [r.get("soil_week") for r in results], keys, partial)
    write("soiling_recommendation.csv", [pd.DataFrame([r["soil_rec"] for r in results if "soil_rec" in r])], keys, partial)
    soil_frames = [d.assign(campus=c) for c, d in soil.items()]
    pd.concat(soil_frames).to_csv(OUT / "soiling_campus_daily.csv", index=False, float_format="%.6g")
    if not args.skip_forecast:
        write("forecast_hourly.csv", [r.get("forecast") for r in results], keys, partial)
        write("forecast_meta.csv", [pd.DataFrame([r["forecast_meta"] for r in results if "forecast_meta" in r])], keys, partial)

    meta = {
        "generated_at": pd.Timestamp.now(tz=settings.TIMEZONE).isoformat(timespec="seconds"),
        "sites_processed": len(results),
        "duration_s": round(time.time() - t0, 1),
        "weather_until": {c: str(w.index.max()) for c, w in weather.items()},
        "tariff_aud_per_kwh": settings.TARIFF_AUD_PER_KWH,
        "analysis_start": settings.ANALYSIS_START,
    }
    (OUT / "pipeline_meta.json").write_text(json.dumps(meta, indent=2))
    log(f"\nDone in {meta['duration_s']} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
