"""Configuración leída del entorno (ConfigMap del namespace en Kubernetes)."""

import os


def env() -> str:
    """Ambiente estático: dev | test | prod (local en docker compose)."""
    return os.getenv("ENV", "local")


def service_name() -> str:
    return os.getenv("SERVICE_NAME", "unknown")


def version() -> str:
    return os.getenv("APP_VERSION", "dev")


def region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def dynamodb_endpoint() -> str | None:
    """Solo para DynamoDB Local; en AWS va vacío y boto3 usa el endpoint regional
    (resuelto vía el Gateway VPC Endpoint desde las subredes privadas)."""
    return os.getenv("DYNAMODB_ENDPOINT") or None


def table_name(logical: str) -> str:
    """aegisvolt-<tabla>-<env>, igual que en Terraform. TABLE_<NOMBRE> lo sobreescribe."""
    return os.getenv(f"TABLE_{logical.upper()}", f"aegisvolt-{logical}-{env()}")
