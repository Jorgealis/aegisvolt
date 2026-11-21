"""Fábrica de apps FastAPI: correlation_id, logs de cada petición, /health y /ready."""

import logging
import os
import random
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config
from .logs import correlation_id, log_event, saga_id, setup_logging

logger = logging.getLogger("aegis.http")
_SKIP_PATHS = {"/health", "/ready"}


class DomainError(Exception):
    """Error de negocio esperado (no se reintenta): 409 {"error": CODE}."""

    def __init__(self, code: str, message: str = "", status: int = 409):
        super().__init__(message or code)
        self.code, self.message, self.status = code, message or code, status


def _fault_injection_rate() -> float:
    """Para la demo de rollback del canary: % de peticiones que responden 500."""
    return float(os.getenv("FAULT_INJECTION_RATE", "0"))


def create_app(title: str) -> FastAPI:
    setup_logging()
    app = FastAPI(title=title, version=config.version())

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        t_cid = correlation_id.set(cid)
        t_sid = saga_id.set(request.headers.get("x-saga-id"))
        start = time.perf_counter()
        try:
            if request.url.path not in _SKIP_PATHS and random.random() < _fault_injection_rate():
                response = JSONResponse({"error": "INJECTED_FAULT"}, status_code=500)
            else:
                response = await call_next(request)
        except Exception:  # noqa: BLE001
            logger.exception("error no controlado")
            response = JSONResponse({"error": "INTERNAL_ERROR"}, status_code=500)
        if request.url.path not in _SKIP_PATHS:
            log_event(
                logger,
                "HTTP_REQUEST",
                level=logging.ERROR if response.status_code >= 500 else logging.INFO,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
        response.headers["x-correlation-id"] = cid
        correlation_id.reset(t_cid)
        saga_id.reset(t_sid)
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError):
        return JSONResponse({"error": exc.code, "detail": exc.message}, status_code=exc.status)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": config.service_name(), "env": config.env(), "version": config.version()}

    @app.get("/ready")
    def ready():
        return {"status": "ready"}

    return app
