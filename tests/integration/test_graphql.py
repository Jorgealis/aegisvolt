"""Endpoint GraphQL del gateway llamando a los 3 servicios reales (en proceso) sobre DynamoDB Local."""

import pytest
from fastapi.testclient import TestClient

from .conftest import get_item, set_flag

MUTATION = """
mutation($f: ID!, $s: ID!, $c: ID!, $k: Float!) {
  reserveAndCharge(fleetId: $f, stationId: $s, connectorId: $c, estimatedKwh: $k) {
    id correlationId state amount error steps { name status error }
  }
}"""


@pytest.fixture
def gql(monkeypatch):
    from billing_wallet.main import app as billing_app
    from energy_dispatch.main import app as dispatch_app
    from graphql_gateway import deps as deps_mod
    from graphql_gateway import schema as schema_mod
    from graphql_gateway.clients import ServiceClient
    from graphql_gateway.main import app as gateway_app
    from station_reservation.main import app as reservation_app

    d = deps_mod.build(
        ServiceClient("station-reservation", "", http=TestClient(reservation_app), backoff=0),
        ServiceClient("billing-wallet", "", http=TestClient(billing_app), backoff=0),
        ServiceClient("energy-dispatch", "", http=TestClient(dispatch_app), backoff=0),
    )
    monkeypatch.setattr(schema_mod, "deps", lambda: d)
    client = TestClient(gateway_app)

    def run(query, variables=None, headers=None):
        body = client.post("/graphql", json={"query": query, "variables": variables or {}}, headers=headers or {}).json()
        assert "errors" not in body, body
        return body["data"]

    return run


def reserve(gql, fleet="FLEET-001", station="MDE-01", connector="C1", kwh=40.0, headers=None):
    return gql(MUTATION, {"f": fleet, "s": station, "c": connector, "k": kwh}, headers)["reserveAndCharge"]


def test_saga_success(gql):
    saga = reserve(gql, headers={"x-correlation-id": "it-corr-1"})
    assert saga["state"] == "COMPLETED"
    assert saga["correlationId"] == "it-corr-1"
    assert get_item("reservations", "STATION#MDE-01", "CONNECTOR#C1")["status"] == "CHARGING"
    assert get_item("sagas", f"SAGA#{saga['id']}", "META")["state"] == "COMPLETED"
    telemetry = gql("query($id: ID!) { telemetry(sessionId: $id) { kwh powerKw } }", {"id": saga["id"]})["telemetry"]
    assert len(telemetry) == 3


def test_saga_hardware_fault_compensates(gql):
    set_flag("SIMULATE_CHARGER_HARDWARE_FAULT", True)
    saga = reserve(gql)
    assert saga["state"] == "COMPENSATED" and saga["error"] == "CHARGER_HARDWARE_FAULT"
    assert [s["name"] for s in saga["steps"]] == ["RESERVE", "CHARGE", "DISPATCH", "REFUND", "RELEASE"]
    assert get_item("billing", "FLEET#FLEET-001", f"TX#{saga['id']}#REFUND")["amount"] == saga["amount"]
    assert get_item("billing", "FLEET#FLEET-001", "WALLET")["balance"] == 500
    assert get_item("reservations", "STATION#MDE-01", "CONNECTOR#C1")["status"] == "AVAILABLE"


def test_saga_insufficient_funds_releases(gql):
    saga = reserve(gql, fleet="FLEET-002", kwh=100)
    assert saga["state"] == "COMPENSATED" and saga["error"] == "INSUFFICIENT_FUNDS"
    assert [s["name"] for s in saga["steps"]] == ["RESERVE", "CHARGE", "RELEASE"]
    assert get_item("reservations", "STATION#MDE-01", "CONNECTOR#C1")["status"] == "AVAILABLE"


def test_queries(gql):
    data = gql('{ environment featureFlags { name enabled env } stations(city: "Bogota") { id connectors { id status powerKw } } tariff { basePerKwh } }')
    assert data["environment"] == "it"
    assert {f["name"] for f in data["featureFlags"]} >= {"SIMULATE_CHARGER_HARDWARE_FAULT", "ENABLE_DYNAMIC_SURGE_PRICING"}
    assert [s["id"] for s in data["stations"]] == ["BOG-01"]
