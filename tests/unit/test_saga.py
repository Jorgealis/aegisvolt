"""Orquestador SAGA con clientes falsos: los 3 caminos de la especificación y más."""

import pytest

from graphql_gateway.clients import ServiceError
from graphql_gateway.saga import SagaOrchestrator


class FakeClient:
    """Responde según un dict ruta -> respuesta | ServiceError, y registra las llamadas."""

    def __init__(self, name, routes, calls):
        self.name, self.routes, self.calls = name, routes, calls

    def post(self, path, json=None):
        self.calls.append((self.name, path))
        matches = [p for p in self.routes if path.startswith(p)]
        if not matches:
            return {}
        resp = self.routes[max(matches, key=len)]  # gana el prefijo más largo
        if isinstance(resp, ServiceError):
            raise resp
        return resp


class FakeRepo:
    def __init__(self):
        self.states = []

    def save(self, saga):
        self.states.append(saga["state"])


def build(reservations=None, billing=None, dispatch=None):
    calls, repo = [], FakeRepo()
    orch = SagaOrchestrator(
        FakeClient("reservations", {"/reservations": {"power_kw": 150}, **(reservations or {})}, calls),
        FakeClient("billing", {"/charges": {"amount": 12.0}, **(billing or {})}, calls),
        FakeClient("dispatch", {"/sessions": {"status": "STARTED"}, **(dispatch or {})}, calls),
        repo,
    )
    return orch, calls, repo


def run(orch):
    return orch.run("FLEET-001", "BOG-01", "C2", 40.0)


def paths(calls):
    return [(svc, p.split("/")[-1] if p.count("/") > 1 else p) for svc, p in calls]


def test_happy_path_completes():
    orch, calls, repo = build()
    saga = run(orch)
    assert saga["state"] == "COMPLETED"
    assert saga["amount"] == 12.0
    assert repo.states == ["STARTED", "RESERVED", "CHARGED", "COMPLETED"]
    assert [s["name"] for s in saga["steps"]] == ["RESERVE", "CHARGE", "DISPATCH"]
    assert saga["correlation_id"] == saga["id"]  # sin header entrante, correlation_id = saga_id


def test_connector_busy_fails_without_compensation():
    orch, calls, _ = build(reservations={"/reservations": ServiceError("reservations", "CONNECTOR_NOT_AVAILABLE", transient=False, status=409)})
    saga = run(orch)
    assert saga["state"] == "FAILED"
    assert saga["error"] == "CONNECTOR_NOT_AVAILABLE"
    assert all(svc == "reservations" for svc, _ in calls) and len(calls) == 1


def test_insufficient_funds_only_releases_connector():
    orch, calls, repo = build(billing={"/charges": ServiceError("billing", "INSUFFICIENT_FUNDS", transient=False, status=409)})
    saga = run(orch)
    assert saga["state"] == "COMPENSATED"
    assert repo.states[-2:] == ["COMPENSATING", "COMPENSATED"]
    assert paths(calls)[-1] == ("reservations", "release")
    assert not any(p.endswith("/refund") for _, p in calls)


def test_hardware_fault_refunds_then_releases():
    orch, calls, _ = build(dispatch={"/sessions": ServiceError("dispatch", "CHARGER_HARDWARE_FAULT", transient=False, status=409)})
    saga = run(orch)
    assert saga["state"] == "COMPENSATED"
    assert saga["error"] == "CHARGER_HARDWARE_FAULT"
    # orden inverso: primero billing (refund), luego reservations (release)
    assert paths(calls)[-2:] == [("billing", "refund"), ("reservations", "release")]
    assert [(s["name"], s["status"]) for s in saga["steps"][-2:]] == [("REFUND", "COMPENSATED"), ("RELEASE", "COMPENSATED")]


def test_transient_charge_failure_also_tries_refund():
    """Si el cobro hizo timeout, pudo aplicarse: se intenta refund (idempotente)."""
    orch, calls, _ = build(billing={"/charges/": {}, "/charges": ServiceError("billing", "UNAVAILABLE", transient=True)})
    saga = run(orch)
    assert saga["state"] == "COMPENSATED"
    assert ("billing", "refund") in paths(calls)


def test_failed_compensation_is_reported():
    orch, _, _ = build(
        dispatch={"/sessions": ServiceError("dispatch", "CHARGER_HARDWARE_FAULT", transient=False, status=409)},
        billing={"/charges/": ServiceError("billing", "UNAVAILABLE", transient=True), "/charges": {"amount": 12.0}},
    )
    saga = run(orch)
    assert saga["state"] == "COMPENSATION_FAILED"
    # aun así intenta liberar el conector
    assert saga["steps"][-1]["name"] == "RELEASE"


@pytest.mark.parametrize("cid", ["corr-123"])
def test_incoming_correlation_id_is_kept(cid):
    orch, _, _ = build()
    saga = orch.run("FLEET-001", "BOG-01", "C2", 10.0, correlation_id=cid)
    assert saga["correlation_id"] == cid and saga["id"] != cid
