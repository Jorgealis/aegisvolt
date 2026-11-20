"""Cambia una Feature Flag en caliente (sin redesplegar) en la tabla del ambiente.

  python scripts/flag.py dev                                         # listar
  python scripts/flag.py dev SIMULATE_CHARGER_HARDWARE_FAULT true    # activar
  python scripts/flag.py local ENABLE_DYNAMIC_SURGE_PRICING false --endpoint http://localhost:8001

Los servicios la leen con caché de 5 s: el cambio se ve en <= 5 s, y solo en
ese ambiente (cada uno tiene su tabla aegisvolt-flags-<env>).
"""

import argparse
import getpass
import os
from datetime import UTC, datetime

import boto3

VALID = {"ENABLE_DYNAMIC_SURGE_PRICING", "ENABLE_FAST_CHARGE_BOOST", "SIMULATE_CHARGER_HARDWARE_FAULT"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("env")
    p.add_argument("name", nargs="?")
    p.add_argument("value", nargs="?", choices=["true", "false"])
    p.add_argument("--endpoint", default=os.getenv("DYNAMODB_ENDPOINT"))
    p.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    a = p.parse_args()

    kwargs = {"region_name": a.region}
    if a.endpoint:
        kwargs.update(endpoint_url=a.endpoint, aws_access_key_id="local", aws_secret_access_key="local")
    ddb = boto3.client("dynamodb", **kwargs)
    table = f"aegisvolt-flags-{a.env}"

    if a.name:
        if a.name not in VALID or a.value is None:
            raise SystemExit(f"uso: flag.py <env> <{'|'.join(sorted(VALID))}> <true|false>")
        ddb.update_item(
            TableName=table,
            Key={"PK": {"S": f"FLAG#{a.name}"}},
            UpdateExpression="SET enabled = :v, #n = :n, updated_at = :t, updated_by = :u",
            ExpressionAttributeNames={"#n": "name"},
            ExpressionAttributeValues={
                ":v": {"BOOL": a.value == "true"},
                ":n": {"S": a.name},
                ":t": {"S": datetime.now(UTC).isoformat(timespec="seconds")},
                ":u": {"S": getpass.getuser()},
            },
        )
        print(f"[{a.env}] {a.name} = {a.value}")

    for item in sorted(ddb.scan(TableName=table, ConsistentRead=True)["Items"], key=lambda i: i["PK"]["S"]):
        print(f"  {item['PK']['S'].removeprefix('FLAG#'):35} {item['enabled']['BOOL']}")


if __name__ == "__main__":
    main()
