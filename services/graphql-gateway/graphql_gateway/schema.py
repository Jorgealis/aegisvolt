"""Esquema GraphQL unificado de AegisVolt (Strawberry).

Exportado a schema.graphql con:
    strawberry export-schema graphql_gateway.schema:schema
"""

import asyncio
from enum import Enum

import strawberry

from aegis_common import config, flags

from .clients import ServiceError
from .deps import deps


@strawberry.enum
class ConnectorStatus(Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    CHARGING = "CHARGING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


@strawberry.enum
class SagaState(Enum):
    STARTED = "STARTED"
    RESERVED = "RESERVED"
    CHARGED = "CHARGED"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"


@strawberry.type
class Connector:
    id: strawberry.ID
    station_id: strawberry.ID
    power_kw: int
    status: ConnectorStatus


@strawberry.type
class Station:
    id: strawberry.ID
    name: str
    city: str
    connectors: list[Connector]


@strawberry.type
class WalletTx:
    saga_id: strawberry.ID
    type: str
    amount: float
    at: str


@strawberry.type
class Wallet:
    fleet_id: strawberry.ID
    balance: float
    transactions: list[WalletTx]


@strawberry.type
class SagaStep:
    name: str
    status: str
    at: str
    error: str | None


@strawberry.type
class Saga:
    id: strawberry.ID
    correlation_id: strawberry.ID
    state: SagaState
    fleet_id: strawberry.ID
    station_id: strawberry.ID
    connector_id: strawberry.ID
    estimated_kwh: float
    amount: float | None
    error: str | None
    steps: list[SagaStep]
    created_at: str
    updated_at: str


@strawberry.type
class Telemetry:
    session_id: strawberry.ID
    kwh: float
    power_kw: float
    at: str


@strawberry.type
class FeatureFlag:
    name: str
    enabled: bool
    env: str


@strawberry.type
class Tariff:
    base_per_kwh: float
    effective_per_kwh: float
    surge_flag: bool
    surge_active: bool
    surge_hours: str


# -- conversión dict -> tipos ---------------------------------------------
def to_station(s: dict) -> Station:
    return Station(
        id=s["id"],
        name=s["name"],
        city=s["city"],
        connectors=[
            Connector(id=c["id"], station_id=c["station_id"], power_kw=int(c["power_kw"]), status=ConnectorStatus(c["status"])) for c in s["connectors"]
        ],
    )


def to_wallet(w: dict) -> Wallet:
    return Wallet(fleet_id=w["fleet_id"], balance=w["balance"], transactions=[WalletTx(**t) for t in w["transactions"]])


def to_saga(s: dict) -> Saga:
    return Saga(
        id=s["id"],
        correlation_id=s["correlation_id"],
        state=SagaState(s["state"]),
        fleet_id=s["fleet_id"],
        station_id=s["station_id"],
        connector_id=s["connector_id"],
        estimated_kwh=s["estimated_kwh"],
        amount=s.get("amount"),
        error=s.get("error"),
        steps=[SagaStep(name=st["name"], status=st["status"], at=st["at"], error=st.get("error")) for st in s.get("steps", [])],
        created_at=s["created_at"],
        updated_at=s.get("updated_at", s["created_at"]),
    )


def _not_found(e: ServiceError) -> bool:
    return e.status == 404


# boto3 y httpx son síncronos: se ejecutan en un hilo para no bloquear el event loop
# (asyncio.to_thread copia los contextvars, así se conserva el correlation_id).
@strawberry.type
class Query:
    @strawberry.field(description="Ambiente estático que atiende esta API (dev | test | prod)")
    def environment(self) -> str:
        return config.env()

    @strawberry.field
    async def stations(self, city: str | None = None) -> list[Station]:
        data = await asyncio.to_thread(deps().reservations.get, "/stations", params={"city": city} if city else None)
        return [to_station(s) for s in data]

    @strawberry.field
    async def wallet(self, fleet_id: strawberry.ID) -> Wallet | None:
        try:
            return to_wallet(await asyncio.to_thread(deps().billing.get, f"/wallets/{fleet_id}"))
        except ServiceError as e:
            if _not_found(e):
                return None
            raise

    @strawberry.field
    async def tariff(self) -> Tariff:
        return Tariff(**await asyncio.to_thread(deps().billing.get, "/tariff"))

    @strawberry.field
    async def saga(self, id: strawberry.ID) -> Saga | None:
        s = await asyncio.to_thread(deps().repo.get, id)
        return to_saga(s) if s else None

    @strawberry.field
    async def sagas(self, limit: int = 20) -> list[Saga]:
        return [to_saga(s) for s in await asyncio.to_thread(deps().repo.list, limit)]

    @strawberry.field
    async def telemetry(self, session_id: strawberry.ID) -> list[Telemetry]:
        data = await asyncio.to_thread(deps().dispatch.get, f"/sessions/{session_id}/telemetry")
        return [Telemetry(**t) for t in data]

    @strawberry.field
    async def feature_flags(self) -> list[FeatureFlag]:
        return [FeatureFlag(**f) for f in await asyncio.to_thread(flags.all_flags)]


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Dispara la SAGA Reserva -> Cobro -> Activación y devuelve su estado final")
    async def reserve_and_charge(
        self, info: strawberry.Info, fleet_id: strawberry.ID, station_id: strawberry.ID, connector_id: strawberry.ID, estimated_kwh: float
    ) -> Saga:
        if estimated_kwh <= 0:
            raise ValueError("estimatedKwh debe ser > 0")
        cid = info.context["request"].headers.get("x-correlation-id")
        saga = await asyncio.to_thread(deps().orchestrator.run, fleet_id, station_id, connector_id, estimated_kwh, cid)
        return to_saga(saga)

    @strawberry.mutation
    async def top_up_wallet(self, fleet_id: strawberry.ID, amount: float) -> Wallet:
        if amount <= 0:
            raise ValueError("amount debe ser > 0")
        return to_wallet(await asyncio.to_thread(deps().billing.post, f"/wallets/{fleet_id}/topup", {"amount": amount}))


schema = strawberry.Schema(query=Query, mutation=Mutation)
