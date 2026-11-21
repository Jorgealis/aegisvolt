# Encender y apagar la plataforma (EKS, API Gateway, canary)

> **Estado actual:** `enable_platform = false` en dev, test y prod. No hay EKS, NAT, NLB ni API Gateway: **USD ~0/h**.
> Este procedimiento NO se ha ejecutado todavía. Hacerlo solo cuando se decida (ensayo general y día de la sustentación).

## Costo mientras está encendida

| Recurso por ambiente | USD/h aprox. |
| --- | --- |
| EKS (plano de control) | 0,10 |
| 2 nodos t3.medium on-demand | 0,08 |
| NAT Gateway + IP elástica | 0,05 (+ 0,045 por GB transferido) |
| Interface VPCE de CloudWatch Logs (1 AZ) | 0,01 |
| NLB interno | 0,02 |
| **Total por ambiente** | **≈ 0,27** |

| Opción | Ambientes con EKS | Costo | Cubre |
| --- | --- | --- | --- |
| **B — económica (recomendada para el ensayo)** | solo dev | ≈ 0,27/h | EKS, canary, rollback, API Gateway, VPC Link en dev. test y prod se demuestran con sus tablas reales vía `docker-compose.aws.yml` (`AEGIS_ENV=test`/`prod`). |
| A — completa (día de la sustentación, si se quiere) | dev, test y prod | ≈ 0,81/h | Todo, con frontend real de dev y prod contra API Gateway. |

Encender ~60 min antes y apagar apenas termine. Dos horas de opción A ≈ USD 1,6.

---

## 0. Preparación local (sin costo)

```powershell
aws sts get-caller-identity          # cuenta 185658217743, usuario jorge-cli
docker info                          # Docker Desktop encendido
cd "C:\Users\jorge\Documents\FINAL PATRONES\aegisvolt"
git checkout dev; git pull
```

Plugin de Argo Rollouts para kubectl (una vez):

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\bin" | Out-Null
Invoke-WebRequest https://github.com/argoproj/argo-rollouts/releases/download/v1.10.2/kubectl-argo-rollouts-windows-amd64 -OutFile "$env:USERPROFILE\bin\kubectl-argo-rollouts.exe"
$env:Path += ";$env:USERPROFILE\bin"
kubectl argo rollouts version
```

## 1. Encender (por PR, lo aplica el pipeline)

```powershell
git checkout -b feature/encender-plataforma
```

Editar `infra/envs/dev.tfvars` (y también `test.tfvars` / `prod.tfvars` para la opción A):

```hcl
enable_platform = true
```

```powershell
git commit -am "chore(infra): encender plataforma para la demo"
git push -u origin feature/encender-plataforma
gh pr create --base dev --title "Encender plataforma (demo)" --body "enable_platform = true"
```

1. Checks en verde → **Merge** → `deploy.yml` en dev:
   - `terraform-apply` (EKS tarda ~12-15 min; node group ~4 min; VPC Link ~5 min).
   - `build-push`: 4 imágenes a ECR con tag = SHA.
   - `deploy-canary`: instala Argo Rollouts y aplica el overlay. **El primer despliegue va directo al 100 %** (no hay versión estable previa).
2. Opción A: promover `dev → test` y `test → prod` con PR (cada merge enciende la plataforma de ese ambiente).

Seguir el pipeline: `gh run watch -R Jorgealis/aegisvolt`.

## 2. Verificar

```powershell
cd infra; terraform workspace select dev
$GQL = terraform output -raw graphql_url   # https://<id>.execute-api.us-east-1.amazonaws.com/dev/graphql
cd ..
aws eks update-kubeconfig --name aegisvolt-dev --region us-east-1
kubectl get nodes
kubectl get pods -n aegisvolt-dev
kubectl argo rollouts list rollouts -n aegisvolt-dev
Invoke-RestMethod ($GQL -replace '/graphql$', '/health')
```

Frontend contra API Gateway de dev:

```powershell
"VITE_GRAPHQL_URL=<graphql_url de dev>" | Out-File frontend\.env.dev.local -Encoding utf8
cd frontend; npm run dev -- --mode dev     # http://localhost:5173
```

Si el entorno se recreó, la URL cambia: también sirve `http://localhost:5173/?api=<graphql_url>`.

Prefect (debe reportar `HEALTHY` en dev):

```powershell
.\.venv\Scripts\prefect.exe server start
# en otra terminal
$env:PREFECT_API_URL = "http://127.0.0.1:4200/api"
.\.venv\Scripts\python.exe observability/prefect/flows.py run
```

## 3. Demo de canary exitoso

Cualquier commit que llegue a dev cambia el tag de imagen y dispara el canary en los 4 servicios. Antes del merge, dejar tráfico corriendo:

```powershell
.\.venv\Scripts\python.exe scripts/load.py --url <graphql_url> --rps 5 --seconds 900
kubectl argo rollouts get rollout graphql-gateway -n aegisvolt-dev --watch
```

Se verá: `SetWeight 20` → pausa 2 min → `AnalysisRun` (4 mediciones de 60 s, error < 2 %) → `SetWeight 50` → `100` → `Healthy`.

## 4. Demo de rollback automático

Añadir al final de `patches:` en `k8s/overlays/dev/kustomization.yaml` (PR `feature/* → dev`):

```yaml
  - target:
      kind: Rollout
      name: graphql-gateway
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/env/-
        value: { name: FAULT_INJECTION_RATE, value: "0.3" }
```

Con `load.py` corriendo, el pod canary responde 500 en el 30 % de las peticiones → el análisis falla 2 veces → Argo **aborta**: el canary baja a 0 y el 100 % queda en la versión estable. El job `deploy-canary` termina en rojo (es la evidencia). Revertir con otro PR que quite el patch.

```powershell
kubectl argo rollouts get rollout graphql-gateway -n aegisvolt-dev        # Status: Degraded / RolloutAborted
kubectl get analysisrun -n aegisvolt-dev
```

## 5. Apagar (inmediatamente después)

```powershell
git checkout dev; git pull; git checkout -b feature/apagar-plataforma
# infra/envs/*.tfvars -> enable_platform = false (+ quitar el patch de FAULT_INJECTION_RATE si quedó)
git commit -am "chore(infra): apagar plataforma"; git push -u origin feature/apagar-plataforma
gh pr create --base dev --title "Apagar plataforma" --body "enable_platform = false"
```

Merge (y promover a test/prod si se encendieron). Terraform destruye EKS, NAT, NLB, VPC Link y API Gateway (~10-15 min) y deja la red gratuita.

**Comprobar que no queda nada que cobre por hora:**

```powershell
aws eks list-clusters
aws ec2 describe-nat-gateways --filter Name=state,Values=available,pending --query "length(NatGateways)"
aws elbv2 describe-load-balancers --query "length(LoadBalancers)"
aws ec2 describe-vpc-endpoints --filters Name=vpc-endpoint-type,Values=Interface --query "length(VpcEndpoints)"
aws ec2 describe-addresses --query "length(Addresses)"
```

**Apagado de emergencia** (si el pipeline falla), desde la máquina local:

```powershell
cd infra; terraform workspace select dev
terraform plan -var-file="envs/dev.tfvars" -var="enable_platform=false" -out=off.tfplan
terraform apply off.tfplan
```

## 6. Cierre del proyecto (después de la nota)

1. `terraform destroy -var-file=envs/<env>.tfvars` en los workspaces dev, test y prod.
2. Borrar imágenes y repos ECR, alerta de presupuesto y roles: en `infra/bootstrap` quitar `prevent_destroy` del bucket y `terraform destroy` (el bucket de estados versionado cuesta centavos; puede conservarse como evidencia).
3. Verificar en Billing que el gasto diario vuelve a 0.
