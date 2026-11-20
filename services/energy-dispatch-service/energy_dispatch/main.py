"""energy-dispatch-service: activación física del cargador y telemetría.

Tabla aegisvolt-dispatch-<env>:
  PK=SESSION#<saga_id>  SK=META        status (STARTED|FAILED|ABORTED), station, connector, power_kw
  PK=SESSION#<saga_id>  SK=TEL#<ts>    kwh, power_kw, at
  PK=IDEM#<clave>       SK=IDEM        resultado guardado
"""

import logging
import os
import random
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from aegis_common import aws, config, flags
from aegis_common.idempotency import BusinessConditionFailed, execute_idempotent
from aegis_common.logs import log_event
from aegis_common.web import DomainError, create_app

app = create_app("energy-dispatch-service")
logger = logging.getLogger("energy-dispatch")


def table() -> str:
    return config.table_name("dispatch")


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


class SessionIn(BaseModel):
    saga_id: str
    station_id: str
    connector_id: str
    power_kw: float = Field(gt=0)
    kwh: float = Field(gt=0)


def charger_fault() -> bool:
    """Falla física del cargador: flag de inyección de fallos o tasa de fallo simulada."""
    return flags.get_flag(flags.HARDWARE_FAULT) or random.random() < float(os.getenv("CHARGER_FAILURE_RATE", "0"))


@app.post("/sessions")
def start_session(body: SessionIn):
    """Paso 3 de la SAGA: inicia el flujo eléctrico (idempotente)."""
    pk = f"SESSION#{body.saga_id}"
    now = datetime.now(UTC)
    meta = {"PK": pk, "SK": "META", "station_id": body.station_id, "connector_id": body.connector_id, "power_kw": body.power_kw, "at": iso(now)}

    if charger_fault():
        aws.dynamodb().put_item(TableName=table(), Item=aws.to_item({**meta, "status": "FAILED", "error": "CHARGER_HARDWARE_FAULT"}))
        log_event(logger, "CHARGER_HARDWARE_FAULT", logging.WARNING, saga_id=body.saga_id, connector_id=body.connector_id)
        raise DomainError("CHARGER_HARDWARE_FAULT", "El cargador reportó un error físico")

    # Telemetría simulada de los primeros minutos de carga (rampa de potencia).
    telemetry = []
    for minute, ratio in ((1, 0.4), (2, 0.8), (3, 1.0)):
        power = round(body.power_kw * ratio, 1)
        telemetry.append(
            {
                "PK": pk,
                "SK": f"TEL#{iso(now + timedelta(minutes=minute))}",
                "kwh": round(power / 60 * minute, 3),
                "power_kw": power,
                "at": iso(now + timedelta(minutes=minute)),
            }
        )

    result = {"saga_id": body.saga_id, "session_id": body.saga_id, "status": "STARTED"}
    ops = [{"Put": {"TableName": table(), "Item": aws.to_item({**meta, "status": "STARTED", "kwh_target": body.kwh})}}]
    ops += [{"Put": {"TableName": table(), "Item": aws.to_item(t)}} for t in telemetry]
    try:
        res, replayed = execute_idempotent(table(), f"{body.saga_id}:dispatch", ops, result)
    except BusinessConditionFailed:
        raise DomainError("SESSION_CONFLICT") from None
    log_event(logger, "IDEMPOTENT_REPLAY" if replayed else "CHARGING_STARTED", saga_id=body.saga_id, power_kw=body.power_kw)
    return {**res, "replayed": replayed}


@app.post("/sessions/{saga_id}/abort")
def abort_session(saga_id: str):
    """Compensación del paso 3 (por completitud): marca la sesión ABORTED si existe."""
    try:
        aws.dynamodb().update_item(
            TableName=table(),
            Key={"PK": {"S": f"SESSION#{saga_id}"}, "SK": {"S": "META"}},
            UpdateExpression="SET #s = :aborted",
            ConditionExpression="attribute_exists(PK) AND #s = :started",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=aws.values({":aborted": "ABORTED", ":started": "STARTED"}),
        )
    except aws.dynamodb().exceptions.ConditionalCheckFailedException:
        return {"saga_id": saga_id, "status": "NOT_STARTED"}
    log_event(logger, "CHARGING_ABORTED", saga_id=saga_id)
    return {"saga_id": saga_id, "status": "ABORTED"}


@app.get("/sessions/{saga_id}/telemetry")
def telemetry(saga_id: str):
    resp = aws.dynamodb().query(
        TableName=table(),
        KeyConditionExpression="PK = :pk AND begins_with(SK, :tel)",
        ExpressionAttributeValues=aws.values({":pk": f"SESSION#{saga_id}", ":tel": "TEL#"}),
    )
    return [{"session_id": saga_id, "kwh": i["kwh"], "power_kw": i["power_kw"], "at": i["at"]} for i in (aws.from_item(x) for x in resp.get("Items", []))]
