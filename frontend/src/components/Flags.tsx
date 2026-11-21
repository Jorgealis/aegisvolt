import type { FeatureFlag, Tariff } from "../api";
import { usePoll } from "../usePoll";

const FLAG_HELP: Record<string, string> = {
  ENABLE_DYNAMIC_SURGE_PRICING: "Tarifa ×1,5 en hora pico",
  ENABLE_FAST_CHARGE_BOOST: "Permite reservar conectores de 350 kW",
  SIMULATE_CHARGER_HARDWARE_FAULT: "El cargador falla: dispara la compensación",
};

// 3) Estado de las Feature Flags del ambiente y su efecto (tarifa vigente).
export function Flags() {
  const { data, error } = usePoll<{ featureFlags: FeatureFlag[]; tariff: Tariff }>(
    "{ featureFlags { name enabled env } tariff { basePerKwh effectivePerKwh surgeFlag surgeActive surgeHours } }",
  );

  return (
    <section className="panel" aria-labelledby="flags-title">
      <header className="panel-head">
        <h2 id="flags-title">Feature flags</h2>
        <span className="live" title="Se actualiza cada 2 s">en vivo</span>
      </header>
      {error && <p className="error">{error}</p>}
      <ul className="flags">
        {data?.featureFlags.map((f) => (
          <li key={f.name} className="flag">
            <div>
              <code>{f.name}</code>
              <span className="muted small">{FLAG_HELP[f.name]}</span>
            </div>
            <span className={`pill ${f.enabled ? "on" : "off"}`}>{f.enabled ? "ON" : "OFF"}</span>
          </li>
        ))}
      </ul>
      {data && (
        <div className={`tariff ${data.tariff.surgeActive ? "surge" : ""}`}>
          <span className="muted">Tarifa vigente</span>
          <strong>USD {data.tariff.effectivePerKwh.toFixed(2)} / kWh</strong>
          <span className="small">
            {data.tariff.surgeActive
              ? `Tarifa dinámica activa (base ${data.tariff.basePerKwh.toFixed(2)} × 1,5)`
              : data.tariff.surgeFlag
                ? `Tarifa dinámica habilitada, fuera de hora pico (${data.tariff.surgeHours} h)`
                : "Tarifa base"}
          </span>
        </div>
      )}
    </section>
  );
}
