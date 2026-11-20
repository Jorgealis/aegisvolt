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

**Apagar al terminar:** volver a `false` y fusionar el PR; Terraform destruye EKS, NAT, NLB y API Gateway y deja la red gratuita. Al cerrar el proyecto: `terraform destroy` en cada workspace. Hay una alerta de presupuesto mensual (`aegisvolt-monthly`, USD 20).
