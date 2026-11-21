import type { Station } from "../api";
import { usePoll } from "../usePoll";

const STATUS_LABEL: Record<string, string> = {
  AVAILABLE: "Disponible",
  RESERVED: "Reservado",
  CHARGING: "Cargando",
  OUT_OF_SERVICE: "Fuera de servicio",
};

// 1) Panel de electrolineras y disponibilidad de conectores (polling 2 s).
export function Stations() {
  const { data, error } = usePoll<{ stations: Station[] }>("{ stations { id name city connectors { id stationId powerKw status } } }");

  return (
    <section className="panel" aria-labelledby="stations-title">
      <header className="panel-head">
        <h2 id="stations-title">Electrolineras</h2>
        <span className="live" title="Se actualiza cada 2 s">en vivo</span>
      </header>
      {error && <p className="error">No se pudo consultar: {error}</p>}
      {!data && !error && <p className="muted">Cargando…</p>}
      <div className="stations">
        {data?.stations.map((s) => (
          <article key={s.id} className="station">
            <div className="station-head">
              <strong>{s.name}</strong>
              <span className="muted">
                {s.id} · {s.city}
              </span>
            </div>
            <ul className="connectors">
              {s.connectors.map((c) => (
                <li key={c.id} className={`connector st-${c.status}`}>
                  <span className="conn-id">{c.id}</span>
                  <span className="conn-kw">{c.powerKw} kW</span>
                  <span className="conn-status">{STATUS_LABEL[c.status] ?? c.status}</span>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}
