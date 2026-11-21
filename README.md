# AegisVolt

Plataforma cloud-native de gestión de carga para flotas eléctricas (Proyecto Final — Patrones Arquitectónicos Avanzados).

## Ramas y promoción

`feature/*` → PR → `dev` → PR → `test` → PR → `prod`

- `dev`, `test` y `prod` están protegidas por el ruleset [`protected-envs`](docs/rulesets/protected-envs.json): sin force push, sin push directo, sin borrado, merge solo por PR con los checks en verde.
- El job `enforce-promotion` de [`pr.yml`](.github/workflows/pr.yml) rechaza cualquier PR que salte la cadena.

## Infraestructura

| Carpeta | Qué contiene | Estado |
| --- | --- | --- |
| `infra/bootstrap/` | Bucket S3 de estados (versionado), roles OIDC para GitHub Actions, alerta de presupuesto | `s3://aegisvolt-tfstate-<cuenta>/bootstrap/` |
| `infra/` | VPC, VPCE, API Gateway, EKS, DynamoDB, CloudWatch por ambiente | `s3://aegisvolt-tfstate-<cuenta>/env:/<workspace>/` |

### Control de costos: `enable_platform`

| Siempre creado (≈ USD 0) | Solo con `enable_platform = true` (≈ USD 0,27/h por ambiente) |
| --- | --- |
| VPC, subredes públicas/privadas, route tables, IGW | NAT Gateway + EIP |
| Gateway VPCE S3 y DynamoDB (con política por ambiente) | Interface VPCE de CloudWatch Logs |
| Tablas DynamoDB on-demand, flags, log groups | EKS + node group (2 × t3.medium) |
| | NLB interno, VPC Link y REST API Gateway |

Todo está declarado en Terraform; la plataforma con costo por hora queda **apagada** en los tres ambientes hasta la demo.

**Encender para la sustentación** (en `envs/<env>.tfvars`, vía PR para que lo aplique el pipeline):

```hcl
enable_platform = true
```

## Kubernetes y canary

- `k8s/base/`: un `Rollout` de Argo + `Service` por servicio (generados con `scripts/gen_k8s_base.py`) y la `AnalysisTemplate` `error-rate-cloudwatch`.
- `k8s/overlays/<env>/`: namespace `aegisvolt-<env>`, ConfigMap del ambiente y réplicas (dev 1, test 2, prod 5).
- `k8s/platform/argo-rollouts/`: controlador de Argo Rollouts v1.10.2 con `AWS_REGION` para el proveedor CloudWatch.

**Canary** (`deploy.yml`, solo con la plataforma encendida): build y push a ECR con tag = SHA → `kubectl apply -k` → `setWeight 20` → pausa 60 s → análisis → `setWeight 50` → `setWeight 100`.
Condición: `ErrorCount / RequestCount < 2 %` de la **versión nueva** (dimensión `Version` = hash de la plantilla del pod), 4 mediciones cada 30 s; 2 fallidas → aborto y rollback automático a la versión estable.

**Demo de rollback:** PR que añade `FAULT_INJECTION_RATE: "0.3"` al `graphql-gateway` del overlay, tráfico con `python scripts/load.py --url <graphql_url>` y `kubectl argo rollouts get rollout graphql-gateway -n aegisvolt-dev --watch`.

## Observabilidad

**CloudWatch:** cada servicio escribe logs JSON (`ts, level, env, service, version, correlation_id, saga_id, event`) en `/aegisvolt/<env>/<servicio>`. Rastreo de una SAGA en Logs Insights (seleccionar los 4 grupos del ambiente):

```
fields ts, service, event, level | filter correlation_id = "<id>" and event != "HTTP_REQUEST" | sort ts asc
```

**Prefect + Dask** (`observability/prefect/`): las tasks de los 3 ambientes corren en paralelo en un clúster Dask local (`DaskTaskRunner`).

| Flow | Programación | Qué reporta (artefactos en el dashboard) |
| --- | --- | --- |
| `environment-health` | cada 5 min | `environment-health`: tablas 5/5, API Gateway `/health`, estado de EKS por ambiente; falla si prod está caído |
| `saga-consistency-audit` | cada 10 min | `saga-audit-summary` (COMPLETED/COMPENSATED/FAILED, huérfanas, inconsistentes), `saga-audit-findings`, `saga-correlation-traces` (correlation_id + consulta de Logs Insights) |

```powershell
.\.venv\Scripts\prefect.exe server start            # dashboard: http://127.0.0.1:4200
$env:PREFECT_API_URL = "http://127.0.0.1:4200/api"
.\.venv\Scripts\python.exe observability/prefect/flows.py run     # una vez
.\.venv\Scripts\python.exe observability/prefect/flows.py serve   # programados
```

**Apagar al terminar:** volver a `false` y fusionar el PR; Terraform destruye EKS, NAT, NLB y API Gateway y deja la red gratuita. Al cerrar el proyecto: `terraform destroy` en cada workspace. Hay una alerta de presupuesto mensual (`aegisvolt-monthly`, USD 20).
