"""Cliente HTTP hacia los microservicios (Service ClusterIP en Kubernetes).

- Propaga x-correlation-id y x-saga-id.
- Timeout de 3 s y 3 reintentos con backoff exponencial SOLO ante fallos
  transitorios (red, timeout, 5xx). Reintentar un POST es seguro porque cada
  operación lleva su clave de idempotencia (<saga_id>:<accion>).
- Un 4xx es un error de negocio (p. ej. INSUFFICIENT_FUNDS): no se reintenta.
"""

import time

import httpx

from aegis_common.logs import correlation_id, saga_id


class ServiceError(Exception):
    def __init__(self, service: str, code: str, transient: bool, status: int | None = None):
        super().__init__(f"{service}: {code}")
        self.service, self.code, self.transient, self.status = service, code, transient, status


class ServiceClient:
    def __init__(self, name: str, base_url: str, http: httpx.Client | None = None, retries: int = 3, timeout: float = 3.0, backoff: float = 0.2):
        self.name, self.retries, self.backoff = name, retries, backoff
        self.http = http or httpx.Client(base_url=base_url, timeout=timeout)

    def _headers(self) -> dict:
        h = {}
        if correlation_id.get():
            h["x-correlation-id"] = correlation_id.get()
        if saga_id.get():
            h["x-saga-id"] = saga_id.get()
        return h

    def request(self, method: str, path: str, **kwargs):
        last = "UNAVAILABLE"
        for attempt in range(self.retries + 1):
            try:
                resp = self.http.request(method, path, headers=self._headers(), **kwargs)
            except httpx.HTTPError as exc:
                last = f"TRANSPORT_ERROR:{type(exc).__name__}"
            else:
                if resp.status_code < 400:
                    return resp.json()
                code = _error_code(resp)
                if resp.status_code < 500:
                    raise ServiceError(self.name, code, transient=False, status=resp.status_code)
                last = code
            if attempt < self.retries:
                time.sleep(self.backoff * 2**attempt)  # 0.2 s, 0.4 s, 0.8 s
        raise ServiceError(self.name, last, transient=True)

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json: dict | None = None):
        return self.request("POST", path, json=json or {})


def _error_code(resp: httpx.Response) -> str:
    try:
        return resp.json().get("error") or f"HTTP_{resp.status_code}"
    except ValueError:
        return f"HTTP_{resp.status_code}"
