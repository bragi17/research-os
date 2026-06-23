from __future__ import annotations

from pydantic import BaseModel, Field


class LLMSettingsUpdate(BaseModel):
    label: str = "DeepSeek"
    base_url: str = Field(default="https://api.deepseek.com", min_length=1)
    model: str = Field(default="deepseek-v4-pro", min_length=1)
    api_key: str | None = None
    clear_api_key: bool = False


class LLMTestRequest(BaseModel):
    label: str = "DeepSeek"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
