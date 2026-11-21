"""Clientes AWS y conversión entre dict de Python y el formato tipado de DynamoDB."""

from decimal import Decimal
from functools import lru_cache
from typing import Any

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.config import Config

from . import config

_BOTO_CONFIG = Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 3, "mode": "standard"})
_ser = TypeSerializer()
_deser = TypeDeserializer()


@lru_cache
def dynamodb():
    return boto3.client(
        "dynamodb",
        region_name=config.region(),
        endpoint_url=config.dynamodb_endpoint(),
        config=_BOTO_CONFIG,
    )


@lru_cache
def logs():
    return boto3.client("logs", region_name=config.region(), config=_BOTO_CONFIG)


def _to_dynamo_value(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo_value(v) for v in value]
    return value


def to_item(data: dict) -> dict:
    """dict -> {"attr": {"S": ...}}; omite los None."""
    return {k: _ser.serialize(_to_dynamo_value(v)) for k, v in data.items() if v is not None}


def from_item(item: dict | None) -> dict | None:
    if item is None:
        return None
    return {k: _plain(_deser.deserialize(v)) for k, v in item.items()}


def values(data: dict) -> dict:
    """Para ExpressionAttributeValues: {":x": valor} -> formato tipado."""
    return {k: _ser.serialize(_to_dynamo_value(v)) for k, v in data.items()}


def _plain(value: Any) -> Any:
    """Decimal -> int/float para poder serializar a JSON."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, set)):
        return [_plain(v) for v in value]
    return value
