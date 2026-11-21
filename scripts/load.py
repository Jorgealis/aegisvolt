"""Genera tráfico GraphQL constante para que el análisis del canary tenga datos.

  python scripts/load.py --url https://<api-id>.execute-api.us-east-1.amazonaws.com/dev/graphql --rps 5 --seconds 300

Mezcla consultas (stations, tariff, featureFlags) y, con --mutations, reservas
que pasan por los 3 microservicios. Imprime la tasa de error cada 10 s.
"""

import argparse
import itertools
import time

import httpx

QUERIES = [
    "{ stations { id connectors { id status } } }",
    "{ tariff { effectivePerKwh surgeActive } }",
    "{ featureFlags { name enabled } environment }",
]
MUTATION = 'mutation { reserveAndCharge(fleetId: "FLEET-001", stationId: "BOG-01", connectorId: "C1", estimatedKwh: 1) { state } }'


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--rps", type=float, default=5)
    p.add_argument("--seconds", type=int, default=300)
    p.add_argument("--mutations", action="store_true", help="incluir reservas (consumen saldo y conectores)")
    a = p.parse_args()

    bodies = itertools.cycle(QUERIES + ([MUTATION] if a.mutations else []))
    ok = err = 0
    start = last = time.monotonic()
    with httpx.Client(timeout=10) as client:
        while time.monotonic() - start < a.seconds:
            t0 = time.monotonic()
            try:
                r = client.post(a.url, json={"query": next(bodies)})
                if r.status_code >= 500:
                    err += 1
                else:
                    ok += 1
            except httpx.HTTPError:
                err += 1
            if time.monotonic() - last >= 10:
                total = ok + err
                print(f"{int(time.monotonic() - start):4d}s  peticiones={total}  errores={err}  tasa={err / total:.1%}", flush=True)
                last = time.monotonic()
            time.sleep(max(0.0, 1 / a.rps - (time.monotonic() - t0)))
    print(f"fin: {ok + err} peticiones, {err} errores")


if __name__ == "__main__":
    main()
