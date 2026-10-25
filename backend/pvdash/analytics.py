"""
Daily aggregation, health ratio H, degradation trends, seasonal analysis and
underperformance detection. Formulas match the old JS dashboard
(``degradation_common.js`` / ``season_analysis_common.js``) so numbers carry over.

H = Σ actual ÷ Σ pvlib expected over valid daylight hours (GHI > 5 W/m²).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import settings

SEASONS = [
    ("summer", "Summer (Dec–Feb)"),
    ("autumn", "Autumn (Mar–May)"),
    ("winter", "Winter (Jun–Aug)"),
    ("spring", "Spring (Sep–Nov)"),
]


def daily_from_hourly(h: pd.DataFrame) -> pd.DataFrame:
    """Per-day energy, H inputs, weather and data-quality counts from a cleaned hourly frame."""
    d = h.copy()
    d["date"] = d.index.normalize()
    exp = d["expected_kwh"]
    valid = d["valid"]
    sunny = d["flag_sunny"]
    lost_hours = d["flag_outage"] | d["flag_missing"] | d["flag_stuck"]
    g = d.groupby("date")
    out = pd.DataFrame(
        {
            "actual_kwh": g["actual_kwh"].sum(),
            "expected_kwh": g["expected_kwh"].sum(min_count=1),
            "actual_valid_kwh": d["actual_kwh"].where(valid, 0.0).groupby(d["date"]).sum(),
            "expected_valid_kwh": exp.where(valid).groupby(d["date"]).sum(min_count=1),
            "outage_expected_kwh": exp.where(lost_hours & sunny).groupby(d["date"]).sum(min_count=1),
            "ghi_kwh_m2": d["ghi"].where(d["ghi"] > settings.DAYLIGHT_GHI_MIN).groupby(d["date"]).sum(min_count=1) / 1000.0,
            "rain_mm": g["rain_mm"].sum(min_count=1),
            "peak_kw": g["actual_kwh"].max(),
            "hours": g["actual_kwh"].size(),
            "hours_good": (~(d["flag_missing"] | d["flag_stuck"] | d["flag_outage"] | d["raw_kwh"].isna())).groupby(d["date"]).sum(),
            "sunny_hours": sunny.groupby(d["date"]).sum(),
            "outage_hours": (d["flag_outage"] | d["flag_missing"]).where(sunny, False).groupby(d["date"]).sum(),
            "stuck_hours": d["flag_stuck"].groupby(d["date"]).sum(),
            "valid_hours": valid.groupby(d["date"]).sum(),
        }
    )
    out["outage_day"] = (out["sunny_hours"] > 0) & (out["outage_hours"] >= settings.OUTAGE_DAY_FRACTION * out["sunny_hours"])
    # A mostly-dead day says nothing about panel health: drop it from H entirely
    # (its few low-light "valid" hours would otherwise give H ≈ 0).
    out.loc[out["outage_day"], ["actual_valid_kwh", "expected_valid_kwh"]] = [0.0, np.nan]
    out["h_ratio"] = np.where(out["expected_valid_kwh"] > 0.5, out["actual_valid_kwh"] / out["expected_valid_kwh"], np.nan)
    return out.reset_index()


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 2 or np.ptp(x[m]) == 0:
        return np.nan, np.nan
    slope, intercept = np.polyfit(x[m], y[m], 1)
    return float(slope), float(intercept)


def health_by_period(daily: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Yearly (``Y``) or monthly (``M``) H from summed valid energy."""
    d = daily.dropna(subset=["expected_valid_kwh"])
    key = d["date"].dt.year.astype(str) if freq == "Y" else d["date"].dt.strftime("%Y-%m")
    g = d.groupby(key)
    out = pd.DataFrame({"actual_kwh": g["actual_valid_kwh"].sum(), "expected_kwh": g["expected_valid_kwh"].sum(), "days": g.size()})
    out = out[out["expected_kwh"] > 0]
    out["h"] = out["actual_kwh"] / out["expected_kwh"]
    return out.reset_index(names="period")


def degradation(daily: pd.DataFrame) -> dict:
    """Year-based and monthly-based linear trends of H, annualised as %/yr of mean H."""
    yearly = health_by_period(daily, "Y")
    monthly = health_by_period(daily, "M")
    res = {
        "window_start": str(daily["date"].min().date()) if len(daily) else "",
        "window_end": str(daily["date"].max().date()) if len(daily) else "",
        "n_years": len(yearly),
        "n_months": len(monthly),
        "yearly_slope": np.nan,
        "yearly_intercept": np.nan,
        "yearly_pct_per_year": np.nan,
        "monthly_slope_per_day": np.nan,
        "monthly_intercept": np.nan,
        "monthly_pct_per_year": np.nan,
        "mean_h": float(yearly["h"].mean()) if len(yearly) else np.nan,
    }
    if len(yearly) >= 2:
        x = yearly["period"].astype(int).to_numpy() - int(yearly["period"].iloc[0])
        s, i = _ols(x.astype(float), yearly["h"].to_numpy())
        res.update(yearly_slope=s, yearly_intercept=i, yearly_pct_per_year=s * 100 / yearly["h"].mean())
    if len(monthly) >= 4:
        t = pd.to_datetime(monthly["period"] + "-01")
        x = ((t - t.iloc[0]).dt.days).to_numpy(dtype=float)
        s, i = _ols(x, monthly["h"].to_numpy())
        res.update(monthly_slope_per_day=s, monthly_intercept=i, monthly_pct_per_year=s * 365 * 100 / monthly["h"].mean())
    return res


def season_of(dates: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Australian meteorological seasons; December belongs to the next year's summer."""
    m, y = dates.dt.month, dates.dt.year
    season = np.select([m.isin([12, 1, 2]), m <= 5, m <= 8], ["summer", "autumn", "winter"], "spring")
    year = np.where(m == 12, y + 1, y)
    return pd.Series(season, index=dates.index), pd.Series(year, index=dates.index)


def seasonal(daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Returns (points, annual_medians, summary) for daily GHI and daily H by season.

    Change %/yr = slope of annual medians vs year ÷ first annual median × 100
    (same as the old ``season_linear_plot.js``).
    """
    d = daily[["date", "ghi_kwh_m2", "h_ratio"]].copy()
    d["season"], d["season_year"] = season_of(d["date"])
    pts = d.melt(id_vars=["date", "season", "season_year"], value_vars=["ghi_kwh_m2", "h_ratio"], var_name="metric", value_name="value")
    pts["metric"] = pts["metric"].map({"ghi_kwh_m2": "ghi", "h_ratio": "h"})
    pts = pts.dropna(subset=["value"])
    pts = pts[(pts["metric"] == "ghi") | pts["value"].between(0, 2)]

    annual = pts.groupby(["season", "metric", "season_year"])["value"].agg(median="median", days="size").reset_index()
    rows = []
    for (season, metric), grp in annual.groupby(["season", "metric"]):
        grp = grp.sort_values("season_year")
        slope, intercept = _ols(grp["season_year"].to_numpy(dtype=float), grp["median"].to_numpy())
        first = grp["median"].iloc[0]
        vals = pts[(pts["season"] == season) & (pts["metric"] == metric)]["value"]
        rows.append(
            {
                "season": season,
                "metric": metric,
                "median": float(vals.median()),
                "days": int(len(vals)),
                "trend_slope": slope,
                "trend_intercept": intercept,
                "pct_per_year": slope / first * 100 if first else np.nan,
            }
        )
    return pts, annual, pd.DataFrame(rows)


def baseline_h(daily: pd.DataFrame, before: pd.Timestamp, days: int = 365) -> float:
    """Site's typical H over the year before ``before`` (falls back to full history)."""
    hist = daily[(daily["date"] < before) & (daily["date"] >= before - pd.Timedelta(days=days))]
    vals = hist["h_ratio"].dropna()
    if len(vals) < 30:
        vals = daily["h_ratio"].dropna()
    return float(vals.median()) if len(vals) else np.nan


def underperformance_events(
    daily: pd.DataFrame,
    *,
    threshold_pct: float = settings.UNDERPERFORM_PCT,
    min_days: int = settings.UNDERPERFORM_MIN_DAYS,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> list[dict]:
    """
    Runs of ≥ ``min_days`` days where actual is ≥ ``threshold_pct`` below expected.

    Expected is scaled by the site's baseline H so a site that always runs at
    H ≈ 0.85 is not flagged every day; outage days are always flagged.
    """
    d = daily.sort_values("date").copy()
    if start is not None:
        base = baseline_h(d, start)
        d = d[d["date"] >= start]
    else:
        base = float(d["h_ratio"].median())
    if end is not None:
        d = d[d["date"] <= end]
    if d.empty:
        return []
    base = base if np.isfinite(base) and base > 0.2 else 1.0
    exp_adj = d["expected_kwh"] * base
    deficit_pct = np.where(exp_adj > 1.0, (exp_adj - d["actual_kwh"]) / exp_adj * 100.0, np.nan)
    frozen = (d["stuck_hours"] >= 0.5 * d["sunny_hours"]) & (d["sunny_hours"] > 0)
    # One label per day; consecutive days with the same label form an event.
    kind = np.select(
        [frozen.to_numpy(), d["outage_day"].to_numpy(), deficit_pct >= threshold_pct],
        ["frozen", "outage", "low"],
        "",
    )
    labels = {
        "frozen": ("Frozen meter", "Meter data check"),
        "outage": ("Zero reading", "Outage detector"),
        "low": ("Low output", "Expected vs actual"),
    }

    events, i, rows = [], 0, d.reset_index(drop=True)
    while i < len(rows):
        if not kind[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(rows) and kind[j + 1] == kind[i] and (rows["date"][j + 1] - rows["date"][j]).days == 1:
            j += 1
        if j - i + 1 >= min_days:
            seg = rows.iloc[i : j + 1]
            exp_sum = float((seg["expected_kwh"] * base).sum())
            act_sum = float(seg["actual_kwh"].sum())
            cause, source = labels[kind[i]]
            events.append(
                {
                    "start": str(seg["date"].iloc[0].date()),
                    "end": str(seg["date"].iloc[-1].date()),
                    "days": int(len(seg)),
                    "difference_kwh": round(act_sum - exp_sum, 1),
                    "deficit_pct": round((exp_sum - act_sum) / exp_sum * 100, 1) if exp_sum > 0 else None,
                    "cause": cause,
                    "source": source,
                }
            )
        i = j + 1
    return events


def rolling_median_trailing(values: pd.Series, window: int = 7) -> pd.Series:
    return values.rolling(window, min_periods=max(1, window // 2)).median()
