import type { Saga } from "../api";

const STEP_LABEL: Record<string, string> = {
  RESERVE: "Reserva del conector",
  CHARGE: "Cobro en billetera",
  DISPATCH: "Activación del cargador",
  ABORT_SESSION: "Compensación: abortar sesión",
  REFUND: "Compensación: reembolso",
  RELEASE: "Compensación: liberar conector",
};

export function stateClass(state: string) {
  if (state === "COMPLETED") return "ok";
  if (state === "COMPENSATED") return "warn";
  if (state === "FAILED" || state === "COMPENSATION_FAILED") return "bad";
  return "info";
}

// Línea de pasos de una SAGA, incluidas las transacciones compensatorias.
export function SagaTimeline({ saga }: { saga: Saga }) {
  return (
    <div className="saga">
      <div className="saga-head">
        <span className={`badge ${stateClass(saga.state)}`}>{saga.state}</span>
        {saga.error && <span className="saga-error">{saga.error}</span>}
        {saga.amount != null && <span className="muted">USD {saga.amount.toFixed(2)}</span>}
      </div>
      <ol className="steps">
        {saga.steps.map((st, i) => (
          <li key={i} className={`step step-${st.status}`}>
            <span className="dot" aria-hidden="true" />
            <span>{STEP_LABEL[st.name] ?? st.name}</span>
            <span className="step-status">{st.status}</span>
            {st.error && <span className="muted">({st.error})</span>}
          </li>
        ))}
      </ol>
      <div className="corr">
        <span className="muted">correlation_id</span>
        <code>{saga.correlationId}</code>
        <button type="button" className="ghost" onClick={() => navigator.clipboard?.writeText(saga.correlationId)}>
          Copiar
        </button>
      </div>
    </div>
  );
}
