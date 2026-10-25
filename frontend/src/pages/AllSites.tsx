import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { type Overview, qs, useApi } from "../api";
import { DateRange } from "../components/DateRange";
import { AXIS, Async, Card, Icon, KpiCard, StatusPill, TipBox } from "../components/ui";
import { useDateRange, useMeta } from "../context";
import { num, signed } from "../format";

const PAGE = 10;

export default function AllSites() {
  const { meta } = useMeta();
  const { start, end, setRange, update, params } = useDateRange();
  const campus = params.get("campus") ?? "ALL";
  const setCampus = (c: string) => update({ campus: c === "ALL" ? null : c });
  const state = useApi<Overview>(`/overview${qs({ start, end, campus })}`);
  const keep = `?${qs({ start, end }).slice(1)}`;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Solar Dashboard – All Sites</h1>
          <p className="page-sub">Generation and health of every solar site across campuses.</p>
        </div>
        <div className="filters">
          <DateRange start={start} end={end} onChange={setRange} />
          <label className="control" aria-label="Campus">
            <select value={campus} onChange={(e) => setCampus(e.target.value)}>
              <option value="ALL">All campuses</option>
              {meta.campuses.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <Async state={state} height={600}>
        {(o) => (
          <div className="stack">
            <div className="grid grid-4">
              <KpiCard highlight icon={Icon.sun} label="Total Solar Generation" value={num(o.kpis.total_mwh, 1)} unit="MWh" meta={`${o.start} to ${o.end} · ${o.kpis.site_count} sites`} />
              <KpiCard
                label="Sites reporting"
                value={`${o.kpis.reporting}`}
                unit={`/ ${o.kpis.site_count}`}
                meta={`${o.kpis.site_count - o.kpis.reporting} with missing or frozen data`}
              />
              <KpiCard label="Average Performance Ratio" value={num(o.kpis.avg_pr_pct, 1)} unit="%" meta="Capacity-weighted across reporting sites" />
              <KpiCard highlight icon={Icon.leaf} label="CO2 Saved" value={num(o.kpis.co2_tonnes, 1)} unit="tonnes CO2-e" meta={`${o.start} to ${o.end}`} />
            </div>

            <div className="grid grid-2">
              <Card title="Generation by Campus" sub="MWh · selected period">
                <CampusBars rows={o.generation_by_campus} />
              </Card>
              <Card
                title="Sites Needing Attention"
                sub="From outage detection, expected-vs-actual and the soiling model"
                right={o.attention_total > o.attention.length ? <span className="muted">{o.attention_total} total</span> : undefined}
              >
                {o.attention.length === 0 ? (
                  <div className="empty">All sites look normal for this period.</div>
                ) : (
                  <div className="stack" style={{ gap: 12 }}>
                    {o.attention.map((a) => (
                      <div key={`${a.site_key}-${a.detail}`} className="inner-card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
                        <StatusPill status={a.type} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600 }}>{a.name}</div>
                          <div className="muted" style={{ fontSize: 13 }}>{a.detail}</div>
                        </div>
                        <Link className="link" to={`/site/${a.site_key}${keep}`}>
                          View site
                        </Link>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>

            <DegradationComparison deg={o.degradation} />
            <SitesTable rows={o.sites} keep={keep} />
          </div>
        )}
      </Async>
    </>
  );
}

function CampusBars({ rows }: { rows: Overview["generation_by_campus"] }) {
  const max = Math.max(1, ...rows.map((r) => r.mwh));
  return (
    <div className="stack" style={{ gap: 14, marginTop: 8 }}>
      {rows.map((r) => (
        <div key={r.campus} style={{ display: "grid", gridTemplateColumns: "110px 1fr 60px", alignItems: "center", gap: 14 }} title={`${r.name}: ${num(r.mwh, 1)} MWh`}>
          <span>{r.name}</span>
          <div style={{ background: "#f3f4f6", borderRadius: 6, height: 26, overflow: "hidden" }}>
            <div style={{ width: `${(r.mwh / max) * 100}%`, background: "var(--green)", height: "100%", borderRadius: 6 }} />
          </div>
          <span style={{ textAlign: "right", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{num(r.mwh, 1)}</span>
        </div>
      ))}
    </div>
  );
}

type DegRow = Overview["degradation"]["sites"][number];
type DegField = "yearly_pct_per_year" | "monthly_pct_per_year";
const DEG_ROW_PX = 24;

/** Rows grouped by campus in the header's campus order; sites A→Z inside each campus. */
function groupByCampus(rows: DegRow[], order: string[]) {
  const groups = new Map<string, { campus: string; name: string; rows: DegRow[] }>();
  for (const r of rows) {
    if (!groups.has(r.campus)) groups.set(r.campus, { campus: r.campus, name: r.campus_name, rows: [] });
    groups.get(r.campus)!.rows.push(r);
  }
  const rank = (c: string) => (order.indexOf(c) === -1 ? order.length : order.indexOf(c));
  return [...groups.values()]
    .sort((a, b) => rank(a.campus) - rank(b.campus))
    .map((g) => ({ ...g, rows: g.rows.sort((a, b) => a.long_name.localeCompare(b.long_name)) }));
}

function DegradationComparison({ deg }: { deg: Overview["degradation"] }) {
  const { meta } = useMeta();
  const groups = groupByCampus([...deg.sites], meta.campuses.map((c) => c.code));
  const down = deg.sites.filter((r) => (r.yearly_pct_per_year ?? 0) < 0).length;
  const up = deg.sites.filter((r) => (r.yearly_pct_per_year ?? 0) > 0).length;
  return (
    <Card
      title="All Meters — Degradation Comparison"
      sub={
        <>
          Linear-trend proxy of health ratio H = Σ actual ÷ Σ pvlib expected (valid daylight hours). Year-based = regression on calendar-year H; monthly-based =
          regression on monthly H, slope annualised.
          <br />
          <span style={{ fontSize: 13 }}>
            Window: <b>{deg.window_start} → {deg.window_end}</b> · data since {meta.analysis_start}, not affected by the date filter
          </span>
        </>
      }
      right={
        <div className="seg">
          <span className="chip down">▼ {down} trending down</span>
          <span className="chip up">▲ {up} trending up</span>
        </div>
      }
    >
      <div className="grid grid-2 deg-grid">
        <DegPanel title="Year-based degradation" dot="#0d9488" groups={groups} field="yearly_pct_per_year" />
        <DegPanel title="Monthly-based degradation" dot="#7c3aed" groups={groups} field="monthly_pct_per_year" />
      </div>
    </Card>
  );
}

function DegPanel({ title, dot, groups, field }: { title: string; dot: string; groups: ReturnType<typeof groupByCampus>; field: DegField }) {
  // One shared scale for every campus so bar lengths stay comparable across groups.
  const all = groups.flatMap((g) => g.rows.map((r) => r[field] ?? 0));
  const lim = Math.min(40, Math.max(10, ...all.map(Math.abs)));
  const domain: [number, number] = [-Math.ceil(lim / 10) * 10, Math.ceil(lim / 10) * 10];
  return (
    <div className="inner-card">
      <div className="sub-title" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span className="sw dot" style={{ background: dot }} /> {title} <span className="sub-note">(~%/yr)</span>
      </div>
      {groups.map((g, i) => (
        <DegGroup key={g.campus} name={g.name} rows={g.rows} field={field} domain={domain} showAxis={i === groups.length - 1} />
      ))}
      <div className="axis-note">Trend (%/yr) · red = H trending down, green = trending up</div>
    </div>
  );
}

function DegGroup({ name, rows, field, domain, showAxis }: { name: string; rows: DegRow[]; field: DegField; domain: [number, number]; showAxis: boolean }) {
  const data = rows.map((r) => ({ name: r.long_name, v: r[field] ?? 0, est: r.capacity_source === "estimated" }));
  const down = data.filter((d) => d.v < 0).length;
  const up = data.filter((d) => d.v > 0).length;
  return (
    <div className="deg-group">
      <div className="deg-group-head">
        <span className="deg-group-name">{name}</span>
        <span className="muted">
          {rows.length} site{rows.length === 1 ? "" : "s"}
        </span>
        <span className="deg-group-counts">
          {down > 0 && <span style={{ color: "var(--red-ink)" }}>▼ {down}</span>}
          {up > 0 && <span style={{ color: "var(--green-ink)" }}>▲ {up}</span>}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={data.length * DEG_ROW_PX + (showAxis ? 34 : 8)}>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 48, top: 4, bottom: showAxis ? 4 : 0 }} barCategoryGap={6}>
          <XAxis type="number" domain={domain} allowDataOverflow hide={!showAxis} {...AXIS} />
          <YAxis
            type="category"
            dataKey="name"
            width={200}
            interval={0}
            {...AXIS}
            tick={(p: { x: number; y: number; payload: { value: string; index: number } }) => {
              const d = data[p.payload.index];
              return (
                <text x={p.x} y={p.y} dy={4} textAnchor="end" fontSize={12.5} fill={d && d.v < 0 ? "#b91c1c" : "#374151"} fontWeight={d && d.v < 0 ? 600 : 400}>
                  {p.payload.value}
                </text>
              );
            }}
          />
          <ReferenceLine x={0} stroke="#9ca3af" />
          <Tooltip
            cursor={{ fill: "#f3f4f6" }}
            content={({ payload }) =>
              payload?.[0] ? (
                <TipBox
                  title={String(payload[0].payload.name)}
                  rows={[{ name: "Campus", value: name }, { name: "Trend", value: signed(payload[0].payload.v, 2, " %/yr") }, ...(payload[0].payload.est ? [{ name: "Capacity", value: "estimated" }] : [])]}
                />
              ) : null
            }
          />
          <Bar dataKey="v" radius={[0, 4, 4, 0]} maxBarSize={14}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.v < 0 ? "#dc2626" : "#16a34a"} />
            ))}
            <LabelList dataKey="v" position="right" formatter={(v: number) => signed(v, 1)} style={{ fontSize: 11.5, fill: "#374151", fontWeight: 600 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function SitesTable({ rows, keep }: { rows: Overview["sites"]; keep: string }) {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const filtered = useMemo(() => rows.filter((r) => `${r.name} ${r.campus_name}`.toLowerCase().includes(q.toLowerCase())), [rows, q]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const cur = Math.min(page, pages - 1);
  const shown = filtered.slice(cur * PAGE, cur * PAGE + PAGE);
  return (
    <Card
      title="Solar Sites"
      sub="Select a site to open its Individual Solar page"
      right={
        <label className="search">
          {Icon.search}
          <input placeholder="Search solar sites..." value={q} onChange={(e) => (setQ(e.target.value), setPage(0))} />
        </label>
      }
    >
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Site</th>
              <th>Campus</th>
              <th className="num">Capacity (kWp)</th>
              <th className="num">Generation (kWh)</th>
              <th className="num">kWh/kWp</th>
              <th className="num">PR (%)</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.site_key}>
                <td style={{ fontWeight: 600 }}>{r.name}</td>
                <td>{r.campus_name}</td>
                <td className="num" title={r.capacity_source === "estimated" ? "Estimated from peak output — add the nameplate to config/sites.csv" : undefined}>
                  {num(r.kwp, 0)}
                  {r.capacity_source === "estimated" && <span className="muted"> est.</span>}
                </td>
                <td className="num">{num(r.generation_kwh, 0)}</td>
                <td className="num">{num(r.kwh_per_kwp, 1)}</td>
                <td className="num">{num(r.pr_pct, 1)}</td>
                <td title={r.status_detail}>
                  <StatusPill status={r.status} />
                </td>
                <td>
                  <Link className="link" to={`/site/${r.site_key}${keep}`}>
                    View
                  </Link>
                </td>
              </tr>
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={8} className="empty">
                  No sites match “{q}”.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="pager">
        {filtered.length ? `${cur * PAGE + 1}–${Math.min(filtered.length, cur * PAGE + PAGE)} of ${filtered.length}` : "0 of 0"}
        <button disabled={cur === 0} onClick={() => setPage(cur - 1)} aria-label="Previous page">
          ‹
        </button>
        <button disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)} aria-label="Next page">
          ›
        </button>
      </div>
    </Card>
  );
}
