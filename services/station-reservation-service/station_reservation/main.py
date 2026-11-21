"""station-reservation-service: disponibilidad y bloqueo temporal de conectores.

Tabla aegisvolt-reservations-<env>:
  PK=STATION#<id>  SK=META               name, city
  PK=STATION#<id>  SK=CONNECTOR#<id>     power_kw, status, saga_id
  PK=IDEM#<clave>  SK=IDEM               resultado guardado (idempotencia)
"""

import logging
import time

from pydantic import BaseModel

from aegis_common import aws, config, flags
from aegis_common.idempotency import BusinessConditionFailed, execute_idempotent
from aegis_common.logs import log_event
from aegis_common.web import DomainError, create_app

FAST_CHARGE_MIN_KW = 350

app = create_app("station-reservation-service")
logger = logging.getLogger("station-reservation")


def table() -> str:
    return config.table_name("reservations")


def connector_key(station_id: str, connector_id: str) -> dict:
    return {"PK": {"S": f"STATION#{station_id}"}, "SK": {"S": f"CONNECTOR#{connector_id}"}}


class ReserveIn(BaseModel):
    saga_id: str
    station_id: str
    connector_id: str


class ConnectorRef(BaseModel):
    station_id: str
    connector_id: str


@app.get("/stations")
def list_stations(city: str | None = None):
    items, kwargs = [], {"TableName": table(), "FilterExpression": "begins_with(PK, :p)", "ExpressionAttributeValues": aws.values({":p": "STATION#"})}
    while True:
        resp = aws.dynamodb().scan(**kwargs)
        items += [aws.from_item(i) for i in resp.get("Items", [])]
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    stations: dict[str, dict] = {}
    for it in items:
        sid = it["PK"].split("#", 1)[1]
        st = stations.setdefault(sid, {"id": sid, "name": sid, "city": "", "connectors": []})
        if it["SK"] == "META":
            st.update(name=it.get("name", sid), city=it.get("city", ""))
        elif it["SK"].startswith("CONNECTOR#"):
            st["connectors"].append(
                {"id": it["SK"].split("#", 1)[1], "station_id": sid, "power_kw": it["power_kw"], "status": it["status"], "saga_id": it.get("saga_id")}
            )
    result = [s for s in stations.values() if not city or s["city"].lower() == city.lower()]
    for s in result:
        s["connectors"].sort(key=lambda c: c["id"])
    return sorted(result, key=lambda s: s["id"])


@app.post("/reservations")
def reserve(body: ReserveIn):
    """Paso 1 de la SAGA: AVAILABLE -> RESERVED (condicional, idempotente)."""
    raw = aws.dynamodb().get_item(TableName=table(), Key=connector_key(body.station_id, body.connector_id), ConsistentRead=True).get("Item")
    connector = aws.from_item(raw)
    if not connector:
        raise DomainError("CONNECTOR_NOT_FOUND", status=404)
    power_kw = connector["power_kw"]
    if power_kw >= FAST_CHARGE_MIN_KW and not flags.get_flag(flags.FAST_CHARGE_BOOST):
        raise DomainError("FAST_CHARGE_DISABLED", f"Los conectores de {power_kw} kW requieren ENABLE_FAST_CHARGE_BOOST")

    result = {"saga_id": body.saga_id, "station_id": body.station_id, "connector_id": body.connector_id, "power_kw": power_kw, "status": "RESERVED"}
    op = {
        "Update": {
            "TableName": table(),
            "Key": connector_key(body.station_id, body.connector_id),
            "UpdateExpression": "SET #s = :reserved, saga_id = :sid, updated_at = :now",
            "ConditionExpression": "#s = :available",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": aws.values({":reserved": "RESERVED", ":available": "AVAILABLE", ":sid": body.saga_id, ":now": int(time.time())}),
        }
    }
    try:
        res, replayed = execute_idempotent(table(), f"{body.saga_id}:reserve", [op], result)
    except BusinessConditionFailed:
        raise DomainError("CONNECTOR_NOT_AVAILABLE", "El conector no está AVAILABLE") from None
    log_event(logger, "IDEMPOTENT_REPLAY" if replayed else "CONNECTOR_RESERVED", saga_id=body.saga_id, connector_id=body.connector_id)
    return {**res, "replayed": replayed}


@app.post("/reservations/{saga_id}/release")
def release(saga_id: str, body: ConnectorRef):
    """Compensación: RESERVED/CHARGING -> AVAILABLE solo si el conector sigue en manos de esta SAGA.

    Idempotente por diseño: si ya se liberó, la condición falla y se responde lo mismo.
    """
    try:
        aws.dynamodb().update_item(
            TableName=table(),
            Key=connector_key(body.station_id, body.connector_id),
            UpdateExpression="SET #s = :available, updated_at = :now REMOVE saga_id",
            ConditionExpression="saga_id = :sid",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=aws.values({":available": "AVAILABLE", ":sid": saga_id, ":now": int(time.time())}),
        )
    except aws.dynamodb().exceptions.ConditionalCheckFailedException:
        log_event(logger, "RELEASE_ALREADY_APPLIED", saga_id=saga_id, connector_id=body.connector_id)
        return {"saga_id": saga_id, "status": "AVAILABLE", "already_released": True}
    log_event(logger, "CONNECTOR_RELEASED", saga_id=saga_id, connector_id=body.connector_id)
    return {"saga_id": saga_id, "status": "AVAILABLE", "already_released": False}


@app.post("/reservations/{saga_id}/charging")
def mark_charging(saga_id: str, body: ConnectorRef):
    """Tras activar el cargador: RESERVED -> CHARGING (idempotente por condición)."""
    try:
        aws.dynamodb().update_item(
            TableName=table(),
            Key=connector_key(body.station_id, body.connector_id),
            UpdateExpression="SET #s = :charging, updated_at = :now",
            ConditionExpression="saga_id = :sid AND #s IN (:reserved, :charging)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=aws.values({":charging": "CHARGING", ":reserved": "RESERVED", ":sid": saga_id, ":now": int(time.time())}),
        )
    except aws.dynamodb().exceptions.ConditionalCheckFailedException:
        raise DomainError("RESERVATION_NOT_HELD", "El conector no pertenece a esta SAGA") from None
    log_event(logger, "CONNECTOR_CHARGING", saga_id=saga_id, connector_id=body.connector_id)
    return {"saga_id": saga_id, "status": "CHARGING"}
