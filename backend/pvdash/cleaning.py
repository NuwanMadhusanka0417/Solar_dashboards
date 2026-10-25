"""
Flag-based meter cleaning (no imputation).

The old ``1_data_cleaning.py`` filled outages with XGBoost predictions. The
dashboard needs the opposite: show real (zero) generation during an outage and
*exclude* those hours from performance ratios. So every hour keeps its measured
value and gets flags instead:

  night    sun below horizon → reading forced to 0
  stuck    identical non-zero value for ≥ STUCK_MIN_HOURS → reading dropped
  capped   above inverter AC × 1.08 (catch-up spikes) → clipped to the cap
  missing  no reading while the sun is up
  outage   zero reading while it is clearly sunny
  valid    daylight hour usable for actual ÷ expected (not missing/stuck/outage/capped)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pvlib import location

from . import settings
from .pvmodel import localize
from .sites import Site


def chain_meters(meters: pd.DataFrame, meter_ids: list[str]) -> pd.Series:
    """One hourly series for a site; later meters in ``meter_ids`` win on overlapping hours."""
    parts = []
    for rank, mid in enumerate(meter_ids):
        m = meters[meters["meter"] == mid][["timestamp", "meter_reading"]].copy()
        m["rank"] = rank
        parts.append(m)
    if not parts:
        return pd.Series(dtype=float)
    df = pd.concat(parts).dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.floor("h")
    df = df.sort_values(["timestamp", "rank"]).drop_duplicates("timestamp", keep="last")
    return df.set_index("timestamp")["meter_reading"].astype(float)


def solar_zenith(index: pd.DatetimeIndex, campus: str) -> np.ndarray:
    c = settings.CAMPUSES[campus]
    loc = location.Location(c.latitude, c.longitude, tz=settings.TIMEZONE, altitude=c.altitude_m)
    # Hour-ending meter timestamps: take the sun position at mid-hour.
    mid = localize(index - pd.Timedelta(minutes=30))
    return loc.get_solarposition(mid)["apparent_zenith"].to_numpy()


def stuck_mask(values: np.ndarray, min_run: int = settings.STUCK_MIN_HOURS) -> np.ndarray:
    """True for runs of the same non-zero value lasting ≥ ``min_run`` hours."""
    v = np.asarray(values, dtype=float)
    out = np.zeros(len(v), dtype=bool)
    i = 0
    while i < len(v):
        if np.isfinite(v[i]) and v[i] > settings.ZERO_EPS:
            j = i
            while j < len(v) and v[j] == v[i]:
                j += 1
            if j - i >= min_run:
                out[i:j] = True
            i = j
        else:
            i += 1
    return out


def estimate_kwp(actual: pd.Series, ghi: pd.Series) -> float | None:
    """Rough DC capacity from output on bright hours, for sites missing from panel_data."""
    bright = actual[(ghi >= 800) & (actual > settings.ZERO_EPS)]
    if len(bright) < 50:
        bright = actual[actual > settings.ZERO_EPS]
    if len(bright) < 50:
        return None
    # p90 ignores catch-up spikes; bright-hour output ≈ 80 % of kWp after losses.
    return float(np.nanquantile(bright, 0.9)) / settings.CAPACITY_ESTIMATE_PEAK_RATIO


def clean_site(site: Site, readings: pd.Series, weather: pd.DataFrame) -> pd.DataFrame:
    """
    Hourly frame for one site on a continuous hourly grid.

    ``weather`` is the campus's hourly Solcast frame indexed by timestamp. Updates
    ``site.kwp`` / ``site.capacity_source`` in place when capacity is estimated.
    """
    if readings.empty:
        return pd.DataFrame()
    idx = pd.date_range(readings.index.min(), readings.index.max(), freq="h", name="timestamp")
    df = pd.DataFrame(index=idx)
    df["raw_kwh"] = readings.reindex(idx)
    w = weather.reindex(idx)
    df["ghi"] = w["ghi"] if "ghi" in w else np.nan
    df["rain_mm"] = w["rain_mm"] if "rain_mm" in w else np.nan
    df["zenith"] = solar_zenith(idx, site.campus)

    raw = df["raw_kwh"].to_numpy(dtype=float)
    night = df["zenith"].to_numpy() >= 90
    sun_up = ~night
    has_ghi = df["ghi"].notna().to_numpy()
    ghi = df["ghi"].to_numpy(dtype=float)
    # Without Solcast (e.g. weather gaps) fall back to sun elevation > 15°.
    sunny = np.where(has_ghi, ghi > settings.OUTAGE_GHI_MIN, df["zenith"].to_numpy() < 75)

    val = raw.copy()
    val[night & np.isfinite(val)] = 0.0
    stuck = stuck_mask(val)
    val[stuck] = np.nan

    if not site.kwp:
        est = estimate_kwp(pd.Series(val, index=idx), df["ghi"])
        if est:
            site.kwp = round(est, 1)
            site.capacity_source = "estimated"
    cap = site.physical_cap_kwh
    capped = np.zeros(len(val), dtype=bool)
    if cap:
        capped = np.isfinite(val) & (val > cap)
        val[capped] = cap

    missing = sun_up & ~np.isfinite(raw)
    outage = sunny & np.isfinite(val) & (val <= settings.ZERO_EPS)
    daylight = np.where(has_ghi, ghi > settings.DAYLIGHT_GHI_MIN, sun_up)
    valid = daylight & ~missing & ~stuck & ~outage & ~capped & np.isfinite(val)

    df["actual_kwh"] = np.where(np.isfinite(val), val, 0.0)
    df["flag_stuck"] = stuck
    df["flag_capped"] = capped
    df["flag_missing"] = missing
    df["flag_outage"] = outage & ~missing
    df["flag_sunny"] = sunny
    df["valid"] = valid
    return df
