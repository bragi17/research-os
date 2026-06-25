from __future__ import annotations

import hashlib
import inspect
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.worker import llm_gateway as llm_gateway_module
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


def _workspace_profile(index: int) -> LLMProfile:
    return LLMProfile(
        id=f"profile-{index}",
        workspace_id=f"00000000-0000-0000-0000-00000000000{index}",
        provider="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        api_key=f"test-secret-key-{index}",
        api_key_preview=f"test****key-{index}",
        is_key_set=True,
        last_test_status=None,
        last_test_error=None,
        last_test_at=None,
    )


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
    api_key = "test-secret-key-1"
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(
        side_effect=RuntimeError(f"structured failed for {api_key}")
    )
    langchain_model = MagicMock()
    langchain_model.with_structured_output.return_value = structured_llm

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(return_value=_profile()),
        ),
        patch("apps.worker.llm_gateway.ChatOpenAI", return_value=langchain_model),
        patch("apps.worker.llm_gateway.logger.debug") as log_debug,
    ):
        gw = LLMGateway()
        gw.chat = AsyncMock(  # type: ignore[method-assign]
            side_effect=ValueError("raw fallback failed")
        )
        with pytest.raises(ValueError, match="raw fallback failed"):
            await gw.chat_json([{"role": "user", "content": "Return JSON"}])

    assert gw.chat.await_count == 1
    assert log_debug.call_args.args[0] == "structured_output_fallback"
    assert api_key not in str(log_debug.call_args.kwargs)


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
async def test_profile_change_keeps_previous_async_client_open() -> None:
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

    first_client.aclose.assert_not_called()


@pytest.mark.asyncio
async def test_workspace_switch_does_not_close_previous_client() -> None:
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

    first_client.aclose.assert_not_called()


@pytest.mark.asyncio
async def test_reset_gateway_async_closes_owned_async_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = MagicMock()
    first_client.aclose = AsyncMock()
    second_client = MagicMock()
    second_client.aclose = AsyncMock()
    gw = LLMGateway()
    first_key = (
        "00000000-0000-0000-0000-000000000000",
        "deepseek",
        "https://api.deepseek.com",
        "deepseek-v4-pro",
        "first",
    )
    second_key = (
        "11111111-1111-1111-1111-111111111111",
        "deepseek",
        "https://api.deepseek.com",
        "deepseek-v4-pro",
        "second",
    )
    gw._clients[first_key] = first_client
    gw._clients[second_key] = second_client

    monkeypatch.setattr(llm_gateway_module, "_gateway", gw)

    await llm_gateway_module.reset_gateway_async()

    first_client.aclose.assert_awaited_once_with()
    second_client.aclose.assert_awaited_once_with()
    assert llm_gateway_module._gateway is None


@pytest.mark.asyncio
async def test_reset_gateway_async_attempts_all_client_closes_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = MagicMock()
    first_client.aclose = AsyncMock(side_effect=RuntimeError("close failed secret"))
    second_client = MagicMock()
    second_client.aclose = AsyncMock()
    gw = LLMGateway()
    first_key = gw._profile_key(_workspace_profile(1))
    second_key = gw._profile_key(_workspace_profile(2))
    gw._clients[first_key] = first_client
    gw._clients[second_key] = second_client

    monkeypatch.setattr(llm_gateway_module, "_gateway", gw)

    await llm_gateway_module.reset_gateway_async()

    first_client.aclose.assert_awaited_once_with()
    second_client.aclose.assert_awaited_once_with()
    assert gw._clients == {}
    assert gw._profile_usage == {}
    assert llm_gateway_module._gateway is None


@pytest.mark.asyncio
async def test_background_reset_failure_log_redacts_bare_api_key() -> None:
    api_key = "test-secret-key-1"

    async def fail_with_key() -> None:
        raise RuntimeError(f"reset failed for {api_key}")

    task = asyncio.create_task(fail_with_key())
    with pytest.raises(RuntimeError):
        await task

    with patch("apps.worker.llm_gateway.logger.warning") as log_warning:
        llm_gateway_module._log_reset_task_failure(task)

    log_warning.assert_called_once()
    assert api_key not in str(log_warning.call_args)


@pytest.mark.asyncio
async def test_profile_cache_evicts_least_recently_used_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_MAX_PROFILES", "2")
    messages = [{"role": "user", "content": "bounded cache"}]
    profiles = [
        LLMProfile(
            id=f"profile-{index}",
            workspace_id=f"00000000-0000-0000-0000-00000000000{index}",
            provider="deepseek",
            label="DeepSeek",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-pro",
            api_key=f"test-secret-key-{index}",
            api_key_preview=f"test****key-{index}",
            is_key_set=True,
            last_test_status=None,
            last_test_error=None,
            last_test_at=None,
        )
        for index in range(1, 4)
    ]
    clients = [MagicMock() for _ in profiles]
    for index, client in enumerate(clients, start=1):
        client.aclose = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_response(f"R{index}"))

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(side_effect=profiles),
        ),
        patch("apps.worker.llm_gateway.AsyncOpenAI", side_effect=clients),
    ):
        gw = LLMGateway()
        first_key = gw._profile_key(profiles[0])
        await gw.chat(messages, temperature=0, max_tokens=5)
        first_cache_key = gw._get_cache_key(
            profiles[0],
            messages,
            profiles[0].model,
            0,
            5,
            None,
            None,
        )
        gw._langchain_models[(first_key, "sentinel")] = MagicMock()

        await gw.chat(messages, temperature=0, max_tokens=5)
        await gw.chat(messages, temperature=0, max_tokens=5)

    clients[0].aclose.assert_awaited_once_with()
    clients[1].aclose.assert_not_called()
    clients[2].aclose.assert_not_called()
    assert first_key not in gw._clients
    assert all(key[0] != first_key for key in gw._langchain_models)
    assert first_cache_key not in gw._cache
    assert len(gw._clients) == 2


@pytest.mark.asyncio
async def test_profile_cache_does_not_evict_active_raw_chat_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_MAX_PROFILES", "2")
    profiles = [_workspace_profile(index) for index in range(1, 5)]
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def wait_for_release(**_: object) -> MagicMock:
        first_started.set()
        await release_first.wait()
        return _response("FIRST")

    first_client = MagicMock()
    first_client.aclose = AsyncMock()
    first_client.chat.completions.create = AsyncMock(side_effect=wait_for_release)
    other_clients = [MagicMock() for _ in range(3)]
    for index, client in enumerate(other_clients, start=2):
        client.aclose = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_response(f"R{index}"))
    clients = [first_client, *other_clients]

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(side_effect=profiles),
        ),
        patch("apps.worker.llm_gateway.AsyncOpenAI", side_effect=clients),
    ):
        gw = LLMGateway()
        first_task = asyncio.create_task(
            gw.chat([{"role": "user", "content": "first"}], use_cache=False)
        )
        await first_started.wait()

        await gw.chat([{"role": "user", "content": "second"}], use_cache=False)
        await gw.chat([{"role": "user", "content": "third"}], use_cache=False)

        first_client.aclose.assert_not_called()
        assert gw._profile_key(profiles[0]) in gw._clients

        release_first.set()
        assert (await first_task)["content"] == "FIRST"

        await gw.chat([{"role": "user", "content": "fourth"}], use_cache=False)

    first_client.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_profile_cache_eviction_close_failure_still_cleans_profile_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_MAX_PROFILES", "1")
    profiles = [_workspace_profile(1), _workspace_profile(2)]
    first_client = MagicMock()
    first_client.aclose = AsyncMock(
        side_effect=RuntimeError(f"close failed {profiles[0].api_key}")
    )
    first_client.chat.completions.create = AsyncMock(return_value=_response("FIRST"))
    second_client = MagicMock()
    second_client.aclose = AsyncMock()
    second_client.chat.completions.create = AsyncMock(return_value=_response("SECOND"))
    messages = [{"role": "user", "content": "bounded cache"}]

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(side_effect=profiles),
        ),
        patch(
            "apps.worker.llm_gateway.AsyncOpenAI",
            side_effect=[first_client, second_client],
        ),
        patch("apps.worker.llm_gateway.logger.warning") as log_warning,
    ):
        gw = LLMGateway()
        first_key = gw._profile_key(profiles[0])
        await gw.chat(messages, temperature=0, max_tokens=5)
        first_cache_key = gw._get_cache_key(
            profiles[0],
            messages,
            profiles[0].model,
            0,
            5,
            None,
            None,
        )
        gw._langchain_models[(first_key, "sentinel")] = MagicMock()

        second = await gw.chat(messages, temperature=0, max_tokens=5)

    assert second["content"] == "SECOND"
    first_client.aclose.assert_awaited_once_with()
    assert first_key not in gw._clients
    assert first_key not in gw._profile_usage
    assert all(key[0] != first_key for key in gw._langchain_models)
    assert first_cache_key not in gw._cache
    assert first_cache_key not in gw._cache_profiles
    log_warning.assert_called()
    assert profiles[0].api_key not in str(log_warning.call_args)


@pytest.mark.asyncio
async def test_eviction_close_await_does_not_clear_reentered_active_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_MAX_PROFILES", "1")
    profile_a = _workspace_profile(1)
    profile_b = _workspace_profile(2)
    old_close_started = asyncio.Event()
    release_old_close = asyncio.Event()
    new_a_started = asyncio.Event()
    release_new_a = asyncio.Event()

    old_a_client = MagicMock()
    old_a_client.chat.completions.create = AsyncMock(return_value=_response("OLD-A"))

    async def close_old_a() -> None:
        old_close_started.set()
        await release_old_close.wait()

    old_a_client.aclose = AsyncMock(side_effect=close_old_a)

    b_client = MagicMock()
    b_client.chat.completions.create = AsyncMock(return_value=_response("B"))
    b_client.aclose = AsyncMock()

    new_a_client = MagicMock()

    async def wait_new_a(**_: object) -> MagicMock:
        new_a_started.set()
        await release_new_a.wait()
        return _response("NEW-A")

    new_a_client.chat.completions.create = AsyncMock(side_effect=wait_new_a)
    new_a_client.aclose = AsyncMock()

    c_client = MagicMock()
    c_client.chat.completions.create = AsyncMock(return_value=_response("C"))
    c_client.aclose = AsyncMock()

    with (
        patch(
            "apps.worker.llm_gateway.get_active_llm_profile",
            AsyncMock(side_effect=[profile_a, profile_b, profile_a, profile_b]),
        ),
        patch(
            "apps.worker.llm_gateway.AsyncOpenAI",
            side_effect=[old_a_client, b_client, new_a_client, c_client],
        ),
    ):
        gw = LLMGateway()
        await gw.chat([{"role": "user", "content": "old a"}], use_cache=False)

        evict_old_a_task = asyncio.create_task(
            gw.chat([{"role": "user", "content": "b"}], use_cache=False)
        )
        await old_close_started.wait()

        new_a_task = asyncio.create_task(
            gw.chat([{"role": "user", "content": "new a"}], use_cache=False)
        )
        await new_a_started.wait()

        release_old_close.set()
        assert (await evict_old_a_task)["content"] == "B"
        assert gw._profile_active_counts[gw._profile_key(profile_a)] == 1
        assert gw._clients[gw._profile_key(profile_a)] is new_a_client

        await gw.chat([{"role": "user", "content": "c"}], use_cache=False)
        new_a_client.aclose.assert_not_called()

        release_new_a.set()
        assert (await new_a_task)["content"] == "NEW-A"

    old_a_client.aclose.assert_awaited_once_with()


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
        gw._clients[gw._profile_key(second_profile)] = second_client
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
