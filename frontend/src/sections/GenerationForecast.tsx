import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { type Forecast, useApi } from "../api";
import { AXIS, Async, Badge, Card, GRID, Legend, TipBox } from "../components/ui";
import { num, weekdayDayMonth } from "../format";

export function GenerationForecast({ siteKey }: { siteKey: string }) {
  const state = useApi<Forecast>(`/sites/${siteKey}/forecast?hours=168`);
  return (
    <Async state={state} height={360}>
      {(f) => {
        const data = f.hourly.map((h) => ({ ...h, band: [h.lo_kwh, h.hi_kwh] as [number, number] }));
        const midnights = f.hourly.filter((h) => h.timestamp.endsWith("T00:00")).map((h) => h.timestamp);
        return (
          <Card
            title={
              <>
                Generation Forecast <Badge kind="research">Research</Badge>
              </>
            }
            sub={
              f.meta?.forecast_start
                ? `Next 72 hours from ${f.meta.forecast_start.slice(0, 10)} · PVLib on Solcast forecast + XGBoost correction, 80% interval from hold-out residuals`
                : "PVLib on Solcast forecast + XGBoost correction"
            }
            right={
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                {f.daily.map((d) => (
                  <div key={d.date} className="inner-card" style={{ minWidth: 150, padding: "10px 16px" }}>
                    <div className="muted">{weekdayDayMonth(d.date)}</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{num(d.kwh)} kWh</div>
                    <div className="muted" style={{ fontSize: 12.5 }}>± {num(d.plus_minus)} kWh</div>
                  </div>
                ))}
              </div>
            }
          >
            {data.length === 0 ? (
              <div className="empty">
                No forecast for this site: Solcast forecast weather for its campus is not downloaded yet (or there is too little history to train the model).
              </div>
            ) : (
              <>
                <Legend
                  align="start"
                  items={[
                    { label: "Forecast (kWh/h ≈ kW)", color: "#15803d", kind: "line" },
                    { label: "80% prediction interval", color: "#22c55e", kind: "band" },
                    { label: "PVLib physics only", color: "#9ca3af", kind: "dash" },
                  ]}
                />
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid {...GRID} />
                    <XAxis
                      dataKey="timestamp"
                      {...AXIS}
                      ticks={f.hourly.filter((h) => h.timestamp.endsWith("T12:00")).map((h) => h.timestamp)}
                      tickFormatter={(t: string) => weekdayDayMonth(t.slice(0, 10))}
                    />
                    <YAxis {...AXIS} width={48} tickFormatter={(v) => num(v)} />
                    {midnights.map((m) => (
                      <ReferenceLine key={m} x={m} stroke="#d1d5db" strokeDasharray="4 4" />
                    ))}
                    <Tooltip
                      content={({ payload, label }) => {
                        const p = payload?.[0]?.payload as (typeof data)[number] | undefined;
                        if (!p) return null;
                        return (
                          <TipBox
                            title={String(label).replace("T", " ")}
                            rows={[
                              { name: "Forecast", value: `${num(p.forecast_kwh, 1)} kWh`, color: "#15803d" },
                              { name: "80% interval", value: `${num(p.lo_kwh, 1)} – ${num(p.hi_kwh, 1)}` },
                              { name: "PVLib only", value: `${num(p.pvlib_kwh, 1)} kWh`, color: "#9ca3af" },
                            ]}
                          />
                        );
                      }}
                    />
                    <Area dataKey="band" stroke="none" fill="#22c55e" fillOpacity={0.2} isAnimationActive={false} />
                    <Line dataKey="pvlib_kwh" stroke="#9ca3af" strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                    <Line dataKey="forecast_kwh" stroke="#15803d" strokeWidth={2.2} dot={false} isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
                {f.meta?.holdout_mae_kwh !== null && f.meta?.holdout_mae_kwh !== undefined && (
                  <p className="muted" style={{ fontSize: 12.5, margin: "6px 0 0" }}>
                    Model hold-out MAE: {num(f.meta.holdout_mae_kwh, 1)} kWh per hour.
                  </p>
                )}
              </>
            )}
          </Card>
        );
      }}
    </Async>
  );
}
