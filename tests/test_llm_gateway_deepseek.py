from __future__ import annotations

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


@pytest.mark.asyncio
async def test_chat_uses_active_deepseek_profile() -> None:
    response = MagicMock()
    response.model = "deepseek-v4-pro"
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 2
    response.choices = [MagicMock()]
    response.choices[0].message.content = "OK"
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = "stop"

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
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
async def test_get_active_llm_profile_requested_with_secret() -> None:
    response = MagicMock()
    response.model = "deepseek-v4-pro"
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 1
    response.usage.total_tokens = 2
    response.choices = [MagicMock()]
    response.choices[0].message.content = "OK"
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = "stop"

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    get_profile = AsyncMock(return_value=_profile())

    with (
        patch("apps.worker.llm_gateway.get_active_llm_profile", get_profile),
        patch("apps.worker.llm_gateway.AsyncOpenAI", return_value=client),
    ):
        gw = LLMGateway()
        await gw.chat([{"role": "user", "content": "hi"}])

    get_profile.assert_awaited_once_with(include_secret=True)
