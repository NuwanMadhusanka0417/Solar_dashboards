"""
Solcast weather → hourly frames aligned with the meters.

The raw Solcast rows mix two timestamp conventions:

* the historical archive (``solcast_df.csv``): period-end, fixed UTC+9
* the live / forecast Azure blobs: period-end, Melbourne wall clock (DST-aware)

The old pipeline read both as Melbourne local time, which put expected power
1–2 h out of step with the meters. Here each calendar day is tested against
Solcast's own ``zenith`` column and converted with whichever convention fits,
then aggregated to hour-ending Melbourne wall clock — the meters' convention.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pvlib import solarposition

from . import settings

WEATHER_COLS = ["ghi", "dni", "dhi", "air_temp", "wind_speed_10m", "albedo", "cloud_opacity"]


def _zenith(utc: pd.DatetimeIndex, campus: settings.Campus) -> np.ndarray:
    z = np.full(len(utc), np.nan)
    ok = ~utc.isna()
    if ok.any():
        sp = solarposition.get_solarposition(utc[ok], campus.latitude, campus.longitude, campus.altitude_m)
        z[ok] = sp["zenith"].to_numpy()
    return z


def to_utc_period_end(raw: pd.DataFrame, campus_code: str) -> pd.Series:
    """UTC instant of each row's period end, choosing the timestamp convention per day."""
    campus = settings.CAMPUSES[campus_code]
    ts = pd.DatetimeIndex(raw["timestamp"])
    candidates = {"local": ts.tz_localize(settings.TIMEZONE, ambiguous="NaT", nonexistent="NaT").tz_convert("UTC")}
    for hours in (9, 10, 11):
        candidates[f"utc+{hours}"] = (ts - pd.Timedelta(hours=hours)).tz_localize("UTC")
    observed = pd.to_numeric(raw["zenith"], errors="coerce").to_numpy() if "zenith" in raw else None
    if observed is None or np.isnan(observed).all():
        return pd.Series(candidates["local"], index=raw.index)

    half = pd.Timedelta(minutes=15)  # Solcast zenith is the mid-point of the 30-min period
    sun = observed < 85
    day = ts.normalize()
    errors = pd.DataFrame({"day": day})
    for name, utc in candidates.items():
        errors[name] = np.where(sun, np.abs(_zenith(utc - half, campus) - observed), np.nan)
    per_day = errors.groupby("day").mean()
    # Prefer local time on ties (e.g. polar-night style days with no sun rows).
    best = per_day.fillna(np.inf).idxmin(axis=1).where(per_day.notna().any(axis=1), "local")
    choice = best.reindex(day).fillna("local").to_numpy()
    out = candidates["local"].copy()
    for name, utc in candidates.items():
        out = out.where(choice != name, utc)
    return pd.Series(out, index=raw.index)


def hourly_campus_weather(raw: pd.DataFrame, campus_code: str) -> pd.DataFrame:
    """Hour-ending Melbourne wall-clock weather for one campus (index ``timestamp``)."""
    df = raw.copy()
    df["utc"] = pd.to_datetime(to_utc_period_end(df, campus_code), utc=True)
    df = df.dropna(subset=["utc"]).sort_values("utc").drop_duplicates("utc", keep="last").set_index("utc")
    num = df[[c for c in WEATHER_COLS + ["precipitation_rate"] if c in df.columns]].apply(pd.to_numeric, errors="coerce")

    step_h = num.index.to_series().diff().dt.total_seconds().median() / 3600 or 0.5
    hourly = num.drop(columns=["precipitation_rate"], errors="ignore").resample("1h", label="right", closed="right").mean()
    if "precipitation_rate" in num:
        hourly["rain_mm"] = (num["precipitation_rate"].fillna(0) * step_h).resample("1h", label="right", closed="right").sum()
    hourly = hourly.dropna(subset=["ghi"])

    local = hourly.index.tz_convert(settings.TIMEZONE).tz_localize(None)
    hourly.index = pd.DatetimeIndex(local, name="timestamp")
    return hourly[~hourly.index.duplicated(keep="first")]


def load_all(path=settings.RAW_WEATHER_CSV, log=print) -> dict[str, pd.DataFrame]:
    w = pd.read_csv(path, parse_dates=["timestamp"])
    out = {}
    for campus, grp in w.groupby("campus"):
        code = str(campus).upper()
        if code not in settings.CAMPUSES:
            continue
        hourly = hourly_campus_weather(grp.drop(columns=["campus"]), code)
        out[code] = hourly
        log(f"  weather {code}: {hourly.index.min()} -> {hourly.index.max()} ({len(hourly):,} h)")
    return out
