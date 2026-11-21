# Guion de la sustentación — AegisVolt

Cada pregunta vale todo o nada: **respuesta en 1-2 frases + mostrarlo en vivo**. Abajo, para cada pregunta del banco: qué decir, qué abrir y los comandos exactos (PowerShell).

Repositorio: https://github.com/Jorgealis/aegisvolt · Cuenta AWS `185658217743` · Región `us-east-1`
Bucket de estados: `aegisvolt-tfstate-185658217743`

---

## Antes de empezar (T-60 min)

1. Encender la plataforma según [PLATAFORMA.md](PLATAFORMA.md) (opción A o B) y verificar (`kubectl get pods`, `/health`).
2. Abrir pestañas:
   - GitHub: [Actions](https://github.com/Jorgealis/aegisvolt/actions), [ruleset `protected-envs`](https://github.com/Jorgealis/aegisvolt/settings/rules/27703858), [PRs cerrados](https://github.com/Jorgealis/aegisvolt/pulls?q=is%3Apr+is%3Aclosed).
   - AWS: S3 (bucket de estados), DynamoDB (tablas `aegisvolt-*`), CloudWatch Logs Insights, VPC (route tables).
   - Prefect: `http://127.0.0.1:4200` (servidor arrancado y flows ejecutados una vez).
   - Frontend de dev (`npm run dev -- --mode dev`) y de prod (opción A: `--mode prod`; opción B: `docker compose` con `AEGIS_ENV=prod` y `npm run dev`).
3. Datos limpios: `python scripts/seed.py --env dev`, `--env test` y `--env prod` (conectores AVAILABLE, saldos 500 / 5).
4. Flags en estado inicial: `python scripts/flag.py dev`, `test`, `prod` (solo listar).

Variables útiles en la terminal:

```powershell
cd "C:\Users\jorge\Documents\FINAL PATRONES\aegisvolt"
$BUCKET = "aegisvolt-tfstate-185658217743"
$PY = ".\.venv\Scripts\python.exe"
```

## Guion sugerido (10 min)

1. Reglas de rama: rechazo de push directo y `--force` (1 min).
2. PR con checks y `terraform plan` del workspace destino; merge y `apply` (2 min).
3. Canary 20 % → análisis → 100 % y el rollback abortado (2 min).
4. SAGA exitosa y SAGA con fallo de hardware: compensación en DynamoDB (2 min).
5. Traza por `correlation_id` en CloudWatch y auditoría en Prefect (2 min).
6. Versiones del tfstate en S3 y cómo restaurar (1 min).

---

## 6.1 Infraestructura como código (30 %)

### ¿Cómo garantiza que un `apply` en `test` no sobrescribe DynamoDB ni el estado de `prod`?

**Respuesta:** cada ambiente es un workspace con su propio objeto de estado en S3 (`env:/test/...` vs `env:/prod/...`) y todos los nombres salen de `terraform.workspace` (`aegisvolt-billing-test` ≠ `aegisvolt-billing-prod`). El plan de test no conoce ni referencia recursos de prod. Además el pipeline solo hace `workspace select` del ambiente de la rama fusionada, hay una guarda que rechaza el workspace `default` y la política del VPC Endpoint de DynamoDB solo deja llegar a las tablas `aegisvolt-*-<env>` de esa VPC.

**Mostrar:** `infra/locals.tf` (env y prefix), `infra/backend.tf` (clave y `workspace_key_prefix`).

```powershell
cd infra
terraform workspace list
aws s3 ls "s3://$BUCKET/" --recursive
terraform workspace select test
terraform plan -var-file="envs/test.tfvars" -lock=false     # solo recursos *-test, "No changes"
cd ..
```

### Muestre las versiones anteriores del `terraform.tfstate` de `dev` y cómo restauraría la previa

**Respuesta:** el bucket tiene versionado habilitado: cada escritura del estado crea una versión nueva y las anteriores se conservan (las 20 últimas siempre). Para restaurar: descargar la versión previa por `version-id` y subirla como estado actual (`terraform state push`), o copiarla sobre la clave actual con `copy-object`; luego `terraform plan` para verificar que no hay drift inesperado.

```powershell
aws s3api get-bucket-versioning --bucket $BUCKET
aws s3api list-object-versions --bucket $BUCKET --prefix "env:/dev/aegisvolt/terraform.tfstate" `
  --query "Versions[?Key=='env:/dev/aegisvolt/terraform.tfstate'].[VersionId,LastModified,Size,IsLatest]" --output table

# Descargar la versión anterior (copiar un VersionId de la tabla)
aws s3api get-object --bucket $BUCKET --key "env:/dev/aegisvolt/terraform.tfstate" --version-id <VERSION_ID> previo.tfstate
cd infra; terraform show ..\previo.tfstate | Select-Object -First 30; cd ..
```

Restauración (explicarla; ejecutarla en vivo solo si lo piden, porque cambia el estado real):

```powershell
cd infra; terraform workspace select dev
terraform state push -force ..\previo.tfstate
terraform plan -var-file="envs/dev.tfvars"     # verificar y reconciliar
# alternativa en S3: aws s3api copy-object --bucket $BUCKET --key "env:/dev/aegisvolt/terraform.tfstate" --copy-source "$BUCKET/env:/dev/aegisvolt/terraform.tfstate?versionId=<VERSION_ID>"
```

### Recorrido de un paquete desde API Gateway hasta el pod a través del VPC Endpoint

**Respuesta:**
1. El navegador hace `POST https://<api-id>.execute-api.us-east-1.amazonaws.com/<env>/graphql` (REST API regional).
2. La integración `HTTP_PROXY` usa un **VPC Link**, que en REST API es **AWS PrivateLink**: un VPC Endpoint Service sobre el **NLB interno** de las subredes privadas. API Gateway entra a la VPC por ese endpoint privado, sin internet.
3. El NLB reenvía al **NodePort 30080** de los nodos EKS; el security group del clúster solo permite 30080 desde el CIDR de la VPC.
4. kube-proxy entrega al Service `graphql-gateway` y a un pod; el gateway llama a los microservicios por **Service ClusterIP** (DNS interno).
5. Los pods escriben en DynamoDB: la **route table privada** tiene la ruta al prefix list de DynamoDB (`pl-…`) → **Gateway VPC Endpoint**, más específica que `0.0.0.0/0`, así que no pasa por el NAT ni por internet. Los logs salen por el **Interface VPCE de `logs`** (DNS privado, SG 443 desde la VPC).

```powershell
aws ec2 describe-route-tables --filters Name=tag:Name,Values=aegisvolt-dev-rt-private `
  --query "RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,NatGatewayId]" --output table
aws ec2 describe-vpc-endpoints --filters Name=tag:Name,Values=aegisvolt-dev-vpce-dynamodb --query "VpcEndpoints[0].PolicyDocument" --output text
# Con la plataforma encendida:
aws apigateway get-vpc-links --query "items[].[name,status,targetArns[0]]" --output table
$TG = aws elbv2 describe-target-groups --names aegisvolt-dev-gw --query "TargetGroups[0].TargetGroupArn" --output text
aws elbv2 describe-target-health --target-group-arn $TG --query "TargetHealthDescriptions[].[Target.Id,Target.Port,TargetHealth.State]" --output table
```

Código: `infra/modules/apigw/main.tf`, `infra/modules/vpce/main.tf`, `infra/modules/network/main.tf`.

---

## 6.2 CI/CD, promoción y canary (25 %)

### Intente un `git push --force` o un push directo a `test`

```powershell
git checkout test; git pull
git commit --allow-empty -m "prueba push directo"
git push origin test              # rechazado
git push --force origin test      # rechazado
git reset --hard origin/test; git checkout dev
```

**Respuesta esperada en la terminal:** `! [remote rejected] test -> test (push declined due to repository rule violations)`.
**Qué lo bloquea:** el ruleset **`protected-envs`** sobre `dev`, `test` y `prod`: *Restrict deletions*, *Block force pushes* (`non_fast_forward`), *Require a pull request* y *Require status checks* (los 6 jobs), **sin bypass** (ni el admin). Mostrar la [página del ruleset](https://github.com/Jorgealis/aegisvolt/settings/rules/27703858) o `docs/rulesets/protected-envs.json`. El job `enforce-promotion` rechaza PRs que salten la cadena (`feature/* → dev → test → prod`).

### En el YAML, ¿cómo se decide sobre qué ambiente corre `terraform apply` tras el merge?

**Respuesta:** `deploy.yml` se dispara con `push` a `dev`, `test` o `prod`, lo que solo ocurre al fusionar un PR (el push directo está bloqueado). El job `resolve-env` toma `GITHUB_REF_NAME` (la rama que recibió el merge) y ese valor es el workspace: `terraform workspace select "$TARGET_ENV"` y `-var-file=envs/$TARGET_ENV.tfvars`. Además el job corre en el GitHub Environment de ese nombre, que es el único claim OIDC que puede asumir el rol `aegisvolt-gha-deploy`.

Mostrar `.github/workflows/deploy.yml`: líneas 6-7 (`on: push`), 29-30 (`GITHUB_REF_NAME`), 37 (`environment`), 59 (`workspace select`). En PR, `pr.yml` hace el `terraform plan` del workspace **de la rama destino** (`github.base_ref`). Evidencia: PRs [#8 dev→test](https://github.com/Jorgealis/aegisvolt/pull/8) y [#9 test→prod](https://github.com/Jorgealis/aegisvolt/pull/9) y sus runs de `deploy`.

### ¿Qué métrica evalúa el canary antes de pasar del 20 % al 100 %?

**Respuesta:** la **tasa de error de la versión nueva** en CloudWatch: `ErrorCount / RequestCount < 2 %`. Las métricas salen de los logs JSON `HTTP_REQUEST` por metric filters, con dimensión `Version` = hash de la plantilla del pod canary, así se mide solo el canary. Pasos: `setWeight 20` → 2 min de tráfico → **AnalysisRun** (4 mediciones de 60 s) → 50 % → 100 %. Con 2 mediciones fallidas, Argo Rollouts **aborta** y vuelve al 100 % estable.

Mostrar `k8s/base/analysis-template.yaml`, `infra/modules/cloudwatch/metrics.tf` y, en vivo:

```powershell
kubectl argo rollouts get rollout graphql-gateway -n aegisvolt-dev
kubectl get analysisrun -n aegisvolt-dev
```

---

## 6.3 SAGA y Feature Flags (25 %)

### Active la flag de fallo en `test`, dispare la mutación y muestre la compensación en DynamoDB

```powershell
& $PY scripts/flag.py test SIMULATE_CHARGER_HARDWARE_FAULT true
Start-Sleep 6                                                     # caché de flags: 5 s
```

Disparar la mutación (frontend de test, o directo):

```powershell
# Opción A: $GQL = URL de API Gateway de test. Opción B: http://localhost:8080/graphql con AEGIS_ENV=test
$body = @{ query = 'mutation { reserveAndCharge(fleetId: "FLEET-001", stationId: "BOG-01", connectorId: "C2", estimatedKwh: 30) { id state error correlationId steps { name status } } }' } | ConvertTo-Json
(Invoke-RestMethod -Method Post -Uri $GQL -ContentType "application/json" -Body $body).data.reserveAndCharge | ConvertTo-Json -Depth 5
& $PY scripts/inspect_saga.py test --latest
& $PY scripts/flag.py test SIMULATE_CHARGER_HARDWARE_FAULT false
```

**Qué se ve en las tablas:** `aegisvolt-sagas-test` en **COMPENSATED** con pasos RESERVE OK → CHARGE OK → DISPATCH FAILED → REFUND COMPENSATED → RELEASE COMPENSATED; en `aegisvolt-billing-test` el `TX#<saga>#DEBIT` **y** el `TX#<saga>#REFUND` con el mismo monto y el saldo restaurado; en `aegisvolt-reservations-test` el conector **AVAILABLE** sin `saga_id`; en `aegisvolt-dispatch-test` la sesión **FAILED / CHARGER_HARDWARE_FAULT**. (También en la consola de DynamoDB → Explore items.)

Si el paso 2 falla (fondos insuficientes, `FLEET-002`), solo se libera el conector: pasos RESERVE → CHARGE FAILED → RELEASE.

### ¿Cómo evita problemas de idempotencia si una compensación se procesa dos veces?

**Respuesta:** cada operación lleva la clave `<saga_id>:<acción>`. El servicio escribe en **una sola transacción `TransactWriteItems`** el registro `IDEM#<clave>` con `attribute_not_exists(PK)` **y** el cambio de negocio. Si la clave ya existe, la transacción entera se cancela (no se aplica el efecto otra vez) y se devuelve el resultado guardado (`replayed: true`). El reembolso además exige que no exista `TX#<saga>#REFUND` (solo puede haber uno), y `release` solo libera si `saga_id` coincide. Por eso el orquestador puede reintentar con seguridad ante timeouts.

Demo (llamar el refund dos veces; el saldo no cambia la segunda vez):

```powershell
# Opción A: kubectl port-forward svc/billing-wallet-service 8102:8000 -n aegisvolt-test   (en otra terminal)
# Opción B: docker compose con AEGIS_ENV=test ya expone 8102
$SAGA = "<saga_id de la SAGA compensada>"
$r = @{ fleet_id = "FLEET-001" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8102/charges/$SAGA/refund" -ContentType "application/json" -Body $r
Invoke-RestMethod -Method Post -Uri "http://localhost:8102/charges/$SAGA/refund" -ContentType "application/json" -Body $r   # replayed: True
& $PY scripts/inspect_saga.py test $SAGA        # un solo REFUND, saldo igual
```

Código: `services/common/aegis_common/idempotency.py`, `services/billing-wallet-service/billing_wallet/main.py` (`refund`). Test: `tests/integration/test_services.py::test_refund_twice_only_refunds_once`.

---

## 6.4 Observabilidad y frontend (20 %)

### Muestre el flujo de Prefect y rastree en CloudWatch el `correlation_id` de una SAGA fallida

```powershell
$env:PREFECT_API_URL = "http://127.0.0.1:4200/api"
& $PY observability/prefect/flows.py run
```

En `http://127.0.0.1:4200`: Runs → `saga-consistency-audit` (tasks `load-*`/`audit-*` en paralelo con Dask) → Artifacts: **`saga-audit-summary`** (COMPLETED / COMPENSATED / huérfanas / inconsistentes por ambiente), **`saga-audit-findings`**, **`saga-correlation-traces`** (copiar el `correlation_id` y la consulta) y **`environment-health`**.

CloudWatch → Logs Insights → seleccionar `/aegisvolt/<env>/graphql-gateway`, `billing-wallet`, `station-reservation`, `energy-dispatch`:

```
fields ts, service, event, level | filter correlation_id = "<correlation_id>" and event != "HTTP_REQUEST" | sort ts asc
```

Se ve la SAGA cruzando los 4 servicios: `SAGA_STARTED → CONNECTOR_RESERVED → CHARGE_APPLIED → CHARGER_HARDWARE_FAULT → SAGA_COMPENSATING → REFUND_APPLIED → CONNECTOR_RELEASED → SAGA_COMPENSATED`.
(Desde la CLI en PowerShell usar comillas simples dentro de la consulta: `correlation_id = '<id>'`.)

### Cambie una flag en `dev` sin redesplegar y muestre que `prod` no cambia

Dos pestañas lado a lado: frontend de **dev** (banda verde) y de **prod** (banda roja).

```powershell
& $PY scripts/flag.py dev ENABLE_DYNAMIC_SURGE_PRICING false    # dev: tarifa 0.45 -> 0.30 en <= 5 s
& $PY scripts/flag.py dev ENABLE_DYNAMIC_SURGE_PRICING true     # vuelve a 0.45
& $PY scripts/flag.py prod                                       # prod: su tabla no cambió
```

**Respuesta:** las flags viven en la tabla `aegisvolt-flags-<env>` de cada ambiente; cada servicio la lee con caché de 5 s, así que el cambio se ve sin redesplegar. prod lee **otra tabla**, por eso no cambia. (En dev `SURGE_HOURS=00-24` para que la tarifa dinámica se vea a cualquier hora; en test/prod es 18-21.) También sirve `SIMULATE_CHARGER_HARDWARE_FAULT`: en dev las reservas pasan a COMPENSATED; en prod siguen COMPLETED.

---

## Preguntas probables adicionales

| Pregunta | Respuesta corta |
| --- | --- |
| ¿Por qué orquestación y no coreografía? | Un solo lugar con el estado de la SAGA (`aegisvolt-sagas-<env>`): fácil de auditar, compensar en orden inverso y explicar. La coreografía reparte esa lógica en eventos entre servicios. |
| ¿Qué pasa si el orquestador cae a mitad de la SAGA? | Queda en STARTED/RESERVED/CHARGED; Prefect la marca **huérfana** a los 5 min. Las compensaciones son idempotentes, así que reintentarlas es seguro. |
| ¿Por qué los reintentos no duplican cobros? | Solo se reintenta ante fallos transitorios (timeout/5xx) y cada POST lleva su clave de idempotencia. Un 409 de negocio no se reintenta. |
| *Database-per-service* | Cada servicio solo escribe su tabla; el gateway no toca billing ni reservations, los llama por HTTP. |
| ¿Por qué canary por réplicas y no por porcentaje de tráfico? | Sin service mesh ni ingress con pesos: con 5 réplicas en prod, 1 pod canary = 20 %. El análisis mide solo la versión nueva por su dimensión `Version`. |
| ¿Por qué el endpoint de EKS es público? | Para que GitHub Actions despliegue con `kubectl`; la autenticación es por IAM (access entries) y los nodos usan el endpoint privado. |
| ¿Cómo controló costos? | `enable_platform`: lo que se cobra por hora solo existe para la demo; red, DynamoDB on-demand y logs cuestan ~0; un NAT en vez de uno por AZ; VPCE de logs en 1 AZ; alerta de presupuesto de USD 20. |
| ¿Cómo autentica el pipeline con AWS? | OIDC, sin llaves guardadas: rol de solo lectura para los PR (`aegisvolt-gha-plan`) y rol de despliegue solo para jobs en un GitHub Environment (`aegisvolt-gha-deploy`). |
