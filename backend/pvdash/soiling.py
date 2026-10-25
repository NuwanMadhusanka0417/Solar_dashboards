"""
pvlib HSU soiling per campus, soiling energy loss per site, cleaning
recommendation and the 7-day cleaning simulator.

Ported from ``0_download_data.py`` (HSU run) and ``tab_health_monitor.js``
(rain-clean detection, soiling rate since last rain clean, week simulation).
Rain and PM are aligned in Melbourne local time (the old script treated the
local Solcast timestamps as UTC, shifting rain by ~10 h).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import settings


# ── HSU model ───────────────────────────────────────────────────────────────


def pm_local_hourly(air: pd.DataFrame, campus: str) -> pd.DataFrame:
    """Open-Meteo PM (UTC) → Melbourne wall-clock hourly, duplicates at DST end dropped."""
    a = air[air["campus"] == campus].copy()
    if a.empty:
        return pd.DataFrame(columns=["pm2_5", "pm10"])
    ts = pd.to_datetime(a["timestamp_utc"]).dt.tz_localize("UTC").dt.tz_convert(settings.TIMEZONE).dt.tz_localize(None)
    a.index = ts
    a = a[~a.index.duplicated(keep="first")].sort_index()
    return a[["pm2_5", "pm10"]].astype(float)


def fill_pm_climatology(pm: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Gaps (e.g. before CAMS in Aug 2022) → month × hour medians of observed PM."""
    out = pm.reindex(index)
    obs = out.dropna()
    if obs.empty:
        # No PM at all for this campus: use a typical clean-air Victorian level.
        return pd.DataFrame({"pm2_5": 6.0, "pm10": 12.0}, index=index)
    out = out.interpolate(limit=6, limit_area="inside")
    med = obs.groupby([obs.index.month, obs.index.hour]).median()
    miss = out["pm2_5"].isna() | out["pm10"].isna()
    if miss.any():
        keys = list(zip(out.index[miss].month, out.index[miss].hour))
        fill = med.reindex(keys)
        out.loc[miss, "pm2_5"] = fill["pm2_5"].fillna(obs["pm2_5"].median()).to_numpy()
        out.loc[miss, "pm10"] = fill["pm10"].fillna(obs["pm10"].median()).to_numpy()
    return out


def hsu_campus(rain_hourly: pd.Series, pm: pd.DataFrame, tilt_deg: float = settings.DEFAULT_TILT_DEG) -> pd.DataFrame:
    """Hourly soiling ratio for one campus from hourly rain (mm) and PM (µg/m³)."""
    import pvlib

    rain = rain_hourly.fillna(0.0)
    # HSU needs a gap-free series; rain gaps count as dry hours.
    idx = pd.date_range(rain.index.min(), rain.index.max(), freq="h")
    rain = rain.reindex(idx, fill_value=0.0)
    pm_full = fill_pm_climatology(pm, idx)
    sr = pvlib.soiling.hsu(
        rainfall=rain,
        cleaning_threshold=settings.HSU_CLEANING_THRESHOLD_MM,
        surface_tilt=tilt_deg,
        pm2_5=pm_full["pm2_5"] * settings.PM_UGM3_TO_GM3,
        pm10=pm_full["pm10"] * settings.PM_UGM3_TO_GM3,
        depo_veloc=None,
        rain_accum_period=pd.Timedelta("1h"),
    )
    return pd.DataFrame({"rain_mm": rain, "pm2_5": pm_full["pm2_5"], "pm10": pm_full["pm10"], "soiling_ratio": sr})


def daily_soiling(hourly: pd.DataFrame) -> pd.DataFrame:
    g = hourly.groupby(hourly.index.normalize())
    out = pd.DataFrame(
        {
            "sr": g["soiling_ratio"].mean(),
            "rain_mm": g["rain_mm"].sum(),
            "rain_max_mm": g["rain_mm"].max(),
            "pm2_5": g["pm2_5"].mean(),
            "pm10": g["pm10"].mean(),
        }
    )
    return out.rename_axis("date").reset_index()


# ── Site-level soiling energy ───────────────────────────────────────────────


def is_rain_clean(rain_max: float, sr: float, sr_prev: float) -> bool:
    if (rain_max or 0) < settings.HSU_CLEANING_THRESHOLD_MM:
        return False
    return (sr - sr_prev) >= settings.HSU_SR_CLEAN_JUMP or sr >= 0.998


def site_soiling_daily(soil: pd.DataFrame, site_daily: pd.DataFrame) -> pd.DataFrame:
    """Join campus SR to a site's daily expected energy; cumulative loss resets on rain cleans."""
    d = soil.merge(site_daily[["date", "expected_kwh"]], on="date", how="left")
    d["loss_kwh"] = (d["expected_kwh"].fillna(0) * (1 - d["sr"])).clip(lower=0)
    cum, clean_flags, prev = [], [], d["sr"].iloc[0] if len(d) else 1.0
    running = 0.0
    for sr, rmax, loss in zip(d["sr"], d["rain_max_mm"], d["loss_kwh"]):
        clean = is_rain_clean(rmax, sr, prev)
        running = loss if clean else running + loss
        cum.append(running)
        clean_flags.append(clean)
        prev = sr
    d["cum_loss_kwh"] = cum
    d["rain_clean"] = clean_flags
    return d


def _slope_per_day(rows: pd.DataFrame) -> float:
    if len(rows) < 3:
        return np.nan
    x = (rows["date"] - rows["date"].iloc[0]).dt.days.to_numpy(dtype=float)
    return float(np.polyfit(x, rows["sr"].to_numpy(), 1)[0])


def soiling_rate_since_rain_clean(d: pd.DataFrame) -> float:
    """SR change per day since the last rain clean (negative = dirtying)."""
    if d.empty:
        return -0.0005
    seg_start = 0
    for i in range(1, len(d)):
        if d["rain_clean"].iloc[i]:
            seg_start = i
    seg = d.iloc[seg_start:]
    dry = pd.concat([seg.iloc[:1], seg.iloc[1:][~seg["rain_clean"].iloc[1:]]])
    for rows in (dry, seg.tail(21), seg, d.tail(120)):
        s = _slope_per_day(rows)
        if np.isfinite(s) and s < 0:
            return s
    return -0.0005


# ── 7-day simulator ─────────────────────────────────────────────────────────


def simulate_week(
    week: pd.DataFrame,
    start_sr: float,
    rate_per_day: float,
    clean_index: int | None = None,
    cost: float = settings.CLEANING_COST_AUD,
    tariff: float = settings.TARIFF_AUD_PER_KWH,
) -> list[dict]:
    """
    Forward week: SR falls by ``rate_per_day`` each dry day, resets to 1 on
    forecast rain ≥ threshold or on the manual clean day (no loss that day).
    """
    rate = rate_per_day if np.isfinite(rate_per_day) and rate_per_day < 0 else -0.0005
    sr, cum, total = start_sr, 0.0, 0.0
    points = []
    for i, row in enumerate(week.itertuples(index=False)):
        manual = clean_index == i
        rain_clean = not manual and (row.rain_max_mm or 0) >= settings.HSU_CLEANING_THRESHOLD_MM
        if manual or rain_clean:
            sr, cum = 1.0, 0.0
            if manual:
                total += cost
        else:
            sr = max(settings.HSU_SR_FLOOR, sr + rate)
        loss_kwh = 0.0 if manual else max(0.0, (row.expected_kwh or 0) * (1 - sr))
        loss = loss_kwh * tariff
        cum += loss
        total += loss
        points.append(
            {
                "date": str(pd.Timestamp(row.date).date()),
                "sr": round(sr, 5),
                "rain_mm": round(float(row.rain_mm or 0), 2),
                "expected_kwh": round(float(row.expected_kwh or 0), 1),
                "loss_kwh": round(loss_kwh, 3),
                "loss_aud": round(loss, 3),
                "cum_loss_aud": round(cum, 3),
                "rain_clean": bool(rain_clean),
                "manual_clean": bool(manual),
            }
        )
    return points


def recommendation(
    d: pd.DataFrame, week: pd.DataFrame, cost: float = settings.CLEANING_COST_AUD, tariff: float = settings.TARIFF_AUD_PER_KWH
) -> dict:
    """Clean only when the energy saved over the forecast week beats the cleaning cost."""
    last = d.iloc[-1]
    rate = soiling_rate_since_rain_clean(d)
    baseline = simulate_week(week, last["sr"], rate, None, cost, tariff)
    base_loss = sum(p["loss_aud"] for p in baseline)
    best_day, best_net = None, -np.inf
    for i in range(len(week)):
        sim = simulate_week(week, last["sr"], rate, i, cost, tariff)
        net = base_loss - sum(p["loss_aud"] for p in sim) - cost
        if net > best_net:
            best_day, best_net = baseline[i]["date"], net
    rain_days = week[week["rain_max_mm"] >= settings.HSU_CLEANING_THRESHOLD_MM]
    next_rain = rain_days.iloc[0] if len(rain_days) else None
    loss_today = float(last["loss_kwh"])

    if best_net > settings.CLEAN_DECISION_MARGIN_AUD:
        action = "clean"
        headline = f"Clean on {pd.Timestamp(best_day):%a %d %b}"
        reason = f"Cleaning saves about ${best_net + cost:,.0f} of energy this week, ${best_net:,.0f} more than it costs."
    else:
        action = "wait"
        headline = "Wait – do not clean yet"
        if next_rain is not None:
            reason = (
                f"Forecast rain on {pd.Timestamp(next_rain['date']):%a %d %b} is expected to recover most of the "
                "current soiling loss; cleaning would not pay back this week."
            )
        else:
            reason = "The soiling loss this week is far smaller than the cleaning cost."
    return {
        "anchor_date": str(pd.Timestamp(last["date"]).date()),
        "current_sr": float(last["sr"]),
        "rate_pct_per_day": rate * 100,
        "loss_kwh_per_day": loss_today,
        "loss_aud_per_day": loss_today * tariff,
        "loss_since_rain_clean_kwh": float(last["cum_loss_kwh"]),
        "next_rain_date": str(pd.Timestamp(next_rain["date"]).date()) if next_rain is not None else "",
        "next_rain_mm": float(next_rain["rain_mm"]) if next_rain is not None else np.nan,
        "best_clean_date": best_day or "",
        "best_net_benefit_aud": float(best_net) if np.isfinite(best_net) else np.nan,
        "week_loss_aud": base_loss,
        "cleaning_cost_aud": cost,
        "action": action,
        "headline": headline,
        "reason": reason,
    }
