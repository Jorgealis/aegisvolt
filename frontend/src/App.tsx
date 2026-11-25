import { ENDPOINTS, GRAPHQL_URL, switchEndpoint } from "./api";
import { Flags } from "./components/Flags";
import { History } from "./components/History";
import { ReserveForm } from "./components/ReserveForm";
import { Stations } from "./components/Stations";
import { usePoll } from "./usePoll";

// La banda superior muestra el ambiente que responde (query `environment`):
// dev verde, test ámbar, prod rojo.
export function App() {
  const { data, error } = usePoll<{ environment: string }>("{ environment }", 10000);
  const env = data?.environment ?? (error ? "sin conexión" : "…");

  return (
    <div className={`app env-${env}`}>
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path fill="currentColor" d="M13 2 3 14h7l-1 8 10-12h-7z" />
          </svg>
          <span>AegisVolt</span>
        </div>
        <span className="env-tag" aria-label={`Ambiente ${env}`}>
          {env.toUpperCase()}
        </span>
        <nav className="env-switch" aria-label="Cambiar de ambiente">
          {ENDPOINTS.map((e) => (
            <button
              key={e.env}
              type="button"
              className={`env-opt opt-${e.env}${e.url === GRAPHQL_URL ? " active" : ""}`}
              aria-pressed={e.url === GRAPHQL_URL}
              title={e.url}
              onClick={() => switchEndpoint(e.url)}
            >
              {e.env}
            </button>
          ))}
        </nav>
        <code className="endpoint" title="Endpoint GraphQL">
          {GRAPHQL_URL}
        </code>
      </header>
      <main className="grid">
        <Stations />
        <ReserveForm onDone={() => undefined} />
        <Flags />
        <History />
      </main>
    </div>
  );
}
