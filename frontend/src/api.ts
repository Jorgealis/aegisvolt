// Cliente GraphQL mínimo (fetch). La URL del endpoint depende del ambiente:
//   1) ?api=<url> en la barra de direcciones (útil si API Gateway se recreó)
//   2) VITE_GRAPHQL_URL del archivo .env.<modo>
//   3) el selector de ambiente de la barra superior (escribe ?api=...)
const fromQuery = new URLSearchParams(window.location.search).get("api");

export const GRAPHQL_URL: string = fromQuery ?? import.meta.env.VITE_GRAPHQL_URL ?? "http://localhost:8080/graphql";

// Endpoints del selector. Por defecto, los stacks de scripts/envs.ps1 (Docker
// contra las tablas reales de cada ambiente). Con la plataforma encendida se
// reemplazan por la URL de API Gateway en .env.local: VITE_ENDPOINT_TEST=https://...
export const ENDPOINTS: { env: string; url: string }[] = [
  { env: "local", url: import.meta.env.VITE_ENDPOINT_LOCAL ?? "http://localhost:8080/graphql" },
  { env: "dev", url: import.meta.env.VITE_ENDPOINT_DEV ?? "http://localhost:8180/graphql" },
  { env: "test", url: import.meta.env.VITE_ENDPOINT_TEST ?? "http://localhost:8280/graphql" },
  { env: "prod", url: import.meta.env.VITE_ENDPOINT_PROD ?? "http://localhost:8380/graphql" },
];

export function switchEndpoint(url: string): void {
  const params = new URLSearchParams(window.location.search);
  params.set("api", url);
  window.location.search = params.toString(); // recarga: todo el estado parte limpio
}

export class GraphQLError extends Error {}

export async function gql<T>(query: string, variables?: Record<string, unknown>, correlationId?: string): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (correlationId) headers["x-correlation-id"] = correlationId;
  const res = await fetch(GRAPHQL_URL, { method: "POST", headers, body: JSON.stringify({ query, variables }) });
  if (!res.ok) throw new GraphQLError(`HTTP ${res.status}`);
  const body = await res.json();
  if (body.errors?.length) throw new GraphQLError(body.errors.map((e: { message: string }) => e.message).join("; "));
  return body.data as T;
}

// --- Tipos del esquema (services/graphql-gateway/schema.graphql) ---------
export type ConnectorStatus = "AVAILABLE" | "RESERVED" | "CHARGING" | "OUT_OF_SERVICE";
export type SagaState =
  | "STARTED"
  | "RESERVED"
  | "CHARGED"
  | "COMPLETED"
  | "COMPENSATING"
  | "COMPENSATED"
  | "FAILED"
  | "COMPENSATION_FAILED";

export interface Connector {
  id: string;
  stationId: string;
  powerKw: number;
  status: ConnectorStatus;
}
export interface Station {
  id: string;
  name: string;
  city: string;
  connectors: Connector[];
}
export interface SagaStep {
  name: string;
  status: string;
  at: string;
  error: string | null;
}
export interface Saga {
  id: string;
  correlationId: string;
  state: SagaState;
  fleetId: string;
  stationId: string;
  connectorId: string;
  estimatedKwh: number;
  amount: number | null;
  error: string | null;
  steps: SagaStep[];
  createdAt: string;
}
export interface FeatureFlag {
  name: string;
  enabled: boolean;
  env: string;
}
export interface Tariff {
  basePerKwh: number;
  effectivePerKwh: number;
  surgeFlag: boolean;
  surgeActive: boolean;
  surgeHours: string;
}
export interface WalletTx {
  sagaId: string;
  type: string;
  amount: number;
  at: string;
}
export interface Wallet {
  fleetId: string;
  balance: number;
  transactions: WalletTx[];
}

export const SAGA_FIELDS = "id correlationId state fleetId stationId connectorId estimatedKwh amount error createdAt steps { name status at error }";
