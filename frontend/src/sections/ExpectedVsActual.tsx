import type { SiteSummary } from "../api";
import { Badge, Card } from "../components/ui";
import { money, num } from "../format";

function Stat({ label, value, unit, tone }: { label: string; value: string; unit: string; tone?: "loss" }) {
  return (
    <div className="inner-card" style={tone ? { background: "var(--red-bg)", borderColor: "var(--red-border)" } : undefined}>
      <div style={{ color: tone ? "var(--red-ink)" : "var(--text-2)" }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: tone ? "var(--red-ink)" : "var(--text)" }}>
        {value}
        <span className="kpi-unit" style={{ color: tone ? "var(--red-ink)" : undefined }}>
          {unit}
        </span>
      </div>
    </div>
  );
}

export function ExpectedVsActual({ s }: { s: SiteSummary }) {
  const e = s.expected_vs_actual;
  const parts = [
    { label: "Outage", kwh: e.outage_kwh, color: "#dc2626" },
    { label: "Soiling", kwh: e.soiling_kwh, color: "#f59e0b" },
    { label: "Other", kwh: e.other_kwh, color: "#9ca3af" },
  ];
  const total = parts.reduce((a, p) => a + p.kwh, 0);
  return (
    <Card
      title={
        <>
          Expected vs Actual <Badge kind="research">Research</Badge>
        </>
      }
      sub="Baseline = pvlib model from Solcast weather, for the selected period."
    >
      <div className="grid grid-2" style={{ gap: 14 }}>
        <Stat label="Expected generation" value={num(e.expected_kwh)} unit="kWh" />
        <Stat label="Actual generation" value={num(e.actual_kwh)} unit="kWh" />
        <Stat label="Energy lost" value={num(e.lost_kwh)} unit="kWh" tone="loss" />
        <Stat label="Value of lost energy" value={money(e.lost_aud)} unit="AUD" tone="loss" />
      </div>
      <div className="sub-title" style={{ margin: "18px 0 8px" }}>
        Where the loss came from
      </div>
      {total > 0 ? (
        <>
          <div style={{ display: "flex", height: 14, borderRadius: 4, overflow: "hidden", gap: 2, background: "#fff" }}>
            {parts
              .filter((p) => p.kwh > 0)
              .map((p) => (
                <div key={p.label} title={`${p.label}: ${num(p.kwh)} kWh`} style={{ flex: p.kwh, background: p.color }} />
              ))}
          </div>
          <div className="legend" style={{ justifyContent: "flex-start", marginTop: 10 }}>
            {parts.map((p) => (
              <span className="legend-item" key={p.label}>
                <span className="sw" style={{ background: p.color, width: 12, height: 12 }} />
                {p.label} {num(p.kwh)} kWh
              </span>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
            Outage = expected energy during zero-reading, missing or frozen hours. Soiling = expected × (1 − HSU soiling ratio). Other = model bias, shading,
            clipping and everything else.
          </p>
        </>
      ) : (
        <div className="muted">Actual generation met or exceeded the model in this period.</div>
      )}
    </Card>
  );
}

/** Placeholder until building consumption is connected — kept so the page matches the template. */
export function ConsumptionCard({ name }: { name: string }) {
  return (
    <Card
      title={
        <>
          Solar vs Building Consumption <Badge kind="blue">Not connected</Badge>
        </>
      }
      sub="How much of the host building's electricity the panels supply."
    >
      <div className="empty" style={{ textAlign: "left", padding: "8px 0" }}>
        Building consumption for {name} is not part of this pipeline yet. Add the building's load meter to <code>download_data.py</code> and a
        <code> consumption_kwh</code> column to <code>daily.csv</code> to enable the solar-share bar and estimated savings here.
      </div>
    </Card>
  );
}
