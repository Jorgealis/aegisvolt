"""Reintentos con backoff solo ante fallos transitorios."""

import httpx
import pytest

from aegis_common.logs import correlation_id
from graphql_gateway.clients import ServiceClient, ServiceError


def client_with(responses, seen):
    it = iter(responses)

    def handler(request):
        seen.append(request)
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    return ServiceClient("svc", "http://svc", http=httpx.Client(base_url="http://svc", transport=httpx.MockTransport(handler)), backoff=0)


def test_retries_5xx_then_succeeds():
    seen = []
    c = client_with([httpx.Response(503), httpx.ConnectTimeout("t"), httpx.Response(200, json={"ok": True})], seen)
    assert c.post("/x") == {"ok": True}
    assert len(seen) == 3


def test_business_error_is_not_retried():
    seen = []
    c = client_with([httpx.Response(409, json={"error": "INSUFFICIENT_FUNDS"})], seen)
    with pytest.raises(ServiceError) as e:
        c.post("/charges")
    assert e.value.code == "INSUFFICIENT_FUNDS" and not e.value.transient
    assert len(seen) == 1


def test_gives_up_after_retries_as_transient():
    seen = []
    c = client_with([httpx.Response(500)] * 4, seen)
    with pytest.raises(ServiceError) as e:
        c.post("/x")
    assert e.value.transient and len(seen) == 4  # 1 intento + 3 reintentos


def test_propagates_correlation_id():
    seen = []
    c = client_with([httpx.Response(200, json={})], seen)
    token = correlation_id.set("abc-123")
    try:
        c.get("/x")
    finally:
        correlation_id.reset(token)
    assert seen[0].headers["x-correlation-id"] == "abc-123"
