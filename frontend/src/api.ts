/** Typed client for the FastAPI service (backend/api_server.py). */
import { useEffect, useState } from "react";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export type Num = number | null;

export interface Meta {
  generated_at: string;
  data_start: string;
  data_end: string;
  default_start: string;
  default_end: string;
  campuses: { code: string; name: string; sites: number }[];
  tariff_aud_per_kwh: number;
  /** Long-term analyses (degradation, seasonal, yearly view) start here. */
  analysis_start: string;
  cleaning_cost_aud: number;
  co2_kg_per_kwh: number;
  underperform_pct: number;
  underperform_min_days: number;
  weather_until: Record<string, string>;
}

export interface Site {
  site_key: string;
  name: string;
  long_name: string;
  campus: string;
  campus_name: string;
  kwp: Num;
  inverter_ac_kw: Num;
  tilt_deg: Num;
  azimuth_deg: Num;
  panel_type: string | null;
  num_modules: Num;
  inverter: string | null;
  commissioned: string | null;
  design_annual_mwh: Num;
  capacity_source: "catalogue" | "estimated";
  notes: string | null;
  last_reading: string;
  weather_until: string;
}

export type Status = "Normal" | "Underperforming" | "Outage" | "Soiling" | "No data";

export interface Overview {
  start: string;
  end: string;
  kpis: { total_mwh: number; site_count: number; reporting: number; co2_tonnes: number; avg_pr_pct: Num };
  generation_by_campus: { campus: string; name: string; mwh: number }[];
  attention: { site_key: string; name: string; type: Status; detail: string; resolved: boolean }[];
  attention_total: number;
  sites: {
    site_key: string;
    name: string;
    campus: string;
    campus_name: string;
    kwp: Num;
    capacity_source: string;
    generation_kwh: number;
    kwh_per_kwp: Num;
    pr_pct: Num;
    status: Status;
    status_detail: string;
  }[];
  degradation: {
    window_start: string | null;
    window_end: string | null;
    sites: { site_key: string; long_name: string; capacity_source: string; campus: string; campus_name: string; yearly_pct_per_year: Num; monthly_pct_per_year: Num; n_years: number }[];
  };
}

interface Span {
  kwh: number;
  start: string;
  end: string;
  prev_kwh: number;
  prev_label: string;
}

export interface SiteSummary {
  site: Site;
  start: string;
  end: string;
  data_quality: { expected_points: number; actual_points: number; pct: Num };
  period: { actual_kwh: number; expected_kwh: number; vs_expected_pct: Num };
  peak: { kw: Num; date: string | null; pct_of_inverter: Num };
  ytd: Span;
  mtd: Span;
  wtd: Span;
  co2_ytd: { tonnes: number; trees: number; start: string; end: string };
  expected_vs_actual: {
    expected_kwh: number;
    actual_kwh: number;
    lost_kwh: number;
    lost_aud: number;
    outage_kwh: number;
    soiling_kwh: number;
    other_kwh: number;
    saved_aud: number;
  };
}

export interface GenerationPoint {
  label: string;
  actual_kwh: number;
  expected_kwh: Num;
  ghi_kwh_m2: Num;
  outage_day: boolean;
  diff_kwh: Num;
  median7: Num;
  trend: Num;
}

export interface SiteEvent {
  site_key: string;
  date: string;
  type: string;
  note: string;
}

export interface Generation {
  view: "daily" | "monthly" | "yearly";
  series: GenerationPoint[];
  outage_spans: { start: string; end: string }[];
  events: SiteEvent[];
}

export interface SeasonMetric {
  points: { x: number; value: number }[];
  annual: { season_year: number; median: number; days: number; trend?: Num }[];
  median: Num;
  pct_per_year: Num;
  days: Num;
}

export interface Seasonal {
  years: number[];
  seasons: { id: "summer" | "autumn" | "winter" | "spring"; label: string; ghi: SeasonMetric; h: SeasonMetric }[];
}

export interface Degradation {
  window_start: string;
  window_end: string;
  yearly_slope: Num;
  yearly_pct_per_year: Num;
  monthly_slope_per_day: Num;
  monthly_pct_per_year: Num;
  annual: { period: number; h: number; fit: Num; days: number }[];
  monthly: { period: string; h: number; fit: Num; days: number }[];
}

export interface UnderEvent {
  start: string;
  end: string;
  days: number;
  difference_kwh: number;
  deficit_pct: Num;
  cause: string;
  source: string;
}

export interface Recommendation {
  anchor_date: string;
  current_sr: number;
  rate_pct_per_day: number;
  loss_kwh_per_day: number;
  loss_aud_per_day: number;
  next_rain_date: string | null;
  next_rain_mm: Num;
  best_clean_date: string;
  best_net_benefit_aud: Num;
  cleaning_cost_aud: number;
  action: "clean" | "wait";
  headline: string;
  reason: string;
}

export interface SoilingMonitor {
  series: { date: string; sr: number; fit: Num; rain_mm: number; cum_loss_aud: number; rain_clean: boolean }[];
  manual_cleans: string[];
  recommendation: Recommendation | null;
  tariff_aud_per_kwh: number;
}

export interface SimPoint {
  date: string;
  sr: number;
  rain_mm: number;
  expected_kwh: number;
  loss_kwh: number;
  loss_aud: number;
  cum_loss_aud: number;
  rain_clean: boolean;
  manual_clean: boolean;
}

export interface Simulation {
  anchor: { date: string; sr: number; rain_mm: number; cum_loss_aud: number };
  week: string[];
  has_weather: boolean[];
  cost_aud: number;
  clean_date: string | null;
  baseline: SimPoint[];
  scenario: SimPoint[] | null;
  stats: {
    rate_pct_per_day: number;
    week_loss_baseline_aud: number;
    week_loss_baseline_kwh: number;
    week_loss_scenario_aud?: number;
    week_loss_scenario_kwh?: number;
    net_benefit_aud?: number;
    kwh_avoided?: number;
  };
}

export interface Forecast {
  meta: { status: string; forecast_start: string | null; holdout_mae_kwh: Num } | null;
  hourly: { timestamp: string; forecast_kwh: number; lo_kwh: number; hi_kwh: number; pvlib_kwh: number }[];
  daily: { date: string; kwh: number; plus_minus: number }[];
}

export function qs(params: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json() as Promise<T>;
}

/** Fetch `path` whenever it changes; pass null to skip. `reloadKey` forces a refetch. */
export function useApi<T>(path: string | null, reloadKey = 0) {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: !!path,
  });
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    getJson<T>(path)
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((e: Error) => alive && setState({ data: null, error: e.message, loading: false }));
    return () => {
      alive = false;
    };
  }, [path, reloadKey]);
  return state;
}
