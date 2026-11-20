"""Dependencias del gateway (reemplazables en tests)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from .clients import ServiceClient
from .saga import SagaOrchestrator, SagaRepository


@dataclass
class Deps:
    reservations: ServiceClient
    billing: ServiceClient
    dispatch: ServiceClient
    repo: SagaRepository
    orchestrator: SagaOrchestrator


def build(reservations: ServiceClient, billing: ServiceClient, dispatch: ServiceClient, repo=None) -> Deps:
    repo = repo or SagaRepository()
    return Deps(reservations, billing, dispatch, repo, SagaOrchestrator(reservations, billing, dispatch, repo))


@lru_cache
def deps() -> Deps:
    # En Kubernetes: DNS interno de los Service ClusterIP del namespace.
    return build(
        ServiceClient("station-reservation", os.getenv("RESERVATION_URL", "http://station-reservation-service:8000")),
        ServiceClient("billing-wallet", os.getenv("BILLING_URL", "http://billing-wallet-service:8000")),
        ServiceClient("energy-dispatch", os.getenv("DISPATCH_URL", "http://energy-dispatch-service:8000")),
    )
