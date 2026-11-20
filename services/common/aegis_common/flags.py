"""Cliente de Feature Flags: tabla aegisvolt-flags-<env> con caché de 5 s.

Cada ambiente lee SU tabla (el nombre sale de ENV), así que cambiar una flag en
dev no afecta a prod, y el cambio se ve en <= 5 s sin redesplegar.
"""

import logging
import os
import time

from . import aws, config

SURGE_PRICING = "ENABLE_DYNAMIC_SURGE_PRICING"
FAST_CHARGE_BOOST = "ENABLE_FAST_CHARGE_BOOST"
HARDWARE_FAULT = "SIMULATE_CHARGER_HARDWARE_FAULT"

logger = logging.getLogger(__name__)
_cache: dict[str, tuple[float, bool]] = {}


def ttl_seconds() -> float:
    return float(os.getenv("FLAGS_CACHE_SECONDS", "5"))


def get_flag(name: str, default: bool = False) -> bool:
    now = time.monotonic()
    cached = _cache.get(name)
    if cached and now - cached[0] < ttl_seconds():
        return cached[1]
    try:
        resp = aws.dynamodb().get_item(
            TableName=config.table_name("flags"),
            Key={"PK": {"S": f"FLAG#{name}"}},
            ConsistentRead=True,
        )
        value = resp.get("Item", {}).get("enabled", {}).get("BOOL", default)
    except Exception:  # noqa: BLE001 - si DynamoDB falla, se usa el último valor conocido
        logger.warning("no se pudo leer la flag %s", name, exc_info=True)
        value = cached[1] if cached else default
    _cache[name] = (now, value)
    return value


def all_flags() -> list[dict]:
    resp = aws.dynamodb().scan(TableName=config.table_name("flags"), ConsistentRead=True)
    flags = [aws.from_item(i) for i in resp.get("Items", [])]
    return sorted(
        ({"name": f["name"], "enabled": bool(f.get("enabled", False)), "env": config.env()} for f in flags if "name" in f),
        key=lambda f: f["name"],
    )


def clear_cache() -> None:
    _cache.clear()
