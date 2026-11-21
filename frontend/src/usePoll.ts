import { useCallback, useEffect, useRef, useState } from "react";

import { gql } from "./api";

// Consulta GraphQL repetida cada `intervalMs` (2 s): "tiempo real" para flags,
// conectores y SAGAs sin WebSockets.
export function usePoll<T>(query: string, intervalMs = 2000, variables?: Record<string, unknown>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const vars = useRef(variables);
  vars.current = variables;

  const refresh = useCallback(async () => {
    try {
      setData(await gql<T>(query, vars.current));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [query]);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(refresh, intervalMs);
    return () => window.clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, refresh };
}
