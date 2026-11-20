"""Idempotencia con TransactWriteItems.

Cada operación de la SAGA llega con una clave "<saga_id>:<accion>". En UNA sola
transacción atómica se escribe:
  (a) el registro PK=IDEM#<clave> con attribute_not_exists(PK), y
  (b) el cambio de negocio (descontar, reembolsar, reservar...).
Si la clave ya existía, la transacción completa se cancela (no se repite el
efecto) y se devuelve el resultado guardado la primera vez.
"""

import json
import time

from botocore.exceptions import ClientError

from . import aws

IDEMPOTENCY_TTL_SECONDS = 24 * 3600


class BusinessConditionFailed(Exception):
    """Falló una condición de negocio (p. ej. saldo insuficiente). Nada se escribió."""

    def __init__(self, reasons: list[dict]):
        super().__init__("condición de negocio no cumplida")
        self.reasons = reasons


def _idem_key(key: str) -> dict:
    return {"PK": {"S": f"IDEM#{key}"}, "SK": {"S": "IDEM"}}


def execute_idempotent(table: str, key: str, business_ops: list[dict], result: dict) -> tuple[dict, bool]:
    """Ejecuta business_ops una sola vez por clave. Devuelve (resultado, replayed)."""
    idem_put = {
        "Put": {
            "TableName": table,
            "Item": aws.to_item(
                {
                    "PK": f"IDEM#{key}",
                    "SK": "IDEM",
                    "result": json.dumps(result),
                    "created_at": int(time.time()),
                    "expires_at": int(time.time()) + IDEMPOTENCY_TTL_SECONDS,  # TTL de DynamoDB
                }
            ),
            "ConditionExpression": "attribute_not_exists(PK)",
        }
    }
    client = aws.dynamodb()
    try:
        client.transact_write_items(TransactItems=[idem_put, *business_ops])
        return result, False
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        stored = client.get_item(TableName=table, Key=_idem_key(key), ConsistentRead=True).get("Item")
        if stored:
            return json.loads(stored["result"]["S"]), True
        raise BusinessConditionFailed(exc.response.get("CancellationReasons", [])) from exc
