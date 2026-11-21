"""E2E: flujo completo por la API pública (GraphQL) sobre el stack de docker compose.

  docker compose up -d --build --wait
  python scripts/seed.py --env local --endpoint http://localhost:8001 --create-tables
  pytest tests/e2e

Verifica en las tablas DynamoDB el resultado de cada camino de la SAGA.
"""

import os
import time
import urllib.request
import uuid

import boto3
import httpx
import pytest

GATEWAY = os.getenv("E2E_GATEWAY_URL", "http://localhost:8080")
BILLING = os.getenv("E2E_BILLING_URL", "http://localhost:8102")
DDB = os.getenv("E2E_DYNAMODB_ENDPOINT", "http://localhost:8001")
ENV = os.getenv("E2E_ENV", "local")
FLAG_CACHE_WAIT = 6  # los servicios cachean las flags 5 s

MUTATION = """
mutation($f: ID!, $s: ID!, $c: ID!, $k: Float!) {
  reserveAndCharge(fleetId: $f, stationId: $s, connectorId: $c, estimatedKwh: $k) {
    id correlationId state amount error steps { name status }
  }
}"""


def _up(url):
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except OSError:
        return False


# En CI el stack DEBE estar arriba (si no, falla); en local se omite si no lo levantaste.
pytestmark = pytest.mark.skipif(not os.getenv("CI") and not _up(f"{GATEWAY}/health"), reason=f"stack no disponible en {GATEWAY}")


@pytest.fixture(scope="module")
def ddb():
    return boto3.client("dynamodb", endpoint_url=DDB, region_name="us-east-1", aws_access_key_id="local", aws_secret_access_key="local")


def item(ddb, table, pk, sk):
    it = ddb.get_item(TableName=f"aegisvolt-{table}-{ENV}", Key={"PK": {"S": pk}, "SK": {"S": sk}}, ConsistentRead=True).get("Item")
    return it


def connector_status(ddb, station, connector):
    return item(ddb, "reservations", f"STATION#{station}", f"CONNECTOR#{connector}")["status"]["S"]


def balance(ddb, fleet):
    return float(item(ddb, "billing", f"FLEET#{fleet}", "WALLET")["balance"]["N"])


def set_flag(ddb, name, enabled):
    ddb.put_item(TableName=f"aegisvolt-flags-{ENV}", Item={"PK": {"S": f"FLAG#{name}"}, "name": {"S": name}, "enabled": {"BOOL": enabled}})


def gql(query, variables=None, correlation_id=None):
    headers = {"x-correlation-id": correlation_id} if correlation_id else {}
    r = httpx.post(f"{GATEWAY}/graphql", json={"query": query, "variables": variables or {}}, headers=headers, timeout=30)
    r.raise_for_status()
    body = r.json()
    assert "errors" not in body, body
    return body["data"]


def reserve(fleet, station, connector, kwh, correlation_id=None):
    return gql(MUTATION, {"f": fleet, "s": station, "c": connector, "k": kwh}, correlation_id)["reserveAndCharge"]


def test_1_successful_charge(ddb):
    before = balance(ddb, "FLEET-001")
    cid = f"e2e-{uuid.uuid4()}"
    saga = reserve("FLEET-001", "LIM-01", "C1", 20, correlation_id=cid)
    assert saga["state"] == "COMPLETED" and saga["correlationId"] == cid
    assert connector_status(ddb, "LIM-01", "C1") == "CHARGING"
    assert balance(ddb, "FLEET-001") == pytest.approx(before - saga["amount"])


def test_2_insufficient_funds_releases_connector(ddb):
    saga = reserve("FLEET-002", "LIM-01", "C2", 200)
    assert saga["state"] == "COMPENSATED" and saga["error"] == "INSUFFICIENT_FUNDS"
    assert connector_status(ddb, "LIM-01", "C2") == "AVAILABLE"
    assert item(ddb, "billing", "FLEET#FLEET-002", f"TX#{saga['id']}#DEBIT") is None


def test_3_hardware_fault_refunds_and_releases(ddb):
    set_flag(ddb, "SIMULATE_CHARGER_HARDWARE_FAULT", True)
    try:
        time.sleep(FLAG_CACHE_WAIT)
        before = balance(ddb, "FLEET-001")
        saga = reserve("FLEET-001", "BOG-01", "C2", 30)
        assert saga["state"] == "COMPENSATED" and saga["error"] == "CHARGER_HARDWARE_FAULT"
        assert [s["name"] for s in saga["steps"]][-2:] == ["REFUND", "RELEASE"]
        assert item(ddb, "billing", "FLEET#FLEET-001", f"TX#{saga['id']}#DEBIT") is not None
        assert item(ddb, "billing", "FLEET#FLEET-001", f"TX#{saga['id']}#REFUND") is not None
        assert balance(ddb, "FLEET-001") == pytest.approx(before)
        assert connector_status(ddb, "BOG-01", "C2") == "AVAILABLE"

        # Idempotencia: repetir la compensación no vuelve a sumar el saldo.
        again = httpx.post(f"{BILLING}/charges/{saga['id']}/refund", json={"fleet_id": "FLEET-001"}).json()
        assert again["replayed"] is True
        assert balance(ddb, "FLEET-001") == pytest.approx(before)
    finally:
        set_flag(ddb, "SIMULATE_CHARGER_HARDWARE_FAULT", False)
        time.sleep(FLAG_CACHE_WAIT)


def test_4_history_and_flags_visible():
    data = gql('{ environment featureFlags { name enabled } sagas(limit: 5) { id state } wallet(fleetId: "FLEET-001") { balance transactions { type } } }')
    assert data["environment"] == ENV
    assert len(data["featureFlags"]) == 3
    assert {s["state"] for s in data["sagas"]} >= {"COMPLETED", "COMPENSATED"}
    assert {"DEBIT", "REFUND"} <= {t["type"] for t in data["wallet"]["transactions"]}
