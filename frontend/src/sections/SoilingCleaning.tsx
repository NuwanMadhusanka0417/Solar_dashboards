import { useEffect, useMemo, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { type Simulation, type SoilingMonitor, qs, useApi } from "../api";
import { AXIS, Async, Badge, Card, GRID, Legend, TipBox } from "../components/ui";
import { dayMonth, money, num, signed, weekdayDayMonth } from "../format";

const C = { sr: "#c2410c", fit: "#4b5563", cum: "#16a34a", rain: "#93c5fd", clean: "#1d4ed8" };

export function SoilingCleaning({ siteKey, eventsVersion }: { siteKey: string; eventsVersion: number }) {
  const mon = useApi<SoilingMonitor>(`/sites/${siteKey}/soiling`, eventsVersion);
  return (
    <Card
      title={
        <>
          Soiling &amp; Cleaning <Badge kind="research">Research</Badge>
        </>
      }
      sub="pvlib HSU soiling model with rain cleaning, driven by PM2.5 / PM10 (Open-Meteo CAMS) and Solcast rainfall"
    >
      <Async state={mon} height={360}>
        {(m) => (
          <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2.2fr) minmax(280px, 1fr)", alignItems: "start" }}>
            <Monitor m={m} />
            <RecommendationCard m={m} />
          </div>
        )}
      </Async>
      <div className="divider" />
      <Simulator siteKey={siteKey} />
    </Card>
  );
}

function Monitor({ m }: { m: SoilingMonitor }) {
  const srs = m.series.map((s) => s.sr);
  const lo = Math.floor(Math.min(...srs) * 1000 - 1) / 1000;
  return (
    <div style={{ minWidth: 0 }}>
      <div className="card-head" style={{ marginBottom: 0 }}>
        <h3 className="sub-title">Soiling &amp; Cleaning Monitor</h3>
        <span className="muted" style={{ fontSize: 13 }}>
          Daily · last {m.series.length} days to {m.series.length ? m.series[m.series.length - 1].date : "—"}
        </span>
      </div>
      <Legend
        align="start"
        items={[
          { label: "Soiling ratio", color: C.sr, kind: "line" },
          { label: "Fit (slope = soiling rate)", color: C.fit, kind: "dash" },
          { label: "Cumulative $ since rain clean", color: C.cum, kind: "line" },
          { label: "Rainfall (mm)", color: C.rain },
          { label: "Manual clean", color: C.clean, kind: "line" },
        ]}
      />
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={m.series} margin={{ top: 10, right: 0, left: 0, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" {...AXIS} tickFormatter={dayMonth} minTickGap={36} />
          <YAxis yAxisId="sr" domain={[lo, 1.0005]} {...AXIS} tick={{ fontSize: 12, fill: C.sr }} width={52} tickFormatter={(v) => num(v, 3)} />
          <YAxis yAxisId="rain" orientation="right" {...AXIS} tick={{ fontSize: 12, fill: "#1d4ed8" }} width={30} />
          <YAxis yAxisId="cum" orientation="right" {...AXIS} tick={{ fontSize: 12, fill: C.cum }} width={44} tickFormatter={(v) => `$${num(v)}`} />
          <Tooltip
            content={({ payload, label }) => {
              const p = payload?.[0]?.payload as SoilingMonitor["series"][number] | undefined;
              if (!p) return null;
              return (
                <TipBox
                  title={String(label)}
                  rows={[
                    { name: "Soiling ratio", value: num(p.sr, 4), color: C.sr },
                    { name: "Rain", value: `${num(p.rain_mm, 1)} mm`, color: C.rain },
                    { name: "Cumulative loss", value: money(p.cum_loss_aud, 2), color: C.cum },
                    ...(p.rain_clean ? [{ name: "Event", value: "Rain clean" }] : []),
                  ]}
                />
              );
            }}
          />
          <Bar yAxisId="rain" dataKey="rain_mm" fill={C.rain} maxBarSize={6} isAnimationActive={false} />
          <Line yAxisId="cum" dataKey="cum_loss_aud" stroke={C.cum} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line yAxisId="sr" dataKey="fit" stroke={C.fit} strokeDasharray="5 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          <Line yAxisId="sr" dataKey="sr" stroke={C.sr} strokeWidth={2} dot={false} isAnimationActive={false} />
          {m.manual_cleans.map((d) => (
            <ReferenceLine key={d} yAxisId="sr" x={d} stroke={C.clean} strokeWidth={2} label={{ value: "Manual clean", position: "insideTopLeft", fill: C.clean, fontSize: 11 }} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="axis-note">
        Left axis: soiling ratio (1 = clean) · <span style={{ color: "#1d4ed8" }}>Rain (mm)</span> · <span style={{ color: C.cum }}>Cumulative $</span>
      </div>
    </div>
  );
}

function RecommendationCard({ m }: { m: SoilingMonitor }) {
  const r = m.recommendation;
  if (!r) return <div className="empty">No recommendation available.</div>;
  const clean = r.action === "clean";
  const rows: [string, string][] = [
    ["Current soiling ratio", num(r.current_sr, 4)],
    ["Soiling rate", `${signed(r.rate_pct_per_day, 3)} %/day`],
    ["Energy lost per day", `${num(r.loss_kwh_per_day, 1)} kWh (${money(r.loss_aud_per_day, 2)})`],
    ["Next effective rain", r.next_rain_date ? `${weekdayDayMonth(r.next_rain_date)} · ${num(r.next_rain_mm, 1)} mm (forecast)` : "None in the next 7 days"],
    ["Cleaning cost", money(r.cleaning_cost_aud)],
    ["Best net benefit this week", money(r.best_net_benefit_aud, 2)],
  ];
  return (
    <div className="card highlight" style={{ background: clean ? "var(--amber-bg)" : "var(--green-bg)", borderColor: clean ? "var(--amber-border)" : "var(--green)" }}>
      <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "0.04em", color: clean ? "var(--amber-ink)" : "var(--green-ink)" }}>CLEANING RECOMMENDATION</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: clean ? "var(--amber-ink)" : "#14532d", margin: "8px 0" }}>{r.headline}</div>
      <p style={{ color: clean ? "var(--amber-ink)" : "var(--green-ink)", marginTop: 0 }}>{r.reason}</p>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "9px 0", borderTop: "1px solid rgba(22,101,52,0.15)" }}>
          <span>{k}</span>
          <b style={{ textAlign: "right" }}>{v}</b>
        </div>
      ))}
      <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
        As of {r.anchor_date}. Decision rule: clean only when the energy saved over the forecast week exceeds the cleaning cost (+$50 margin).
      </p>
    </div>
  );
}

function Simulator({ siteKey }: { siteKey: string }) {
  const [mode, setMode] = useState<"none" | "manual">("none");
  const [cleanDate, setCleanDate] = useState<string | null>(null);
  const [cost, setCost] = useState("300");
  const [debCost, setDebCost] = useState(cost);
  useEffect(() => {
    const t = setTimeout(() => setDebCost(cost), 400);
    return () => clearTimeout(t);
  }, [cost]);
  useEffect(() => setCleanDate(null), [siteKey]);
  const state = useApi<Simulation>(`/sites/${siteKey}/soiling/simulate${qs({ clean_date: mode === "manual" ? cleanDate : null, cost: Number(debCost) || 0 })}`);

  return (
    <div>
      <h3 className="sub-title">7-day Soiling Simulator</h3>
      <p className="muted" style={{ marginTop: 4 }}>
        Forecast soiling ratio and dollar loss for the next 7 days. The first point is the last measured SR. Choose No maintenance or Manual clean to compare
        scenarios.
      </p>
      <Async state={state} height={420}>
        {(s) => (
          <>
            <SimStats s={s} cost={cost} setCost={setCost} mode={mode} />
            <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2.2fr) minmax(280px, 1fr)", alignItems: "start", marginTop: 16 }}>
              <SimChart s={s} />
              <div>
                <div className="muted" style={{ fontSize: 12.5, letterSpacing: "0.04em", marginBottom: 8 }}>
                  MAINTENANCE OPTION
                </div>
                {(["none", "manual"] as const).map((m) => (
                  <button
                    key={m}
                    className="inner-card"
                    onClick={() => setMode(m)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      marginBottom: 10,
                      background: mode === m ? "var(--green-bg)" : "#fff",
                      borderColor: mode === m ? "var(--green)" : "var(--border)",
                      borderWidth: mode === m ? 2 : 1,
                    }}
                  >
                    <div style={{ fontWeight: 700 }}>{m === "none" ? "No maintenance" : "Manual clean"}</div>
                    <div className="muted" style={{ fontSize: 13 }}>
                      {m === "none" ? "Forecast soiling only (rain resets if forecast rain ≥ 0.5 mm)" : "Choose a forecast day below (cost set in Net vs baseline)"}
                    </div>
                  </button>
                ))}
                <WeekCalendar s={s} selected={mode === "manual" ? cleanDate : null} enabled={mode === "manual"} onPick={(d) => setCleanDate((cur) => (cur === d ? null : d))} />
              </div>
            </div>
          </>
        )}
      </Async>
    </div>
  );
}

function SimStats({ s, cost, setCost, mode }: { s: Simulation; cost: string; setCost: (v: string) => void; mode: string }) {
  const st = s.stats;
  const box = (label: string, value: string, sub: string, color?: string) => (
    <div className="inner-card" style={{ flex: "1 1 170px" }}>
      <div className="muted" style={{ fontSize: 12, letterSpacing: "0.03em" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color ?? "var(--text)" }}>{value}</div>
      <div className="muted" style={{ fontSize: 12.5 }}>{sub}</div>
    </div>
  );
  const scenario = s.scenario && s.clean_date;
  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
      {box("FORECAST SOILING RATE", `${signed(st.rate_pct_per_day, 3)} %/day`, "since last rain clean", "#c2410c")}
      {box("MAINTENANCE SCENARIO", scenario ? weekdayDayMonth(s.clean_date!) : mode === "manual" ? "Pick a day" : "None", scenario ? "Manual clean" : "No maintenance")}
      {box("WEEK LOSS (BASELINE)", money(st.week_loss_baseline_aud, 2), `${num(st.week_loss_baseline_kwh, 1)} kWh lost to soiling`)}
      {scenario && box("WEEK LOSS (SIMULATED)", money(st.week_loss_scenario_aud, 2), `${num(st.week_loss_scenario_kwh, 1)} kWh lost to soiling`)}
      <div className="inner-card" style={{ flex: "2 1 300px" }}>
        <div className="muted" style={{ fontSize: 12, letterSpacing: "0.03em" }}>NET VS BASELINE (7-DAY)</div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, margin: "6px 0" }}>
          Maintenance cost $
          <input className="input" style={{ width: 110 }} type="number" min={0} step={10} value={cost} onChange={(e) => setCost(e.target.value)} />
        </label>
        {scenario ? (
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div>
              <div className="muted" style={{ fontSize: 12 }}>NET BENEFIT</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: (st.net_benefit_aud ?? 0) >= 0 ? "var(--green-ink)" : "var(--red-ink)" }}>{money(st.net_benefit_aud, 2)}</div>
              <div className="muted" style={{ fontSize: 12 }}>Energy $ saved − maintenance</div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 12 }}>POWER LOSS AVOIDED</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{num(st.kwh_avoided, 1)} kWh</div>
              <div className="muted" style={{ fontSize: 12 }}>Less soiling loss vs no clean</div>
            </div>
          </div>
        ) : (
          <div className="muted" style={{ fontSize: 13 }}>Select Manual clean and a day to compare against the baseline.</div>
        )}
      </div>
    </div>
  );
}

function SimChart({ s }: { s: Simulation }) {
  const data = useMemo(() => {
    const first = { date: s.anchor.date, srBase: s.anchor.sr, srSim: s.scenario ? s.anchor.sr : null, cumBase: 0, cumSim: s.scenario ? 0 : null, rain: null as number | null };
    return [
      first,
      ...s.baseline.map((b, i) => ({
        date: b.date,
        srBase: b.sr,
        srSim: s.scenario ? s.scenario[i].sr : null,
        cumBase: b.cum_loss_aud,
        cumSim: s.scenario ? s.scenario[i].cum_loss_aud : null,
        rain: b.rain_mm,
      })),
    ];
  }, [s]);
  const srs = data.flatMap((d) => [d.srBase, d.srSim ?? d.srBase]);
  const lo = Math.floor(Math.min(...srs) * 1000 - 1) / 1000;
  return (
    <div style={{ minWidth: 0 }}>
      <Legend
        align="start"
        items={[
          { label: "SR (baseline)", color: C.sr, kind: "dash" },
          ...(s.scenario ? [{ label: "SR (with clean)", color: C.sr, kind: "line" as const }] : []),
          { label: "Cumulative $ (baseline)", color: C.cum, kind: "dash" },
          ...(s.scenario ? [{ label: "Cumulative $ (simulated)", color: C.cum, kind: "line" as const }] : []),
          { label: "Forecast rain (mm)", color: C.rain },
        ]}
      />
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={data} margin={{ top: 10, right: 0, left: 0, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" {...AXIS} tickFormatter={dayMonth} />
          <YAxis yAxisId="sr" domain={[lo, 1.0005]} {...AXIS} tick={{ fontSize: 12, fill: C.sr }} width={52} tickFormatter={(v) => num(v, 3)} />
          <YAxis yAxisId="rain" orientation="right" {...AXIS} tick={{ fontSize: 12, fill: "#1d4ed8" }} width={30} />
          <YAxis yAxisId="cum" orientation="right" {...AXIS} tick={{ fontSize: 12, fill: C.cum }} width={44} tickFormatter={(v) => `$${num(v, 1)}`} />
          <Tooltip
            content={({ payload, label }) => {
              const p = payload?.[0]?.payload as (typeof data)[number] | undefined;
              if (!p) return null;
              return (
                <TipBox
                  title={String(label) === s.anchor.date ? `${label} (last measured)` : String(label)}
                  rows={[
                    { name: "SR baseline", value: num(p.srBase, 4), color: C.sr },
                    ...(p.srSim !== null ? [{ name: "SR with clean", value: num(p.srSim, 4), color: C.sr }] : []),
                    { name: "Cumulative $ baseline", value: money(p.cumBase, 2), color: C.cum },
                    ...(p.cumSim !== null ? [{ name: "Cumulative $ simulated", value: money(p.cumSim, 2), color: C.cum }] : []),
                    ...(p.rain !== null ? [{ name: "Forecast rain", value: `${num(p.rain, 1)} mm`, color: C.rain }] : []),
                  ]}
                />
              );
            }}
          />
          <Bar yAxisId="rain" dataKey="rain" fill={C.rain} maxBarSize={22} isAnimationActive={false} />
          <Line yAxisId="cum" dataKey="cumBase" stroke={C.cum} strokeDasharray="5 4" strokeWidth={1.8} dot={false} isAnimationActive={false} />
          {s.scenario && <Line yAxisId="cum" dataKey="cumSim" stroke={C.cum} strokeWidth={2.2} dot={{ r: 3.5, fill: C.cum }} isAnimationActive={false} />}
          <Line yAxisId="sr" dataKey="srBase" stroke={C.sr} strokeDasharray="5 4" strokeWidth={1.8} dot={s.scenario ? false : { r: 3.5, fill: C.sr }} isAnimationActive={false} />
          {s.scenario && <Line yAxisId="sr" dataKey="srSim" stroke={C.sr} strokeWidth={2.2} dot={{ r: 3.5, fill: C.sr }} isAnimationActive={false} />}
          {s.clean_date && <ReferenceLine yAxisId="sr" x={s.clean_date} stroke={C.clean} strokeDasharray="4 3" strokeWidth={2} />}
        </ComposedChart>
      </ResponsiveContainer>
      {s.has_weather.some((h) => !h) && <p className="notice">Some forecast days have no Solcast forecast yet; they use recent average expected generation and no rain.</p>}
    </div>
  );
}

function WeekCalendar({ s, selected, enabled, onPick }: { s: Simulation; selected: string | null; enabled: boolean; onPick: (d: string) => void }) {
  const anchor = new Date(`${s.anchor.date}T12:00:00`);
  const first = new Date(anchor);
  first.setDate(anchor.getDate() - anchor.getDay() - 7); // Sunday of the week before the anchor
  const cells: Date[] = Array.from({ length: 21 }, (_, i) => new Date(first.getFullYear(), first.getMonth(), first.getDate() + i, 12));
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const week = new Set(s.week);
  const months = [...new Set(cells.map((d) => d.toLocaleString("en-AU", { month: "short" })))].join(" – ");
  return (
    <div className="inner-card">
      <div style={{ textAlign: "center", fontWeight: 700, marginBottom: 8 }}>
        {months} {cells[cells.length - 1].getFullYear()}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6, textAlign: "center" }}>
        {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => (
          <div key={d} className="muted" style={{ fontSize: 12 }}>
            {d}
          </div>
        ))}
        {cells.map((d) => {
          const k = iso(d);
          const inWeek = week.has(k);
          const isAnchor = k === s.anchor.date;
          const isSel = k === selected;
          return (
            <button
              key={k}
              disabled={!inWeek || !enabled}
              onClick={() => onPick(k)}
              title={inWeek ? (enabled ? "Click to simulate a manual clean on this day" : "Select Manual clean first") : isAnchor ? "Last measured day" : ""}
              style={{
                padding: "8px 0",
                borderRadius: 8,
                border: isAnchor ? "2px solid #ea580c" : "1px solid transparent",
                background: isSel ? "#16a34a" : inWeek ? "#f3f4f6" : "transparent",
                color: isSel ? "#fff" : isAnchor ? "#c2410c" : inWeek ? "var(--text)" : "var(--faint)",
                fontWeight: isSel || isAnchor ? 700 : 500,
                cursor: inWeek && enabled ? "pointer" : "default",
              }}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 10, lineHeight: 1.7 }}>
        <span style={{ display: "inline-block", width: 10, height: 10, border: "2px solid #ea580c", borderRadius: 3, marginRight: 6 }} />
        Last measured day
        <br />
        <span style={{ display: "inline-block", width: 10, height: 10, background: "#e5e7eb", borderRadius: 3, marginRight: 6 }} />
        Forecast week — click a day to set a manual clean
        <br />
        <span style={{ display: "inline-block", width: 10, height: 10, background: "#16a34a", borderRadius: 3, marginRight: 6 }} />
        Selected clean day (SR → 1.0, cumulative $ resets)
      </div>
    </div>
  );
}
