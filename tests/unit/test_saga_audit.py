"""Reglas de la auditoría de consistencia SAGA (lo que reporta Prefect)."""

from datetime import UTC, datetime, timedelta

from audit_logic import audit, classify

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def saga(state, minutes_ago=1, sid="s1"):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return {"id": sid, "correlation_id": f"c-{sid}", "state": state, "station_id": "BOG-01", "connector_id": "C1", "created_at": ts, "updated_at": ts}


def test_compensated_with_refund_and_released_connector_is_ok():
    assert classify(saga("COMPENSATED"), debit=True, refund=True, connector_holder=None, session_status="FAILED", now=NOW) == ("COMPENSATED_OK", [])


def test_compensated_without_refund_is_inconsistent():
    cat, issues = classify(saga("COMPENSATED"), debit=True, refund=False, connector_holder="s1", session_status="FAILED", now=NOW)
    assert cat == "INCONSISTENT"
    assert "cobro sin REFUND" in issues and "conector sigue retenido por la SAGA" in issues


def test_insufficient_funds_compensation_needs_no_refund():
    assert classify(saga("COMPENSATED"), debit=False, refund=False, connector_holder=None, session_status=None, now=NOW)[0] == "COMPENSATED_OK"


def test_stuck_saga_becomes_orphan_after_threshold():
    assert classify(saga("CHARGED", minutes_ago=2), False, False, "s1", None, NOW)[0] == "IN_PROGRESS"
    cat, issues = classify(saga("CHARGED", minutes_ago=12), False, False, "s1", None, NOW)
    assert cat == "ORPHAN" and "12 min" in issues[0]


def test_completed_requires_debit_and_started_session():
    assert classify(saga("COMPLETED"), True, False, "s1", "STARTED", NOW)[0] == "COMPLETED_OK"
    assert classify(saga("COMPLETED"), False, False, "s1", None, NOW)[0] == "INCONSISTENT"


def test_audit_summary_counts_and_traces():
    data = {
        "sagas": [saga("COMPLETED", sid="a"), saga("COMPENSATED", sid="b"), saga("STARTED", 30, sid="c")],
        "debits": {"a", "b"},
        "refunds": {"b"},
        "connectors": {("BOG-01", "C1"): "a"},
        "sessions": {"a": "STARTED", "b": "FAILED"},
    }
    r = audit("dev", data, now=NOW)
    assert r["total"] == 3
    assert r["counts"]["COMPLETED_OK"] == 1 and r["counts"]["COMPENSATED_OK"] == 1 and r["counts"]["ORPHAN"] == 1
    assert [t["correlation_id"] for t in r["traces"]] == ["c-b"]
    assert r["findings"][0]["saga_id"] == "c"
