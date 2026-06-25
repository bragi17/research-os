from __future__ import annotations

import hashlib
import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.worker.llm_gateway import LLMGateway, ModelTier
from services.llm_settings import LLMProfile


def _profile(api_key: str | None = "test-secret-key") -> LLMProfile:
    return LLMProfile(
        id="profile-1",
        workspace_id="00000000-0000-0000-0000-000000000000",
        provider="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        api_key=api_key,
        api_key_preview="test****-key",
        is_key_set=bool(api_key),
        last_test_status=None,
        last_test_error=None,
        last_test_at=None,
    )


def _response(content: str, model: str = "deepseek-v4-pro") -> MagicMock:
    response = MagicMock()
    response.model = model
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 2
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = "stop"
    return response


@pytest.mark.asyncio
async def test_chat_uses_active_deepseek_profile() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_response("OK"))
    get_profile = AsyncMock(return_value=_profile())

    with (
        patch("apps.worker.llm_gateway.get_active_llm_profile", get_profile),
        patch("apps.worker.llm_gateway.AsyncOpenAI", return_value=client) as openai_cls,
    ):
        gw = LLMGateway()
        result = await gw.chat([{"role": "user", "content": "hi"}], tier=ModelTier.HIGH)

    openai_cls.assert_called_once_with(
        api_key="test-secret-key",
        base_url="https://api.deepseek.com",
    )
    get_profile.assert_awaited_once_with(include_secret=True)
    client.chat.completions.create.assert_awaited_once()
    assert client.chat.completions.create.await_args.kwargs["model"] == "deepseek-v4-pro"
    assert result["content"] == "OK"


def test_constructor_does_not_accept_direct_credentials() -> None:
    signature = inspect.signature(LLMGateway)

    assert "api_key" not in signature.parameters
    assert "base_url" not in signature.parameters

    with pytest.raises(TypeError):
        LLMGateway(api_key="test-secret-key")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_chat_fails_when_deepseek_key_missing() -> None:
    with patch(
        "apps.worker.llm_gateway.get_active_llm_profile",
        AsyncMock(return_value=_profile(api_key=None)),
    ):
        gw = LLMGateway()
        with pytest.raises(ValueError, match="DeepSeek API key is not configured"):
            await gw.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_redacts_api_key_from_error_logs() -> None:
    api_key = "test-secret-key-1234567890"
    provider_key = "sk-" + ("x" * 24)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError(
            f"failed Authorization: Bearer {api_key}; token {provider_key}"
        )
    )

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(return_value=_profile(api_key=api_key)),
        ),
        patch("apps.worker.llm_gateway.AsyncOpenAI", return_value=client),
        patch("apps.worker.llm_gateway.logger.error") as log_error,
    ):
        gw = LLMGateway()
        with pytest.raises(RuntimeError):
            await gw.chat([{"role": "user", "content": "hi"}])

    logged_error = log_error.call_args.kwargs["error"]
    assert api_key not in logged_error
    assert provider_key not in logged_error
    assert "[redacted]" in logged_error


@pytest.mark.asyncio
async def test_get_active_llm_profile_requested_with_secret() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_response("OK"))
    get_profile = AsyncMock(return_value=_profile())

    with (
        patch("apps.worker.llm_gateway.get_active_llm_profile", get_profile),
        patch("apps.worker.llm_gateway.AsyncOpenAI", return_value=client),
    ):
        gw = LLMGateway()
        await gw.chat([{"role": "user", "content": "hi"}])

    get_profile.assert_awaited_once_with(include_secret=True)


@pytest.mark.asyncio
async def test_chat_json_uses_one_prompt_fallback_when_structured_output_fails() -> None:
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(side_effect=RuntimeError("structured failed"))
    langchain_model = MagicMock()
    langchain_model.with_structured_output.return_value = structured_llm

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(return_value=_profile()),
        ),
        patch("apps.worker.llm_gateway.ChatOpenAI", return_value=langchain_model),
    ):
        gw = LLMGateway()
        gw.chat = AsyncMock(  # type: ignore[method-assign]
            side_effect=ValueError("raw fallback failed")
        )
        with pytest.raises(ValueError, match="raw fallback failed"):
            await gw.chat_json([{"role": "user", "content": "Return JSON"}])

    assert gw.chat.await_count == 1


@pytest.mark.parametrize(
    ("first_kwargs", "second_kwargs"),
    [
        (
            {"tools": [{"type": "function", "function": {"name": "first"}}]},
            {"tools": [{"type": "function", "function": {"name": "second"}}]},
        ),
        ({"max_tokens": 10}, {"max_tokens": 20}),
    ],
)
@pytest.mark.asyncio
async def test_low_temperature_cache_separates_tools_and_max_tokens(
    first_kwargs: dict,
    second_kwargs: dict,
) -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[_response("FIRST"), _response("SECOND")]
    )

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(return_value=_profile()),
        ),
        patch("apps.worker.llm_gateway.AsyncOpenAI", return_value=client),
    ):
        gw = LLMGateway()
        first = await gw.chat(
            [{"role": "user", "content": "hi"}],
            temperature=0,
            **first_kwargs,
        )
        second = await gw.chat(
            [{"role": "user", "content": "hi"}],
            temperature=0,
            **second_kwargs,
        )

    assert first["content"] == "FIRST"
    assert second["content"] == "SECOND"
    assert client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_profile_change_rebuilds_client_and_clears_response_cache() -> None:
    first_profile = _profile()
    second_profile = LLMProfile(
        id="profile-2",
        workspace_id=first_profile.workspace_id,
        provider="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v2",
        model="deepseek-v4-pro",
        api_key="test-secret-key",
        api_key_preview="test****-key",
        is_key_set=True,
        last_test_status=None,
        last_test_error=None,
        last_test_at=None,
    )

    first_client = MagicMock()
    first_client.chat.completions.create = AsyncMock(return_value=_response("FIRST"))
    second_client = MagicMock()
    second_client.chat.completions.create = AsyncMock(return_value=_response("SECOND"))

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(side_effect=[first_profile, second_profile]),
        ),
        patch(
            "apps.worker.llm_gateway.AsyncOpenAI",
            side_effect=[first_client, second_client],
        ) as openai_cls,
    ):
        gw = LLMGateway()
        first = await gw.chat([{"role": "user", "content": "hi"}], temperature=0)
        second = await gw.chat([{"role": "user", "content": "hi"}], temperature=0)

    assert first["content"] == "FIRST"
    assert second["content"] == "SECOND"
    assert openai_cls.call_count == 2
    first_client.chat.completions.create.assert_awaited_once()
    second_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_profile_change_closes_previous_async_client() -> None:
    first_profile = _profile()
    second_profile = LLMProfile(
        id="profile-2",
        workspace_id=first_profile.workspace_id,
        provider="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v2",
        model="deepseek-v4-pro",
        api_key="test-secret-key",
        api_key_preview="test****-key",
        is_key_set=True,
        last_test_status=None,
        last_test_error=None,
        last_test_at=None,
    )
    first_client = MagicMock()
    first_client.aclose = AsyncMock()
    first_client.chat.completions.create = AsyncMock(return_value=_response("FIRST"))
    second_client = MagicMock()
    second_client.chat.completions.create = AsyncMock(return_value=_response("SECOND"))

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(side_effect=[first_profile, second_profile]),
        ),
        patch(
            "apps.worker.llm_gateway.AsyncOpenAI",
            side_effect=[first_client, second_client],
        ),
    ):
        gw = LLMGateway()
        await gw.chat([{"role": "user", "content": "hi"}], use_cache=False)
        await gw.chat([{"role": "user", "content": "hi"}], use_cache=False)

    first_client.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workspace_change_rebuilds_client_even_with_same_credentials() -> None:
    first_profile = _profile()
    second_profile = LLMProfile(
        id="profile-2",
        workspace_id="11111111-1111-1111-1111-111111111111",
        provider=first_profile.provider,
        label=first_profile.label,
        base_url=first_profile.base_url,
        model=first_profile.model,
        api_key=first_profile.api_key,
        api_key_preview=first_profile.api_key_preview,
        is_key_set=first_profile.is_key_set,
        last_test_status=None,
        last_test_error=None,
        last_test_at=None,
    )

    first_client = MagicMock()
    first_client.chat.completions.create = AsyncMock(return_value=_response("FIRST"))
    second_client = MagicMock()
    second_client.chat.completions.create = AsyncMock(return_value=_response("SECOND"))

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(side_effect=[first_profile, second_profile]),
        ),
        patch(
            "apps.worker.llm_gateway.AsyncOpenAI",
            side_effect=[first_client, second_client],
        ) as openai_cls,
    ):
        gw = LLMGateway()
        first = await gw.chat([{"role": "user", "content": "hi"}], temperature=0)
        second = await gw.chat([{"role": "user", "content": "hi"}], temperature=0)

    assert first["content"] == "FIRST"
    assert second["content"] == "SECOND"
    assert openai_cls.call_count == 2
    first_client.chat.completions.create.assert_awaited_once()
    second_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_response_cache_is_scoped_by_workspace_even_after_interleaved_switch() -> None:
    messages = [{"role": "user", "content": "same prompt"}]
    first_profile = _profile()
    second_profile = LLMProfile(
        id="profile-2",
        workspace_id="11111111-1111-1111-1111-111111111111",
        provider=first_profile.provider,
        label=first_profile.label,
        base_url=first_profile.base_url,
        model=first_profile.model,
        api_key=first_profile.api_key,
        api_key_preview=first_profile.api_key_preview,
        is_key_set=first_profile.is_key_set,
        last_test_status=None,
        last_test_error=None,
        last_test_at=None,
    )
    stale_key_data = {
        "messages": messages,
        "model": first_profile.model,
        "temperature": 0,
        "max_tokens": 5,
        "response_format": None,
        "tools": None,
    }
    stale_cache_key = hashlib.sha256(
        json.dumps(stale_key_data, sort_keys=True, default=str).encode()
    ).hexdigest()
    second_client = MagicMock()
    second_client.chat.completions.create = AsyncMock(return_value=_response("SECOND"))

    with patch(
        "apps.worker.llm_gateway.get_active_llm_profile",
        AsyncMock(return_value=second_profile),
    ):
        gw = LLMGateway()
        gw._client = second_client
        gw._client_profile_key = gw._profile_key(second_profile)
        gw._cache[stale_cache_key] = (
            {
                "content": "FIRST",
                "model": first_profile.model,
                "usage": {},
                "finish_reason": "stop",
            },
            0,
        )

        result = await gw.chat(messages, temperature=0, max_tokens=5)

    assert result["content"] == "SECOND"
    second_client.chat.completions.create.assert_awaited_once()
