import { createContext, useContext } from "react";
import { useSearchParams } from "react-router-dom";
import type { Meta, Site } from "./api";

export const MetaContext = createContext<{ meta: Meta; sites: Site[] } | null>(null);

export function useMeta() {
  const ctx = useContext(MetaContext);
  if (!ctx) throw new Error("MetaContext missing");
  return ctx;
}

/** Filters live in the URL (?start=&end=&campus=) so views are shareable and survive reloads. */
export function useDateRange() {
  const { meta } = useMeta();
  const [params, setParams] = useSearchParams();
  const start = params.get("start") ?? meta.default_start;
  const end = params.get("end") ?? meta.default_end;
  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: true });
  };
  const setRange = (s: string, e: string) => update({ start: s, end: e });
  return { start, end, setRange, update, params };
}
