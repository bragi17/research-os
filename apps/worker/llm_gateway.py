"""
Research OS - LLM Gateway

Centralized LLM call management with model routing, caching, and tracing.
Uses LangChain with_structured_output for reliable JSON extraction via
function calling (works with proxies that don't support response_format).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, create_model
from structlog import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


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
    - Structured output via LangChain with_structured_output (function calling)
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

        # AsyncOpenAI client for raw chat calls
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        # LangChain ChatOpenAI instances (lazy-init per tier)
        self._langchain_models: dict[str, ChatOpenAI] = {}

        # Cost / token tracking
        self._total_cost_usd = 0.0
        self._call_count = 0
        self._total_tokens = 0

        # Simple response cache
        self._cache: dict[str, tuple[Any, float]] = {}

    def _get_langchain_model(self, tier: ModelTier) -> ChatOpenAI:
        """Get or create a LangChain ChatOpenAI for the given tier."""
        model_config = self.models[tier]
        key = model_config.name
        if key not in self._langchain_models:
            kwargs: dict[str, Any] = {
                "model": model_config.name,
                "api_key": self.api_key,
                "max_tokens": model_config.max_tokens,
                "temperature": 0,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._langchain_models[key] = ChatOpenAI(**kwargs)
        return self._langchain_models[key]

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
        request_params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or model_config.max_tokens,
        }

        if response_format:
            request_params["response_format"] = response_format
        if tools:
            request_params["tools"] = tools

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
                self._cache[cache_key] = (result, time.time())

            self._total_tokens += response.usage.total_tokens

            logger.debug(
                "llm_call_complete",
                model=model,
                tokens=response.usage.total_tokens,
                total_tokens=self._total_tokens,
            )

            return result

        except Exception as e:
            logger.error("llm_call_failed", error=str(e), model=model)
            raise

    # ------------------------------------------------------------------
    # Structured output via LangChain with_structured_output
    # ------------------------------------------------------------------

    async def chat_structured(
        self,
        output_schema: type[T],
        messages: list[dict[str, str]],
        tier: ModelTier = ModelTier.MEDIUM,
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
        model_config = self.models[tier]

        try:
            llm = self._get_langchain_model(tier)
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
                model=model_config.name,
                schema=output_schema.__name__,
                estimated_tokens=estimated_tokens,
                total_tokens=self._total_tokens,
            )

            return result

        except Exception as e:
            logger.error(
                "structured_output_failed",
                error=str(e),
                model=model_config.name,
                schema=output_schema.__name__,
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
                pydantic_model = _json_schema_to_pydantic(schema)
            else:
                # Use a generic wrapper that accepts any JSON
                pydantic_model = _build_generic_model_from_prompt(messages)

            result = await self.chat_structured(pydantic_model, messages, tier)
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
# JSON Schema → Pydantic model conversion
# ======================================================================


def _json_schema_to_pydantic(schema: dict[str, Any]) -> type[BaseModel]:
    """
    Convert a JSON schema dict to a dynamic Pydantic model.
    Handles common types: string, number, integer, boolean, array, object.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for name, prop in properties.items():
        field_type = _resolve_type(prop)
        if name in required:
            fields[name] = (field_type, ...)
        else:
            fields[name] = (field_type, Field(default=None))

    # If schema has no properties, create a generic container
    if not fields:
        fields["data"] = (dict[str, Any], Field(default_factory=dict))

    return create_model("DynamicSchema", **fields)


def _resolve_type(prop: dict[str, Any]) -> type:
    """Resolve a JSON schema property to a Python type."""
    t = prop.get("type", "string")
    if t == "string":
        return str | None
    if t == "number":
        return float | None
    if t == "integer":
        return int | None
    if t == "boolean":
        return bool | None
    if t == "array":
        return list[Any]
    if t == "object":
        return dict[str, Any]
    return str | None


def _build_generic_model_from_prompt(messages: list[dict[str, str]]) -> type[BaseModel]:
    """
    Analyze the system prompt to infer expected JSON keys and build
    a Pydantic model. Looks for patterns like:
      - "Output MUST be valid JSON with keys:"
      - "- key_name: type  (description)"
    """
    system_content = ""
    for msg in messages:
        if msg["role"] == "system":
            system_content = msg["content"]
            break

    # Try to extract key names from common prompt patterns
    fields: dict[str, Any] = {}

    # Pattern: "- key_name: type" or "- key_name: [type]"
    key_pattern = re.findall(
        r'[-*]\s+(\w+):\s+(str|string|int|float|number|bool|\[.*?\]|list|array|dict|object)',
        system_content,
        re.IGNORECASE,
    )
    for name, type_hint in key_pattern:
        if "list" in type_hint.lower() or "[" in type_hint or "array" in type_hint.lower():
            fields[name] = (list[Any], Field(default_factory=list))
        elif type_hint.lower() in ("str", "string"):
            fields[name] = (str, Field(default=""))
        elif type_hint.lower() in ("int", "integer", "float", "number"):
            fields[name] = (float | None, Field(default=None))
        elif type_hint.lower() in ("bool",):
            fields[name] = (bool, Field(default=False))
        elif type_hint.lower() in ("dict", "object"):
            fields[name] = (dict[str, Any], Field(default_factory=dict))
        else:
            fields[name] = (str | None, Field(default=None))

    if not fields:
        # Fallback: generic model that accepts anything
        fields["result"] = (dict[str, Any], Field(default_factory=dict))
        fields["items"] = (list[Any], Field(default_factory=list))
        fields["summary"] = (str, Field(default=""))

    return create_model("InferredOutput", **fields)


# ======================================================================
# Singleton
# ======================================================================

_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    """Get or create the singleton LLMGateway."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
