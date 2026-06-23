"""Settings API — read/write model configurations to .env file."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from structlog import get_logger

from libs.schemas.settings import LLMSettingsUpdate, LLMTestRequest
from services.llm_settings import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    LLMProfile,
    LLMSettingsRepository,
    invalidate_llm_config,
    redact_secret_text,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# .env file path
ENV_PATH = Path(os.getenv("ENV_FILE_PATH", "/root/research-os/.env"))

# Model config categories
MODEL_CATEGORIES = {
    "llm": {
        "keys": ["DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"],
        "label": "LLM Models",
    },
    "embedding": {
        "keys": ["DASHSCOPE_API_KEY", "DASHSCOPE_EMBEDDING_MODEL", "DASHSCOPE_EMBEDDING_DIMENSION"],
        "label": "Embedding Models",
    },
    "rerank": {
        "keys": ["DASHSCOPE_RERANK_MODEL"],
        "label": "Rerank Models",
    },
    "academic": {
        "keys": ["S2_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "OPENALEX_EMAIL", "CROSSREF_EMAIL", "UNPAYWALL_EMAIL"],
        "label": "Academic APIs",
    },
    "storage": {
        "keys": ["STORAGE_BACKEND", "LIBRARY_STORAGE_DIR", "GROBID_URL"],
        "label": "Storage & Services",
    },
}

# Keys that should be masked in GET responses
SENSITIVE_KEYS = {"DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "S2_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "JWT_SECRET"}


def _read_env() -> dict[str, str]:
    """Read all key=value pairs from .env file."""
    result: dict[str, str] = {}
    if not ENV_PATH.exists():
        return result
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _write_env(updates: dict[str, str]) -> None:
    """Update specific keys in .env file, preserving comments and structure."""
    if not ENV_PATH.exists():
        raise FileNotFoundError(f".env file not found at {ENV_PATH}")

    lines = ENV_PATH.read_text().splitlines()
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Append any new keys not found in existing file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n")


def _mask_value(key: str, value: str) -> str:
    """Mask sensitive values for display."""
    if key in SENSITIVE_KEYS and len(value) > 8:
        return value[:4] + "****" + value[-4:]
    return value


def _profile_response(profile: LLMProfile) -> dict[str, Any]:
    """Return a profile response without plaintext secrets."""
    return {
        "provider": profile.provider,
        "label": profile.label,
        "base_url": profile.base_url,
        "model": profile.model,
        "api_key_preview": profile.api_key_preview,
        "is_key_set": profile.is_key_set,
        "last_test_status": profile.last_test_status,
        "last_test_error": redact_secret_text(profile.last_test_error)
        if profile.last_test_error
        else None,
        "last_test_at": profile.last_test_at,
    }


def _llm_category(profile: LLMProfile) -> dict[str, Any]:
    return {
        "id": "llm",
        "label": MODEL_CATEGORIES["llm"]["label"],
        "profile": _profile_response(profile),
        "items": [
            {
                "key": "DEEPSEEK_API_KEY",
                "value": "",
                "display_value": profile.api_key_preview,
                "is_set": profile.is_key_set,
                "is_sensitive": True,
            },
            {
                "key": "DEEPSEEK_BASE_URL",
                "value": profile.base_url,
                "is_set": bool(profile.base_url),
                "is_sensitive": False,
            },
            {
                "key": "DEEPSEEK_MODEL",
                "value": profile.model,
                "is_set": bool(profile.model),
                "is_sensitive": False,
            },
        ],
    }


def _reset_llm_runtime() -> None:
    invalidate_llm_config()
    try:
        from apps.worker.llm_gateway import reset_gateway

        reset_gateway()
    except Exception:
        pass


def _reset_embedding_runtime() -> None:
    try:
        import services.embedding as emb_mod

        emb_mod._service = None
    except Exception:
        pass


@router.get("/models")
async def get_model_settings() -> dict[str, Any]:
    """Get all model configuration grouped by category."""
    env = _read_env()
    profile = await LLMSettingsRepository().get_active_profile(include_secret=False)
    categories: list[dict[str, Any]] = [_llm_category(profile)]

    for cat_id, cat_info in MODEL_CATEGORIES.items():
        if cat_id == "llm":
            continue
        items: list[dict[str, Any]] = []
        for key in cat_info["keys"]:
            value = env.get(key, "")
            items.append({
                "key": key,
                "value": _mask_value(key, value),
                "is_set": bool(value),
                "is_sensitive": key in SENSITIVE_KEYS,
            })
        categories.append({
            "id": cat_id,
            "label": cat_info["label"],
            "items": items,
        })

    return {"categories": categories}


@router.put("/models")
async def update_model_settings(body: dict[str, str]) -> dict[str, Any]:
    """Update model configuration. Body is {KEY: VALUE} pairs."""
    if not body:
        raise HTTPException(status_code=400, detail="No settings provided")

    # Validate: only allow known keys
    all_known_keys = set()
    for cat in MODEL_CATEGORIES.values():
        all_known_keys.update(cat["keys"])

    unknown = set(body.keys()) - all_known_keys
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown keys: {unknown}")

    deepseek_keys = set(MODEL_CATEGORIES["llm"]["keys"])
    requested_deepseek_keys = set(body.keys()) & deepseek_keys
    if requested_deepseek_keys:
        raise HTTPException(
            status_code=400,
            detail="DeepSeek LLM settings must be updated via /api/v1/settings/llm",
        )

    try:
        _write_env(body)

        # Update os.environ for the current process
        for key, value in body.items():
            os.environ[key] = value

        # Preserve existing runtime refresh behavior after model updates.
        _reset_llm_runtime()
        _reset_embedding_runtime()

        logger.info("settings.updated", keys=list(body.keys()))
        return {"status": "updated", "keys": list(body.keys())}
    except Exception as exc:
        logger.error("settings.update_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/llm")
async def update_llm_settings(body: LLMSettingsUpdate) -> dict[str, Any]:
    """Update active DeepSeek LLM profile without returning plaintext secrets."""
    try:
        profile = await LLMSettingsRepository().upsert_active_profile(
            label=body.label,
            base_url=body.base_url,
            model=body.model,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
        )
        _reset_llm_runtime()
        return _profile_response(profile)
    except Exception as exc:
        error = redact_secret_text(str(exc), secrets=[body.api_key])[:200]
        logger.error("settings.llm_update_failed", error=error)
        raise HTTPException(status_code=500, detail=error)


@router.delete("/llm/api-key")
async def delete_llm_api_key() -> dict[str, Any]:
    """Clear the active DeepSeek API key."""
    try:
        profile = await LLMSettingsRepository().clear_api_key()
        _reset_llm_runtime()
        return _profile_response(profile)
    except Exception as exc:
        error = redact_secret_text(str(exc))[:200]
        logger.error("settings.llm_key_delete_failed", error=error)
        raise HTTPException(status_code=500, detail=error)


async def _test_saved_llm_connection() -> dict[str, Any]:
    """Test LLM API connection with current settings."""
    repo = LLMSettingsRepository()
    profile = await repo.peek_active_profile(include_secret=False)
    if profile is None or not profile.is_key_set:
        return {
            "status": "error",
            "error": "DeepSeek API key is not configured",
        }

    try:
        from apps.worker.llm_gateway import get_gateway

        gw = get_gateway()
        result = await gw.chat(
            messages=[{"role": "user", "content": "Reply with just: OK"}],
            max_tokens=5,
            temperature=0,
        )
        await repo.record_test_result("ok", None)
        return {"status": "ok", "model": result.get("model", "?"), "response": result.get("content", "")}
    except Exception as exc:
        error = redact_secret_text(str(exc))[:200]
        await repo.record_test_result("error", error)
        return {"status": "error", "error": error}


@router.post("/llm/test")
async def test_llm_settings(body: LLMTestRequest | None = None) -> dict[str, Any]:
    """Test the saved active DeepSeek profile."""
    if body and (body.base_url or body.model or body.api_key):
        raise HTTPException(
            status_code=400,
            detail="Only saved active profile testing is supported",
        )
    return await _test_saved_llm_connection()


@router.post("/models/test-llm")
async def test_llm_connection() -> dict[str, Any]:
    """Legacy compatibility alias for testing the saved LLM profile."""
    return await _test_saved_llm_connection()


@router.post("/models/test-embedding")
async def test_embedding_connection() -> dict[str, Any]:
    """Test embedding API connection."""
    try:
        from services.embedding import get_embedding_service
        svc = get_embedding_service()
        vectors = await svc.embed_texts(["test"], dimension=1024)
        return {"status": "ok", "dimension": len(vectors[0]) if vectors else 0}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}
