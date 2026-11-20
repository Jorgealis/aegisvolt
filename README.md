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
| `infra/` | VPC, VPCE, API Gateway, EKS, DynamoDB, CloudWatch por ambiente | `s3://aegisvolt-tfstate-<cuenta>/env/<workspace>/` |

### Control de costos

Proyecto corto: `dev` se mantiene encendido solo mientras se desarrolla; `test` y `prod` se crean para las promociones y la sustentación y luego se destruyen (`terraform destroy` en su workspace). Hay una alerta de presupuesto mensual (`aegisvolt-monthly`).
