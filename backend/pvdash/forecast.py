"""
Generation forecast: PVLib physics on Solcast forecast weather, corrected by an
XGBoost model trained on the site's own history (from ``4_forecast_7d_pvlib_xgboost.py``).

New: an 80 % prediction interval from hold-out residual quantiles, binned by
predicted output, for the dashboard's uncertainty band.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FORECAST_HOURS_MAX = 240
FEATURES = ["expected_kwh", "ghi", "dni", "dhi", "poa_wm2", "temp_cell_c", "zenith", "air_temp", "wind_speed_10m", "hour_sin", "hour_cos", "doy_sin", "doy_cos"]


def _features(df: pd.DataFrame) -> pd.DataFrame:
    t = df.index
    X = pd.DataFrame(index=t)
    for c in FEATURES[:9]:
        X[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    X["hour_sin"] = np.sin(2 * np.pi * t.hour / 24)
    X["hour_cos"] = np.cos(2 * np.pi * t.hour / 24)
    X["doy_sin"] = np.sin(2 * np.pi * t.dayofyear / 365.25)
    X["doy_cos"] = np.cos(2 * np.pi * t.dayofyear / 365.25)
    return X


def forecast_site(history: pd.DataFrame, future: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    ``history``: hourly frame (actual_kwh, valid, weather + pvlib columns) up to the last reading.
    ``future``: hourly weather + pvlib columns for the forecast window.
    """
    import xgboost as xgb

    train = history[history["valid"] & history["expected_kwh"].notna()]
    if len(train) < 500 or future.empty:
        return pd.DataFrame(), {"status": "skipped", "train_hours": int(len(train))}
    X, y = _features(train), train["actual_kwh"].to_numpy()
    cut = max(int(len(X) * 0.9), len(X) - 2000)
    model = xgb.XGBRegressor(
        n_estimators=500,
        max_depth=7,
        learning_rate=0.06,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_weight=3,
        random_state=42,
        n_jobs=-1,
        early_stopping_rounds=40,
    )
    model.fit(X.iloc[:cut], y[:cut], eval_set=[(X.iloc[cut:], y[cut:])], verbose=False)

    # Residual quantiles on the hold-out, per bin of predicted output.
    pred_va = model.predict(X.iloc[cut:])
    resid = y[cut:] - pred_va
    edges = np.unique(np.quantile(pred_va, [0, 0.25, 0.5, 0.75, 1.0]))
    bins = np.clip(np.digitize(pred_va, edges[1:-1]), 0, max(len(edges) - 2, 0))
    q = {b: (np.quantile(resid[bins == b], 0.1), np.quantile(resid[bins == b], 0.9)) for b in np.unique(bins)}

    pred = np.clip(model.predict(_features(future)), 0, None)
    pred = np.where(future["expected_kwh"].to_numpy() <= 0, 0.0, pred)  # nothing at night
    fb = np.clip(np.digitize(pred, edges[1:-1]), 0, max(len(edges) - 2, 0))
    lo = np.array([q.get(b, (0, 0))[0] for b in fb])
    hi = np.array([q.get(b, (0, 0))[1] for b in fb])
    dark = pred <= 0
    out = pd.DataFrame(
        {
            "timestamp": future.index,
            "pvlib_kwh": future["expected_kwh"].to_numpy(),
            "forecast_kwh": pred,
            "lo_kwh": np.where(dark, 0.0, np.clip(pred + lo, 0, None)),
            "hi_kwh": np.where(dark, 0.0, np.clip(pred + hi, 0, None)),
        }
    )
    mae = float(np.mean(np.abs(resid)))
    return out, {"status": "ok", "train_hours": int(len(train)), "holdout_mae_kwh": mae}
