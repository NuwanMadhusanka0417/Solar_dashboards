import type { ReactNode } from "react";
import type { Num, Status } from "../api";
import { num, signed } from "../format";

/* ── icons (inline, stroke = currentColor) ───────────────────────── */
const svg = (d: ReactNode, size = 18) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    {d}
  </svg>
);
export const Icon = {
  sun: svg(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>),
  leaf: svg(<><path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10Z" /><path d="M2 21c0-3 1.9-5.4 5.1-6" /></>),
  bolt: svg(<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />),
  trend: svg(<><path d="m22 7-8.5 8.5-5-5L2 17" /><path d="M16 7h6v6" /></>),
  grid: svg(<><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>, 17),
  search: svg(<><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></>, 16),
  plus: svg(<path d="M12 5v14M5 12h14" />, 16),
  arrow: svg(<path d="M5 12h14M13 6l6 6-6 6" />, 15),
};

/* ── layout pieces ───────────────────────────────────────────────── */
export function Card(props: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; highlight?: boolean; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${props.highlight ? "highlight" : ""} ${props.className ?? ""}`}>
      {(props.title || props.right) && (
        <div className="card-head">
          <div>
            {props.title && <h2 className="card-title">{props.title}</h2>}
            {props.sub && <p className="card-sub">{props.sub}</p>}
          </div>
          {props.right}
        </div>
      )}
      {props.children}
    </section>
  );
}

export function Badge({ kind = "gray", children }: { kind?: "gray" | "research" | "amber" | "blue"; children: ReactNode }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}

export function StatusPill({ status }: { status: Status }) {
  return <span className={`status ${status}`}>{status}</span>;
}

/** Green/red/grey delta chip with an arrow; colour follows "good" not the sign when `invert`. */
export function DeltaChip({ value, invert = false, suffix = "%" }: { value: Num; invert?: boolean; suffix?: string }) {
  if (value === null || !Number.isFinite(value)) return <span className="chip flat">—</span>;
  const flat = Math.abs(value) < 0.005;
  const good = invert ? value < 0 : value > 0;
  const cls = flat ? "flat" : good ? "up" : "down";
  const arrow = flat ? "–" : value > 0 ? "↗" : "↘";
  return (
    <span className={`chip ${cls}`}>
      {arrow} {num(Math.abs(value), 2)}
      {suffix}
    </span>
  );
}

export function KpiCard(props: {
  icon?: ReactNode;
  plainIcon?: boolean;
  label: string;
  value: string;
  unit?: string;
  meta?: ReactNode;
  delta?: ReactNode;
  highlight?: boolean;
}) {
  return (
    <section className={`card ${props.highlight ? "highlight" : ""}`}>
      <div className="kpi-label">
        {props.icon && <span className={`kpi-icon ${props.plainIcon ? "plain" : ""}`}>{props.icon}</span>}
        {props.label}
      </div>
      <div className="kpi-value">
        {props.value}
        {props.unit && <span className="kpi-unit">{props.unit}</span>}
      </div>
      {props.meta && <div className="kpi-meta">{props.meta}</div>}
      {props.delta && <div className="kpi-delta">{props.delta}</div>}
    </section>
  );
}

export function TrendChip({ pct, kind }: { pct: Num; kind: "health" | "change" }) {
  if (pct === null || !Number.isFinite(pct)) return <span className="chip flat">—</span>;
  if (kind === "change") return <span className={`chip ${pct >= 0 ? "up" : "down"}`}>Change {pct >= 0 ? "▲" : "▼"} {signed(pct, 2, "%/yr")}</span>;
  if (Math.abs(pct) < 0.5) return <span className="chip flat">Stable ≈ {signed(pct, 2, "%/yr")}</span>;
  return pct < 0 ? (
    <span className="chip down">Degradation ▼ {signed(pct, 2, "%/yr")}</span>
  ) : (
    <span className="chip up">Improvement ▲ {signed(pct, 2, "%/yr")}</span>
  );
}

/* ── chart helpers ───────────────────────────────────────────────── */
export type LegendEntry = { label: string; color: string; kind?: "box" | "line" | "dash" | "dot" | "band" };

export function Legend({ items, align = "center" }: { items: LegendEntry[]; align?: "center" | "start" }) {
  return (
    <div className="legend" style={{ justifyContent: align === "start" ? "flex-start" : "center" }}>
      {items.map((it) => (
        <span className="legend-item" key={it.label}>
          {it.kind === "dash" ? (
            <span className="sw dash" style={{ color: it.color }} />
          ) : (
            <span className={`sw ${it.kind === "line" ? "line" : it.kind === "dot" ? "dot" : ""}`} style={{ background: it.color, opacity: it.kind === "band" ? 0.35 : 1 }} />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}

type TipRow = { name: string; value: string; color?: string };
export function TipBox({ title, rows }: { title: string; rows: TipRow[] }) {
  return (
    <div className="chart-tip">
      <div className="t">{title}</div>
      {rows.map((r) => (
        <div className="r" key={r.name}>
          <span>
            {r.color && <span className="sw dot" style={{ background: r.color, marginRight: 6 }} />}
            {r.name}
          </span>
          <b>{r.value}</b>
        </div>
      ))}
    </div>
  );
}

export function Loading({ height = 220 }: { height?: number }) {
  return <div className="skeleton" style={{ height }} aria-label="Loading" />;
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="error">Could not load data: {message}</div>;
}

/** Render children once data is ready, otherwise a skeleton or an error box. */
export function Async<T>({ state, height, children }: { state: { data: T | null; error: string | null; loading: boolean }; height?: number; children: (d: T) => ReactNode }) {
  if (state.error) return <ErrorBox message={state.error} />;
  if (!state.data) return <Loading height={height} />;
  return <>{children(state.data)}</>;
}

export const AXIS = { tick: { fontSize: 12, fill: "#6b7280" }, tickLine: false, axisLine: false, stroke: "#d1d5db" } as const;
export const GRID = { stroke: "#eef0f2", vertical: false } as const;
