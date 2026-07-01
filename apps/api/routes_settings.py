"""Settings API — read/write model configurations to .env file."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from structlog import get_logger

from apps.api.auth import get_current_user
from apps.api.tenancy import WorkspaceContext
from libs.schemas.literature import LiteratureSource, LiteratureSourceUpdate
from libs.schemas.settings import LLMSettingsUpdate, LLMTestRequest
from services.literature_settings import LiteratureSettingsRepository
from services.literature_source_probe import probe_literature_source
from services.llm_settings import (
    DEEPSEEK_PROVIDER,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_LABEL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_WORKSPACE_ID,
    LLMProfile,
    LLMSettingsRepository,
    invalidate_llm_config,
    mask_api_key,
    redact_secret_text,
)
from services.workspace_context import DEFAULT_WORKSPACE_UUID, workspace_context

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# .env file path
ENV_PATH = Path(os.getenv("ENV_FILE_PATH", "/root/research-os/.env"))
DEFAULT_EXPERIMENT_ROOT = "/data/research-os/experiments"

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
        "keys": [
            "RESEARCH_OS_WORKSPACE_ROOT",
            "STORAGE_BACKEND",
            "LIBRARY_STORAGE_DIR",
            "GROBID_URL",
        ],
        "label": "Storage & Services",
    },
}

DEFAULT_SETTING_VALUES = {
    "RESEARCH_OS_WORKSPACE_ROOT": DEFAULT_EXPERIMENT_ROOT,
}
MISSING_CREDENTIAL_ENCRYPTION_KEY_FRAGMENT = "CREDENTIAL_ENCRYPTION_KEY is required"
GLOBAL_SETTINGS_OPERATOR_ROLES = {"admin", "operator", "production_operator"}

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


def _effective_setting_value(key: str, env: dict[str, str]) -> str:
    value = env.get(key)
    if value is None:
        value = os.getenv(key)
    if value is None or value.strip() == "":
        value = DEFAULT_SETTING_VALUES.get(key, "")
    return value


def _llm_settings_error_status(error: str) -> int:
    if MISSING_CREDENTIAL_ENCRYPTION_KEY_FRAGMENT in error:
        return 400
    return 500


def _require_global_settings_operator(user: dict[str, Any]) -> None:
    if user.get("role") not in GLOBAL_SETTINGS_OPERATOR_ROLES:
        raise HTTPException(status_code=403, detail="Global settings require operator role")


def _fallback_llm_profile(
    env: dict[str, str],
    error: Exception | None = None,
    workspace_id: Any = DEFAULT_WORKSPACE_ID,
) -> LLMProfile:
    api_key = (
        _effective_setting_value("DEEPSEEK_API_KEY", env)
        if str(workspace_id) == str(DEFAULT_WORKSPACE_UUID)
        else ""
    )
    return LLMProfile(
        id=None,
        workspace_id=str(workspace_id),
        provider=DEEPSEEK_PROVIDER,
        label=DEFAULT_DEEPSEEK_LABEL,
        base_url=_effective_setting_value("DEEPSEEK_BASE_URL", env)
        or DEFAULT_DEEPSEEK_BASE_URL,
        model=_effective_setting_value("DEEPSEEK_MODEL", env)
        or DEFAULT_DEEPSEEK_MODEL,
        api_key=None,
        api_key_preview=mask_api_key(api_key),
        is_key_set=bool(api_key),
        last_test_status="error" if error else None,
        last_test_error=redact_secret_text(str(error)) if error else None,
        last_test_at=None,
    )


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


async def _literature_secret_values(
    repo: LiteratureSettingsRepository,
    source: LiteratureSource | None = None,
) -> list[str]:
    sources = [source] if source is not None else list(LiteratureSource)
    secrets: list[str] = []
    seen: set[str] = set()
    for literature_source in sources:
        try:
            credentials = await repo.get_active_credentials(literature_source)
        except Exception:
            continue
        for credential in credentials:
            secret = getattr(credential, "secret", "")
            if secret and secret not in seen:
                secrets.append(secret)
                seen.add(secret)
    return secrets


async def _literature_sources_category() -> dict[str, Any]:
    repo = LiteratureSettingsRepository()
    try:
        sources = await repo.list_sources(include_secrets=False)
    except Exception as exc:
        secrets = await _literature_secret_values(repo)
        logger.warning(
            "settings.literature_sources_fallback_failed",
            error=redact_secret_text(str(exc), secrets=secrets)[:200],
        )
        sources = []
    return {
        "id": "literature_sources",
        "label": "Literature Sources",
        "items": [],
        "sources": [source.model_dump(mode="json") for source in sources],
    }


async def _reset_llm_runtime() -> None:
    invalidate_llm_config()
    try:
        from apps.worker.llm_gateway import reset_gateway_async

        await reset_gateway_async()
    except Exception as exc:
        logger.warning(
            "settings.llm_runtime_reset_failed",
            error_type=type(exc).__name__,
            message="LLM runtime reset failed",
        )


def _reset_embedding_runtime() -> None:
    try:
        import services.embedding as emb_mod

        emb_mod._service = None
    except Exception:
        pass


@router.get("/models")
async def get_model_settings(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get all model configuration grouped by category."""
    ctx = WorkspaceContext.from_user(user)
    env = _read_env()
    try:
        profile = await LLMSettingsRepository(
            workspace_id=ctx.workspace_id,
        ).get_active_profile(include_secret=False)
    except Exception as exc:
        logger.warning(
            "settings.llm_profile_fallback",
            error=redact_secret_text(str(exc))[:200],
        )
        profile = _fallback_llm_profile(env, exc, workspace_id=ctx.workspace_id)
    categories: list[dict[str, Any]] = [_llm_category(profile)]

    for cat_id, cat_info in MODEL_CATEGORIES.items():
        if cat_id == "llm":
            continue
        items: list[dict[str, Any]] = []
        for key in cat_info["keys"]:
            value = _effective_setting_value(key, env)
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
        if cat_id == "academic":
            categories.append(await _literature_sources_category())

    return {"categories": categories}


@router.put("/models")
async def update_model_settings(
    body: dict[str, str],
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Update model configuration. Body is {KEY: VALUE} pairs."""
    _require_global_settings_operator(user)
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
            detail="LLM settings must be updated via /api/v1/settings/llm",
        )

    try:
        _write_env(body)

        # Update os.environ for the current process
        for key, value in body.items():
            os.environ[key] = value

        # Preserve existing runtime refresh behavior after model updates.
        await _reset_llm_runtime()
        _reset_embedding_runtime()

        logger.info("settings.updated", keys=list(body.keys()))
        return {"status": "updated", "keys": list(body.keys())}
    except Exception as exc:
        logger.error("settings.update_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/llm")
async def update_llm_settings(
    body: LLMSettingsUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Update the active LLM profile without returning plaintext secrets."""
    ctx = WorkspaceContext.from_user(user)
    try:
        profile = await LLMSettingsRepository(
            workspace_id=ctx.workspace_id,
        ).upsert_active_profile(
            provider=body.provider,
            label=body.label,
            base_url=body.base_url,
            model=body.model,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
        )
        await _reset_llm_runtime()
        return _profile_response(profile)
    except Exception as exc:
        error = redact_secret_text(str(exc), secrets=[body.api_key])[:200]
        logger.error("settings.llm_update_failed", error=error)
        raise HTTPException(status_code=_llm_settings_error_status(error), detail=error) from exc


@router.delete("/llm/api-key")
async def delete_llm_api_key(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Clear the active LLM API key."""
    ctx = WorkspaceContext.from_user(user)
    try:
        profile = await LLMSettingsRepository(
            workspace_id=ctx.workspace_id,
        ).clear_api_key()
        await _reset_llm_runtime()
        return _profile_response(profile)
    except Exception as exc:
        error = redact_secret_text(str(exc))[:200]
        logger.error("settings.llm_key_delete_failed", error=error)
        raise HTTPException(
            status_code=_llm_settings_error_status(error),
            detail=error,
        ) from exc


@router.put("/literature/{source}")
async def update_literature_source(
    source: LiteratureSource,
    body: LiteratureSourceUpdate,
) -> dict[str, Any]:
    new_credentials = [
        credential.get_secret_value() for credential in body.new_credentials
    ]
    repo = LiteratureSettingsRepository()
    try:
        updated = await repo.update_source(
            source,
            enabled=body.enabled,
            options=body.options,
            new_credentials=new_credentials,
            clear_credential_ids=[
                str(credential_id) for credential_id in body.clear_credential_ids
            ],
        )
        return updated.model_dump(mode="json")
    except ValueError as exc:
        secrets = new_credentials + await _literature_secret_values(repo, source)
        error = redact_secret_text(str(exc), secrets=secrets)[:200]
        logger.error(
            "settings.literature_update_failed",
            source=source.value,
            error=error,
        )
        raise HTTPException(status_code=400, detail=error) from exc
    except Exception as exc:
        secrets = new_credentials + await _literature_secret_values(repo, source)
        error = redact_secret_text(str(exc), secrets=secrets)[:200]
        logger.error(
            "settings.literature_update_failed",
            source=source.value,
            error=error,
        )
        raise HTTPException(
            status_code=_llm_settings_error_status(error),
            detail=error,
        ) from exc


@router.post("/literature/{source}/test")
async def test_literature_source(source: LiteratureSource) -> dict[str, Any]:
    repo = LiteratureSettingsRepository()
    try:
        settings = await repo.get_source(source)
        if settings.configured:
            result = await probe_literature_source(source, repo=repo)
            status = str(result.get("status") or "error")
            error = result.get("error")
        else:
            status = "error"
            error = f"{source.value} is not configured"
        await repo.record_source_test(source, status, error)
        return {"status": status, "error": error}
    except Exception as exc:
        secrets = await _literature_secret_values(repo, source)
        error = redact_secret_text(str(exc), secrets=secrets)[:200]
        try:
            await repo.record_source_test(source, "error", error)
        except Exception as record_exc:
            logger.warning(
                "settings.literature_test_record_failed",
                source=source.value,
                error=redact_secret_text(str(record_exc), secrets=secrets)[:200],
            )
        return {"status": "error", "error": error}


async def _test_saved_llm_connection(workspace_id: Any) -> dict[str, Any]:
    """Test LLM API connection with current settings."""
    repo = LLMSettingsRepository(workspace_id=workspace_id)
    profile = await repo.peek_active_profile(include_secret=True)
    if profile is None or not profile.is_key_set:
        return {
            "status": "error",
            "error": "LLM API key is not configured",
        }

    try:
        from apps.worker.llm_gateway import get_gateway

        gw = get_gateway()
        with workspace_context(workspace_id):
            result = await gw.chat(
                messages=[{"role": "user", "content": "Reply with just: OK"}],
                max_tokens=5,
                temperature=0,
            )
        await repo.record_test_result("ok", None)
        return {"status": "ok", "model": result.get("model", "?"), "response": result.get("content", "")}
    except Exception as exc:
        error = redact_secret_text(str(exc), secrets=[profile.api_key])[:200]
        await repo.record_test_result("error", error)
        return {"status": "error", "error": error}


@router.post("/llm/test")
async def test_llm_settings(
    body: LLMTestRequest | None = None,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Test the saved active LLM profile."""
    ctx = WorkspaceContext.from_user(user)
    if body and (body.base_url or body.model or body.api_key):
        raise HTTPException(
            status_code=400,
            detail="Only saved active profile testing is supported",
        )
    return await _test_saved_llm_connection(ctx.workspace_id)


@router.post("/models/test-llm")
async def test_llm_connection(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Legacy compatibility alias for testing the saved LLM profile."""
    ctx = WorkspaceContext.from_user(user)
    return await _test_saved_llm_connection(ctx.workspace_id)


@router.post("/models/test-embedding")
async def test_embedding_connection(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Test embedding API connection."""
    _require_global_settings_operator(user)
    try:
        from services.embedding import get_embedding_service
        svc = get_embedding_service()
        vectors = await svc.embed_texts(["test"], dimension=1024)
        return {"status": "ok", "dimension": len(vectors[0]) if vectors else 0}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}
