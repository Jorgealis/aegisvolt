"""Tarifa dinámica y caché de 5 s de las feature flags."""

from datetime import UTC, datetime

from aegis_common import flags
from billing_wallet import pricing


def utc(hour):
    return datetime(2026, 11, 20, hour, 0, tzinfo=UTC)


def test_surge_only_in_peak_hours_local_time(monkeypatch):
    monkeypatch.setenv("SURGE_HOURS", "18-21")
    monkeypatch.setenv("TZ_OFFSET_HOURS", "-5")
    assert pricing.tariff(True, utc(23))["surge_active"]  # 18:00 en Bogotá
    assert not pricing.tariff(True, utc(15))["surge_active"]  # 10:00 en Bogotá
    assert not pricing.tariff(False, utc(23))["surge_active"]  # flag apagada


def test_surge_multiplies_by_1_5(monkeypatch):
    monkeypatch.setenv("BASE_RATE_PER_KWH", "0.30")
    t = pricing.tariff(True, utc(23))
    assert t["effective_per_kwh"] == 0.45
    assert pricing.amount_for(40, t["effective_per_kwh"]) == pricing.amount_for(40, 0.45) == 18


class FakeDynamo:
    def __init__(self):
        self.calls, self.value = 0, True

    def get_item(self, **_):
        self.calls += 1
        return {"Item": {"enabled": {"BOOL": self.value}}}


def test_flag_cache_5_seconds(monkeypatch):
    fake, clock = FakeDynamo(), [100.0]
    monkeypatch.setattr(flags.aws, "dynamodb", lambda: fake)
    monkeypatch.setattr(flags.time, "monotonic", lambda: clock[0])
    monkeypatch.delenv("FLAGS_CACHE_SECONDS", raising=False)
    flags.clear_cache()

    assert flags.get_flag("X") is True
    fake.value = False
    clock[0] += 4.9
    assert flags.get_flag("X") is True  # aún en caché
    clock[0] += 0.2
    assert flags.get_flag("X") is False  # caché vencida: lee el nuevo valor
    assert fake.calls == 2
