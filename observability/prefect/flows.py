"""Flows de observabilidad de AegisVolt (Prefect 3 + Dask).

  environment_health_flow       cada 5 min: salud de dev/test/prod
  saga_consistency_audit_flow   cada 10 min: auditoría de SAGAs en DynamoDB

Las tasks de cada ambiente corren EN PARALELO sobre un clúster Dask local
(DaskTaskRunner). Los resultados se publican como artefactos (tablas y
markdown) en el dashboard de Prefect.

Uso:
  prefect server start                                   # dashboard en http://127.0.0.1:4200
  python observability/prefect/flows.py run              # ejecuta ambos flows una vez
  python observability/prefect/flows.py serve            # deja ambos flows programados
"""

import sys
from datetime import UTC, datetime
from decimal import Decimal

import boto3
import httpx
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
from prefect import flow, get_run_logger, serve, task
from prefect.artifacts import create_markdown_artifact, create_table_artifact
from prefect_dask import DaskTaskRunner

from audit_logic import CATEGORIES, audit, logs_insights_query

REGION = "us-east-1"
ENVS = ["dev", "test", "prod"]
TABLES = ["reservations", "billing", "dispatch", "sagas", "flags"]

# Clúster Dask local con hilos: un worker por ambiente en paralelo, sin coste.
dask_runner = DaskTaskRunner(cluster_kwargs={"n_workers": 1, "threads_per_worker": len(ENVS), "processes": False})

_deser = TypeDeserializer()


def _plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _scan(ddb, table: str) -> list[dict]:
    items, kwargs = [], {"TableName": table}
    while True:
        resp = ddb.scan(**kwargs)
        items += [{k: _plain(_deser.deserialize(v)) for k, v in i.items()} for i in resp.get("Items", [])]
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


# ---------------------------------------------------------------------------
# 1) Salud de los ambientes
# ---------------------------------------------------------------------------
@task(retries=2, retry_delay_seconds=5, task_run_name="health-{env}")
def check_environment(env: str) -> dict:
    log = get_run_logger()
    ddb = boto3.client("dynamodb", region_name=REGION)
    tables_ok = 0
    for t in TABLES:
        try:
            if ddb.describe_table(TableName=f"aegisvolt-{t}-{env}")["Table"]["TableStatus"] == "ACTIVE":
                tables_ok += 1
        except ClientError:
            pass

    # API: la REST API aegisvolt-<env>-api solo existe con enable_platform = true.
    api_status, latency = "OFF", None
    apis = boto3.client("apigateway", region_name=REGION).get_rest_apis(limit=100)["items"]
    api = next((a for a in apis if a["name"] == f"aegisvolt-{env}-api"), None)
    if api:
        url = f"https://{api['id']}.execute-api.{REGION}.amazonaws.com/{env}/health"
        try:
            r = httpx.get(url, timeout=5)
            api_status, latency = ("UP" if r.status_code == 200 else f"HTTP {r.status_code}"), round(r.elapsed.total_seconds() * 1000)
        except httpx.HTTPError as exc:
            api_status = f"DOWN ({type(exc).__name__})"

    try:
        eks = boto3.client("eks", region_name=REGION).describe_cluster(name=f"aegisvolt-{env}")["cluster"]["status"]
    except ClientError:
        eks = "OFF"

    if tables_ok == 0:
        status = "NOT_DEPLOYED"
    elif tables_ok < len(TABLES) or api_status not in ("OFF", "UP"):
        status = "DOWN"
    else:
        status = "HEALTHY" if api_status == "UP" else "DATA_ONLY"  # DATA_ONLY: plataforma apagada (sin costo)
    log.info("%s: %s (tablas %d/%d, API %s, EKS %s)", env, status, tables_ok, len(TABLES), api_status, eks)
    return {"env": env, "status": status, "tables": f"{tables_ok}/{len(TABLES)}", "api": api_status, "latency_ms": latency, "eks": eks}


@flow(name="environment-health", task_runner=dask_runner, log_prints=True)
def environment_health_flow(envs: list[str] = ENVS) -> list[dict]:
    futures = [check_environment.with_options(tags=[f"env:{e}"]).submit(e) for e in envs]
    rows = [f.result() for f in futures]
    create_table_artifact(
        key="environment-health",
        table=rows,
        description=f"Salud de los ambientes AegisVolt — {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
    )
    down = [r["env"] for r in rows if r["status"] == "DOWN"]
    if "prod" in down:
        raise RuntimeError(f"prod está caído: {rows}")
    if down:
        get_run_logger().warning("ambientes degradados: %s", down)
    return rows


# ---------------------------------------------------------------------------
# 2) Auditoría de consistencia SAGA
# ---------------------------------------------------------------------------
@task(retries=2, retry_delay_seconds=5, task_run_name="load-{env}")
def load_environment(env: str) -> dict | None:
    ddb = boto3.client("dynamodb", region_name=REGION)
    try:
        sagas = [s for s in _scan(ddb, f"aegisvolt-sagas-{env}") if s.get("SK") == "META"]
        billing = _scan(ddb, f"aegisvolt-billing-{env}")
        reservations = _scan(ddb, f"aegisvolt-reservations-{env}")
        dispatch = _scan(ddb, f"aegisvolt-dispatch-{env}")
    except ddb.exceptions.ResourceNotFoundException:
        return None  # ambiente aún no desplegado
    return {
        "sagas": sagas,
        "debits": {b["SK"].split("#")[1] for b in billing if b["SK"].endswith("#DEBIT")},
        "refunds": {b["SK"].split("#")[1] for b in billing if b["SK"].endswith("#REFUND")},
        "connectors": {(r["PK"].split("#", 1)[1], r["SK"].split("#", 1)[1]): r.get("saga_id") for r in reservations if r["SK"].startswith("CONNECTOR#")},
        "sessions": {d["PK"].split("#", 1)[1]: d.get("status") for d in dispatch if d.get("SK") == "META"},
    }


@task(task_run_name="audit-{env}")
def audit_environment(env: str, data: dict | None, orphan_minutes: int) -> dict | None:
    if data is None:
        return None
    result = audit(env, data, orphan_minutes=orphan_minutes)
    get_run_logger().info("%s: %d SAGAs %s", env, result["total"], result["counts"])
    return result


@flow(name="saga-consistency-audit", task_runner=dask_runner, log_prints=True)
def saga_consistency_audit_flow(envs: list[str] = ENVS, orphan_minutes: int = 5) -> list[dict]:
    loaded = {e: load_environment.with_options(tags=[f"env:{e}"]).submit(e) for e in envs}
    audited = [audit_environment.with_options(tags=[f"env:{e}"]).submit(e, loaded[e], orphan_minutes) for e in envs]
    results = [r for r in (f.result() for f in audited) if r]

    summary = [
        {
            "env": r["env"],
            "total": r["total"],
            "COMPLETED": r["states"].get("COMPLETED", 0),
            "COMPENSATED": r["states"].get("COMPENSATED", 0),
            "FAILED": r["states"].get("FAILED", 0),
            "huerfanas": r["counts"]["ORPHAN"],
            "inconsistentes": r["counts"]["INCONSISTENT"],
            "consistentes": sum(r["counts"][c] for c in CATEGORIES if c.endswith("_OK")),
        }
        for r in results
    ]
    stamp = f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC"
    create_table_artifact(key="saga-audit-summary", table=summary, description=f"Auditoría SAGA por ambiente — {stamp}")

    findings = [f for r in results for f in r["findings"]]
    create_table_artifact(
        key="saga-audit-findings",
        table=findings or [{"resultado": "sin huérfanas ni inconsistencias"}],
        description="SAGAs huérfanas o inconsistentes",
    )

    lines = [f"# Rastreo de SAGAs fallidas/compensadas ({stamp})", ""]
    for r in results:
        for t in r["traces"][:10]:
            lines += [
                f"### {r['env']} · `{t['saga_id']}` · {t['state']} ({t['error']})",
                f"CloudWatch Logs Insights sobre los grupos `/aegisvolt/{r['env']}/*`:",
                f"```\n{logs_insights_query(t['correlation_id'])}\n```",
                "",
            ]
    if len(lines) == 2:
        lines.append("Sin SAGAs fallidas o compensadas.")
    create_markdown_artifact(key="saga-correlation-traces", markdown="\n".join(lines), description="correlation_id para rastrear en CloudWatch")
    return summary


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "serve":
        serve(
            environment_health_flow.to_deployment(name="cada-5-min", interval=300, tags=["aegisvolt"]),
            saga_consistency_audit_flow.to_deployment(name="cada-10-min", interval=600, tags=["aegisvolt"]),
        )
    else:
        print(environment_health_flow())
        print(saga_consistency_audit_flow())
