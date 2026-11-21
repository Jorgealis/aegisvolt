import { useMemo, useState } from "react";

import { SAGA_FIELDS, type Saga, type Station, gql } from "../api";
import { usePoll } from "../usePoll";
import { SagaTimeline } from "./SagaTimeline";

const FLEETS = [
  { id: "FLEET-001", label: "FLEET-001 (saldo normal)" },
  { id: "FLEET-002", label: "FLEET-002 (saldo bajo)" },
];

// 2) Flujo de reserva y activación: dispara la SAGA con la mutation reserveAndCharge.
export function ReserveForm({ onDone }: { onDone: () => void }) {
  const { data } = usePoll<{ stations: Station[] }>("{ stations { id name city connectors { id stationId powerKw status } } }", 4000);
  const [fleetId, setFleetId] = useState(FLEETS[0].id);
  const [stationId, setStationId] = useState("");
  const [connectorId, setConnectorId] = useState("");
  const [kwh, setKwh] = useState(30);
  const [busy, setBusy] = useState(false);
  const [saga, setSaga] = useState<Saga | null>(null);
  const [error, setError] = useState<string | null>(null);

  const stations = data?.stations ?? [];
  const station = stations.find((s) => s.id === stationId) ?? stations[0];
  const connectors = useMemo(() => station?.connectors ?? [], [station]);
  const connector = connectors.find((c) => c.id === connectorId) ?? connectors.find((c) => c.status === "AVAILABLE") ?? connectors[0];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!station || !connector) return;
    setBusy(true);
    setError(null);
    try {
      const cid = `ui-${crypto.randomUUID()}`;
      const res = await gql<{ reserveAndCharge: Saga }>(
        `mutation($f: ID!, $s: ID!, $c: ID!, $k: Float!) { reserveAndCharge(fleetId: $f, stationId: $s, connectorId: $c, estimatedKwh: $k) { ${SAGA_FIELDS} } }`,
        { f: fleetId, s: station.id, c: connector.id, k: kwh },
        cid,
      );
      setSaga(res.reserveAndCharge);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="reserve-title">
      <header className="panel-head">
        <h2 id="reserve-title">Reservar y activar carga</h2>
      </header>
      <form className="form" onSubmit={submit}>
        <label>
          Flota
          <select value={fleetId} onChange={(e) => setFleetId(e.target.value)}>
            {FLEETS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Estación
          <select value={station?.id ?? ""} onChange={(e) => (setStationId(e.target.value), setConnectorId(""))}>
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.city})
              </option>
            ))}
          </select>
        </label>
        <label>
          Conector
          <select value={connector?.id ?? ""} onChange={(e) => setConnectorId(e.target.value)}>
            {connectors.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id} · {c.powerKw} kW · {c.status}
              </option>
            ))}
          </select>
        </label>
        <label>
          kWh estimados
          <input type="number" min={1} max={500} step={1} value={kwh} onChange={(e) => setKwh(Number(e.target.value))} />
        </label>
        <button type="submit" disabled={busy || !connector}>
          {busy ? "Ejecutando SAGA…" : "Reservar y activar"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {saga && <SagaTimeline saga={saga} />}
    </section>
  );
}
