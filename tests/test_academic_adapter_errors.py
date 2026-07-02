from __future__ import annotations

import httpx
import pytest

import libs.adapters.openalex as openalex_module
import libs.adapters.semantic_scholar as s2_module
from libs.adapters.openalex import OPENALEX_API_BASE, OpenAlexAdapter, OpenAlexConfig
from libs.adapters.semantic_scholar import (
    S2_GRAPH_BASE,
    RateLimitConfig,
    SemanticScholarAdapter,
)
from libs.schemas.literature import LiteratureErrorKind, LiteratureSource
from services.literature_errors import SourceRequestError


async def _no_sleep(_: float) -> None:
    return None


def test_semantic_scholar_api_key_defaults_to_one_request_per_second() -> None:
    adapter = SemanticScholarAdapter(api_key="key")

    assert adapter.rate_limit.requests_per_second == 1.0
    assert adapter.rate_limit.burst_capacity == 1


def test_openalex_retry_max_delay_defaults_to_30_seconds() -> None:
    assert OpenAlexConfig().retry_max_delay == 30.0


@pytest.mark.asyncio
async def test_semantic_scholar_429_raises_rate_limited_error_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    request_count = 0

    async def capture_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "0.25"},
            request=request,
            text="too many requests",
        )

    adapter = SemanticScholarAdapter(
        api_key="key",
        rate_limit=RateLimitConfig(
            requests_per_second=100.0,
            burst_capacity=10,
            retry_attempts=2,
            retry_base_delay=5.0,
            retry_max_delay=10.0,
        ),
    )
    adapter._client = httpx.AsyncClient(
        base_url=S2_GRAPH_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(s2_module.asyncio, "sleep", capture_sleep)

    with pytest.raises(SourceRequestError) as exc_info:
        await adapter._request_with_retry("GET", "paper/search", params={"query": "rag"})

    error = exc_info.value
    assert error.source == LiteratureSource.SEMANTIC_SCHOLAR
    assert error.kind == LiteratureErrorKind.RATE_LIMITED
    assert error.status_code == 429
    assert error.retry_after_seconds == 0.25
    assert sleep_calls == [0.25]
    assert request_count == 2

    await adapter.close()


@pytest.mark.asyncio
async def test_semantic_scholar_403_raises_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(403, request=request, text="forbidden")

    adapter = SemanticScholarAdapter(
        api_key="key",
        rate_limit=RateLimitConfig(
            requests_per_second=100.0,
            burst_capacity=10,
            retry_attempts=3,
        ),
    )
    adapter._client = httpx.AsyncClient(
        base_url=S2_GRAPH_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(s2_module.asyncio, "sleep", _no_sleep)

    with pytest.raises(SourceRequestError) as exc_info:
        await adapter._request_with_retry("GET", "paper/search", params={"query": "rag"})

    error = exc_info.value
    assert error.source == LiteratureSource.SEMANTIC_SCHOLAR
    assert error.kind == LiteratureErrorKind.CREDENTIAL_ERROR
    assert error.status_code == 403
    assert request_count == 1

    await adapter.close()


@pytest.mark.asyncio
async def test_semantic_scholar_recommendations_429_raises_rate_limited_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "1.5"},
            request=request,
            text="too many requests",
        )

    adapter = SemanticScholarAdapter(
        api_key="key",
        rate_limit=RateLimitConfig(
            requests_per_second=100.0,
            burst_capacity=10,
            retry_attempts=1,
        ),
    )
    adapter._client = httpx.AsyncClient(
        base_url=S2_GRAPH_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(s2_module.asyncio, "sleep", _no_sleep)

    with pytest.raises(SourceRequestError) as exc_info:
        await adapter.get_recommendations(["paper-1"])

    error = exc_info.value
    assert error.source == LiteratureSource.SEMANTIC_SCHOLAR
    assert error.kind == LiteratureErrorKind.RATE_LIMITED
    assert error.status_code == 429
    assert error.retry_after_seconds == 1.5

    await adapter.close()


@pytest.mark.asyncio
async def test_semantic_scholar_dataset_5xx_raises_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request, text="service unavailable")

    adapter = SemanticScholarAdapter(
        api_key="key",
        rate_limit=RateLimitConfig(
            requests_per_second=100.0,
            burst_capacity=10,
            retry_attempts=1,
        ),
    )
    adapter._client = httpx.AsyncClient(
        base_url=S2_GRAPH_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(s2_module.asyncio, "sleep", _no_sleep)

    with pytest.raises(SourceRequestError) as exc_info:
        await adapter.get_latest_release()

    error = exc_info.value
    assert error.source == LiteratureSource.SEMANTIC_SCHOLAR
    assert error.kind == LiteratureErrorKind.TRANSIENT_ERROR
    assert error.status_code == 503

    await adapter.close()


@pytest.mark.asyncio
async def test_openalex_api_key_is_sent_as_query_param_without_mutating_params() -> None:
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, request=request, json={"results": []})

    adapter = OpenAlexAdapter(
        api_key="openalex-key",
        config=OpenAlexConfig(requests_per_second=100.0),
    )
    adapter._client = httpx.AsyncClient(
        base_url=OPENALEX_API_BASE,
        transport=httpx.MockTransport(handler),
    )
    params = {"search": "rag", "mailto": "owner@example.com"}

    await adapter._request("/works", params=params, use_cache=False)

    assert params == {"search": "rag", "mailto": "owner@example.com"}
    assert captured_request is not None
    assert captured_request.url.params["api_key"] == "openalex-key"
    assert captured_request.url.params["search"] == "rag"
    assert captured_request.url.params["mailto"] == "owner@example.com"
    assert "api-key" not in captured_request.headers

    await adapter.close()


@pytest.mark.asyncio
async def test_openalex_rotates_to_next_api_key_after_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_keys: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        seen_keys.append(api_key)
        if api_key == "key-one":
            return httpx.Response(
                429,
                headers={"Retry-After": "60"},
                request=request,
                text="too many requests",
            )
        return httpx.Response(200, request=request, json={"results": [{"id": "ok"}]})

    adapter = OpenAlexAdapter(
        api_keys=["key-one", "key-two"],
        config=OpenAlexConfig(
            requests_per_second=100.0,
            retry_attempts=2,
            retry_base_delay=0.0,
            retry_max_delay=0.0,
        ),
    )
    adapter._client = httpx.AsyncClient(
        base_url=OPENALEX_API_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(openalex_module.asyncio, "sleep", _no_sleep)

    result = await adapter._request("/works", params={"search": "rag"}, use_cache=False)

    assert result == {"results": [{"id": "ok"}]}
    assert seen_keys == ["key-one", "key-two"]

    await adapter.close()


@pytest.mark.asyncio
async def test_openalex_rotates_to_next_api_key_after_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_keys: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        seen_keys.append(api_key)
        if api_key == "bad-key":
            return httpx.Response(403, request=request, text="forbidden")
        return httpx.Response(200, request=request, json={"results": []})

    adapter = OpenAlexAdapter(
        api_keys=["bad-key", "good-key"],
        config=OpenAlexConfig(
            requests_per_second=100.0,
            retry_attempts=2,
            retry_base_delay=0.0,
            retry_max_delay=0.0,
        ),
    )
    adapter._client = httpx.AsyncClient(
        base_url=OPENALEX_API_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(openalex_module.asyncio, "sleep", _no_sleep)

    result = await adapter._request("/works", params={"search": "rag"}, use_cache=False)

    assert result == {"results": []}
    assert seen_keys == ["bad-key", "good-key"]

    await adapter.close()


@pytest.mark.asyncio
async def test_openalex_429_raises_rate_limited_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(429, request=request, text="too many requests")

    adapter = OpenAlexAdapter(
        config=OpenAlexConfig(
            requests_per_second=100.0,
            retry_attempts=2,
            retry_base_delay=0.0,
            retry_max_delay=0.0,
        )
    )
    adapter._client = httpx.AsyncClient(
        base_url=OPENALEX_API_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(openalex_module.asyncio, "sleep", _no_sleep)

    with pytest.raises(SourceRequestError) as exc_info:
        await adapter._request("/works", params={"search": "rag"})

    error = exc_info.value
    assert error.source == LiteratureSource.OPENALEX
    assert error.kind == LiteratureErrorKind.RATE_LIMITED
    assert error.status_code == 429
    assert request_count == 2

    await adapter.close()


@pytest.mark.asyncio
async def test_openalex_retry_after_delay_is_capped_by_retry_max_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    request_count = 0

    async def capture_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "35589"},
                request=request,
                text="too many requests",
            )
        return httpx.Response(200, request=request, json={"results": []})

    adapter = OpenAlexAdapter(
        config=OpenAlexConfig(
            requests_per_second=100.0,
            retry_attempts=2,
            retry_base_delay=1.0,
            retry_max_delay=3.0,
        )
    )
    adapter._client = httpx.AsyncClient(
        base_url=OPENALEX_API_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(openalex_module.asyncio, "sleep", capture_sleep)

    result = await adapter._request("/works", params={"search": "rag"}, use_cache=False)

    assert result == {"results": []}
    assert sleep_calls[0] == 3.0
    assert request_count == 2

    await adapter.close()


@pytest.mark.asyncio
async def test_openalex_5xx_after_retries_raises_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(503, request=request, text="service unavailable")

    adapter = OpenAlexAdapter(
        config=OpenAlexConfig(
            requests_per_second=100.0,
            retry_attempts=2,
            retry_base_delay=0.0,
            retry_max_delay=0.0,
        )
    )
    adapter._client = httpx.AsyncClient(
        base_url=OPENALEX_API_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(openalex_module.asyncio, "sleep", _no_sleep)

    with pytest.raises(SourceRequestError) as exc_info:
        await adapter._request("/works", params={"search": "rag"})

    error = exc_info.value
    assert error.source == LiteratureSource.OPENALEX
    assert error.kind == LiteratureErrorKind.TRANSIENT_ERROR
    assert error.status_code == 503
    assert request_count == 2

    await adapter.close()
