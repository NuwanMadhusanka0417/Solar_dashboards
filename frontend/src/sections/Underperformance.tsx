import { useEffect, useState } from "react";
import { type UnderEvent, qs, useApi } from "../api";
import { Async, Card } from "../components/ui";
import { useMeta } from "../context";
import { addDays, longDate, num } from "../format";

/** Debounce numeric inputs so typing "15" doesn't fire a request for "1". */
function useDebounced<T>(value: T, ms = 400) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function Underperformance(props: { siteKey: string; start: string; end: string; onView: (start: string, end: string) => void }) {
  const { meta } = useMeta();
  const [pct, setPct] = useState(String(meta.underperform_pct));
  const [days, setDays] = useState(String(meta.underperform_min_days));
  const p = useDebounced(pct);
  const d = useDebounced(days);
  const state = useApi<{ baseline_h: number | null; events: UnderEvent[] }>(
    `/sites/${props.siteKey}/underperformance${qs({ start: props.start, end: props.end, threshold_pct: Number(p) || 10, min_days: Number(d) || 1 })}`,
  );

  return (
    <Card title="Underperformance Detection" sub="Expected is scaled by the site's own 12-month median H, so a site's normal model bias isn't flagged.">
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 18 }}>
        <label style={{ width: 240 }}>
          <span className="field-label">Below Expected by (%)</span>
          <input className="input" type="number" min={1} max={100} value={pct} onChange={(e) => setPct(e.target.value)} />
        </label>
        <label style={{ width: 240 }}>
          <span className="field-label">Number of Consecutive Days</span>
          <input className="input" type="number" min={1} max={60} value={days} onChange={(e) => setDays(e.target.value)} />
        </label>
      </div>
      <Async state={state} height={120}>
        {(r) => (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>From</th>
                    <th>To</th>
                    <th className="num">Total Days</th>
                    <th className="num">Difference (kWh)</th>
                    <th>Likely cause</th>
                    <th>Source</th>
                    <th>View</th>
                  </tr>
                </thead>
                <tbody>
                  {r.events.map((e) => (
                    <tr key={e.start}>
                      <td>{longDate(e.start)}</td>
                      <td>{longDate(e.end)}</td>
                      <td className="num">{e.days}</td>
                      <td className="num" style={{ color: "var(--red-ink)", fontWeight: 700 }}>
                        {e.difference_kwh < 0 ? "−" : "+"}
                        {num(Math.abs(e.difference_kwh))}
                      </td>
                      <td>{e.cause}</td>
                      <td className="muted">{e.source}</td>
                      <td>
                        <button className="link" onClick={() => props.onView(addDays(e.start, -7), addDays(e.end, 7) > meta.data_end ? meta.data_end : addDays(e.end, 7))}>
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                  {r.events.length === 0 && (
                    <tr>
                      <td colSpan={7} className="empty">
                        No periods ≥ {p}% below expected for ≥ {d} consecutive days in the selected range.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>
              Baseline H for this site: {num(r.baseline_h, 3)}. “View” zooms the date range to the event (±7 days).
            </p>
          </>
        )}
      </Async>
    </Card>
  );
}
