# Levanta (o baja) dev, test y prod a la vez en Docker, cada uno contra sus
# tablas y log groups REALES de AWS, para cambiar de ambiente desde el
# selector del frontend. Sin EKS ni API Gateway: costo ~0 (DynamoDB on-demand).
#
#   .\scripts\envs.ps1 up            # los tres
#   .\scripts\envs.ps1 up test       # solo uno
#   .\scripts\envs.ps1 down
#
# Puertos del gateway: dev 8180, test 8280, prod 8380 (local sigue en 8080).
# Billing (demo de idempotencia): dev 8182, test 8282, prod 8382.
param(
    [ValidateSet("up", "down")] [string] $Action = "up",
    [ValidateSet("dev", "test", "prod")] [string[]] $Envs = @("dev", "test", "prod")
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ports = @{ dev = 8180; test = 8280; prod = 8380 }

foreach ($e in $Envs) {
    $env:AEGIS_ENV = $e
    $env:GATEWAY_PORT = $ports[$e]
    $env:BILLING_PORT = $ports[$e] + 2
    $compose = @("compose", "-p", "aegisvolt-$e", "-f", "$root/docker-compose.yml", "-f", "$root/docker-compose.aws.yml")
    if ($Action -eq "up") {
        Write-Host "== $e -> http://localhost:$($ports[$e])/graphql"
        & docker @compose up -d --build --wait
    } else {
        Write-Host "== bajando $e"
        & docker @compose down
    }
    if ($LASTEXITCODE -ne 0) { throw "docker compose $Action fallo para $e" }
}
Remove-Item Env:AEGIS_ENV, Env:GATEWAY_PORT, Env:BILLING_PORT -ErrorAction SilentlyContinue
