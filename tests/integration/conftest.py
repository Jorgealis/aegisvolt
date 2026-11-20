"""Integración contra DynamoDB Local (service container en CI, docker compose en local).

Requiere DYNAMODB_ENDPOINT (p. ej. http://localhost:8001). Cada test parte de
datos recién sembrados con scripts/seed.py.
"""

import os
import runpy
import sys
import urllib.request
from pathlib import Path

import pytest

ENDPOINT = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8001")
ENV = "it"
SEED = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"


def _reachable(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=2)
    except urllib.error.HTTPError:
        return True  # DynamoDB Local responde 400 a un GET: está vivo
    except OSError:
        return False
    return True


@pytest.fixture(scope="session", autouse=True)
def dynamodb_local():
    if not _reachable(ENDPOINT):
        if os.getenv("CI"):
            pytest.fail(f"DynamoDB Local no disponible en {ENDPOINT}")
        pytest.skip(f"DynamoDB Local no disponible en {ENDPOINT}")
    os.environ.update(
        ENV=ENV,
        DYNAMODB_ENDPOINT=ENDPOINT,
        AWS_ACCESS_KEY_ID="local",
        AWS_SECRET_ACCESS_KEY="local",
        AWS_REGION="us-east-1",
        FLAGS_CACHE_SECONDS="0",
    )
    from aegis_common import aws

    aws.dynamodb.cache_clear()
    seed(create_tables=True)


def seed(create_tables: bool = False) -> None:
    argv = [str(SEED), "--env", ENV, "--endpoint", ENDPOINT] + (["--create-tables"] if create_tables else [])
    old, sys.argv = sys.argv, argv
    try:
        runpy.run_path(str(SEED), run_name="__main__")
    finally:
        sys.argv = old


@pytest.fixture(autouse=True)
def fresh_data(dynamodb_local):
    seed()
    set_flag("SIMULATE_CHARGER_HARDWARE_FAULT", False)
    set_flag("ENABLE_FAST_CHARGE_BOOST", True)
    yield


def set_flag(name: str, enabled: bool) -> None:
    from aegis_common import aws

    aws.dynamodb().put_item(
        TableName=f"aegisvolt-flags-{ENV}",
        Item={"PK": {"S": f"FLAG#{name}"}, "name": {"S": name}, "enabled": {"BOOL": enabled}},
    )


def get_item(table: str, pk: str, sk: str) -> dict | None:
    from aegis_common import aws

    return aws.from_item(aws.dynamodb().get_item(TableName=f"aegisvolt-{table}-{ENV}", Key={"PK": {"S": pk}, "SK": {"S": sk}}).get("Item"))
