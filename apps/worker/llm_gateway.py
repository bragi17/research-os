"""
Research OS - LLM Gateway

Centralized LLM call management with model routing, caching, and tracing.
Uses LangChain with_structured_output for reliable JSON extraction via
function calling (works with proxies that don't support response_format).
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
from collections import OrderedDict
from typing import Any, TypeVar

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pydantic import BaseModel
from structlog import get_logger

from apps.worker.llm import (
    DEFAULT_MODELS,
    ModelConfig,
    ModelTier,
    build_generic_model_from_prompt,
    json_schema_to_pydantic,
)
from services.llm_settings import (
    LLMProfile,
    get_active_llm_profile,
    redact_secret_text,
)

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)
ProfileKey = tuple[str, str, str, str, str]
DEFAULT_MAX_PROFILES = 32


class LLMGateway:
    """
    Centralized gateway for LLM calls.

    Features:
    - Model routing by tier
    - Structured output via LangChain with_structured_output (function calling)
    - Response caching
    - Cost tracking
    - Retry logic
    """

    def __init__(
        self,
        models: dict[ModelTier, ModelConfig] | None = None,
    ):
        self.models = models or DEFAULT_MODELS
        self._max_profiles = _configured_max_profiles()

        # AsyncOpenAI clients for raw chat calls, built per active profile.
        self._clients: dict[ProfileKey, AsyncOpenAI] = {}
        self._profile_usage: OrderedDict[ProfileKey, None] = OrderedDict()

        # LangChain ChatOpenAI instances (lazy-init per profile + tier)
        self._langchain_models: dict[tuple[ProfileKey, str], ChatOpenAI] = {}

        # Cost / token tracking
        self._total_cost_usd = 0.0
        self._call_count = 0
        self._total_tokens = 0

        # Simple response cache
        self._cache: dict[str, tuple[Any, float]] = {}
        self._cache_profiles: dict[str, ProfileKey] = {}

    def _profile_key(self, profile: LLMProfile) -> ProfileKey:
        return (
            profile.workspace_id,
            profile.provider,
            profile.base_url,
            profile.model,
            self._api_key_fingerprint(profile.api_key),
        )

    def _api_key_fingerprint(self, api_key: str | None) -> str:
        if not api_key:
            return ""
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    async def _get_profile(self) -> LLMProfile:
        profile = await get_active_llm_profile(include_secret=True)
        if not profile.api_key:
            raise ValueError("DeepSeek API key is not configured")
        return profile

    async def _close_client(self, client: AsyncOpenAI) -> None:
        close = getattr(client, "aclose", None)
        if not callable(close):
            close = getattr(client, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def _get_client(self) -> tuple[AsyncOpenAI, LLMProfile]:
        profile = await self._get_profile()
        profile_key = self._profile_key(profile)
        client = self._clients.get(profile_key)
        if client is None:
            client = AsyncOpenAI(
                api_key=profile.api_key,
                base_url=profile.base_url,
            )
            self._clients[profile_key] = client
        await self._touch_profile(profile_key)
        return client, profile

    async def _touch_profile(self, profile_key: ProfileKey) -> None:
        self._profile_usage[profile_key] = None
        self._profile_usage.move_to_end(profile_key)
        await self._evict_idle_profiles(current_profile_key=profile_key)

    async def _evict_idle_profiles(self, current_profile_key: ProfileKey) -> None:
        while len(self._profile_usage) > self._max_profiles:
            evicted_profile_key, _ = self._profile_usage.popitem(last=False)
            if evicted_profile_key == current_profile_key:
                self._profile_usage[evicted_profile_key] = None
                self._profile_usage.move_to_end(evicted_profile_key)
                continue

            client = self._clients.pop(evicted_profile_key, None)
            if client is not None:
                await self._close_client(client)

            self._langchain_models = {
                key: model
                for key, model in self._langchain_models.items()
                if key[0] != evicted_profile_key
            }
            for cache_key, profile_key in list(self._cache_profiles.items()):
                if profile_key == evicted_profile_key:
                    self._cache_profiles.pop(cache_key, None)
                    self._cache.pop(cache_key, None)

    async def aclose(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        self._profile_usage.clear()
        self._langchain_models.clear()
        self._cache.clear()
        self._cache_profiles.clear()
        for client in clients:
            await self._close_client(client)

    def _get_langchain_model(
        self,
        tier: ModelTier,
        profile: LLMProfile,
    ) -> ChatOpenAI:
        """Get or create a LangChain ChatOpenAI for the given tier."""
        model_config = self.models[tier]
        profile_key = self._profile_key(profile)
        self._profile_usage[profile_key] = None
        self._profile_usage.move_to_end(profile_key)

        key = (profile_key, str(model_config.max_tokens))
        if key not in self._langchain_models:
            self._langchain_models[key] = ChatOpenAI(
                model=profile.model,
                api_key=profile.api_key,
                base_url=profile.base_url,
                max_tokens=model_config.max_tokens,
                temperature=0,
            )
        return self._langchain_models[key]

    def _get_cache_key(
        self,
        profile: LLMProfile,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: dict | None,
        tools: list[dict] | None,
    ) -> str:
        """Generate cache key for a request."""
        key_data = {
            "profile": {
                "workspace_id": profile.workspace_id,
                "provider": profile.provider,
                "base_url": profile.base_url,
                "model": profile.model,
                "api_key_fingerprint": self._api_key_fingerprint(profile.api_key),
            },
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "tools": tools,
        }
        return hashlib.sha256(
            json.dumps(key_data, sort_keys=True, default=str).encode()
        ).hexdigest()

    # ------------------------------------------------------------------
    # Raw chat (no structured output)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        tier: ModelTier = ModelTier.MEDIUM,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        tools: list[dict] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Make a raw chat completion request."""
        client, profile = await self._get_client()
        model_config = self.models[tier]
        model = profile.model
        request_max_tokens = max_tokens or model_config.max_tokens

        # Check cache
        if use_cache and temperature < 0.1:
            cache_key = self._get_cache_key(
                profile,
                messages,
                model,
                temperature,
                request_max_tokens,
                response_format,
                tools,
            )
            cached = self._cache.get(cache_key)
            if cached:
                logger.debug("llm_cache_hit", key=cache_key[:16])
                return cached[0]

        # Build request
        request_params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": request_max_tokens,
        }

        if response_format:
            request_params["response_format"] = response_format
        if tools:
            request_params["tools"] = tools

        self._call_count += 1

        try:
            response = await client.chat.completions.create(**request_params)

            result = {
                "content": response.choices[0].message.content,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                "finish_reason": response.choices[0].finish_reason,
            }

            if response.choices[0].message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in response.choices[0].message.tool_calls
                ]

            # Cache result
            if use_cache and temperature < 0.1:
                self._cache[cache_key] = (result, time.time())
                self._cache_profiles[cache_key] = self._profile_key(profile)

            self._total_tokens += response.usage.total_tokens

            logger.debug(
                "llm_call_complete",
                model=model,
                tokens=response.usage.total_tokens,
                total_tokens=self._total_tokens,
            )

            return result

        except Exception as e:
            logger.error(
                "llm_call_failed",
                error=redact_secret_text(str(e), secrets=[profile.api_key]),
                model=model,
            )
            raise

    # ------------------------------------------------------------------
    # Structured output via LangChain with_structured_output
    # ------------------------------------------------------------------

    async def chat_structured(
        self,
        output_schema: type[T],
        messages: list[dict[str, str]],
        tier: ModelTier = ModelTier.MEDIUM,
        allow_prompt_fallback: bool = True,
    ) -> T:
        """
        Get structured output using LangChain with_structured_output.

        Uses function calling under the hood — works with any OpenAI-compatible
        API including proxies that don't support response_format: json_object.

        Args:
            output_schema: Pydantic model class defining the expected output
            messages: List of message dicts (role + content)
            tier: Model tier to use

        Returns:
            Instance of output_schema with parsed data
        """
        self._call_count += 1
        profile = await self._get_profile()
        await self._touch_profile(self._profile_key(profile))

        try:
            llm = self._get_langchain_model(tier, profile)
            structured_llm = llm.with_structured_output(output_schema)

            # Convert messages to LangChain format
            from langchain_core.messages import HumanMessage, SystemMessage

            lc_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    lc_messages.append(SystemMessage(content=msg["content"]))
                else:
                    lc_messages.append(HumanMessage(content=msg["content"]))

            result = await structured_llm.ainvoke(lc_messages)

            # Estimate tokens (LangChain doesn't expose usage from with_structured_output)
            input_chars = sum(len(m.content) for m in lc_messages)
            estimated_tokens = input_chars // 3 + 200  # rough: 3 chars/token + output
            self._total_tokens += estimated_tokens

            logger.debug(
                "structured_output_complete",
                model=profile.model,
                schema=output_schema.__name__,
                estimated_tokens=estimated_tokens,
                total_tokens=self._total_tokens,
            )

            return result

        except Exception as e:
            if not allow_prompt_fallback:
                raise

            logger.warning(
                "structured_output_failed_trying_fallback",
                error=redact_secret_text(str(e), secrets=[profile.api_key])[:100],
                model=profile.model,
                schema=output_schema.__name__,
            )

            # Fallback: use chat_json (prompt-based) and parse into Pydantic model
            try:
                json_result = await self._chat_json_prompt_fallback(
                    messages, tier, 0.0, None
                )
                return output_schema.model_validate(json_result)
            except Exception as fallback_err:
                logger.error(
                    "structured_output_fallback_also_failed",
                    error=redact_secret_text(
                        str(fallback_err),
                        secrets=[profile.api_key],
                    )[:100],
                )
            raise

    # ------------------------------------------------------------------
    # chat_json — now uses function calling via with_structured_output
    # ------------------------------------------------------------------

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        tier: ModelTier = ModelTier.MEDIUM,
        temperature: float = 0.0,
        schema: dict | None = None,
    ) -> dict[str, Any]:
        """
        Get JSON output from LLM.

        Strategy:
        1. If a JSON schema dict is provided, convert it to a Pydantic model
           and use with_structured_output (function calling)
        2. Otherwise, try function calling with a generic JSON wrapper
        3. Fall back to prompt-based JSON extraction if function calling fails

        Returns:
            Parsed JSON dict
        """
        # Strategy 1: Use structured output via function calling
        try:
            if schema:
                # Build dynamic Pydantic model from JSON schema
                pydantic_model = json_schema_to_pydantic(schema)
            else:
                # Use a generic wrapper that accepts any JSON
                pydantic_model = build_generic_model_from_prompt(messages)

            result = await self.chat_structured(
                pydantic_model,
                messages,
                tier,
                allow_prompt_fallback=False,
            )
            return result.model_dump()

        except Exception as e:
            logger.debug(
                "structured_output_fallback",
                error=str(e)[:100],
                reason="falling back to prompt-based JSON",
            )

        # Strategy 2: Fall back to prompt-based with regex extraction
        return await self._chat_json_prompt_fallback(messages, tier, temperature, schema)

    async def _chat_json_prompt_fallback(
        self,
        messages: list[dict[str, str]],
        tier: ModelTier,
        temperature: float,
        schema: dict | None,
    ) -> dict[str, Any]:
        """Fallback: prompt-based JSON extraction."""
        messages = [dict(m) for m in messages]

        json_prefix = (
            "CRITICAL: You MUST respond with ONLY valid JSON. "
            "No markdown, no explanation, no code blocks. "
            "Start with { and end with }.\n\n"
        )
        for i, msg in enumerate(messages):
            if msg["role"] == "system":
                messages[i] = {**msg, "content": json_prefix + msg["content"]}
                break

        json_suffix = "\n\nRespond with ONLY valid JSON."
        if schema:
            json_suffix += f"\nSchema:\n{json.dumps(schema, indent=2)}"
        if messages and messages[-1]["role"] == "user":
            messages[-1] = {
                **messages[-1],
                "content": messages[-1]["content"] + json_suffix,
            }

        result = await self.chat(
            messages=messages,
            tier=tier,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        content = result["content"]

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown blocks
        json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding first { ... } block
        for sc, ec in [('{', '}'), ('[', ']')]:
            start = content.find(sc)
            if start >= 0:
                end = content.rfind(ec)
                if end > start:
                    try:
                        return json.loads(content[start:end + 1])
                    except json.JSONDecodeError:
                        pass

        logger.error("json_parse_failed", content=content[:200])
        raise ValueError("Failed to parse JSON from LLM output")

    # ------------------------------------------------------------------
    # Embedding (delegates to Tongyi service)
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings using Tongyi text-embedding-v4."""
        from services.embedding import get_embedding_service

        svc = get_embedding_service()
        return await svc.embed_texts(texts)

    @property
    def total_cost_usd(self) -> float:
        """Total estimated cost in USD."""
        return self._total_cost_usd

    @property
    def call_count(self) -> int:
        """Total number of LLM calls."""
        return self._call_count

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed across all calls."""
        return self._total_tokens


# ======================================================================
# Singleton
# ======================================================================

_gateway: LLMGateway | None = None


def _configured_max_profiles() -> int:
    raw = os.getenv("LLM_GATEWAY_MAX_PROFILES")
    if raw is None:
        return DEFAULT_MAX_PROFILES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_PROFILES


def _log_reset_task_failure(task: asyncio.Task) -> None:
    try:
        task.result()
    except Exception as exc:
        logger.warning("llm_gateway.reset_failed", error=str(exc))


def reset_gateway() -> None:
    """Reset the singleton LLMGateway."""
    global _gateway
    gateway = _gateway
    _gateway = None
    if gateway is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(gateway.aclose())
    else:
        task = loop.create_task(gateway.aclose())
        task.add_done_callback(_log_reset_task_failure)


async def reset_gateway_async() -> None:
    """Reset the singleton LLMGateway and close owned clients."""
    global _gateway
    gateway = _gateway
    _gateway = None
    if gateway is not None:
        await gateway.aclose()


def get_gateway() -> LLMGateway:
    """Get or create the singleton LLMGateway."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
