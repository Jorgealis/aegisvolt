"""Muestra en las tablas DynamoDB REALES de un ambiente qué dejó una SAGA.

  python scripts/inspect_saga.py test --latest          # la SAGA más reciente de test
  python scripts/inspect_saga.py test <saga_id>

Para la sustentación: evidencia de la compensación en cada tabla (database-per-service):
  aegisvolt-sagas-<env>         estado y pasos del orquestador
  aegisvolt-billing-<env>       TX#<saga>#DEBIT y TX#<saga>#REFUND, saldo de la billetera
  aegisvolt-reservations-<env>  estado del conector y quién lo retiene
  aegisvolt-dispatch-<env>      sesión de carga (STARTED / FAILED / ABORTED)
"""

import argparse
import os

import boto3
from boto3.dynamodb.types import TypeDeserializer

_deser = TypeDeserializer()


def plain(item):
    return {k: _deser.deserialize(v) for k, v in (item or {}).items()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("env")
    p.add_argument("saga_id", nargs="?")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--endpoint", default=os.getenv("DYNAMODB_ENDPOINT"))
    a = p.parse_args()

    kwargs = {"region_name": os.getenv("AWS_REGION", "us-east-1")}
    if a.endpoint:
        kwargs.update(endpoint_url=a.endpoint, aws_access_key_id="local", aws_secret_access_key="local")
    ddb = boto3.client("dynamodb", **kwargs)
    t = lambda name: f"aegisvolt-{name}-{a.env}"  # noqa: E731

    if a.latest or not a.saga_id:
        sagas = [plain(i) for i in ddb.scan(TableName=t("sagas"))["Items"]]
        if not sagas:
            raise SystemExit(f"no hay SAGAs en {t('sagas')}")
        saga = max(sagas, key=lambda s: s["created_at"])
    else:
        saga = plain(ddb.get_item(TableName=t("sagas"), Key={"PK": {"S": f"SAGA#{a.saga_id}"}, "SK": {"S": "META"}}, ConsistentRead=True).get("Item"))
        if not saga:
            raise SystemExit("SAGA no encontrada")

    sid, fleet = saga["id"], saga["fleet_id"]
    print(f"\n== {t('sagas')}  SAGA#{sid}")
    print(f"   estado={saga['state']}  error={saga.get('error')}  correlation_id={saga['correlation_id']}")
    for st in saga.get("steps", []):
        print(f"   - {st['name']:<14} {st['status']:<12} {st.get('error') or ''}")

    print(f"\n== {t('billing')}  FLEET#{fleet}")
    txs = ddb.query(
        TableName=t("billing"),
        KeyConditionExpression="PK = :pk AND begins_with(SK, :tx)",
        ExpressionAttributeValues={":pk": {"S": f"FLEET#{fleet}"}, ":tx": {"S": f"TX#{sid}#"}},
        ConsistentRead=True,
    )["Items"]
    for tx in map(plain, txs):
        print(f"   {tx['SK']:<52} amount={tx['amount']}  at={tx.get('at')}")
    if not txs:
        print("   (sin DEBIT ni REFUND para esta SAGA)")
    wallet = plain(ddb.get_item(TableName=t("billing"), Key={"PK": {"S": f"FLEET#{fleet}"}, "SK": {"S": "WALLET"}}, ConsistentRead=True).get("Item"))
    print(f"   saldo actual de la billetera: {wallet.get('balance')}")

    print(f"\n== {t('reservations')}  STATION#{saga['station_id']} / CONNECTOR#{saga['connector_id']}")
    conn = plain(
        ddb.get_item(
            TableName=t("reservations"),
            Key={"PK": {"S": f"STATION#{saga['station_id']}"}, "SK": {"S": f"CONNECTOR#{saga['connector_id']}"}},
            ConsistentRead=True,
        ).get("Item")
    )
    print(f"   status={conn.get('status')}  retenido_por_saga={conn.get('saga_id') or '-'}")

    print(f"\n== {t('dispatch')}  SESSION#{sid}")
    session = plain(ddb.get_item(TableName=t("dispatch"), Key={"PK": {"S": f"SESSION#{sid}"}, "SK": {"S": "META"}}, ConsistentRead=True).get("Item"))
    print(f"   status={session.get('status', '(sin sesión)')}  error={session.get('error', '-')}\n")


if __name__ == "__main__":
    main()
