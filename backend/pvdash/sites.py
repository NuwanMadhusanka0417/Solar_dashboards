"""
Site registry (``backend/config/sites.csv``).

One row per solar site shown on the dashboard. ``meter_ids`` may list several
SQL meter keys separated by ``|`` — used when a meter was renamed (e.g. the
Library meter became ``library_intertrip`` in Aug 2026); later meters take over
from earlier ones on overlapping hours.

Blank ``kwp`` means the nameplate is unknown: ``process_data.py`` estimates it
from peak output and marks ``capacity_source = estimated``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from . import settings


@dataclass
class Site:
    key: str
    meter_ids: list[str]
    name: str
    long_name: str
    campus: str  # campus code, e.g. BUNDOORA
    kwp: float | None
    inverter_ac_kw: float | None
    tilt_deg: float
    azimuth_deg: float
    panel_type: str = ""
    num_modules: int | None = None
    inverter: str = ""
    network: str = ""
    commissioned: str = ""
    design_annual_mwh: float | None = None
    enabled: bool = True
    notes: str = ""
    capacity_source: str = field(default="catalogue")

    @property
    def campus_name(self) -> str:
        c = settings.CAMPUSES.get(self.campus)
        return c.name if c else self.campus.title()

    @property
    def physical_cap_kwh(self) -> float | None:
        """Upper bound for one hour of energy (kWh) from the inverter AC rating."""
        if self.inverter_ac_kw and self.inverter_ac_kw > 0:
            return self.inverter_ac_kw * settings.PHYSICAL_CAP_AC_MULT
        if self.kwp and self.kwp > 0:
            return self.kwp * settings.PHYSICAL_CAP_AC_MULT
        return None

    def to_record(self) -> dict:
        return {
            "site_key": self.key,
            "meter_ids": "|".join(self.meter_ids),
            "name": self.name,
            "long_name": self.long_name,
            "campus": self.campus,
            "campus_name": self.campus_name,
            "kwp": self.kwp,
            "inverter_ac_kw": self.inverter_ac_kw,
            "tilt_deg": self.tilt_deg,
            "azimuth_deg": self.azimuth_deg,
            "panel_type": self.panel_type,
            "num_modules": self.num_modules,
            "inverter": self.inverter,
            "network": self.network,
            "commissioned": self.commissioned,
            "design_annual_mwh": self.design_annual_mwh,
            "capacity_source": self.capacity_source,
            "notes": self.notes,
        }


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return f if pd.notna(f) else None


def _text(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def load_sites(*, include_disabled: bool = False) -> list[Site]:
    df = pd.read_csv(settings.SITES_CSV, dtype=str, keep_default_na=False)
    sites: list[Site] = []
    for r in df.to_dict("records"):
        enabled = _text(r.get("enabled", "1")).lower() not in ("0", "false", "no")
        if not enabled and not include_disabled:
            continue
        n_mod = _num(r.get("num_modules"))
        sites.append(
            Site(
                key=_text(r["site_key"]).lower(),
                meter_ids=[m.strip() for m in _text(r["meter_ids"]).split("|") if m.strip()],
                name=_text(r.get("name")) or _text(r["site_key"]),
                long_name=_text(r.get("long_name")) or _text(r.get("name")),
                campus=_text(r.get("campus")).upper() or "BUNDOORA",
                kwp=_num(r.get("kwp")),
                inverter_ac_kw=_num(r.get("inverter_ac_kw")),
                tilt_deg=_num(r.get("tilt_deg")) if _num(r.get("tilt_deg")) is not None else settings.DEFAULT_TILT_DEG,
                azimuth_deg=_num(r.get("azimuth_deg")) if _num(r.get("azimuth_deg")) is not None else settings.DEFAULT_AZIMUTH_DEG,
                panel_type=_text(r.get("panel_type")),
                num_modules=int(n_mod) if n_mod else None,
                inverter=_text(r.get("inverter")),
                network=_text(r.get("network")),
                commissioned=_text(r.get("commissioned")),
                design_annual_mwh=_num(r.get("design_annual_mwh")),
                enabled=enabled,
                notes=_text(r.get("notes")),
            )
        )
    return sites


def all_meter_ids(sites: list[Site]) -> list[str]:
    return sorted({m for s in sites for m in s.meter_ids})


def parse_inverter_kw(text: str) -> float | None:
    """Sum SolarEdge ratings from strings like ``2 x SolarEdge SE25K + 1 x SolarEdge SE15K``."""
    total = 0.0
    for count, kw in re.findall(r"(\d+)\s*x\s*\w+\s*SE([\d.]+)K", text, re.IGNORECASE):
        total += int(count) * float(kw)
    if total == 0:
        total = sum(float(kw) for kw in re.findall(r"SE([\d.]+)K", text, re.IGNORECASE))
    return total or None
