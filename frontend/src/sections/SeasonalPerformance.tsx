import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { useMeta } from "../context";
import { type SeasonMetric, type Seasonal, useApi } from "../api";
import { AXIS, Async, Badge, Card, GRID, Legend, TipBox, TrendChip } from "../components/ui";
import { num } from "../format";

const SEASON_COLOR: Record<string, string> = { summer: "#d97706", autumn: "#059669", winter: "#0284c7", spring: "#7c3aed" };

function Diamond(props: { cx?: number; cy?: number }) {
  const { cx = 0, cy = 0 } = props;
  return <path d={`M${cx} ${cy - 5}L${cx + 5} ${cy}L${cx} ${cy + 5}L${cx - 5} ${cy}Z`} fill="#fff" stroke="#111827" strokeWidth={1.6} />;
}

function SeasonChart({ m, color, years, metric }: { m: SeasonMetric; color: string; years: number[]; metric: "ghi" | "h" }) {
  const annual = m.annual.map((a) => ({ x: a.season_year, median: a.median, trend: a.trend ?? null, days: a.days }));
  const domain: [number, number] = metric === "h" ? [0, 1.5] : [0, Math.ceil(Math.max(1, ...m.points.map((p) => p.value)) / 2) * 2];
  return (
    <ResponsiveContainer width="100%" height={170}>
      <ComposedChart margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis type="number" dataKey="x" domain={[years[0] - 0.5, years[years.length - 1] + 0.5]} ticks={years} {...AXIS} allowDuplicatedCategory={false} />
        <YAxis type="number" domain={domain} allowDataOverflow {...AXIS} width={36} tickFormatter={(v) => num(v, metric === "h" ? 1 : 1)} />
        {metric === "h" && <ReferenceLine y={1} stroke="#9ca3af" strokeDasharray="4 4" />}
        {m.median !== null && <ReferenceLine y={m.median} stroke={color} strokeDasharray="2 3" strokeWidth={1.5} />}
        <Tooltip
          cursor={false}
          content={({ payload }) => {
            const p = payload?.[0]?.payload as { x: number; median?: number; value?: number; days?: number } | undefined;
            if (!p || p.median === undefined) return null;
            return <TipBox title={`${Math.round(p.x)} season`} rows={[{ name: "Annual median", value: num(p.median, metric === "h" ? 3 : 2) }, { name: "Days", value: num(p.days) }]} />;
          }}
        />
        <Scatter data={m.points} dataKey="value" fill={color} fillOpacity={0.55} shape={(p: { cx?: number; cy?: number }) => <circle cx={p.cx} cy={p.cy} r={1.7} fill={color} fillOpacity={0.6} />} isAnimationActive={false} />
        <Line data={annual} dataKey="trend" stroke="#dc2626" strokeDasharray="5 4" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
        <Line data={annual} dataKey="median" stroke="#111827" strokeWidth={1.6} dot={<Diamond />} activeDot={<Diamond />} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function SeasonalPerformance({ siteKey }: { siteKey: string }) {
  const { meta } = useMeta();
  const state = useApi<Seasonal>(`/sites/${siteKey}/seasonal`);
  return (
    <Card
      title={
        <>
          Seasonal Performance Analysis <Badge kind="research">Research</Badge>
        </>
      }
      sub={`Australian seasons, data since ${meta.analysis_start}. Upper: daily GHI summed over daylight hours (GHI > 5 W/m²). Lower: health ratio H = actual ÷ expected.`}
      right={
        <Legend
          items={[
            { label: "Daily value", color: "#6b7280", kind: "dot" },
            { label: "Season median", color: "#059669", kind: "dash" },
            { label: "Annual median", color: "#111827", kind: "line" },
            { label: "Trend (annual medians)", color: "#dc2626", kind: "dash" },
          ]}
        />
      }
    >
      <Async state={state} height={600}>
        {(s) =>
          s.years.length === 0 ? (
            <div className="empty">Not enough history for a seasonal analysis.</div>
          ) : (
            <div className="grid grid-2">
              {s.seasons.map((season) => {
                const color = SEASON_COLOR[season.id];
                return (
                  <div key={season.id} className="inner-card">
                    <div className="sub-title" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 17 }}>
                      <span className="sw dot" style={{ background: color, width: 11, height: 11 }} />
                      {season.label}
                    </div>
                    <div style={{ fontWeight: 600, fontSize: 13, margin: "10px 0 2px" }}>Daily GHI (kWh/m²/day)</div>
                    <SeasonChart m={season.ghi} color={color} years={s.years} metric="ghi" />
                    <div className="kpi-delta" style={{ marginTop: 4 }}>
                      Median daily GHI: <b style={{ color: "var(--text)" }}>{num(season.ghi.median, 2)} kWh/m²</b>
                      <TrendChip pct={season.ghi.pct_per_year} kind="change" />
                      {num(season.ghi.days)} days
                    </div>
                    <div style={{ fontWeight: 600, fontSize: 13, margin: "14px 0 2px" }}>Health ratio H (actual ÷ expected)</div>
                    <SeasonChart m={season.h} color={color} years={s.years} metric="h" />
                    <div className="kpi-delta" style={{ marginTop: 4 }}>
                      Median H: <b style={{ color: "var(--text)" }}>{num(season.h.median, 3)}</b>
                      <TrendChip pct={season.h.pct_per_year} kind="health" />
                      {num(season.h.days)} days
                    </div>
                  </div>
                );
              })}
            </div>
          )
        }
      </Async>
    </Card>
  );
}
