"""SAGA orquestada "Reservar y Activar Carga".

STARTED -> RESERVED -> CHARGED -> COMPLETED
Fallos:
  Paso 1 (reserva)   -> FAILED (nada que compensar; si fue transitorio se libera por si acaso)
  Paso 2 (cobro)     -> COMPENSATING -> release                -> COMPENSATED
  Paso 3 (activación)-> COMPENSATING -> refund -> release      -> COMPENSATED
Si una compensación agota sus reintentos -> COMPENSATION_FAILED (lo detecta Prefect).

Cada transición se persiste en aegisvolt-sagas-<env> (PK=SAGA#<id>, SK=META).
"""

import logging
import uuid
from datetime import UTC, datetime

from aegis_common import aws, config
from aegis_common.logs import correlation_id as correlation_var
from aegis_common.logs import log_event
from aegis_common.logs import saga_id as saga_var

from .clients import ServiceClient, ServiceError

logger = logging.getLogger("saga-orchestrator")

FINAL_STATES = {"COMPLETED", "COMPENSATED", "FAILED", "COMPENSATION_FAILED"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SagaRepository:
    def table(self) -> str:
        return config.table_name("sagas")

    def save(self, saga: dict) -> None:
        saga["updated_at"] = now_iso()
        aws.dynamodb().put_item(TableName=self.table(), Item=aws.to_item({"PK": f"SAGA#{saga['id']}", "SK": "META", **saga}))

    def get(self, saga_id: str) -> dict | None:
        item = aws.dynamodb().get_item(TableName=self.table(), Key={"PK": {"S": f"SAGA#{saga_id}"}, "SK": {"S": "META"}}, ConsistentRead=True).get("Item")
        return _strip(aws.from_item(item))

    def list(self, limit: int = 20) -> list[dict]:
        items, kwargs = [], {"TableName": self.table()}
        while True:
            resp = aws.dynamodb().scan(**kwargs)
            items += [_strip(aws.from_item(i)) for i in resp.get("Items", [])]
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return sorted(items, key=lambda s: s["created_at"], reverse=True)[:limit]


def _strip(item: dict | None) -> dict | None:
    if item:
        item.pop("PK", None)
        item.pop("SK", None)
    return item


class SagaOrchestrator:
    def __init__(self, reservations: ServiceClient, billing: ServiceClient, dispatch: ServiceClient, repo):
        self.reservations, self.billing, self.dispatch, self.repo = reservations, billing, dispatch, repo

    # -- helpers -----------------------------------------------------------
    def _transition(self, saga: dict, state: str, **extra) -> None:
        saga["state"] = state
        saga.update(extra)
        self.repo.save(saga)
        level = logging.ERROR if state == "COMPENSATION_FAILED" else logging.INFO
        log_event(logger, f"SAGA_{state}", level, saga_id=saga["id"], state=state, error=saga.get("error"))

    def _step(self, saga: dict, name: str, status: str, error: str | None = None) -> None:
        saga["steps"].append({"name": name, "status": status, "at": now_iso(), "error": error})
        log_event(logger, "SAGA_STEP", saga_id=saga["id"], step=name, step_status=status, error=error)

    # -- flujo -------------------------------------------------------------
    def run(self, fleet_id: str, station_id: str, connector_id: str, estimated_kwh: float, correlation_id: str | None = None) -> dict:
        sid = str(uuid.uuid4())
        cid = correlation_id or sid
        correlation_var.set(cid)
        saga_var.set(sid)
        saga = {
            "id": sid,
            "correlation_id": cid,
            "env": config.env(),
            "fleet_id": fleet_id,
            "station_id": station_id,
            "connector_id": connector_id,
            "estimated_kwh": estimated_kwh,
            "amount": None,
            "error": None,
            "steps": [],
            "created_at": now_iso(),
        }
        connector = {"station_id": station_id, "connector_id": connector_id}
        self._transition(saga, "STARTED")

        # Paso 1: reserva
        try:
            reserved = self.reservations.post("/reservations", {"saga_id": sid, **connector})
            self._step(saga, "RESERVE", "OK")
            self._transition(saga, "RESERVED")
        except ServiceError as e:
            self._step(saga, "RESERVE", "FAILED", e.code)
            if e.transient:  # timeout: la reserva pudo aplicarse; liberar es idempotente
                return self._compensate(saga, e.code, refund=False, abort=False)
            self._transition(saga, "FAILED", error=e.code)
            return saga

        # Paso 2: cobro
        try:
            charged = self.billing.post("/charges", {"saga_id": sid, "fleet_id": fleet_id, "kwh": estimated_kwh})
            saga["amount"] = charged["amount"]
            self._step(saga, "CHARGE", "OK")
            self._transition(saga, "CHARGED")
        except ServiceError as e:
            self._step(saga, "CHARGE", "FAILED", e.code)
            # Fondos insuficientes: solo se libera el conector. Si fue transitorio el
            # cobro pudo aplicarse: refund es idempotente y no hace nada si no hubo débito.
            return self._compensate(saga, e.code, refund=e.transient, abort=False)

        # Paso 3: activación física
        try:
            self.dispatch.post(
                "/sessions",
                {"saga_id": sid, **connector, "power_kw": reserved["power_kw"], "kwh": estimated_kwh},
            )
            self._step(saga, "DISPATCH", "OK")
        except ServiceError as e:
            self._step(saga, "DISPATCH", "FAILED", e.code)
            return self._compensate(saga, e.code, refund=True, abort=e.transient)

        try:
            self.reservations.post(f"/reservations/{sid}/charging", connector)
        except ServiceError as e:  # no invalida la carga ya iniciada
            log_event(logger, "MARK_CHARGING_FAILED", logging.WARNING, saga_id=sid, error=e.code)
        self._transition(saga, "COMPLETED")
        return saga

    def _compensate(self, saga: dict, error: str, refund: bool, abort: bool) -> dict:
        """Compensa en orden inverso: (abort) -> refund -> release."""
        self._transition(saga, "COMPENSATING", error=error)
        ok = True
        connector = {"station_id": saga["station_id"], "connector_id": saga["connector_id"]}
        actions = []
        if abort:
            actions.append(("ABORT_SESSION", lambda: self.dispatch.post(f"/sessions/{saga['id']}/abort")))
        if refund:
            actions.append(("REFUND", lambda: self.billing.post(f"/charges/{saga['id']}/refund", {"fleet_id": saga["fleet_id"]})))
        actions.append(("RELEASE", lambda: self.reservations.post(f"/reservations/{saga['id']}/release", connector)))

        for name, action in actions:
            try:
                action()
                self._step(saga, name, "COMPENSATED")
            except ServiceError as e:
                ok = False
                self._step(saga, name, "FAILED", e.code)
        self._transition(saga, "COMPENSATED" if ok else "COMPENSATION_FAILED")
        return saga
