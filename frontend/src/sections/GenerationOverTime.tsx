import { useState } from "react";
import { useMeta } from "../context";
import { Bar, Brush, CartesianGrid, Cell, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { type Generation, type GenerationPoint, postJson, qs, useApi } from "../api";
import { AXIS, Async, Card, GRID, Icon, Legend, TipBox } from "../components/ui";
import { dayMonth, num } from "../format";

type View = "daily" | "monthly" | "yearly";
const C = { actual: "#22c55e", expected: "#111827", ghi: "#f59e0b", above: "#ef4444", below: "#3b82f6", median: "#a16207", event: "#2563eb", outage: "#fee2e2" };

const EVENT_LABEL: Record<string, string> = { panel_cleaning: "Panels cleaned", maintenance: "Maintenance", inverter_fault: "Inverter fault", other: "Event" };

function tickLabel(view: View, label: string) {
  if (view === "daily") return dayMonth(label);
  if (view === "monthly") return new Date(`${label}-01T12:00:00`).toLocaleString("en-AU", { month: "short", year: "2-digit" });
  return label;
}

export function GenerationOverTime(props: { siteKey: string; start: string; end: string; eventsVersion: number; onEventAdded: () => void }) {
  const { meta } = useMeta();
  const [view, setView] = useState<View>("daily");
  const [zoom, setZoom] = useState(false);
  const [adding, setAdding] = useState(false);
  const state = useApi<Generation>(`/sites/${props.siteKey}/generation${qs({ start: props.start, end: props.end, view })}`, props.eventsVersion);
  const unit = view === "daily" ? "kWh/day" : view === "monthly" ? "kWh/month" : "kWh/year";

  return (
    <Card
      title={<>Total Solar Generation Over Time</>}
      sub={view === "daily" ? "Daily View" : view === "monthly" ? "Monthly View · last 24 months" : `Yearly View · since ${meta.analysis_start}`}
      right={
        <div className="seg" style={{ alignItems: "center" }}>
          {(["daily", "monthly", "yearly"] as View[]).map((v) => (
            <button key={v} className={`btn ${view === v ? "active" : ""}`} onClick={() => setView(v)}>
              {v[0].toUpperCase() + v.slice(1)} View
            </button>
          ))}
          <button className="btn dark" onClick={() => setAdding((a) => !a)}>
            {Icon.plus} Event
          </button>
          <label className="btn square" style={{ gap: 8 }}>
            Zoom
            <input type="checkbox" checked={zoom} onChange={(e) => setZoom(e.target.checked)} />
          </label>
        </div>
      }
    >
      {adding && (
        <EventForm
          siteKey={props.siteKey}
          defaultDate={props.end}
          onDone={(saved) => {
            setAdding(false);
            if (saved) props.onEventAdded();
          }}
        />
      )}
      <Legend
        items={[
          { label: "Actual generation", color: C.actual },
          { label: "Expected (pvlib)", color: C.expected, kind: "dash" },
          { label: "Irradiance (kWh/m²)", color: C.ghi, kind: "line" },
          { label: "Outage (zero reading)", color: C.outage },
          { label: "Event", color: C.event, kind: "line" },
        ]}
      />
      <Async state={state} height={340}>
        {(g) =>
          g.series.length === 0 ? (
            <div className="empty">No readings in this period.</div>
          ) : (
            <>
              <MainChart g={g} view={view} zoom={zoom} unit={unit} />
              <div className="divider" />
              <h3 className="sub-title">
                Daily Difference – Expected minus Actual <span className="sub-note">{unit} · red = below expected, blue = above expected</span>
              </h3>
              <Legend
                items={[
                  { label: "Expected − Actual > 0", color: C.above },
                  { label: "Expected − Actual < 0", color: C.below },
                  { label: "Trend", color: C.expected, kind: "dash" },
                  { label: view === "daily" ? "7-day median" : "3-period median", color: C.median, kind: "line" },
                ]}
              />
              <DiffChart g={g} view={view} />
            </>
          )
        }
      </Async>
    </Card>
  );
}

function overlays(g: Generation) {
  return [
    ...g.outage_spans.map((s) => (
      <ReferenceArea key={`o-${s.start}`} yAxisId="kwh" x1={s.start} x2={s.end} fill={C.outage} fillOpacity={0.8} ifOverflow="extendDomain" label={{ value: "Zero reading", position: "insideTop", fill: "#b91c1c", fontSize: 11 }} />
    )),
    ...g.events.map((e) => (
      <ReferenceLine key={`e-${e.date}-${e.type}`} yAxisId="kwh" x={e.date} stroke={C.event} strokeWidth={2} label={{ value: EVENT_LABEL[e.type] ?? "Event", position: "insideTopRight", fill: C.event, fontSize: 11 }} />
    )),
  ];
}

function MainChart({ g, view, zoom, unit }: { g: Generation; view: View; zoom: boolean; unit: string }) {
  return (
    <ResponsiveContainer width="100%" height={zoom ? 380 : 340}>
      <ComposedChart data={g.series} margin={{ top: 16, right: 8, left: 8, bottom: 0 }} barCategoryGap="22%">
        <CartesianGrid {...GRID} />
        <XAxis dataKey="label" {...AXIS} tickFormatter={(l) => tickLabel(view, l)} minTickGap={24} />
        <YAxis yAxisId="kwh" {...AXIS} width={56} tickFormatter={(v) => num(v)} label={{ value: unit, angle: -90, position: "insideLeft", fill: "#6b7280", fontSize: 12, dy: 30 }} />
        <YAxis yAxisId="ghi" orientation="right" {...AXIS} width={44} tick={{ fontSize: 12, fill: "#b45309" }} tickFormatter={(v) => num(v, view === "daily" ? 1 : 0)} />
        {overlays(g)}
        <Tooltip
          content={({ payload, label }) => {
            const p = payload?.[0]?.payload as GenerationPoint | undefined;
            if (!p) return null;
            return (
              <TipBox
                title={view === "daily" ? String(label) : tickLabel(view, String(label))}
                rows={[
                  { name: "Actual", value: `${num(p.actual_kwh)} kWh`, color: C.actual },
                  { name: "Expected (pvlib)", value: `${num(p.expected_kwh)} kWh`, color: C.expected },
                  { name: "Irradiance", value: `${num(p.ghi_kwh_m2, 2)} kWh/m²`, color: C.ghi },
                  ...(p.outage_day ? [{ name: "Status", value: "Zero reading" }] : []),
                ]}
              />
            );
          }}
        />
        <Bar yAxisId="kwh" dataKey="actual_kwh" fill={C.actual} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
        <Line yAxisId="kwh" dataKey="expected_kwh" stroke={C.expected} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        <Line yAxisId="ghi" dataKey="ghi_kwh_m2" stroke={C.ghi} strokeWidth={2} dot={false} isAnimationActive={false} />
        {zoom && <Brush dataKey="label" height={24} stroke="#9ca3af" tickFormatter={(l) => tickLabel(view, l)} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function DiffChart({ g, view }: { g: Generation; view: View }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={g.series} margin={{ top: 10, right: 52, left: 8, bottom: 0 }} barCategoryGap="22%">
        <CartesianGrid {...GRID} />
        <XAxis dataKey="label" {...AXIS} tickFormatter={(l) => tickLabel(view, l)} minTickGap={24} />
        <YAxis yAxisId="kwh" {...AXIS} width={56} tickFormatter={(v) => num(v)} />
        {overlays(g)}
        <ReferenceLine yAxisId="kwh" y={0} stroke="#9ca3af" />
        <Tooltip
          content={({ payload, label }) => {
            const p = payload?.[0]?.payload as GenerationPoint | undefined;
            if (!p) return null;
            return (
              <TipBox
                title={view === "daily" ? String(label) : tickLabel(view, String(label))}
                rows={[
                  { name: "Expected − Actual", value: `${num(p.diff_kwh)} kWh`, color: (p.diff_kwh ?? 0) >= 0 ? C.above : C.below },
                  { name: "Median", value: `${num(p.median7)} kWh`, color: C.median },
                  { name: "Trend", value: `${num(p.trend)} kWh`, color: C.expected },
                ]}
              />
            );
          }}
        />
        <Bar yAxisId="kwh" dataKey="diff_kwh" maxBarSize={22} isAnimationActive={false} radius={[3, 3, 3, 3]}>
          {g.series.map((p) => (
            <Cell key={p.label} fill={(p.diff_kwh ?? 0) >= 0 ? C.above : C.below} />
          ))}
        </Bar>
        <Line yAxisId="kwh" dataKey="trend" stroke={C.expected} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        <Line yAxisId="kwh" dataKey="median7" stroke={C.median} strokeWidth={2} dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function EventForm({ siteKey, defaultDate, onDone }: { siteKey: string; defaultDate: string; onDone: (saved: boolean) => void }) {
  const [date, setDate] = useState(defaultDate);
  const [type, setType] = useState("panel_cleaning");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await postJson("/events", { site_key: siteKey, date, type, note });
      onDone(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="inner-card" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 14, background: "var(--surface-2)" }}>
      <label>
        <span className="field-label">Date</span>
        <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label>
        <span className="field-label">Type</span>
        <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
          {Object.entries(EVENT_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label style={{ flex: 1, minWidth: 220 }}>
        <span className="field-label">Note</span>
        <input className="input" value={note} maxLength={300} placeholder="e.g. contractor wash, all arrays" onChange={(e) => setNote(e.target.value)} />
      </label>
      <button className="btn dark" disabled={busy || !date} onClick={save}>
        Save event
      </button>
      <button className="btn square" onClick={() => onDone(false)}>
        Cancel
      </button>
      {error && <div className="error" style={{ width: "100%" }}>{error}</div>}
    </div>
  );
}
