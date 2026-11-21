"""Reglas de consistencia de las SAGAs (código puro, sin Prefect ni AWS: se prueba en tests/unit).

Cruza el estado guardado por el orquestador (aegisvolt-sagas-<env>) con lo que
realmente quedó en las tablas de cada servicio:

  COMPLETED    -> debe existir el DEBIT en billing y la sesión STARTED en dispatch.
  COMPENSATED  -> si hubo DEBIT debe existir su REFUND; el conector no puede seguir
                  retenido por la SAGA; la sesión no puede quedar STARTED.
  FAILED       -> no puede haber DEBIT ni conector retenido.
  COMPENSATION_FAILED -> siempre inconsistente (requiere intervención).
  STARTED/RESERVED/CHARGED/COMPENSATING con más de N minutos -> HUÉRFANA.
"""

from datetime import UTC, datetime, timedelta

IN_FLIGHT = {"STARTED", "RESERVED", "CHARGED", "COMPENSATING"}
CATEGORIES = ["COMPLETED_OK", "COMPENSATED_OK", "FAILED_OK", "IN_PROGRESS", "ORPHAN", "INCONSISTENT"]


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def classify(saga: dict, debit: bool, refund: bool, connector_holder: str | None, session_status: str | None, now: datetime, orphan_minutes: int = 5):
    """Devuelve (categoría, [problemas])."""
    sid, state = saga["id"], saga["state"]
    holds_connector = connector_holder == sid
    issues: list[str] = []

    if state in IN_FLIGHT:
        age = now - parse_ts(saga.get("updated_at") or saga["created_at"])
        if age > timedelta(minutes=orphan_minutes):
            return "ORPHAN", [f"en {state} desde hace {int(age.total_seconds() // 60)} min"]
        return "IN_PROGRESS", []

    if state == "COMPLETED":
        if not debit:
            issues.append("COMPLETED sin DEBIT en billing")
        if session_status != "STARTED":
            issues.append(f"COMPLETED con sesión de carga {session_status or 'inexistente'}")
        return ("INCONSISTENT", issues) if issues else ("COMPLETED_OK", [])

    if state == "COMPENSATED":
        if debit and not refund:
            issues.append("cobro sin REFUND")
        if holds_connector:
            issues.append("conector sigue retenido por la SAGA")
        if session_status == "STARTED":
            issues.append("sesión de carga sigue STARTED")
        return ("INCONSISTENT", issues) if issues else ("COMPENSATED_OK", [])

    if state == "FAILED":
        if debit:
            issues.append("FAILED con DEBIT")
        if holds_connector:
            issues.append("FAILED con conector retenido")
        return ("INCONSISTENT", issues) if issues else ("FAILED_OK", [])

    if state == "COMPENSATION_FAILED":
        return "INCONSISTENT", ["compensación agotó reintentos"]

    return "INCONSISTENT", [f"estado desconocido {state}"]


def audit(env: str, data: dict, now: datetime | None = None, orphan_minutes: int = 5) -> dict:
    """data = {"sagas": [...], "debits": set(ids), "refunds": set(ids),
    "connectors": {(station, connector): saga_id|None}, "sessions": {saga_id: status}}"""
    now = now or datetime.now(UTC)
    counts = dict.fromkeys(CATEGORIES, 0)
    states: dict[str, int] = {}
    findings, traces = [], []
    for saga in data["sagas"]:
        states[saga["state"]] = states.get(saga["state"], 0) + 1
        category, issues = classify(
            saga,
            debit=saga["id"] in data["debits"],
            refund=saga["id"] in data["refunds"],
            connector_holder=data["connectors"].get((saga["station_id"], saga["connector_id"])),
            session_status=data["sessions"].get(saga["id"]),
            now=now,
            orphan_minutes=orphan_minutes,
        )
        counts[category] += 1
        if issues:
            findings.append({"env": env, "saga_id": saga["id"], "state": saga["state"], "category": category, "issues": "; ".join(issues)})
        if saga["state"] in {"COMPENSATED", "FAILED", "COMPENSATION_FAILED"}:
            traces.append({"saga_id": saga["id"], "correlation_id": saga["correlation_id"], "state": saga["state"], "error": saga.get("error") or ""})
    return {"env": env, "total": len(data["sagas"]), "states": states, "counts": counts, "findings": findings, "traces": traces}


def logs_insights_query(correlation_id: str) -> str:
    return f'fields ts, service, event, level, message | filter correlation_id = "{correlation_id}" | sort ts asc'
