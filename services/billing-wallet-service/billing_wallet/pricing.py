"""Tarifa por kWh. ENABLE_DYNAMIC_SURGE_PRICING la multiplica x1.5 en hora pico."""

import os
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

SURGE_MULTIPLIER = Decimal("1.5")


def base_rate() -> Decimal:
    return Decimal(os.getenv("BASE_RATE_PER_KWH", "0.30"))


def surge_hours() -> tuple[int, int]:
    """SURGE_HOURS="18-21" -> [18, 21) en hora local (UTC-5 por defecto, sin horario de verano)."""
    start, end = os.getenv("SURGE_HOURS", "18-21").split("-")
    return int(start), int(end)


def local_hour(now_utc: datetime | None = None) -> int:
    offset = int(os.getenv("TZ_OFFSET_HOURS", "-5"))
    now_utc = now_utc or datetime.now(UTC)
    return (now_utc + timedelta(hours=offset)).hour


def in_surge_window(now_utc: datetime | None = None) -> bool:
    start, end = surge_hours()
    return start <= local_hour(now_utc) < end


def tariff(surge_flag: bool, now_utc: datetime | None = None) -> dict:
    surge_active = surge_flag and in_surge_window(now_utc)
    base = base_rate()
    effective = base * SURGE_MULTIPLIER if surge_active else base
    return {
        "base_per_kwh": float(base),
        "effective_per_kwh": float(effective),
        "surge_flag": surge_flag,
        "surge_active": surge_active,
        "surge_hours": os.getenv("SURGE_HOURS", "18-21"),
    }


def amount_for(kwh: float, effective_per_kwh: float) -> Decimal:
    return (Decimal(str(kwh)) * Decimal(str(effective_per_kwh))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
