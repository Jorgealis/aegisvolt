import { Fragment, useState } from "react";

import { SAGA_FIELDS, type Saga, type Wallet } from "../api";
import { usePoll } from "../usePoll";
import { SagaTimeline, stateClass } from "./SagaTimeline";

const TX_LABEL: Record<string, string> = { DEBIT: "Cobro", REFUND: "Reembolso", TOPUP: "Recarga" };

// 4) Historial de transacciones y estado de las compensaciones.
export function History() {
  const { data, error } = usePoll<{ sagas: Saga[]; w1: Wallet | null; w2: Wallet | null }>(
    `{ sagas(limit: 15) { ${SAGA_FIELDS} }
       w1: wallet(fleetId: "FLEET-001") { fleetId balance transactions { sagaId type amount at } }
       w2: wallet(fleetId: "FLEET-002") { fleetId balance transactions { sagaId type amount at } } }`,
  );
  const [open, setOpen] = useState<string | null>(null);
  const wallets = [data?.w1, data?.w2].filter((w): w is Wallet => !!w);

  return (
    <section className="panel wide" aria-labelledby="history-title">
      <header className="panel-head">
        <h2 id="history-title">Historial de SAGAs y billeteras</h2>
        <span className="live" title="Se actualiza cada 2 s">en vivo</span>
      </header>
      {error && <p className="error">{error}</p>}

      <div className="wallets">
        {wallets.map((w) => (
          <div key={w.fleetId} className="wallet">
            <span className="muted">{w.fleetId}</span>
            <strong>USD {w.balance.toFixed(2)}</strong>
            <span className="small muted">
              {w.transactions.slice(0, 4).map((t) => `${TX_LABEL[t.type] ?? t.type} ${t.amount.toFixed(2)}`).join(" · ") || "sin movimientos"}
            </span>
          </div>
        ))}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Hora</th>
              <th>Estado</th>
              <th>Flota</th>
              <th>Conector</th>
              <th>Monto</th>
              <th>Motivo</th>
              <th>Compensaciones</th>
            </tr>
          </thead>
          <tbody>
            {data?.sagas.map((s) => {
              const comps = s.steps.filter((st) => st.status === "COMPENSATED").map((st) => st.name);
              return (
                <Fragment key={s.id}>
                  <tr className="clickable" onClick={() => setOpen(open === s.id ? null : s.id)}>
                    <td>{new Date(s.createdAt).toLocaleTimeString()}</td>
                    <td>
                      <span className={`badge ${stateClass(s.state)}`}>{s.state}</span>
                    </td>
                    <td>{s.fleetId}</td>
                    <td>
                      {s.stationId}/{s.connectorId}
                    </td>
                    <td>{s.amount != null ? s.amount.toFixed(2) : "—"}</td>
                    <td>{s.error ?? "—"}</td>
                    <td>{comps.length ? comps.join(" → ") : "—"}</td>
                  </tr>
                  {open === s.id && (
                    <tr>
                      <td colSpan={7}>
                        <SagaTimeline saga={s} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {data && data.sagas.length === 0 && <p className="muted">Aún no hay SAGAs en este ambiente.</p>}
      </div>
    </section>
  );
}
