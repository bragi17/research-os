"""Live probe helpers for configured literature sources."""

from __future__ import annotations

from typing import Any

from libs.schemas.literature import LiteratureSource, LiteratureSourceSettings
from services.literature_settings import (
    LiteratureSettingsRepository,
    mask_api_key,
    redact_secret_text,
)
from services.source_key_pool import KeyMaterial, SourceKeyPool


async def probe_literature_source(
    source: LiteratureSource,
    *,
    repo: LiteratureSettingsRepository | None = None,
    query: str = "machine learning reproducibility",
) -> dict[str, Any]:
    """Run a small real search against one configured literature source."""

    repository = repo or LiteratureSettingsRepository()
    settings = await repository.get_source(source)
    if not settings.configured:
        return {
            "status": "error",
            "error": f"{source.value} is not configured",
            "candidate_count": 0,
        }

    credentials = await repository.get_active_credentials(source)
    secrets = [credential.secret for credential in credentials]
    adapter = _adapter_for_source(settings, credentials)
    try:
        result = await adapter.search(query, limit=3)
    except Exception as exc:
        return {
            "status": "error",
            "error": redact_secret_text(str(exc), secrets=secrets)[:200],
            "candidate_count": 0,
        }
    finally:
        close = getattr(adapter, "close", None)
        if close is not None:
            await close()

    candidate_count = len(result.candidates)
    if result.errors:
        first_error = result.errors[0]
        kind = getattr(first_error.kind, "value", str(first_error.kind))
        message = redact_secret_text(first_error.message, secrets=secrets)[:200]
        return {
            "status": "error",
            "error": f"{kind}: {message}",
            "candidate_count": candidate_count,
        }
    if result.unavailable_reason:
        return {
            "status": "error",
            "error": redact_secret_text(result.unavailable_reason, secrets=secrets)[:200],
            "candidate_count": candidate_count,
        }
    return {"status": "ok", "error": None, "candidate_count": candidate_count}


def _adapter_for_source(
    settings: LiteratureSourceSettings,
    credentials: list[Any],
) -> Any:
    from services.literature_sources.deepxiv import DeepXivSource
    from services.literature_sources.local_library import LocalLibrarySource
    from services.literature_sources.obsidian import ObsidianSource
    from services.literature_sources.openalex import OpenAlexSource
    from services.literature_sources.semantic_scholar import SemanticScholarSource
    from services.literature_sources.web_search import WebSearchSource
    from services.literature_sources.zotero import ZoteroSource

    source = settings.source
    options = _adapter_options(source, settings.options)
    if source is LiteratureSource.LOCAL_LIBRARY:
        return LocalLibrarySource(options=options)
    if source is LiteratureSource.ZOTERO:
        return ZoteroSource(options=options)
    if source is LiteratureSource.OBSIDIAN:
        return ObsidianSource(options=options)
    if source is LiteratureSource.WEB_SEARCH:
        return WebSearchSource(
            options=options,
            api_key=_first_secret(credentials),
        )
    if source is LiteratureSource.SEMANTIC_SCHOLAR:
        return SemanticScholarSource(
            options=options,
            source_key_pool=SourceKeyPool(
                [
                    KeyMaterial(
                        id=str(credential.id) if credential.id else None,
                        secret=str(credential.secret),
                        preview=mask_api_key(str(credential.secret)),
                    )
                    for credential in credentials
                ],
                requests_per_second=_positive_float(
                    options.get("requests_per_second"),
                    1.0,
                ),
                burst_capacity=_positive_int(options.get("burst_capacity"), 1),
            ),
        )
    if source is LiteratureSource.OPENALEX:
        key_pool = None
        if credentials:
            key_pool = SourceKeyPool(
                [
                    KeyMaterial(
                        id=str(credential.id) if credential.id else None,
                        secret=str(credential.secret),
                        preview=mask_api_key(str(credential.secret)),
                    )
                    for credential in credentials
                ],
                requests_per_second=_positive_float(
                    options.get("requests_per_second"),
                    2.0,
                ),
                burst_capacity=_positive_int(options.get("burst_capacity"), 1),
            )
        return OpenAlexSource(
            options=options,
            email=options.get("email"),
            api_key=_first_secret(credentials),
            source_key_pool=key_pool,
        )
    if source is LiteratureSource.DEEPXIV:
        return DeepXivSource(options=options)
    raise ValueError(f"Unsupported literature source: {source.value}")


def _adapter_options(source: LiteratureSource, options: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(options)
    if source is LiteratureSource.ZOTERO and "path" not in normalized:
        path = normalized.get("library_path")
        if path:
            normalized["path"] = path
    if source is LiteratureSource.OBSIDIAN and "path" not in normalized:
        path = normalized.get("vault_path")
        if path:
            normalized["path"] = path
    return normalized


def _first_secret(credentials: list[Any]) -> str | None:
    for credential in credentials:
        secret = getattr(credential, "secret", "")
        if secret:
            return str(secret)
    return None


def _positive_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
