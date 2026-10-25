import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { type SiteSummary, qs, useApi } from "../api";
import { DateRange } from "../components/DateRange";
import { Async, Card, DeltaChip, Icon, KpiCard } from "../components/ui";
import { useDateRange, useMeta } from "../context";
import { num, pctChange } from "../format";
import { ExpectedVsActual, ConsumptionCard } from "../sections/ExpectedVsActual";
import { GenerationForecast } from "../sections/GenerationForecast";
import { GenerationOverTime } from "../sections/GenerationOverTime";
import { LongTermDegradation } from "../sections/LongTermDegradation";
import { SeasonalPerformance } from "../sections/SeasonalPerformance";
import { SoilingCleaning } from "../sections/SoilingCleaning";
import { Underperformance } from "../sections/Underperformance";

export default function SiteDashboard() {
  const { key = "" } = useParams();
  const { sites } = useMeta();
  const navigate = useNavigate();
  const { search } = useLocation();
  const { start, end, setRange } = useDateRange();
  const [eventsVersion, setEventsVersion] = useState(0);
  const summary = useApi<SiteSummary>(`/sites/${key}/summary${qs({ start, end })}`);
  const site = sites.find((s) => s.site_key === key);

  if (!site) return <div className="error">Unknown site “{key}”.</div>;
  const byCampus = sites.reduce<Record<string, typeof sites>>((acc, s) => ((acc[s.campus_name] ??= []).push(s), acc), {});

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{site.name}</h1>
          <p className="page-sub">Solar generation and performance insights at a glance.</p>
        </div>
        <div className="filters">
          <DateRange start={start} end={end} onChange={setRange} />
          <label className="control" aria-label="Site">
            <select value={key} onChange={(e) => navigate(`/site/${e.target.value}${search}`)}>
              {Object.entries(byCampus).map(([campus, list]) => (
                <optgroup key={campus} label={campus}>
                  {list.map((s) => (
                    <option key={s.site_key} value={s.site_key}>
                      {s.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="stack">
        <Async state={summary} height={300}>
          {(s) => (
            <>
              <SiteDetails s={s} />
              <KpiGrid s={s} />
            </>
          )}
        </Async>
        <GenerationOverTime siteKey={key} start={start} end={end} eventsVersion={eventsVersion} onEventAdded={() => setEventsVersion((v) => v + 1)} />
        <div className="grid grid-2">
          <Async state={summary} height={360}>
            {(s) => <ExpectedVsActual s={s} />}
          </Async>
          <ConsumptionCard name={site.name} />
        </div>
        <SeasonalPerformance siteKey={key} />
        <LongTermDegradation siteKey={key} />
        <Underperformance siteKey={key} start={start} end={end} onView={(a, b) => setRange(a, b)} />
        <SoilingCleaning siteKey={key} eventsVersion={eventsVersion} />
        <GenerationForecast siteKey={key} />
      </div>
    </>
  );
}

function RoofLayout({ name, quality }: { name: string; quality: number | null }) {
  const q = quality ?? 0;
  const r = 52;
  const c = 2 * Math.PI * r;
  const panels = [
    [60, 60, "Array A"],
    [262, 60, "Array B"],
    [60, 158, "Array C"],
    [262, 158, "Array D"],
  ] as const;
  return (
    <svg viewBox="0 0 800 300" style={{ width: "100%", borderRadius: 10, background: "#4b4b52", display: "block" }} role="img" aria-label={`${name} roof layout, data quality ${num(quality, 1)}%`}>
      <rect x="44" y="40" width="436" height="214" fill="#6b6b73" />
      {panels.map(([x, y, label]) => (
        <g key={label}>
          <rect x={x} y={y} width="186" height="78" fill="#1d4ed8" />
          {[1, 2, 3].map((i) => (
            <line key={i} x1={x} x2={x + 186} y1={y + i * 19.5} y2={y + i * 19.5} stroke="#3b6ff0" strokeWidth="1" />
          ))}
          <text x={x + 8} y={y + 72} fill="#dbeafe" fontSize="13">
            {label}
          </text>
        </g>
      ))}
      <rect x="506" y="40" width="254" height="104" fill="#a1a1aa" />
      <rect x="506" y="166" width="254" height="88" fill="#a1a1aa" />
      <rect x="22" y="18" width="222" height="26" rx="6" fill="#27272a" />
      <text x="34" y="36" fill="#fff" fontSize="13" fontWeight="600">
        SOLAR SITE · ROOF LAYOUT
      </text>
      <text x="22" y="288" fill="#fff" fontSize="26" fontWeight="700">
        {name}
      </text>
      <circle cx="640" cy="150" r="70" fill="#27272a" />
      <circle cx="640" cy="150" r={r} fill="none" stroke="#3f3f46" strokeWidth="10" />
      <circle cx="640" cy="150" r={r} fill="none" stroke={q >= 90 ? "#22c55e" : q >= 70 ? "#f59e0b" : "#ef4444"} strokeWidth="10" strokeLinecap="round" strokeDasharray={`${(q / 100) * c} ${c}`} transform="rotate(-90 640 150)" />
      <text x="640" y="152" textAnchor="middle" fill="#fff" fontSize="24" fontWeight="700">
        {num(quality, 1)}%
      </text>
      <text x="640" y="172" textAnchor="middle" fill="#d4d4d8" fontSize="12">
        Data Quality
      </text>
    </svg>
  );
}

function SiteDetails({ s }: { s: SiteSummary }) {
  const st = s.site;
  const azimuth = (a: number | null) => (a === null ? "—" : a === 0 ? "north" : a === 180 ? "south" : `${a}°`);
  const items: [string, string][] = [
    ["System size (DC)", `${num(st.kwp, 2)} kWp${st.capacity_source === "estimated" ? " (est.)" : ""}`],
    ["Inverter (AC)", st.inverter_ac_kw ? `${num(st.inverter_ac_kw, 1)} kW` : "—"],
    ["Modules", st.num_modules ? `${num(st.num_modules)} × ${st.panel_type}` : st.panel_type || "—"],
    ["Tilt / Azimuth", `${num(st.tilt_deg)}° / ${azimuth(st.azimuth_deg)}`],
    ["Commissioned", st.commissioned || "—"],
    ["Campus", st.campus_name],
    ["Expected data points", num(s.data_quality.expected_points)],
    ["Actual data points", num(s.data_quality.actual_points)],
    ["Annual production (design)", st.design_annual_mwh ? `${num(st.design_annual_mwh, 1)} MWh` : "—"],
  ];
  return (
    <Card>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.35fr) minmax(0, 1fr)", alignItems: "center", gap: 28 }}>
        <RoofLayout name={st.name} quality={s.data_quality.pct} />
        <div>
          <div className="sub-title" style={{ marginBottom: 14 }}>
            Site details
          </div>
          <div className="grid grid-3" style={{ rowGap: 18 }}>
            {items.map(([k, v]) => (
              <div key={k}>
                <div style={{ fontSize: 12, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.03em" }}>{k}</div>
                <div style={{ fontWeight: 700, fontSize: 17, marginTop: 2 }}>{v}</div>
              </div>
            ))}
          </div>
          {st.capacity_source === "estimated" && (
            <p className="notice" style={{ marginTop: 16 }}>
              Nameplate capacity is not in the site catalogue yet — estimated from peak output. Add it to <code>backend/config/sites.csv</code>.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

function KpiGrid({ s }: { s: SiteSummary }) {
  const p = s.period;
  return (
    <div className="grid grid-3">
      <KpiCard
        highlight
        icon={Icon.sun}
        label="Total Solar Generation for the Period"
        value={num(p.actual_kwh, 2)}
        unit="kWh"
        meta={`${s.start} to ${s.end}`}
        delta={
          p.vs_expected_pct === null ? (
            <span>No pvlib expected for this period (campus weather not downloaded)</span>
          ) : (
            <>
              <DeltaChip value={p.vs_expected_pct} />
              {p.vs_expected_pct < 0 ? "below" : "above"} expected (pvlib)
            </>
          )
        }
      />
      <KpiCard
        plainIcon
        icon={Icon.trend}
        label="Maximum Peak Output for the Period"
        value={num(s.peak.kw, 2)}
        unit="kW"
        meta={s.peak.date ? `${s.peak.date} · hourly average` : `${s.start} to ${s.end}`}
        delta={<span>{num(s.peak.pct_of_inverter, 0)}% of inverter AC rating</span>}
      />
      <KpiCard
        highlight
        icon={Icon.bolt}
        label="Solar Generation YTD"
        value={num(s.ytd.kwh, 2)}
        unit="kWh"
        meta={`${s.ytd.start} to ${s.ytd.end}`}
        delta={
          <>
            <DeltaChip value={pctChange(s.ytd.kwh, s.ytd.prev_kwh)} /> vs previous year ({s.ytd.prev_label})
          </>
        }
      />
      <KpiCard
        plainIcon
        icon={Icon.bolt}
        label="Solar Generation MTD"
        value={num(s.mtd.kwh, 2)}
        unit="kWh"
        meta={`${s.mtd.start} to ${s.mtd.end}`}
        delta={
          <>
            <DeltaChip value={pctChange(s.mtd.kwh, s.mtd.prev_kwh)} /> vs previous month ({s.mtd.prev_label})
          </>
        }
      />
      <KpiCard
        plainIcon
        icon={Icon.bolt}
        label="Solar Generation WTD"
        value={num(s.wtd.kwh, 2)}
        unit="kWh"
        meta={`${s.wtd.start} to ${s.wtd.end}`}
        delta={
          <>
            <DeltaChip value={pctChange(s.wtd.kwh, s.wtd.prev_kwh)} /> vs previous week ({s.wtd.prev_label})
          </>
        }
      />
      <KpiCard
        highlight
        icon={Icon.leaf}
        label="CO2 Saved YTD"
        value={num(s.co2_ytd.tonnes, 1)}
        unit="tonnes CO2-e"
        meta={`${s.co2_ytd.start} to ${s.co2_ytd.end}`}
        delta={
          <>
            <span className="chip up">≈ {num(s.co2_ytd.trees)} trees</span> equivalent planted
          </>
        }
      />
    </div>
  );
}
