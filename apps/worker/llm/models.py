"""Model tier definitions for the worker LLM gateway."""

from dataclasses import dataclass
from enum import Enum

from services.llm_settings import DEFAULT_DEEPSEEK_MODEL


class ModelTier(str, Enum):
    """Model tier for cost/quality tradeoffs."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ModelConfig:
    """Configuration for a model tier."""

    name: str
    tier: ModelTier
    max_tokens: int = 4096
    supports_json: bool = True
    supports_vision: bool = False


DEFAULT_MODELS = {
    ModelTier.HIGH: ModelConfig(
        name=DEFAULT_DEEPSEEK_MODEL,
        tier=ModelTier.HIGH,
        max_tokens=8192,
    ),
    ModelTier.MEDIUM: ModelConfig(
        name=DEFAULT_DEEPSEEK_MODEL,
        tier=ModelTier.MEDIUM,
        max_tokens=4096,
    ),
    ModelTier.LOW: ModelConfig(
        name=DEFAULT_DEEPSEEK_MODEL,
        tier=ModelTier.LOW,
        max_tokens=2048,
    ),
}
