"""
PVLib expected generation from Solcast weather.

Same physics as the old ``3_expected_power_pvlib.py``: Hay–Davies POA,
Faiman cell temperature, PVWatts DC, inverter AC clipping. Solar position now
uses each campus's own coordinates instead of always Bundoora.
"""
from __future__ import annotations

import pandas as pd
from pvlib import irradiance, location, pvsystem, temperature

from . import settings

REQUIRED = ("ghi", "dni", "dhi", "air_temp")


def localize(ts: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Solcast timestamps are Melbourne wall-clock; attach the zone (DST-safe)."""
    if ts.tz is None:
        return ts.tz_localize(settings.TIMEZONE, ambiguous=True, nonexistent="shift_forward")
    return ts.tz_convert(settings.TIMEZONE)


def expected_generation(
    weather: pd.DataFrame,
    *,
    campus: str,
    system_dc_kw: float,
    inverter_ac_kw: float | None,
    tilt_deg: float,
    azimuth_deg: float,
) -> pd.DataFrame:
    """Hourly expected kWh for one site. ``weather`` is one campus, hourly, with a ``timestamp`` column."""
    missing = [c for c in REQUIRED if c not in weather.columns]
    if missing:
        raise ValueError(f"Weather is missing columns {missing}")

    df = weather.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    labels = pd.DatetimeIndex(df["timestamp"])
    times = localize(labels)
    site = settings.CAMPUSES[campus]
    loc = location.Location(site.latitude, site.longitude, tz=settings.TIMEZONE, altitude=site.altitude_m)
    # Hour-ending labels (same as the meters): sun position at the middle of the hour.
    solpos = loc.get_solarposition(localize(labels - pd.Timedelta(minutes=30)))
    solpos.index = times

    ghi = pd.Series(df["ghi"].astype(float).values, index=times)
    dni = pd.Series(df["dni"].astype(float).values, index=times)
    dhi = pd.Series(df["dhi"].astype(float).values, index=times)
    albedo = (
        pd.Series(df["albedo"].astype(float).values, index=times).clip(0.05, 0.4).fillna(0.2)
        if "albedo" in df.columns
        else 0.2
    )
    poa = irradiance.get_total_irradiance(
        surface_tilt=tilt_deg,
        surface_azimuth=azimuth_deg,
        solar_zenith=solpos["apparent_zenith"].clip(0, 90),
        solar_azimuth=solpos["azimuth"],
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        dni_extra=pd.Series(irradiance.get_extra_radiation(times.dayofyear), index=times),
        albedo=albedo,
        model="haydavies",
    )["poa_global"].fillna(0.0)

    air = pd.Series(df["air_temp"].astype(float).values, index=times)
    wind = (
        pd.Series(df["wind_speed_10m"].astype(float).values, index=times).fillna(2.0)
        if "wind_speed_10m" in df.columns
        else 2.0
    )
    t_cell = temperature.faiman(poa, air, wind, u0=25.0, u1=6.84)
    p_dc = pvsystem.pvwatts_dc(
        effective_irradiance=poa, temp_cell=t_cell, pdc0=system_dc_kw * 1000.0, gamma_pdc=settings.GAMMA_PDC
    ).clip(lower=0.0)
    p_ac = p_dc.clip(upper=inverter_ac_kw * 1000.0) if inverter_ac_kw else p_dc

    return pd.DataFrame(
        {
            "timestamp": df["timestamp"].values,
            "poa_wm2": poa.values,
            "temp_cell_c": t_cell.values,
            "expected_kwh": (p_ac / 1000.0).fillna(0.0).values,
        }
    )
