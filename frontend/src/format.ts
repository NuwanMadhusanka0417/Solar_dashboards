/** Number / date formatting shared by every section (en-AU). */
import type { Num } from "./api";

const nf = (d: number) => new Intl.NumberFormat("en-AU", { minimumFractionDigits: d, maximumFractionDigits: d });

export function num(v: Num | undefined, digits = 0): string {
  return v === null || v === undefined || !Number.isFinite(v) ? "—" : nf(digits).format(v);
}

export function signed(v: Num | undefined, digits = 1, suffix = ""): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const s = nf(digits).format(Math.abs(v));
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${s}${suffix}`;
}

export function money(v: Num | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${v < 0 ? "−" : ""}$${nf(digits).format(Math.abs(v))}`;
}

export function pctChange(cur: number, prev: number): Num {
  return prev > 0 ? ((cur - prev) / prev) * 100 : null;
}

const parse = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00`);

/** "30 Aug" */
export function dayMonth(iso: string): string {
  const d = parse(iso);
  return `${d.getDate()} ${d.toLocaleString("en-AU", { month: "short" })}`;
}

/** "Thu 1 Oct" */
export function weekdayDayMonth(iso: string): string {
  const d = parse(iso);
  return `${d.toLocaleString("en-AU", { weekday: "short" })} ${d.getDate()} ${d.toLocaleString("en-AU", { month: "short" })}`;
}

/** "10 Sep 2026" */
export function longDate(iso: string): string {
  const d = parse(iso);
  return `${d.getDate()} ${d.toLocaleString("en-AU", { month: "short" })} ${d.getFullYear()}`;
}

export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addDays(iso: string, n: number): string {
  const d = parse(iso);
  d.setDate(d.getDate() + n);
  return isoDate(d);
}
