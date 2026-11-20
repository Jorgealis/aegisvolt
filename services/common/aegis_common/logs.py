"""Logs estructurados en JSON con correlation_id, enviados a CloudWatch Logs.

Cada línea lleva ts, level, env, service, version, correlation_id, saga_id y
event. Se escriben siempre en stdout y, si CLOUDWATCH_LOG_GROUP está definido,
también al grupo /aegisvolt/<env>/<servicio> con put_log_events (desde EKS el
tráfico sale por el Interface VPC Endpoint de "logs").
"""

import atexit
import contextvars
import json
import logging
import os
import queue
import socket
import sys
import threading
import time
from datetime import UTC, datetime

from . import aws, config

correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
saga_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("saga_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "env": config.env(),
            "service": config.service_name(),
            "version": config.version(),
            "correlation_id": correlation_id.get(),
            "saga_id": saga_id.get(),
            "message": record.getMessage(),
        }
        data.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str, ensure_ascii=False)


class CloudWatchHandler(logging.Handler):
    """Encola los eventos y un hilo los envía en lotes cada 2 s (no bloquea las peticiones)."""

    def __init__(self, group: str, stream: str, flush_seconds: float = 2.0):
        super().__init__()
        self.group, self.stream, self.flush_seconds = group, stream, flush_seconds
        self._queue: queue.Queue = queue.Queue(maxsize=10_000)
        self._lock = threading.Lock()
        self._ready = False
        threading.Thread(target=self._loop, daemon=True, name="cloudwatch-logs").start()
        atexit.register(self.flush)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait({"timestamp": int(record.created * 1000), "message": self.format(record)})
        except queue.Full:
            pass  # nunca tumbar el servicio por los logs

    def _ensure_stream(self) -> None:
        if self._ready:
            return
        try:
            aws.logs().create_log_stream(logGroupName=self.group, logStreamName=self.stream)
        except aws.logs().exceptions.ResourceAlreadyExistsException:
            pass
        self._ready = True

    def flush(self) -> None:
        with self._lock:
            events = []
            while not self._queue.empty() and len(events) < 1000:
                events.append(self._queue.get_nowait())
            if not events:
                return
            try:
                self._ensure_stream()
                events.sort(key=lambda e: e["timestamp"])
                aws.logs().put_log_events(logGroupName=self.group, logStreamName=self.stream, logEvents=events)
            except Exception as exc:  # noqa: BLE001 - se informa por stderr y se sigue
                print(f"[cloudwatch-logs] envío fallido: {exc}", file=sys.stderr)

    def _loop(self) -> None:
        while True:
            time.sleep(self.flush_seconds)
            self.flush()


_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    formatter = JsonFormatter()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    root.addHandler(stdout)

    group = os.getenv("CLOUDWATCH_LOG_GROUP")
    if group:
        stream = f"{config.service_name()}/{socket.gethostname()}"
        cw = CloudWatchHandler(group, stream)
        cw.setFormatter(formatter)
        root.addHandler(cw)

    # uvicorn/botocore: que pasen por el formato JSON y sin ruido.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """Escribe un evento de negocio: {"event": "REFUND_APPLIED", "amount": 42.5, ...}."""
    logger.log(level, event, extra={"fields": {"event": event, **fields}})
