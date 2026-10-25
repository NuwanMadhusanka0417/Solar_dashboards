#!/usr/bin/env python3
"""
STEP 3 — REST API over ``data/processed/`` for the React dashboard.

Reads the CSVs written by ``process_data.py`` (reloads automatically after each
pipeline run) and serves JSON under ``/api``. If ``frontend/dist`` exists it is
served at ``/`` too, so one process is enough in production.

Run (from ``backend/``)::

  python api_server.py                    # http://127.0.0.1:8000  (docs at /docs)
  python api_server.py --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import csv
import math
import threading
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pvdash import analytics, settings, soiling

DIST_DIR = settings.PROJECT_DIR / "frontend" / "dist"
SEASON_START_MONTH = {"summer": 12, "autumn": 3, "winter": 6, "spring": 9}
EVENT_TYPES = {"panel_cleaning", "maintenance", "inverter_fault", "other"}


# ── data store ──────────────────────────────────────────────────────────────


class Store:
    """Processed CSVs held in memory; reloaded when ``pipeline_meta.json`` changes."""

    files = {
        "sites": "sites.csv",
        "daily": "daily.csv",
        "yearly": "health_yearly.csv",
        "monthly": "health_monthly.csv",
        "deg": "degradation.csv",
        "season_pts": "seasonal_points.csv",
        "season_annual": "seasonal_annual.csv",
        "season_summary": "seasonal_summary.csv",
        "soil_site": "soiling_site_daily.csv",
        "soil_week": "soiling_week.csv",
        "soil_rec": "soiling_recommendation.csv",
        "forecast": "forecast_hourly.csv",
        "forecast_meta": "forecast_meta.csv",
    }
    date_cols = {"daily": ["date"], "season_pts": ["date"], "soil_site": ["date"], "soil_week": ["date"], "forecast": ["timestamp"]}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stamp: float | None = None
        self.meta: dict = {}
        self.t: dict[str, pd.DataFrame] = {}

    def _meta_path(self) -> Path:
        return settings.PROCESSED_DIR / "pipeline_meta.json"

    def ensure(self) -> "Store":
        p = self._meta_path()
        stamp = p.stat().st_mtime if p.is_file() else None
        if stamp is not None and stamp == self._stamp:
            return self
        with self._lock:
            if stamp == self._stamp:
                return self
            if stamp is None:
                raise HTTPException(503, "No processed data yet - run process_data.py first.")
            import json

            self.meta = json.loads(p.read_text())
            t = {}
            for key, name in self.files.items():
                path = settings.PROCESSED_DIR / name
                t[key] = pd.read_csv(path, parse_dates=self.date_cols.get(key, [])) if path.is_file() else pd.DataFrame()
            t["sites"]["site_key"] = t["sites"]["site_key"].astype(str)
            self.daily_by_site = {k: g.sort_values("date").reset_index(drop=True) for k, g in t["daily"].groupby("site_key")}
            self.t = t
            self._stamp = stamp
        return self

    def site(self, key: str) -> dict:
        s = self.t["sites"]
        row = s[s["site_key"] == key]
        if row.empty:
            raise HTTPException(404, f"Unknown site '{key}'")
        return row.iloc[0].to_dict()

    def daily(self, key: str) -> pd.DataFrame:
        return self.daily_by_site.get(key, pd.DataFrame(columns=self.t["daily"].columns))

    @property
    def data_end(self) -> pd.Timestamp:
        d = self.t["daily"]
        return d.loc[d["actual_kwh"] > 0, "date"].max()


store = Store()


# ── helpers ─────────────────────────────────────────────────────────────────


def clean(v):
    """JSON-safe values: NaN/inf → None, numpy → python, timestamps → ISO strings."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if not math.isfinite(float(v)) else round(float(v), 6)
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else (v.date().isoformat() if v == v.normalize() else v.isoformat())
    if v is pd.NaT:
        return None
    return v


def records(df: pd.DataFrame) -> list[dict]:
    return clean(df.to_dict("records"))


def window(start: date | None, end: date | None) -> tuple[pd.Timestamp, pd.Timestamp]:
    e = pd.Timestamp(end) if end else store.data_end
    s = pd.Timestamp(start) if start else e - pd.Timedelta(days=29)
    if s > e:
        raise HTTPException(400, "start must be before end")
    return s.normalize(), e.normalize()


def in_window(d: pd.DataFrame, s: pd.Timestamp, e: pd.Timestamp) -> pd.DataFrame:
    return d[(d["date"] >= s) & (d["date"] <= e)]


def h_of(d: pd.DataFrame) -> float:
    exp = d["expected_valid_kwh"].sum()
    return d["actual_valid_kwh"].sum() / exp if exp > 0 else np.nan


def pct_change(cur: float, prev: float) -> float:
    return (cur - prev) / prev * 100 if prev and prev > 0 else np.nan


def trailing_outage_days(d: pd.DataFrame) -> int:
    n = 0
    for v in d["outage_day"].iloc[::-1]:
        if not v:
            break
        n += 1
    return n


def site_status(key: str, s: pd.Timestamp, e: pd.Timestamp) -> tuple[str, str, list[dict]]:
    """(status, detail, events) for the All-sites table and attention list."""
    full = store.daily(key)
    d = in_window(full, s, e)
    if d.empty or d["hours_good"].sum() == 0:
        return "No data", "No readings in the selected period", []
    tail = d[d["date"] > e - pd.Timedelta(days=settings.STALE_DATA_DAYS)]
    events = analytics.underperformance_events(full, start=s, end=e)
    n_out = trailing_outage_days(d)
    if n_out or (len(tail) and tail["hours_good"].sum() == 0):
        return "Outage", f"Zero reading for {max(n_out, 1)} day{'s' if max(n_out, 1) > 1 else ''}", events
    low = [ev for ev in events if ev["cause"] != "Zero reading"]
    if low:
        worst = max(low, key=lambda ev: ev["deficit_pct"] or 0)
        if worst["cause"] == "Frozen meter" or worst["deficit_pct"] is None:
            return "Underperforming", f"{worst['cause']} for {worst['days']} days", events
        return "Underperforming", f"{worst['deficit_pct']:.0f}% below expected for {worst['days']} days", events
    rec = store.t["soil_rec"]
    rec = rec[rec["site_key"] == key]
    if len(rec) and (1 - rec.iloc[0]["current_sr"]) * 100 >= settings.SOILING_ALERT_LOSS_PCT:
        loss = (1 - rec.iloc[0]["current_sr"]) * 100
        return "Soiling", f"Soiling loss {loss:.1f}% - {rec.iloc[0]['headline']}", events
    return "Normal", "", events


def fmt_range(a: str, b: str) -> str:
    da, db = pd.Timestamp(a), pd.Timestamp(b)
    if da == db:
        return f"{da.day} {da:%b}"
    return f"{da.day}–{db.day} {db:%b}" if da.month == db.month else f"{da.day} {da:%b} – {db.day} {db:%b}"


# ── API ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="LEAP Solar Dashboard API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/meta")
def meta():
    st = store.ensure()
    sites = st.t["sites"]
    end = st.data_end
    campuses = []
    for code in settings.CAMPUS_ORDER:
        n = int((sites["campus"] == code).sum())
        if n:
            campuses.append({"code": code, "name": settings.CAMPUSES[code].name, "sites": n})
    return clean(
        {
            **st.meta,
            "data_start": st.t["daily"]["date"].min(),
            "data_end": end,
            "default_start": end - pd.Timedelta(days=29),
            "default_end": end,
            "campuses": campuses,
            "tariff_aud_per_kwh": settings.TARIFF_AUD_PER_KWH,
            "analysis_start": st.meta.get("analysis_start", settings.ANALYSIS_START),
            "cleaning_cost_aud": settings.CLEANING_COST_AUD,
            "co2_kg_per_kwh": settings.CO2_KG_PER_KWH,
            "underperform_pct": settings.UNDERPERFORM_PCT,
            "underperform_min_days": settings.UNDERPERFORM_MIN_DAYS,
        }
    )


@app.get("/api/sites")
def sites(campus: str | None = None):
    s = store.ensure().t["sites"]
    if campus and campus.upper() != "ALL":
        s = s[s["campus"] == campus.upper()]
    return records(s.sort_values(["campus", "name"]))


@app.get("/api/overview")
def overview(start: date | None = None, end: date | None = None, campus: str = "ALL"):
    st = store.ensure()
    s, e = window(start, end)
    sites = st.t["sites"]
    if campus.upper() != "ALL":
        sites = sites[sites["campus"] == campus.upper()]
    keys = set(sites["site_key"])
    d = in_window(st.t["daily"], s, e)
    d = d[d["site_key"].isin(keys)]

    by_site = d.groupby("site_key").agg(
        actual=("actual_kwh", "sum"), act_v=("actual_valid_kwh", "sum"), exp_v=("expected_valid_kwh", "sum")
    )
    rows, attention = [], []
    reporting = 0
    for site in sites.to_dict("records"):
        k = site["site_key"]
        status, detail, events = site_status(k, s, e)
        if status not in ("No data", "Outage"):
            reporting += 1
        agg = by_site.loc[k] if k in by_site.index else None
        gen = float(agg["actual"]) if agg is not None else 0.0
        pr = float(agg["act_v"] / agg["exp_v"] * 100) if agg is not None and agg["exp_v"] > 0 else np.nan
        rows.append(
            {
                "site_key": k,
                "name": site["name"],
                "campus": site["campus"],
                "campus_name": site["campus_name"],
                "kwp": site["kwp"],
                "capacity_source": site["capacity_source"],
                "generation_kwh": gen,
                "kwh_per_kwp": gen / site["kwp"] if site["kwp"] else np.nan,
                "pr_pct": pr,
                "status": status,
                "status_detail": detail,
            }
        )
        if status in ("Outage", "Underperforming", "Soiling"):
            attention.append({"site_key": k, "name": site["name"], "type": status, "detail": detail, "resolved": False})
        for ev in events:
            if ev["cause"] == "Zero reading" and status != "Outage":
                attention.append(
                    {"site_key": k, "name": site["name"], "type": "Outage", "detail": f"Zero reading {fmt_range(ev['start'], ev['end'])} - resolved", "resolved": True}
                )
                break

    order = {"Outage": 0, "Underperforming": 1, "Soiling": 2}
    attention.sort(key=lambda a: (a["resolved"], order.get(a["type"], 9), a["name"]))

    reporting_df = pd.DataFrame(rows)
    ok = reporting_df[reporting_df["pr_pct"].notna() & reporting_df["status"].isin(["Normal", "Underperforming", "Soiling"])]
    avg_pr = float(np.average(ok["pr_pct"], weights=ok["kwp"])) if len(ok) and ok["kwp"].sum() > 0 else np.nan
    total_kwh = float(d["actual_kwh"].sum())

    gen_campus = d.merge(sites[["site_key", "campus"]], on="site_key").groupby("campus")["actual_kwh"].sum()
    by_campus = [
        {"campus": c, "name": settings.CAMPUSES[c].name, "mwh": float(gen_campus.get(c, 0)) / 1000}
        for c in settings.CAMPUS_ORDER
        if c in set(sites["campus"])
    ]

    deg = st.t["deg"].merge(sites[["site_key", "long_name", "capacity_source", "campus", "campus_name"]], on="site_key")
    deg = deg[deg["n_years"] >= 3]
    return clean(
        {
            "start": s,
            "end": e,
            "kpis": {
                "total_mwh": total_kwh / 1000,
                "site_count": len(sites),
                "reporting": reporting,
                "co2_tonnes": total_kwh * settings.CO2_KG_PER_KWH / 1000,
                "avg_pr_pct": avg_pr,
            },
            "generation_by_campus": by_campus,
            "attention": attention[:4],
            "attention_total": len(attention),
            "sites": sorted(rows, key=lambda r: (settings.CAMPUS_ORDER.index(r["campus"]), r["name"])),
            "degradation": {
                "window_start": deg["window_start"].min() if len(deg) else None,
                "window_end": deg["window_end"].max() if len(deg) else None,
                "sites": records(deg[["site_key", "long_name", "capacity_source", "campus", "campus_name", "yearly_pct_per_year", "monthly_pct_per_year", "n_years"]]),
            },
        }
    )


@app.get("/api/sites/{key}/summary")
def site_summary(key: str, start: date | None = None, end: date | None = None):
    st = store.ensure()
    site = st.site(key)
    s, e = window(start, end)
    full = st.daily(key)
    d = in_window(full, s, e)

    def span_sum(a: pd.Timestamp, b: pd.Timestamp) -> float:
        return float(in_window(full, a, b)["actual_kwh"].sum())

    ytd_s = e.replace(month=1, day=1)
    mtd_s = e.replace(day=1)
    wtd_s = e - pd.Timedelta(days=(e.dayofweek + 1) % 7)  # weeks start on Sunday
    prev_m_s = (mtd_s - pd.offsets.MonthBegin(1)).normalize()
    prev_m_e = min(prev_m_s + (e - mtd_s), mtd_s - pd.Timedelta(days=1))
    ytd = span_sum(ytd_s, e)
    exp = float(d["expected_kwh"].sum())
    act = float(d["actual_kwh"].sum())
    peak_row = d.loc[d["peak_kw"].idxmax()] if len(d) and d["peak_kw"].notna().any() else None
    inv = next((v for v in (site.get("inverter_ac_kw"), site.get("kwp")) if v is not None and np.isfinite(v) and v > 0), None)
    hours_total = int(d["hours"].sum())
    good = int(d["hours_good"].sum())

    soil = st.t["soil_site"]
    soil = in_window(soil[soil["site_key"] == key], s, e)
    lost = max(0.0, exp - act)
    outage_loss = min(lost, float(d["outage_expected_kwh"].sum()))
    soiling_loss = min(lost - outage_loss, float(soil["loss_kwh"].sum())) if len(soil) else 0.0

    return clean(
        {
            "site": site,
            "start": s,
            "end": e,
            "data_quality": {"expected_points": hours_total, "actual_points": good, "pct": good / hours_total * 100 if hours_total else np.nan},
            "period": {"actual_kwh": act, "expected_kwh": exp, "vs_expected_pct": pct_change(act, exp)},
            "peak": {
                "kw": float(peak_row["peak_kw"]) if peak_row is not None else np.nan,
                "date": peak_row["date"] if peak_row is not None else None,
                "pct_of_inverter": float(peak_row["peak_kw"]) / inv * 100 if peak_row is not None and inv else np.nan,
            },
            "ytd": {"kwh": ytd, "start": ytd_s, "end": e, "prev_kwh": span_sum(ytd_s - pd.DateOffset(years=1), e - pd.DateOffset(years=1)), "prev_label": str(e.year - 1)},
            "mtd": {"kwh": span_sum(mtd_s, e), "start": mtd_s, "end": e, "prev_kwh": span_sum(prev_m_s, prev_m_e), "prev_label": f"{prev_m_s:%b}"},
            "wtd": {"kwh": span_sum(wtd_s, e), "start": wtd_s, "end": e, "prev_kwh": span_sum(wtd_s - pd.Timedelta(days=7), e - pd.Timedelta(days=7)), "prev_label": f"{wtd_s - pd.Timedelta(days=7):%b} {(wtd_s - pd.Timedelta(days=7)).day}"},
            "co2_ytd": {"tonnes": ytd * settings.CO2_KG_PER_KWH / 1000, "trees": ytd * settings.CO2_KG_PER_KWH / settings.CO2_KG_PER_TREE, "start": ytd_s, "end": e},
            "expected_vs_actual": {
                "expected_kwh": exp,
                "actual_kwh": act,
                "lost_kwh": lost,
                "lost_aud": lost * settings.TARIFF_AUD_PER_KWH,
                "outage_kwh": outage_loss,
                "soiling_kwh": soiling_loss,
                "other_kwh": max(0.0, lost - outage_loss - soiling_loss),
                "saved_aud": act * settings.TARIFF_AUD_PER_KWH,
            },
        }
    )


def load_events(key: str | None = None) -> pd.DataFrame:
    if not settings.EVENTS_CSV.is_file():
        return pd.DataFrame(columns=["site_key", "date", "type", "note"])
    ev = pd.read_csv(settings.EVENTS_CSV, dtype=str, keep_default_na=False)
    return ev[ev["site_key"] == key] if key else ev


@app.get("/api/sites/{key}/generation")
def generation(key: str, start: date | None = None, end: date | None = None, view: str = Query("daily", pattern="^(daily|monthly|yearly)$")):
    st = store.ensure()
    st.site(key)
    s, e = window(start, end)
    full = st.daily(key)
    if view == "daily":
        d = in_window(full, s, e).copy()
        d["label"] = d["date"].dt.strftime("%Y-%m-%d")
        # First/last day of a meter's record can be a few hours only; don't plot a fake dip.
        partial = d["hours"] < 20
        d.loc[partial, ["expected_kwh", "ghi_kwh_m2"]] = np.nan
    else:
        if view == "monthly":
            d = full[(full["date"] > e - pd.DateOffset(months=24)) & (full["date"] <= e)].copy()
            d["label"] = d["date"].dt.strftime("%Y-%m")
        else:
            d = full[(full["date"] >= pd.Timestamp(settings.ANALYSIS_START)) & (full["date"] <= e)].copy()
            d["label"] = d["date"].dt.strftime("%Y")
        d = d.groupby("label", as_index=False).agg(
            date=("date", "min"), actual_kwh=("actual_kwh", "sum"), expected_kwh=("expected_kwh", lambda x: x.sum(min_count=1)),
            ghi_kwh_m2=("ghi_kwh_m2", "sum"), outage_day=("outage_day", "mean"),
        )
        d["outage_day"] = d["outage_day"] >= 0.5

    d["diff_kwh"] = d["expected_kwh"] - d["actual_kwh"]
    d["median7"] = analytics.rolling_median_trailing(d["diff_kwh"], 7 if view == "daily" else 3)
    x = np.arange(len(d), dtype=float)
    ok = d["diff_kwh"].notna().to_numpy()
    if ok.sum() >= 2:
        slope, intercept = np.polyfit(x[ok], d["diff_kwh"].to_numpy()[ok], 1)
        d["trend"] = intercept + slope * x
    else:
        d["trend"] = np.nan

    spans, cur = [], None
    for row in d.itertuples():
        if row.outage_day:
            cur = [row.label, row.label] if cur is None else [cur[0], row.label]
        elif cur:
            spans.append(cur)
            cur = None
    if cur:
        spans.append(cur)

    ev = load_events(key)
    ev = ev[(ev["date"] >= str(d["date"].min().date()) if len(d) else True) & (ev["date"] <= str(e.date()))] if len(ev) else ev
    if view != "daily" and len(ev):
        ev = ev.assign(date=ev["date"].str[: 7 if view == "monthly" else 4])
    cols = ["label", "actual_kwh", "expected_kwh", "ghi_kwh_m2", "outage_day", "diff_kwh", "median7", "trend"]
    return clean({"view": view, "series": records(d[cols]), "outage_spans": [{"start": a, "end": b} for a, b in spans], "events": records(ev)})


@app.get("/api/sites/{key}/seasonal")
def seasonal(key: str):
    st = store.ensure()
    st.site(key)
    pts = st.t["season_pts"]
    pts = pts[pts["site_key"] == key].copy()
    start = pd.to_datetime(
        {"year": pts["season_year"] - (pts["season"] == "summer").astype(int), "month": pts["season"].map(SEASON_START_MONTH), "day": 1}
    )
    pts["x"] = pts["season_year"] - 0.4 + 0.8 * ((pts["date"] - start).dt.days / 91).clip(0, 1)
    ann = st.t["season_annual"]
    ann = ann[ann["site_key"] == key]
    summ = st.t["season_summary"]
    summ = summ[summ["site_key"] == key]
    out = []
    for sid, label in analytics.SEASONS:
        block = {"id": sid, "label": label}
        for metric in ("ghi", "h"):
            p = pts[(pts["season"] == sid) & (pts["metric"] == metric)]
            a = ann[(ann["season"] == sid) & (ann["metric"] == metric)].sort_values("season_year").copy()
            sm = summ[(summ["season"] == sid) & (summ["metric"] == metric)]
            sm = sm.iloc[0].to_dict() if len(sm) else {}
            if len(a) and np.isfinite(sm.get("trend_slope", np.nan)):
                a["trend"] = sm["trend_intercept"] + sm["trend_slope"] * a["season_year"]
            block[metric] = {
                "points": records(p[["x", "value"]].round(4)),
                "annual": records(a[["season_year", "median", "days"] + (["trend"] if "trend" in a else [])]),
                "median": sm.get("median"),
                "pct_per_year": sm.get("pct_per_year"),
                "days": sm.get("days"),
            }
        out.append(block)
    years = sorted(pts["season_year"].unique().tolist())
    return clean({"seasons": out, "years": years})


@app.get("/api/sites/{key}/degradation")
def degradation(key: str):
    st = store.ensure()
    st.site(key)
    dg = st.t["deg"]
    dg = dg[dg["site_key"] == key]
    if dg.empty:
        raise HTTPException(404, "No degradation results for this site")
    g = dg.iloc[0].to_dict()
    y = st.t["yearly"]
    y = y[y["site_key"] == key].sort_values("period").copy()
    y0 = int(y["period"].iloc[0]) if len(y) else 0
    y["fit"] = g["yearly_intercept"] + g["yearly_slope"] * (y["period"].astype(int) - y0)
    m = st.t["monthly"]
    m = m[m["site_key"] == key].sort_values("period").copy()
    if len(m):
        days = (pd.to_datetime(m["period"] + "-01") - pd.Timestamp(m["period"].iloc[0] + "-01")).dt.days
        m["fit"] = g["monthly_intercept"] + g["monthly_slope_per_day"] * days
    return clean(
        {
            **g,
            "annual": records(y[["period", "h", "fit", "days"]]),
            "monthly": records(m[["period", "h", "fit", "days"]] if len(m) else m),
        }
    )


@app.get("/api/sites/{key}/underperformance")
def underperformance(
    key: str,
    start: date | None = None,
    end: date | None = None,
    threshold_pct: float = Query(settings.UNDERPERFORM_PCT, ge=1, le=100),
    min_days: int = Query(settings.UNDERPERFORM_MIN_DAYS, ge=1, le=60),
):
    st = store.ensure()
    st.site(key)
    s, e = window(start, end)
    full = st.daily(key)
    events = analytics.underperformance_events(full, threshold_pct=threshold_pct, min_days=min_days, start=s, end=e)
    return clean({"baseline_h": analytics.baseline_h(full, s), "events": events})


def _soil_frames(key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    st = store.ensure()
    st.site(key)
    sd = st.t["soil_site"]
    sd = sd[sd["site_key"] == key].sort_values("date").reset_index(drop=True)
    wk = st.t["soil_week"]
    wk = wk[wk["site_key"] == key].sort_values("date").reset_index(drop=True)
    if sd.empty:
        raise HTTPException(404, "No soiling data for this site")
    return sd, wk


@app.get("/api/sites/{key}/soiling")
def soiling_monitor(key: str, days: int = Query(settings.SOILING_MONITOR_DAYS, ge=14, le=730)):
    st = store.ensure()
    sd, _ = _soil_frames(key)
    last = sd.tail(days).copy()
    x = (last["date"] - last["date"].iloc[0]).dt.days.to_numpy(dtype=float)
    if len(last) >= 2:
        slope, intercept = np.polyfit(x, last["sr"].to_numpy(), 1)
        last["fit"] = intercept + slope * x
    last["cum_loss_aud"] = last["cum_loss_kwh"] * settings.TARIFF_AUD_PER_KWH
    rec = st.t["soil_rec"]
    rec = rec[rec["site_key"] == key]
    ev = load_events(key)
    ev = ev[(ev["type"] == "panel_cleaning") & (ev["date"] >= str(last["date"].iloc[0].date()))]
    return clean(
        {
            "series": records(last[["date", "sr", "fit", "rain_mm", "cum_loss_aud", "rain_clean"]]),
            "manual_cleans": ev["date"].tolist(),
            "recommendation": rec.iloc[0].to_dict() if len(rec) else None,
            "tariff_aud_per_kwh": settings.TARIFF_AUD_PER_KWH,
        }
    )


@app.get("/api/sites/{key}/soiling/simulate")
def soiling_simulate(key: str, clean_date: date | None = None, cost: float = Query(settings.CLEANING_COST_AUD, ge=0, le=100000)):
    sd, wk = _soil_frames(key)
    if wk.empty:
        raise HTTPException(404, "No forecast week for this site")
    last = sd.iloc[-1]
    rate = soiling.soiling_rate_since_rain_clean(sd)
    idx = None
    if clean_date:
        hits = wk.index[wk["date"].dt.date == clean_date]
        if len(hits) == 0:
            raise HTTPException(400, "clean_date must be one of the forecast days")
        idx = int(hits[0])
    baseline = soiling.simulate_week(wk, last["sr"], rate, None, cost)
    scenario = soiling.simulate_week(wk, last["sr"], rate, idx, cost) if idx is not None else None
    b_aud = sum(p["loss_aud"] for p in baseline)
    b_kwh = sum(p["loss_kwh"] for p in baseline)
    stats = {"rate_pct_per_day": rate * 100, "week_loss_baseline_aud": b_aud, "week_loss_baseline_kwh": b_kwh}
    if scenario:
        s_aud = sum(p["loss_aud"] for p in scenario)
        s_kwh = sum(p["loss_kwh"] for p in scenario)
        stats.update(
            week_loss_scenario_aud=s_aud,
            week_loss_scenario_kwh=s_kwh,
            net_benefit_aud=(b_aud - s_aud) - cost,
            kwh_avoided=b_kwh - s_kwh,
        )
    anchor = {"date": last["date"], "sr": last["sr"], "rain_mm": last["rain_mm"], "cum_loss_aud": last["cum_loss_kwh"] * settings.TARIFF_AUD_PER_KWH}
    return clean(
        {
            "anchor": anchor,
            "week": [str(d.date()) for d in wk["date"]],
            "has_weather": wk["has_weather"].tolist() if "has_weather" in wk else [],
            "cost_aud": cost,
            "clean_date": clean_date.isoformat() if clean_date else None,
            "baseline": baseline,
            "scenario": scenario,
            "stats": stats,
        }
    )


@app.get("/api/sites/{key}/forecast")
def forecast(key: str, hours: int = Query(72, ge=24, le=240)):
    st = store.ensure()
    st.site(key)
    fc = st.t["forecast"]
    fc = fc[fc["site_key"] == key].sort_values("timestamp").head(hours).copy()
    meta = st.t["forecast_meta"]
    meta = meta[meta["site_key"] == key]
    fc["day"] = fc["timestamp"].dt.normalize()
    daily = fc.groupby("day").agg(kwh=("forecast_kwh", "sum"), lo=("lo_kwh", "sum"), hi=("hi_kwh", "sum")).reset_index()
    daily["plus_minus"] = (daily["hi"] - daily["lo"]) / 2
    fc["timestamp"] = fc["timestamp"].dt.strftime("%Y-%m-%dT%H:%M")
    return clean(
        {
            "meta": meta.iloc[0].to_dict() if len(meta) else None,
            "hourly": records(fc[["timestamp", "forecast_kwh", "lo_kwh", "hi_kwh", "pvlib_kwh"]]),
            "daily": records(daily.rename(columns={"day": "date"})[["date", "kwh", "plus_minus"]]),
        }
    )


class EventIn(BaseModel):
    site_key: str
    date: date
    type: str = Field("panel_cleaning")
    note: str = Field("", max_length=300)


@app.get("/api/events")
def events(site_key: str | None = None):
    return records(load_events(site_key))


@app.post("/api/events", status_code=201)
def add_event(ev: EventIn):
    st = store.ensure()
    st.site(ev.site_key)
    if ev.type not in EVENT_TYPES:
        raise HTTPException(400, f"type must be one of {sorted(EVENT_TYPES)}")
    new = not settings.EVENTS_CSV.is_file()
    with open(settings.EVENTS_CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["site_key", "date", "type", "note"])
        w.writerow([ev.site_key, ev.date.isoformat(), ev.type, ev.note.replace("\n", " ").strip()])
    return {"site_key": ev.site_key, "date": ev.date.isoformat(), "type": ev.type, "note": ev.note}


# ── built React app (production) ────────────────────────────────────────────

if DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (DIST_DIR / path).resolve()
        if path and target.is_file() and DIST_DIR.resolve() in target.parents:
            return FileResponse(target)
        # index.html must always be revalidated so a new `npm run build` shows up immediately
        # (the hashed files under /assets can be cached forever).
        return FileResponse(DIST_DIR / "index.html", headers={"Cache-Control": "no-cache"})


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description="Serve the dashboard API (and built frontend).")
    ap.add_argument("--host", default=settings.env("PVDASH_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(settings.env("PVDASH_PORT", "8000")))
    ap.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development).")
    args = ap.parse_args()
    uvicorn.run("api_server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
