import { CartesianGrid, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useMeta } from "../context";
import { type Degradation, type Num, useApi } from "../api";
import { AXIS, Async, Badge, Card, GRID, Legend, TipBox } from "../components/ui";
import { num, signed } from "../format";

function TrendBadge({ label, pct }: { label: string; pct: Num }) {
  const cls = pct === null ? "flat" : pct < 0 ? "down" : "up";
  return <span className={`chip ${cls}`}>{label} {signed(pct, 2, " %/yr")}</span>;
}

export function LongTermDegradation({ siteKey }: { siteKey: string }) {
  const { meta } = useMeta();
  const state = useApi<Degradation>(`/sites/${siteKey}/degradation`);
  return (
    <Card
      title={
        <>
          Long-term Degradation <Badge kind="research">Research</Badge>
        </>
      }
      sub={`Health ratio H = Σ actual ÷ Σ pvlib expected over valid daylight hours (GHI > 5 W/m², outage hours excluded) · data since ${meta.analysis_start}`}
    >
      <Async state={state} height={560}>
        {(d) => {
          const annual = d.annual.map((a) => ({ ...a, label: String(a.period) }));
          const hs = annual.map((a) => a.h);
          const lo = Math.floor((Math.min(...hs) - 0.02) * 50) / 50;
          const hi = Math.ceil((Math.max(...hs) + 0.02) * 50) / 50;
          return (
            <>
              <div className="card-head" style={{ marginBottom: 4 }}>
                <h3 className="sub-title">
                  Annual H — primary degradation trend <span className="sub-note">linear regression vs calendar year · {d.window_start} → {d.window_end}</span>
                </h3>
                <div className="seg" style={{ alignItems: "center" }}>
                  <Legend items={[{ label: "Annual H", color: "#0d9488", kind: "line" }, { label: `OLS fit · ${signed(d.yearly_slope, 4)} / yr`, color: "#ea580c", kind: "dash" }]} />
                  <TrendBadge label="Annual trend" pct={d.yearly_pct_per_year} />
                </div>
              </div>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={annual} margin={{ top: 24, right: 24, left: 0, bottom: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="label" {...AXIS} padding={{ left: 30, right: 30 }} />
                  <YAxis domain={[lo, hi]} {...AXIS} width={44} tickFormatter={(v) => num(v, 2)} />
                  <Tooltip content={({ payload, label }) => (payload?.[0] ? <TipBox title={String(label)} rows={[{ name: "H", value: num(payload[0].payload.h, 3) }, { name: "Fit", value: num(payload[0].payload.fit, 3) }, { name: "Days", value: num(payload[0].payload.days) }]} /> : null)} />
                  <Line dataKey="fit" stroke="#ea580c" strokeDasharray="6 5" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line dataKey="h" stroke="#0d9488" strokeWidth={2.2} dot={{ r: 5, fill: "#0d9488", stroke: "#fff", strokeWidth: 2 }} isAnimationActive={false}>
                    <LabelList dataKey="h" position="top" offset={10} formatter={(v: number) => num(v, 3)} style={{ fontSize: 12, fontWeight: 600, fill: "#0f766e" }} />
                  </Line>
                </LineChart>
              </ResponsiveContainer>

              <div className="divider" />
              <div className="card-head" style={{ marginBottom: 4 }}>
                <h3 className="sub-title">
                  Monthly H — medium-term detail <span className="sub-note">seasonal swing around the long-term level</span>
                </h3>
                <div className="seg" style={{ alignItems: "center" }}>
                  <Legend items={[{ label: "Monthly H", color: "#7c3aed", kind: "line" }, { label: `Fit · ${signed(d.monthly_slope_per_day, 6)} / day`, color: "#ea580c", kind: "dash" }]} />
                  <TrendBadge label="Monthly trend" pct={d.monthly_pct_per_year} />
                </div>
              </div>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={d.monthly} margin={{ top: 10, right: 24, left: 0, bottom: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="period" {...AXIS} interval="preserveStartEnd" minTickGap={30} tickFormatter={(p: string) => new Date(`${p}-01T12:00:00`).toLocaleString("en-AU", { month: "short", year: "numeric" })} />
                  <YAxis {...AXIS} width={44} domain={["auto", "auto"]} tickFormatter={(v) => num(v, 1)} />
                  <ReferenceLine y={1} stroke="#9ca3af" strokeDasharray="4 4" />
                  <Tooltip content={({ payload, label }) => (payload?.[0] ? <TipBox title={String(label)} rows={[{ name: "H", value: num(payload[0].payload.h, 3) }, { name: "Days", value: num(payload[0].payload.days) }]} /> : null)} />
                  <Line dataKey="fit" stroke="#ea580c" strokeDasharray="6 5" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line dataKey="h" stroke="#7c3aed" strokeWidth={2} dot={{ r: 2.5, fill: "#7c3aed" }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </>
          );
        }}
      </Async>
    </Card>
  );
}
