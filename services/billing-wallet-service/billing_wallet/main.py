"""billing-wallet-service: verificación de fondos, cobro y reembolso.

Tabla aegisvolt-billing-<env>:
  PK=FLEET#<id>   SK=WALLET                    balance
  PK=FLEET#<id>   SK=TX#<saga_id>#DEBIT        amount, at
  PK=FLEET#<id>   SK=TX#<saga_id>#REFUND       amount, at
  PK=FLEET#<id>   SK=TX#<uuid>#TOPUP           amount, at
  PK=IDEM#<clave> SK=IDEM                      resultado guardado
"""

import logging
import time
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from aegis_common import aws, config, flags
from aegis_common.idempotency import BusinessConditionFailed, execute_idempotent
from aegis_common.logs import log_event
from aegis_common.web import DomainError, create_app

from . import pricing

app = create_app("billing-wallet-service")
logger = logging.getLogger("billing-wallet")


def table() -> str:
    return config.table_name("billing")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def wallet_key(fleet_id: str) -> dict:
    return {"PK": {"S": f"FLEET#{fleet_id}"}, "SK": {"S": "WALLET"}}


def tx_key(fleet_id: str, saga_id: str, kind: str) -> dict:
    return {"PK": {"S": f"FLEET#{fleet_id}"}, "SK": {"S": f"TX#{saga_id}#{kind}"}}


class ChargeIn(BaseModel):
    saga_id: str
    fleet_id: str
    kwh: float = Field(gt=0)


class RefundIn(BaseModel):
    fleet_id: str


class TopUpIn(BaseModel):
    amount: float = Field(gt=0)


def current_tariff() -> dict:
    return pricing.tariff(flags.get_flag(flags.SURGE_PRICING))


@app.get("/tariff")
def get_tariff():
    return current_tariff()


@app.get("/wallets/{fleet_id}")
def get_wallet(fleet_id: str):
    resp = aws.dynamodb().query(
        TableName=table(),
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues=aws.values({":pk": f"FLEET#{fleet_id}"}),
        ConsistentRead=True,
    )
    items = [aws.from_item(i) for i in resp.get("Items", [])]
    wallet = next((i for i in items if i["SK"] == "WALLET"), None)
    if not wallet:
        raise DomainError("WALLET_NOT_FOUND", status=404)
    txs = [{"saga_id": i["SK"].split("#")[1], "type": i["type"], "amount": i["amount"], "at": i.get("at", "")} for i in items if i["SK"].startswith("TX#")]
    txs.sort(key=lambda t: t["at"], reverse=True)
    return {"fleet_id": fleet_id, "balance": wallet["balance"], "transactions": txs}


@app.post("/charges")
def charge(body: ChargeIn):
    """Paso 2 de la SAGA: descuenta el saldo estimado si alcanza (idempotente)."""
    t = current_tariff()
    amount = pricing.amount_for(body.kwh, t["effective_per_kwh"])
    result = {"saga_id": body.saga_id, "fleet_id": body.fleet_id, "amount": float(amount), "surge_active": t["surge_active"], "status": "CHARGED"}
    ops = [
        {
            "Update": {
                "TableName": table(),
                "Key": wallet_key(body.fleet_id),
                "UpdateExpression": "SET balance = balance - :amt",
                "ConditionExpression": "attribute_exists(PK) AND balance >= :amt",
                "ExpressionAttributeValues": aws.values({":amt": amount}),
            }
        },
        {
            "Put": {
                "TableName": table(),
                "Item": aws.to_item(
                    {
                        "PK": f"FLEET#{body.fleet_id}",
                        "SK": f"TX#{body.saga_id}#DEBIT",
                        "type": "DEBIT",
                        "amount": amount,
                        "saga_id": body.saga_id,
                        "at": now_iso(),
                    }
                ),
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
    ]
    try:
        res, replayed = execute_idempotent(table(), f"{body.saga_id}:charge", ops, result)
    except BusinessConditionFailed:
        wallet = aws.dynamodb().get_item(TableName=table(), Key=wallet_key(body.fleet_id), ConsistentRead=True).get("Item")
        if not wallet:
            raise DomainError("WALLET_NOT_FOUND", status=404) from None
        log_event(logger, "INSUFFICIENT_FUNDS", logging.WARNING, saga_id=body.saga_id, amount=float(amount))
        raise DomainError("INSUFFICIENT_FUNDS", f"Saldo insuficiente para cobrar {amount}") from None
    log_event(logger, "IDEMPOTENT_REPLAY" if replayed else "CHARGE_APPLIED", saga_id=body.saga_id, amount=res["amount"])
    return {**res, "replayed": replayed}


@app.post("/charges/{saga_id}/refund")
def refund(saga_id: str, body: RefundIn):
    """Compensación del paso 2. Doble garantía de no duplicar el reembolso:
    1) clave de idempotencia <saga_id>:refund en la misma transacción, y
    2) el TX#<saga>#REFUND se crea con attribute_not_exists (solo puede existir uno).
    """
    debit = aws.from_item(aws.dynamodb().get_item(TableName=table(), Key=tx_key(body.fleet_id, saga_id, "DEBIT"), ConsistentRead=True).get("Item"))
    if not debit:
        log_event(logger, "NOTHING_TO_REFUND", saga_id=saga_id)
        return {"saga_id": saga_id, "fleet_id": body.fleet_id, "amount": 0, "status": "NOTHING_TO_REFUND", "replayed": False}

    amount = debit["amount"]
    result = {"saga_id": saga_id, "fleet_id": body.fleet_id, "amount": amount, "status": "REFUNDED"}
    ops = [
        {
            "Put": {
                "TableName": table(),
                "Item": aws.to_item(
                    {"PK": f"FLEET#{body.fleet_id}", "SK": f"TX#{saga_id}#REFUND", "type": "REFUND", "amount": amount, "saga_id": saga_id, "at": now_iso()}
                ),
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
        {
            "Update": {
                "TableName": table(),
                "Key": wallet_key(body.fleet_id),
                "UpdateExpression": "SET balance = balance + :amt",
                "ExpressionAttributeValues": aws.values({":amt": amount}),
            }
        },
    ]
    try:
        res, replayed = execute_idempotent(table(), f"{saga_id}:refund", ops, result)
    except BusinessConditionFailed:
        # El REFUND ya existe aunque la clave de idempotencia expiró (TTL): no se repite.
        log_event(logger, "REFUND_ALREADY_APPLIED", saga_id=saga_id)
        return {**result, "status": "ALREADY_REFUNDED", "replayed": True}
    log_event(logger, "IDEMPOTENT_REPLAY" if replayed else "REFUND_APPLIED", saga_id=saga_id, amount=amount)
    return {**res, "replayed": replayed}


@app.post("/wallets/{fleet_id}/topup")
def top_up(fleet_id: str, body: TopUpIn):
    amount = round(body.amount, 2)
    tx_id = str(uuid.uuid4())
    aws.dynamodb().transact_write_items(
        TransactItems=[
            {
                "Update": {
                    "TableName": table(),
                    "Key": wallet_key(fleet_id),
                    "UpdateExpression": "SET balance = if_not_exists(balance, :zero) + :amt",
                    "ExpressionAttributeValues": aws.values({":amt": amount, ":zero": 0}),
                }
            },
            {
                "Put": {
                    "TableName": table(),
                    "Item": aws.to_item(
                        {"PK": f"FLEET#{fleet_id}", "SK": f"TX#{tx_id}#TOPUP", "type": "TOPUP", "amount": amount, "at": now_iso(), "created": int(time.time())}
                    ),
                }
            },
        ]
    )
    log_event(logger, "WALLET_TOPUP", fleet_id=fleet_id, amount=amount)
    return get_wallet(fleet_id)
