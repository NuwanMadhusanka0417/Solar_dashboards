import { useMeta } from "../context";

export function DateRange({ start, end, onChange }: { start: string; end: string; onChange: (s: string, e: string) => void }) {
  const { meta } = useMeta();
  return (
    <label className="control" aria-label="Date range">
      <input type="date" value={start} min={meta.data_start} max={end} onChange={(e) => e.target.value && onChange(e.target.value, end)} />
      <span className="muted">–</span>
      <input type="date" value={end} min={start} max={meta.data_end} onChange={(e) => e.target.value && onChange(start, e.target.value)} />
    </label>
  );
}
