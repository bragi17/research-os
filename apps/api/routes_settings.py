"""Settings API — read/write model configurations to .env file."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from structlog import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# .env file path
ENV_PATH = Path(os.getenv("ENV_FILE_PATH", "/root/research-os/.env"))

# Model config categories
MODEL_CATEGORIES = {
    "llm": {
        "keys": ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL_DEFAULT", "OPENAI_MODEL_CHEAP"],
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
SENSITIVE_KEYS = {"OPENAI_API_KEY", "DASHSCOPE_API_KEY", "S2_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "JWT_SECRET"}


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


@router.get("/models")
async def get_model_settings() -> dict[str, Any]:
    """Get all model configuration grouped by category."""
    env = _read_env()
    categories: list[dict[str, Any]] = []

    for cat_id, cat_info in MODEL_CATEGORIES.items():
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
async def update_model_settings(body: dict[str, str]) -> dict[str, str]:
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

    try:
        _write_env(body)

        # Also update os.environ for the current process
        for key, value in body.items():
            os.environ[key] = value

        logger.info("settings.updated", keys=list(body.keys()))
        return {"status": "updated", "keys": list(body.keys())}
    except Exception as exc:
        logger.error("settings.update_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/models/test-llm")
async def test_llm_connection() -> dict[str, Any]:
    """Test LLM API connection with current settings."""
    try:
        from apps.worker.llm_gateway import get_gateway
        gw = get_gateway()
        result = await gw.chat(
            messages=[{"role": "user", "content": "Reply with just: OK"}],
            max_tokens=5,
            temperature=0,
        )
        return {"status": "ok", "model": result.get("model", "?"), "response": result.get("content", "")}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}


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
