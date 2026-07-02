"""
Research OS - Shared Mode Graph Utilities

Shared state definition, helper functions, and reusable node logic
extracted from the v1 graph_state.py for use across all mode-specific graphs.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal, overload
from uuid import UUID, uuid4

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from structlog import get_logger

from apps.worker.llm_gateway import LLMGateway, ModelTier
from libs.adapters.openalex import OpenAlexAdapter
from libs.adapters.semantic_scholar import SemanticScholarAdapter
from libs.adapters.scholar_fusion import FusedPaper, ScholarFusionService
from libs.prompts.templates import (
    CLAIM_OUTPUT_SCHEMA,
    PAPER_SUMMARY_SCHEMA,
    PromptName,
    get_system_prompt,
)
from services.parser import detect_arxiv_id, parse_paper

logger = get_logger(__name__)

LiteratureSearchResult = tuple[list[str], list[str], list[str], dict[str, str]]
LiteratureSearchResultWithReport = tuple[
    list[str],
    list[str],
    list[str],
    dict[str, str],
    dict[str, Any] | None,
]

# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

_COST_PER_1K_INPUT = {
    ModelTier.HIGH: 0.005,
    ModelTier.MEDIUM: 0.00015,
    ModelTier.LOW: 0.00008,
}
_COST_PER_1K_OUTPUT = {
    ModelTier.HIGH: 0.015,
    ModelTier.MEDIUM: 0.0006,
    ModelTier.LOW: 0.0004,
}


def _estimate_cost(result: dict[str, Any], tier: ModelTier) -> float:
    """Estimate USD cost from an LLM result dict containing usage info."""
    usage = result.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cost = (
        (prompt_tokens / 1000) * _COST_PER_1K_INPUT.get(tier, 0.005)
        + (completion_tokens / 1000) * _COST_PER_1K_OUTPUT.get(tier, 0.015)
    )
    return cost


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------


def _normalize_title(title: str) -> str:
    """Normalize a paper title for deduplication."""
    if not title:
        return ""
    normalized = title.lower()
    normalized = "".join(c if c.isalnum() or c.isspace() else " " for c in normalized)
    return " ".join(normalized.split())


def _stable_unique(values: list[str]) -> list[str]:
    """Return values deduplicated in first-seen order."""
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


# ---------------------------------------------------------------------------
# Progress event emitter — writes fine-grained actions to run_event table
# ---------------------------------------------------------------------------


async def emit_progress(
    run_id: UUID | str,
    stage: str,
    action: str,
    detail: str = "",
    severity: str = "info",
    meta: dict[str, Any] | None = None,
) -> None:
    """
    Emit a fine-grained progress event to the database.

    Examples:
        emit_progress(run_id, "candidate_retrieval", "searching",
                      "Querying Semantic Scholar for '3D anomaly detection'")
        emit_progress(run_id, "candidate_retrieval", "result",
                      "Found 50 papers from Semantic Scholar")
        emit_progress(run_id, "deep_reading", "reading",
                      "Reading paper: 'PointAD: A Framework for...'")
    """
    try:
        from apps.api.database import create_event
        payload: dict[str, Any] = {
            "stage": stage,
            "action": action,
            "message": detail,
        }
        if meta:
            payload.update(meta)
        await create_event(
            run_id=run_id if isinstance(run_id, UUID) else UUID(str(run_id)),
            event_type=f"progress.{stage}.{action}",
            severity=severity,
            payload=payload,
        )
    except Exception as exc:
        logger.debug("emit_progress_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Shared ModeGraphState
# ---------------------------------------------------------------------------


class ModeGraphState(BaseModel):
    """
    Shared state for all mode-specific LangGraph workflows.

    Extends the v1 GraphState with v2 fields for multi-mode support.
    """

    # Core identification
    run_id: UUID = Field(default_factory=uuid4)
    project_id: UUID | None = None
    thread_id: str = ""
    mode: str = "atlas"
    current_stage: str = "plan"

    # Research configuration
    topic: str = ""
    goal_type: str = "survey_plus_innovations"
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)

    # Budget tracking
    max_papers: int = 150
    max_fulltext_reads: int = 40
    max_cost_usd: float = 30.0
    current_cost_usd: float = 0.0
    papers_discovered: int = 0
    papers_read: int = 0

    # Papers
    seed_paper_ids: list[str] = Field(default_factory=list)
    candidate_paper_ids: list[str] = Field(default_factory=list)
    selected_paper_ids: list[str] = Field(default_factory=list)
    read_paper_ids: list[str] = Field(default_factory=list)

    # Queries
    pending_queries: list[dict[str, Any]] = Field(default_factory=list)
    executed_queries: list[str] = Field(default_factory=list)

    # Analysis
    clusters: list[dict[str, Any]] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)

    # Hypotheses
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    verified_hypothesis_ids: list[str] = Field(default_factory=list)
    rejected_hypothesis_ids: list[str] = Field(default_factory=list)

    # Control flow
    current_step: str = "init"
    iteration_count: int = 0
    max_iterations: int = 10
    saturation_score: float = 0.0
    should_pause: bool = False
    pause_reason: str | None = None
    should_stop: bool = False
    stop_reason: str | None = None

    # Messages (for LLM interactions — accepts AIMessage, HumanMessage, or dicts)
    messages: Annotated[list[Any], add_messages] = Field(
        default_factory=list
    )

    # Outputs
    report_markdown: str = ""
    export_urls: list[str] = Field(default_factory=list)
    paper_summaries: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    experiments: list[dict[str, Any]] = Field(default_factory=list)

    # Errors and warnings
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # ---- V2 additions ----
    domain_id: str | None = None
    pain_points: list[dict[str, Any]] = Field(default_factory=list)
    idea_cards: list[dict[str, Any]] = Field(default_factory=list)
    timeline_data: list[dict[str, Any]] = Field(default_factory=list)
    taxonomy_tree: dict[str, Any] = Field(default_factory=dict)
    reading_path: list[dict[str, Any]] = Field(default_factory=list)
    comparison_matrix: list[dict[str, Any]] = Field(default_factory=list)
    context_bundle: dict[str, Any] = Field(default_factory=dict)
    mindmap_json: dict[str, Any] = Field(default_factory=dict)
    figures: list[dict[str, Any]] = Field(default_factory=list)

    # Library integration
    library_seeds: list[dict[str, Any]] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


# ---------------------------------------------------------------------------
# Shared conditional edge: check_should_continue
# ---------------------------------------------------------------------------


def check_should_continue(
    state: ModeGraphState,
) -> Literal["continue", "pause", "stop"]:
    """Determine whether the graph should continue, pause, or stop."""
    if state.should_stop:
        return "stop"
    if state.should_pause:
        return "pause"
    # max_cost check removed — we display token usage instead of limiting
    if state.papers_read >= state.max_fulltext_reads:
        return "pause"
    if state.saturation_score > 0.9:
        return "stop"
    if state.iteration_count >= state.max_iterations:
        return "stop"
    return "continue"


# ---------------------------------------------------------------------------
# Shared reusable async helpers
# ---------------------------------------------------------------------------


@overload
async def search_academic_sources(
    topic: str,
    queries: list[dict[str, Any]],
    keywords: list[str] | None = None,
    existing_titles: set[str] | None = None,
    return_report: Literal[False] = False,
    coordinator: Any | None = None,
) -> LiteratureSearchResult:
    ...


@overload
async def search_academic_sources(
    topic: str,
    queries: list[dict[str, Any]],
    keywords: list[str] | None = None,
    existing_titles: set[str] | None = None,
    return_report: Literal[True] = True,
    coordinator: Any | None = None,
) -> LiteratureSearchResultWithReport:
    ...


async def search_academic_sources(
    topic: str,
    queries: list[dict[str, Any]],
    keywords: list[str] | None = None,
    existing_titles: set[str] | None = None,
    return_report: bool = False,
    coordinator: Any | None = None,
) -> LiteratureSearchResult | LiteratureSearchResultWithReport:
    """
    Unified search across configured literature sources.

    Returns:
        (new_candidate_ids, executed_query_texts, error_messages, id_to_title_map)
    """
    executed = _executed_query_texts(topic, queries)
    owns_coordinator = coordinator is None
    if coordinator is None:
        try:
            coordinator = await _build_literature_search_coordinator()
        except Exception as exc:
            if not _is_missing_literature_settings_table(exc):
                raise
            logger.warning(
                "search_academic.literature_settings_unavailable",
                error=str(exc),
            )
            result = await _legacy_search_academic_sources(
                topic=topic,
                queries=queries,
                existing_titles=existing_titles,
            )
            if return_report:
                return (*result, None)
            return result

    try:
        candidates, report = await coordinator.search(
            topic=topic,
            queries=queries,
            limit_per_query=50,
        )
    finally:
        if owns_coordinator:
            await coordinator.close()

    seen_titles: set[str] = set(existing_titles or set())
    new_candidates: list[str] = []
    id_to_title: dict[str, str] = {}
    for candidate in candidates:
        candidate_id = (
            _verification_candidate_id(candidate)
            if return_report
            else _legacy_candidate_id(candidate)
        )
        if not candidate_id:
            logger.debug(
                "search_academic.skipped_unresolvable_candidate",
                source=candidate.source.value,
                title=candidate.title[:80],
            )
            continue
        norm = _normalize_title(candidate.title)
        if norm and norm in seen_titles:
            continue
        if norm:
            seen_titles.add(norm)
        new_candidates.append(candidate_id)
        id_to_title[candidate_id] = candidate.title

    errors = [
        _format_literature_source_error(error)
        for error in report.source_errors
    ]
    errors.extend(
        f"{source} unavailable: {reason}"
        for source, reason in report.unavailable_sources.items()
    )
    report_payload = report.model_dump(mode="json")
    logger.info(
        "search_academic.literature_done",
        queries=len(executed),
        candidates=len(new_candidates),
        gate_status=report.gate_status.value,
    )
    if return_report:
        return new_candidates, executed, errors, id_to_title, report_payload
    return new_candidates, executed, errors, id_to_title


async def _legacy_search_academic_sources(
    topic: str,
    queries: list[dict[str, Any]],
    existing_titles: set[str] | None = None,
) -> LiteratureSearchResult:
    """Fallback direct S2/OpenAlex search for pre-migration databases."""
    s2 = SemanticScholarAdapter(api_key=os.getenv("S2_API_KEY"))
    oa = OpenAlexAdapter(email=os.getenv("OPENALEX_EMAIL"))

    executed: list[str] = []
    new_candidates: list[str] = []
    errors: list[str] = []
    id_to_title: dict[str, str] = {}
    seen_titles: set[str] = set(existing_titles or set())

    try:
        for query_spec in queries:
            query_text = query_spec.get("query", "")
            if not query_text:
                continue
            executed.append(query_text)
            source = query_spec.get("source", "both")
            year = query_spec.get("year")
            fields_of_study = query_spec.get("fields_of_study")
            min_citation_count = query_spec.get("min_citation_count")

            # --- Semantic Scholar ---
            if source in ("both", "semantic_scholar"):
                try:
                    s2_params: dict[str, Any] = {"query": query_text, "limit": 50}
                    if year:
                        s2_params["year"] = year
                    if fields_of_study:
                        s2_params["fields_of_study"] = fields_of_study
                    if min_citation_count:
                        s2_params["min_citation_count"] = min_citation_count

                    s2_result = await s2.search_papers(**s2_params)
                    for paper in s2_result.get("data", []):
                        title = paper.get("title", "")
                        norm = _normalize_title(title)
                        if norm and norm not in seen_titles:
                            seen_titles.add(norm)
                            pid = paper.get("paperId", "")
                            if pid:
                                new_candidates.append(pid)
                                id_to_title[pid] = title

                    logger.info(
                        "search_academic.s2_done",
                        query=query_text[:60],
                        results=len(s2_result.get("data", [])),
                    )
                except Exception as exc:
                    logger.error(
                        "search_academic.s2_failed",
                        query=query_text[:60],
                        error=str(exc),
                    )
                    errors.append(f"S2 search failed for '{query_text[:40]}': {exc}")

            # --- OpenAlex ---
            if source in ("both", "openalex"):
                try:
                    oa_result = await oa.search_works(query=query_text, per_page=50)
                    for work in oa_result.get("results", []):
                        title = (
                            work.get("display_name") or work.get("title", "")
                        )
                        norm = _normalize_title(title)
                        if norm and norm not in seen_titles:
                            seen_titles.add(norm)
                            oa_id = (
                                work.get("id", "").split("/")[-1]
                                if work.get("id")
                                else ""
                            )
                            if oa_id:
                                new_candidates.append(f"OA:{oa_id}")
                                id_to_title[f"OA:{oa_id}"] = title

                    logger.info(
                        "search_academic.oa_done",
                        query=query_text[:60],
                        results=len(oa_result.get("results", [])),
                    )
                except Exception as exc:
                    logger.error(
                        "search_academic.oa_failed",
                        query=query_text[:60],
                        error=str(exc),
                    )
                    errors.append(
                        f"OpenAlex search failed for '{query_text[:40]}': {exc}"
                    )
    finally:
        await s2.close()
        await oa.close()

    return new_candidates, executed, errors, id_to_title


async def _build_literature_search_coordinator() -> Any:
    """Build a literature search coordinator from saved source settings."""
    from libs.schemas.literature import LiteratureSource
    from services.literature_search import LiteratureSearchCoordinator
    from services.literature_settings import LiteratureSettingsRepository, mask_api_key
    from services.literature_sources.deepxiv import DeepXivSource
    from services.literature_sources.local_library import LocalLibrarySource
    from services.literature_sources.obsidian import ObsidianSource
    from services.literature_sources.openalex import OpenAlexSource
    from services.literature_sources.semantic_scholar import SemanticScholarSource
    from services.literature_sources.web_search import WebSearchSource
    from services.literature_sources.zotero import ZoteroSource
    from services.source_key_pool import KeyMaterial, SourceKeyPool

    repo = LiteratureSettingsRepository()
    settings = await repo.list_sources()
    adapters: list[Any] = []
    for source_settings in settings:
        if not source_settings.enabled:
            continue
        source = source_settings.source
        options = _literature_adapter_options(source, source_settings.options)

        if source is LiteratureSource.LOCAL_LIBRARY:
            adapters.append(LocalLibrarySource(options=options))
        elif source is LiteratureSource.ZOTERO:
            adapters.append(ZoteroSource(options=options))
        elif source is LiteratureSource.OBSIDIAN:
            adapters.append(ObsidianSource(options=options))
        elif source is LiteratureSource.WEB_SEARCH:
            credentials = await repo.get_active_credentials(source)
            adapters.append(
                WebSearchSource(
                    options=options,
                    api_key=_first_literature_secret(credentials),
                )
            )
        elif source is LiteratureSource.SEMANTIC_SCHOLAR:
            credentials = await repo.get_active_credentials(source)
            key_pool = SourceKeyPool(
                [
                    KeyMaterial(
                        id=str(credential.id) if credential.id else None,
                        secret=credential.secret,
                        preview=mask_api_key(credential.secret),
                    )
                    for credential in credentials
                ],
                requests_per_second=_positive_float(
                    options.get("requests_per_second"),
                    1.0,
                ),
                burst_capacity=_positive_int(options.get("burst_capacity"), 1),
            )
            adapters.append(
                SemanticScholarSource(
                    options=options,
                    source_key_pool=key_pool,
                )
            )
        elif source is LiteratureSource.OPENALEX:
            credentials = await repo.get_active_credentials(source)
            key_pool = None
            if credentials:
                key_pool = SourceKeyPool(
                    [
                        KeyMaterial(
                            id=str(credential.id) if credential.id else None,
                            secret=credential.secret,
                            preview=mask_api_key(credential.secret),
                        )
                        for credential in credentials
                    ],
                    requests_per_second=_positive_float(
                        options.get("requests_per_second"),
                        2.0,
                    ),
                    burst_capacity=_positive_int(options.get("burst_capacity"), 1),
                )
            adapters.append(
                OpenAlexSource(
                    options=options,
                    email=options.get("email"),
                    api_key=_first_literature_secret(credentials),
                    source_key_pool=key_pool,
                )
            )
        elif source is LiteratureSource.DEEPXIV:
            adapters.append(DeepXivSource(options=options))

    return LiteratureSearchCoordinator(adapters)


def _literature_adapter_options(source: Any, options: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(options)
    source_value = getattr(source, "value", str(source))
    if source_value == "zotero" and "path" not in normalized:
        path = normalized.get("library_path")
        if path:
            normalized["path"] = path
    if source_value == "obsidian" and "path" not in normalized:
        path = normalized.get("vault_path")
        if path:
            normalized["path"] = path
    return normalized


def _first_literature_secret(credentials: list[Any]) -> str | None:
    for credential in credentials:
        secret = getattr(credential, "secret", "")
        if secret:
            return str(secret)
    return None


def _legacy_candidate_id(candidate: Any) -> str | None:
    s2_id = _clean_identifier(getattr(candidate, "s2_id", None))
    if s2_id:
        return s2_id

    openalex_id = _clean_identifier(getattr(candidate, "openalex_id", None))
    if openalex_id:
        return f"OA:{openalex_id}"

    arxiv_id = _clean_identifier(getattr(candidate, "arxiv_id", None))
    if arxiv_id:
        return arxiv_id if arxiv_id.lower().startswith("arxiv:") else f"arxiv:{arxiv_id}"

    candidate_id = _clean_identifier(getattr(candidate, "candidate_id", None))
    if candidate_id:
        lower = candidate_id.lower()
        if lower.startswith("s2:") or lower.startswith("semanticscholar:"):
            return candidate_id.split(":", 1)[1].strip() or None
        if lower.startswith("openalex:"):
            openalex_value = candidate_id.split(":", 1)[1].strip()
            return f"OA:{openalex_value}" if openalex_value else None
        if lower.startswith("oa:"):
            return f"OA:{candidate_id.split(':', 1)[1].strip()}"

    doi = _legacy_bare_doi(getattr(candidate, "doi", None))
    if doi:
        return doi
    if fallback_doi := _legacy_bare_doi(candidate_id):
        return fallback_doi

    title = _clean_identifier(getattr(candidate, "title", None))
    normalized_title = _normalize_title(title or "")
    if normalized_title:
        return f"title:{normalized_title}"

    return None


def _verification_candidate_id(candidate: Any) -> str | None:
    doi = _legacy_bare_doi(getattr(candidate, "doi", None))
    if doi:
        return doi

    arxiv_id = _clean_identifier(getattr(candidate, "arxiv_id", None))
    if arxiv_id:
        return (
            arxiv_id
            if arxiv_id.lower().startswith("arxiv:")
            else f"arxiv:{arxiv_id}"
        )

    s2_id = _clean_identifier(getattr(candidate, "s2_id", None))
    if s2_id:
        return s2_id if s2_id.lower().startswith("s2:") else f"S2:{s2_id}"

    openalex_id = _clean_identifier(getattr(candidate, "openalex_id", None))
    if openalex_id:
        return (
            openalex_id
            if openalex_id.lower().startswith(("oa:", "openalex:"))
            else f"OPENALEX:{openalex_id}"
        )

    candidate_id = _clean_identifier(getattr(candidate, "candidate_id", None))
    if candidate_id:
        return candidate_id

    title = _clean_identifier(getattr(candidate, "title", None))
    normalized_title = _normalize_title(title or "")
    if normalized_title:
        return f"title:{normalized_title}"

    return None


def _clean_identifier(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _legacy_bare_doi(value: object) -> str | None:
    text = _clean_identifier(value)
    if not text:
        return None
    lower = text.lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if lower.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    text = text.rstrip(".,;")
    return text if text.lower().startswith("10.") and "/" in text else None


def _executed_query_texts(topic: str, queries: list[dict[str, Any]]) -> list[str]:
    executed: list[str] = []
    for query_spec in queries:
        query_text = str(query_spec.get("query") or topic).strip()
        if query_text:
            executed.append(query_text)
    return executed


def _format_literature_source_error(error: Any) -> str:
    source = getattr(
        getattr(error, "source", None),
        "value",
        None,
    ) or getattr(error, "source", "source")
    kind = getattr(
        getattr(error, "kind", None),
        "value",
        None,
    ) or getattr(error, "kind", "error")
    message = getattr(error, "message", str(error))
    query = getattr(error, "query", None)
    prefix = f"{source} {kind}"
    if query:
        return f"{prefix} for '{str(query)[:40]}': {message}"
    return f"{prefix}: {message}"


def _is_missing_literature_settings_table(exc: Exception) -> bool:
    if getattr(exc, "sqlstate", None) == "42P01" or getattr(exc, "pgcode", None) == "42P01":
        return True
    name = type(exc).__name__
    message = str(exc).casefold()
    return (
        name == "UndefinedTableError"
        or (
            "literature_source_" in message
            and "does not exist" in message
        )
    )


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


async def verify_paper_candidates_for_run(
    run_id: UUID | str,
    candidate_ids: list[str],
    title_map: dict[str, str] | None = None,
    source: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Verify paper candidates and persist verification records when possible."""
    if not candidate_ids:
        return {}

    source_run_id = UUID(str(run_id))
    unique_candidate_ids = _stable_unique(candidate_ids)

    from apps.api.database import upsert_paper_verification
    from services.paper_verification import PaperVerifier, candidate_from_id

    title_map = title_map or {}
    verifier = PaperVerifier(
        s2_api_key=os.getenv("S2_API_KEY"),
        crossref_email=os.getenv("CROSSREF_EMAIL"),
        openalex_email=os.getenv("OPENALEX_EMAIL"),
    )
    records: dict[str, dict[str, Any]] = {}
    try:
        for candidate_id in unique_candidate_ids:
            candidate = candidate_from_id(
                candidate_id,
                title=title_map.get(candidate_id),
                source=source,
            )
            record = await verifier.verify(candidate)
            db_payload = record.model_dump(mode="python")
            db_payload["source_run_id"] = source_run_id
            context_payload = record.model_dump(mode="json")
            context_payload["source_run_id"] = str(source_run_id)
            records[candidate_id] = context_payload
            try:
                await upsert_paper_verification(db_payload)
            except Exception as exc:
                logger.debug(
                    "paper_verification.persist_failed",
                    candidate_id=candidate_id,
                    error=str(exc),
                )
    finally:
        await verifier.close()
    return records


async def tool_resolve_metadata(pid: str) -> tuple[Any | None, list[str]]:
    """TOOL: Resolve paper metadata via ScholarFusionService. No LLM."""
    errors: list[str] = []
    fusion = ScholarFusionService(
        s2_api_key=os.getenv("S2_API_KEY"),
        openalex_email=os.getenv("OPENALEX_EMAIL"),
        crossref_email=os.getenv("CROSSREF_EMAIL"),
        unpaywall_email=os.getenv("UNPAYWALL_EMAIL"),
    )
    try:
        kwargs: dict[str, str] = {}
        lower_pid = pid.lower()
        parsed_arxiv_id = detect_arxiv_id(pid)
        if lower_pid.startswith(("oa:", "openalex:")):
            kwargs["openalex_id"] = pid.split(":", 1)[1].strip()
        elif lower_pid.startswith(("s2:", "semanticscholar:")):
            kwargs["s2_id"] = pid.split(":", 1)[1].strip()
        elif lower_pid.startswith("title:"):
            kwargs["title"] = pid.split(":", 1)[1].strip()
        elif parsed_arxiv_id:
            kwargs["s2_id"] = f"ARXIV:{parsed_arxiv_id}"
        elif pid.startswith("10."):
            kwargs["doi"] = pid
        else:
            kwargs["s2_id"] = pid

        fused = await fusion.resolve_paper(**kwargs)
        if fused is None:
            if parsed_arxiv_id:
                try:
                    parsed = await parse_paper(parsed_arxiv_id)
                    title = getattr(parsed, "title", "") or pid
                    abstract = getattr(parsed, "abstract", None)
                    fused = FusedPaper(
                        canonical_title=title,
                        normalized_title=_normalize_title(title),
                        arxiv_id=parsed_arxiv_id,
                        abstract=abstract,
                        sources=["arxiv"],
                        source_trust_score=0.25,
                    )
                    return fused, errors
                except Exception as exc:
                    logger.debug(
                        "tool_resolve_metadata.arxiv_parse_fallback_failed",
                        pid=pid,
                        error=str(exc),
                    )
            errors.append(f"Could not resolve paper for deep read: {pid}")
            return None, errors
        return fused, errors
    except Exception as exc:
        logger.error("tool_resolve_metadata.error", pid=pid, error=str(exc))
        errors.append(f"Metadata resolution failed for {pid}: {exc}")
        return None, errors
    finally:
        await fusion.close()


async def tool_parse_paper_content(pid: str, fused: Any) -> tuple[str, str, str, bool]:
    """TOOL: Parse paper content (LaTeX preferred, GROBID fallback). No LLM.

    Returns (paper_title, paper_text, full_content, has_full_text).
    """
    paper_title = fused.canonical_title or pid
    paper_text = fused.abstract or ""
    parsed_sections_text = ""

    # Try to find arXiv ID from multiple sources (LaTeX parsing priority)
    arxiv_id = detect_arxiv_id(pid)
    if not arxiv_id:
        arxiv_id = getattr(fused, "arxiv_id", None)
    if not arxiv_id:
        fused_doi = getattr(fused, "doi", None)
        if fused_doi:
            arxiv_id = detect_arxiv_id(fused_doi)
    if not arxiv_id:
        # Try extracting from S2 externalIds
        ext_ids = getattr(fused, "external_ids", None) or {}
        if isinstance(ext_ids, dict) and ext_ids.get("ArXiv"):
            arxiv_id = str(ext_ids["ArXiv"])

    if arxiv_id:
        try:
            parsed = await parse_paper(arxiv_id)
            if parsed.parse_quality != "low" and parsed.sections:
                section_texts = []
                for sec in parsed.sections:
                    sec_header = f"## {sec.title}" if sec.title else ""
                    sec_body = (
                        "\n".join(sec.paragraphs) if sec.paragraphs else ""
                    )
                    if sec_header or sec_body:
                        section_texts.append(f"{sec_header}\n{sec_body}")
                parsed_sections_text = "\n\n".join(section_texts)
                if parsed.abstract:
                    paper_text = parsed.abstract
                if parsed.title:
                    paper_title = parsed.title
                logger.info(
                    "tool_parse_paper_content.latex_parsed",
                    pid=pid,
                    sections=len(parsed.sections),
                )
        except Exception as exc:
            logger.debug(
                "tool_parse_paper_content.latex_fallback", pid=pid, error=str(exc)
            )

    full_content = parsed_sections_text or paper_text
    has_full_text = bool(parsed_sections_text)
    return paper_title, paper_text, full_content, has_full_text


async def _summarize_paper(
    pid: str,
    paper_title: str,
    full_content: str,
    fused: Any,
    gateway: LLMGateway,
    has_full_text: bool,
) -> tuple[dict[str, Any] | None, float, list[str]]:
    """AGENT: Summarize a paper via LLM. Returns (summary, cost, errors)."""
    cost = 0.0
    errors: list[str] = []
    try:
        summary_system = get_system_prompt(PromptName.PAPER_SUMMARY)
        summary_user = (
            f"Paper title: {paper_title}\n"
            f"Year: {fused.year or 'unknown'}\n"
            f"Venue: {fused.venue or 'unknown'}\n"
            f"{'Full paper content' if has_full_text else 'Abstract'}:\n"
            f"{full_content[:12000]}\n"
        )

        summary_result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": summary_system},
                {"role": "user", "content": summary_user},
            ],
            tier=ModelTier.HIGH,
            schema=PAPER_SUMMARY_SCHEMA,
        )
        if isinstance(summary_result, dict):
            summary_result["paper_id"] = pid
            summary_result["title"] = paper_title
            summary_result["year"] = fused.year
            summary_result["venue"] = fused.venue
            cost += (
                _estimate_cost(summary_result, ModelTier.HIGH)
                if "usage" in summary_result
                else 0.01
            )
            return summary_result, cost, errors
    except Exception as exc:
        logger.error(
            "resolve_and_read.summary_failed", pid=pid, error=str(exc)
        )
        errors.append(f"Summary LLM failed for {pid}: {exc}")
    return None, cost, errors


async def _tag_paper(
    summary: dict[str, Any] | None,
    full_content: str,
    paper_title: str,
    fused: Any,
    gateway: LLMGateway,
) -> dict[str, Any] | None:
    """AGENT: Tag paper via PaperTagAgent. Returns updated summary or original."""
    try:
        from apps.worker.agents.paper_tag_agent import PaperTagAgent
        tag_agent = PaperTagAgent(gateway=gateway)
        tag_result = await tag_agent.run(
            paper_text=full_content,
            metadata={
                "title": paper_title,
                "year": getattr(fused, "year", None),
                "venue": getattr(fused, "venue", None),
            },
        )
        if summary and isinstance(summary, dict):
            return {**summary, "paper_tags": tag_result.model_dump()}
    except Exception as exc:
        logger.debug("paper_tag_skipped", title=paper_title[:60], error=str(exc))
    return summary


async def resolve_and_read_paper(
    pid: str,
    gateway: LLMGateway,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], float, list[str]]:
    """
    Resolve paper metadata, parse LaTeX/GROBID if available, summarize via LLM,
    and extract claims.

    Returns:
        (summary_dict | None, claims_list, cost_delta, error_messages)
    """
    errors: list[str] = []
    cost = 0.0
    summary: dict[str, Any] | None = None
    claims: list[dict[str, Any]] = []

    try:
        # Step 1: TOOL -- resolve metadata (deterministic, no LLM)
        fused, meta_errors = await tool_resolve_metadata(pid)
        errors.extend(meta_errors)
        if not fused:
            return None, [], cost, errors

        # Step 2: TOOL -- parse content (deterministic, no LLM)
        paper_title, paper_text, full_content, has_full_text = (
            await tool_parse_paper_content(pid, fused)
        )

        # Step 3: AGENT -- LLM summarize
        summary, summary_cost, summary_errors = await _summarize_paper(
            pid, paper_title, full_content, fused, gateway, has_full_text
        )
        cost += summary_cost
        errors.extend(summary_errors)

        # Step 4: AGENT -- LLM extract claims
        claims, claim_cost, claim_errors = await extract_claims(
            paper_title, full_content, gateway
        )
        cost += claim_cost
        for c in claims:
            c["source_paper_id"] = pid
        errors.extend(claim_errors)

        # Step 5: AGENT -- PaperTagAgent
        summary = await _tag_paper(
            summary, full_content, paper_title, fused, gateway
        )

        logger.info(
            "resolve_and_read.done", pid=pid, title=paper_title[:60]
        )
    except Exception as exc:
        logger.error("resolve_and_read.error", pid=pid, error=str(exc))
        errors.append(f"Resolve/read failed for {pid}: {exc}")

    return summary, claims, cost, errors


async def extract_claims(
    paper_title: str,
    paper_text: str,
    gateway: LLMGateway,
) -> tuple[list[dict[str, Any]], float, list[str]]:
    """
    Extract structured claims from paper text via LLM.

    Returns:
        (claims_list, cost_delta, error_messages)
    """
    cost = 0.0
    errors: list[str] = []
    all_claims: list[dict[str, Any]] = []

    try:
        claim_system = get_system_prompt(PromptName.CLAIM_EXTRACTION)
        claim_user = (
            f"Paper: {paper_title}\nText chunk:\n{paper_text[:8000]}\n"
        )

        claim_result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": claim_system},
                {"role": "user", "content": claim_user},
            ],
            tier=ModelTier.MEDIUM,
            schema=CLAIM_OUTPUT_SCHEMA,
        )

        if isinstance(claim_result, list):
            all_claims.extend(claim_result)
        elif isinstance(claim_result, dict) and "claims" in claim_result:
            all_claims.extend(claim_result["claims"])

        cost += (
            _estimate_cost(claim_result, ModelTier.MEDIUM)
            if isinstance(claim_result, dict) and "usage" in claim_result
            else 0.003
        )
    except Exception as exc:
        logger.error(
            "extract_claims.failed", title=paper_title[:60], error=str(exc)
        )
        errors.append(f"Claim extraction failed for {paper_title[:40]}: {exc}")

    return all_claims, cost, errors


async def generate_llm_json(
    system_prompt: str,
    user_content: str,
    gateway: LLMGateway,
    tier: ModelTier = ModelTier.MEDIUM,
    schema: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | list, float, list[str]]:
    """
    Wrapper for gateway.chat_json with standardised error handling.

    Returns:
        (parsed_result, cost_delta, error_messages)
    """
    cost = 0.0
    errors: list[str] = []

    try:
        result = await gateway.chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            tier=tier,
            schema=schema,
        )
        cost += (
            _estimate_cost(result, tier)
            if isinstance(result, dict) and "usage" in result
            else 0.005
        )
        return result, cost, errors
    except Exception as exc:
        logger.error("generate_llm_json.failed", error=str(exc))
        errors.append(f"LLM JSON call failed: {exc}")
        return {}, cost, errors


async def rerank_search_results(
    query: str,
    paper_titles: list[str],
    paper_ids: list[str],
    top_n: int = 50,
) -> list[str]:
    """
    Rerank paper candidates by relevance using Tongyi gte-rerank-v2.

    Args:
        query: The research topic or search query.
        paper_titles: Parallel list of paper titles to score.
        paper_ids: Parallel list of paper IDs (same order as titles).
        top_n: Maximum number of results to return.

    Returns:
        Reranked list of paper IDs (most relevant first).
        Falls back to original order on failure.
    """
    from services.embedding import get_embedding_service

    if not paper_titles:
        return paper_ids

    try:
        svc = get_embedding_service()
        results = await svc.rerank(
            query=query,
            documents=paper_titles,
            top_n=top_n,
        )
        reranked_ids = [
            paper_ids[r["index"]]
            for r in results
            if r["index"] < len(paper_ids)
        ]
        return reranked_ids
    except Exception as exc:
        logger.warning("rerank_failed_using_original_order", error=str(exc))
        return paper_ids


def _create_fusion_service() -> ScholarFusionService:
    """Create a ScholarFusionService with env-based credentials."""
    return ScholarFusionService(
        s2_api_key=os.getenv("S2_API_KEY"),
        openalex_email=os.getenv("OPENALEX_EMAIL"),
        crossref_email=os.getenv("CROSSREF_EMAIL"),
        unpaywall_email=os.getenv("UNPAYWALL_EMAIL"),
    )
