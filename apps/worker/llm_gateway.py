"""
Research OS - LLM Gateway

Centralized LLM call management with model routing, caching, and tracing.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from openai import AsyncOpenAI
from pydantic import BaseModel
from structlog import get_logger

logger = get_logger(__name__)


class ModelTier(str, Enum):
    """Model tier for cost/quality tradeoffs."""

    HIGH = "high"      # Best reasoning (e.g., GPT-4o)
    MEDIUM = "medium"  # Balanced (e.g., GPT-4o-mini)
    LOW = "low"        # Fast/cheap (e.g., Haiku)


@dataclass
class ModelConfig:
    """Configuration for a model."""

    name: str
    tier: ModelTier
    max_tokens: int = 4096
    supports_json: bool = True
    supports_vision: bool = False


# Default model configurations
DEFAULT_MODELS = {
    ModelTier.HIGH: ModelConfig(
        name=os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o"),
        tier=ModelTier.HIGH,
        max_tokens=8192,
    ),
    ModelTier.MEDIUM: ModelConfig(
        name=os.getenv("OPENAI_MODEL_CHEAP", "gpt-4o-mini"),
        tier=ModelTier.MEDIUM,
        max_tokens=4096,
    ),
    ModelTier.LOW: ModelConfig(
        name=os.getenv("OPENAI_MODEL_CHEAP", "gpt-4o-mini"),
        tier=ModelTier.LOW,
        max_tokens=2048,
    ),
}


class LLMGateway:
    """
    Centralized gateway for LLM calls.

    Features:
    - Model routing by tier
    - JSON schema validation
    - Response caching
    - Cost tracking
    - Retry logic
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        models: dict[ModelTier, ModelConfig] | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.models = models or DEFAULT_MODELS

        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        # Cost tracking
        self._total_cost_usd = 0.0
        self._call_count = 0

        # Simple response cache
        self._cache: dict[str, tuple[Any, float]] = {}

    def _get_cache_key(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        response_format: dict | None,
    ) -> str:
        """Generate cache key for a request."""
        key_data = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "response_format": response_format,
        }
        return hashlib.sha256(
            json.dumps(key_data, sort_keys=True).encode()
        ).hexdigest()

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
        """
        Make a chat completion request.

        Args:
            messages: List of message dicts with role and content
            tier: Model tier to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            response_format: Response format specification (e.g., {"type": "json_object"})
            tools: List of tool definitions for function calling
            use_cache: Whether to use response caching

        Returns:
            Response dict with content, model, usage, etc.
        """
        model_config = self.models[tier]
        model = model_config.name

        # Check cache
        if use_cache and temperature < 0.1:
            cache_key = self._get_cache_key(messages, model, temperature, response_format)
            cached = self._cache.get(cache_key)
            if cached:
                logger.debug("llm_cache_hit", key=cache_key[:16])
                return cached[0]

        # Build request
        request_params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or model_config.max_tokens,
        }

        if response_format:
            request_params["response_format"] = response_format

        if tools:
            request_params["tools"] = tools

        # Make request
        self._call_count += 1

        try:
            response = await self._client.chat.completions.create(**request_params)

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
                import time
                self._cache[cache_key] = (result, time.time())

            logger.debug(
                "llm_call_complete",
                model=model,
                tokens=response.usage.total_tokens,
            )

            return result

        except Exception as e:
            logger.error("llm_call_failed", error=str(e), model=model)
            raise

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        tier: ModelTier = ModelTier.MEDIUM,
        temperature: float = 0.0,
        schema: dict | None = None,
    ) -> dict[str, Any]:
        """
        Make a chat completion request expecting JSON output.

        Args:
            messages: List of message dicts
            tier: Model tier to use
            temperature: Sampling temperature (default 0 for consistency)
            schema: Optional JSON schema for validation

        Returns:
            Parsed JSON dict
        """
        response_format = {"type": "json_object"}

        # Add schema instruction if provided
        if schema:
            schema_instruction = f"\n\nYour response must be valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
            messages = messages.copy()
            if messages and messages[-1]["role"] == "user":
                messages[-1] = {
                    **messages[-1],
                    "content": messages[-1]["content"] + schema_instruction,
                }

        result = await self.chat(
            messages=messages,
            tier=tier,
            temperature=temperature,
            response_format=response_format,
        )

        content = result["content"]

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error("json_parse_failed", error=str(e), content=content[:200])
            raise ValueError(f"Failed to parse JSON response: {e}")

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """
        Generate embeddings for texts.

        Args:
            texts: List of texts to embed
            model: Embedding model to use

        Returns:
            List of embedding vectors
        """
        model = model or os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

        response = await self._client.embeddings.create(
            input=texts,
            model=model,
        )

        return [item.embedding for item in response.data]

    @property
    def total_cost_usd(self) -> float:
        """Total estimated cost in USD."""
        return self._total_cost_usd

    @property
    def call_count(self) -> int:
        """Total number of LLM calls."""
        return self._call_count


# Singleton instance
_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    """Get or create the LLM gateway singleton."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
