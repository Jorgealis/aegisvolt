"""Servicios FastAPI reales contra DynamoDB Local: condiciones e idempotencia."""

import uuid

import pytest
from fastapi.testclient import TestClient

from .conftest import get_item, set_flag


@pytest.fixture
def billing():
    from billing_wallet.main import app

    return TestClient(app)


@pytest.fixture
def reservations():
    from station_reservation.main import app

    return TestClient(app)


def balance(fleet="FLEET-001"):
    return get_item("billing", f"FLEET#{fleet}", "WALLET")["balance"]


def sid():
    return str(uuid.uuid4())


# --- billing-wallet -------------------------------------------------------
def test_charge_is_idempotent(billing):
    s = sid()
    first = billing.post("/charges", json={"saga_id": s, "fleet_id": "FLEET-001", "kwh": 10}).json()
    after_first = balance()
    second = billing.post("/charges", json={"saga_id": s, "fleet_id": "FLEET-001", "kwh": 10}).json()
    assert not first["replayed"] and second["replayed"]
    assert balance() == after_first == 500 - first["amount"]


def test_insufficient_funds_writes_nothing(billing):
    s = sid()
    r = billing.post("/charges", json={"saga_id": s, "fleet_id": "FLEET-002", "kwh": 100})
    assert r.status_code == 409 and r.json()["error"] == "INSUFFICIENT_FUNDS"
    assert balance("FLEET-002") == 5
    assert get_item("billing", "FLEET#FLEET-002", f"TX#{s}#DEBIT") is None


def test_refund_twice_only_refunds_once(billing):
    """Pregunta de sustentación: una compensación procesada dos veces no duplica el efecto."""
    s = sid()
    charged = billing.post("/charges", json={"saga_id": s, "fleet_id": "FLEET-001", "kwh": 20}).json()
    assert balance() == 500 - charged["amount"]

    r1 = billing.post(f"/charges/{s}/refund", json={"fleet_id": "FLEET-001"}).json()
    r2 = billing.post(f"/charges/{s}/refund", json={"fleet_id": "FLEET-001"}).json()
    assert r1["status"] == "REFUNDED" and not r1["replayed"]
    assert r2["replayed"] and r2["amount"] == r1["amount"]
    assert balance() == 500  # el reembolso se aplicó una sola vez


def test_refund_without_debit_does_nothing(billing):
    r = billing.post(f"/charges/{sid()}/refund", json={"fleet_id": "FLEET-001"}).json()
    assert r["status"] == "NOTHING_TO_REFUND"
    assert balance() == 500


# --- station-reservation --------------------------------------------------
def test_connector_cannot_be_reserved_twice(reservations):
    body = {"station_id": "BOG-01", "connector_id": "C1"}
    assert reservations.post("/reservations", json={"saga_id": sid(), **body}).status_code == 200
    r = reservations.post("/reservations", json={"saga_id": sid(), **body})
    assert r.status_code == 409 and r.json()["error"] == "CONNECTOR_NOT_AVAILABLE"


def test_release_is_idempotent_and_saga_scoped(reservations):
    s, body = sid(), {"station_id": "BOG-01", "connector_id": "C2"}
    reservations.post("/reservations", json={"saga_id": s, **body})
    # otra SAGA no puede liberar un conector que no es suyo
    assert reservations.post(f"/reservations/{sid()}/release", json=body).json()["already_released"]
    assert get_item("reservations", "STATION#BOG-01", "CONNECTOR#C2")["status"] == "RESERVED"

    assert not reservations.post(f"/reservations/{s}/release", json=body).json()["already_released"]
    assert reservations.post(f"/reservations/{s}/release", json=body).json()["already_released"]
    assert get_item("reservations", "STATION#BOG-01", "CONNECTOR#C2")["status"] == "AVAILABLE"


def test_fast_charge_requires_flag(reservations):
    set_flag("ENABLE_FAST_CHARGE_BOOST", False)
    r = reservations.post("/reservations", json={"saga_id": sid(), "station_id": "BOG-01", "connector_id": "C3"})
    assert r.status_code == 409 and r.json()["error"] == "FAST_CHARGE_DISABLED"
