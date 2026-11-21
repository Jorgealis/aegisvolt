"""Siembra (o reinicia) los datos de demo de un ambiente.

  # Local (DynamoDB Local de docker compose): crea tablas + flags + datos
  python scripts/seed.py --env local --endpoint http://localhost:8001 --create-tables

  # AWS (las tablas y flags ya las creó Terraform): solo datos de negocio
  python scripts/seed.py --env dev

Reejecutarlo deja todos los conectores en AVAILABLE y los saldos iniciales.
"""

import argparse
import os

import boto3

STATIONS = [
    {"id": "BOG-01", "name": "Electrolinera Calle 80", "city": "Bogota", "connectors": [("C1", 50), ("C2", 150), ("C3", 350)]},
    {"id": "MDE-01", "name": "Hub Logistico El Poblado", "city": "Medellin", "connectors": [("C1", 150), ("C2", 350)]},
    {"id": "LIM-01", "name": "Terminal Callao", "city": "Lima", "connectors": [("C1", 50), ("C2", 150)]},
]
WALLETS = {"FLEET-001": 500, "FLEET-002": 5}  # FLEET-002: saldo bajo para la demo de fondos insuficientes

# Mismo esquema que infra/modules/dynamodb (solo se usa con DynamoDB Local).
TABLES = {"reservations": True, "billing": True, "dispatch": True, "sagas": True, "flags": False}
LOCAL_FLAGS = {"ENABLE_DYNAMIC_SURGE_PRICING": True, "ENABLE_FAST_CHARGE_BOOST": True, "SIMULATE_CHARGER_HARDWARE_FAULT": False}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env", required=True)
    p.add_argument("--endpoint", default=os.getenv("DYNAMODB_ENDPOINT"))
    p.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    p.add_argument("--create-tables", action="store_true", help="solo para DynamoDB Local")
    a = p.parse_args()

    if a.create_tables and not a.endpoint:
        raise SystemExit("--create-tables solo con --endpoint (DynamoDB Local); en AWS las tablas las crea Terraform")

    kwargs = {"region_name": a.region}
    if a.endpoint:
        kwargs.update(endpoint_url=a.endpoint, aws_access_key_id="local", aws_secret_access_key="local")
    ddb = boto3.client("dynamodb", **kwargs)
    t = lambda name: f"aegisvolt-{name}-{a.env}"  # noqa: E731

    if a.create_tables:
        existing = set(ddb.list_tables()["TableNames"])
        for name, has_sk in TABLES.items():
            if t(name) in existing:
                continue
            keys = [{"AttributeName": "PK", "KeyType": "HASH"}] + ([{"AttributeName": "SK", "KeyType": "RANGE"}] if has_sk else [])
            attrs = [{"AttributeName": "PK", "AttributeType": "S"}] + ([{"AttributeName": "SK", "AttributeType": "S"}] if has_sk else [])
            ddb.create_table(TableName=t(name), KeySchema=keys, AttributeDefinitions=attrs, BillingMode="PAY_PER_REQUEST")
            ddb.get_waiter("table_exists").wait(TableName=t(name))
            print(f"tabla creada: {t(name)}")
        for flag, enabled in LOCAL_FLAGS.items():
            ddb.put_item(
                TableName=t("flags"), Item={"PK": {"S": f"FLAG#{flag}"}, "name": {"S": flag}, "enabled": {"BOOL": enabled}, "updated_by": {"S": "seed"}}
            )

    for st in STATIONS:
        ddb.put_item(
            TableName=t("reservations"), Item={"PK": {"S": f"STATION#{st['id']}"}, "SK": {"S": "META"}, "name": {"S": st["name"]}, "city": {"S": st["city"]}}
        )
        for cid, kw in st["connectors"]:
            ddb.put_item(
                TableName=t("reservations"),
                Item={"PK": {"S": f"STATION#{st['id']}"}, "SK": {"S": f"CONNECTOR#{cid}"}, "power_kw": {"N": str(kw)}, "status": {"S": "AVAILABLE"}},
            )
    for fleet, balance in WALLETS.items():
        ddb.put_item(TableName=t("billing"), Item={"PK": {"S": f"FLEET#{fleet}"}, "SK": {"S": "WALLET"}, "balance": {"N": str(balance)}})

    print(f"[{a.env}] {len(STATIONS)} estaciones, {sum(len(s['connectors']) for s in STATIONS)} conectores AVAILABLE, wallets {WALLETS}")


if __name__ == "__main__":
    main()
