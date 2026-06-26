"""Coordinator for multi-source literature retrieval and ARIS gate reports."""

from __future__ import annotations

from collections.abc import Iterable

from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureGateStatus,
    LiteratureSearchReport,
    LiteratureSource,
    LiteratureSourceError,
)
from services.literature_sources.base import LiteratureSourceAdapter, candidate_key


class LiteratureSearchCoordinator:
    def __init__(self, sources: Iterable[LiteratureSourceAdapter]) -> None:
        self.sources = list(sources)

    async def search(
        self,
        topic: str,
        queries: list[dict[str, object]],
        limit_per_query: int = 50,
    ) -> tuple[list[LiteratureCandidate], LiteratureSearchReport]:
        requested = [source.source for source in self.sources]
        candidates: list[LiteratureCandidate] = []
        seen: set[str] = set()
        errors: list[LiteratureSourceError] = []
        unavailable: dict[str, str] = {}
        counts = {source.value: 0 for source in requested}

        for query_spec in queries:
            query_text = str(query_spec.get("query") or topic).strip()
            if not query_text:
                continue
            for source in self.sources:
                try:
                    result = await source.search(query_text, limit=limit_per_query)
                except Exception as exc:
                    errors.append(self._exception_error(source.source, query_text, exc))
                    continue
                if result.unavailable_reason:
                    unavailable[source.source.value] = result.unavailable_reason
                errors.extend(result.errors)
                for candidate in result.candidates:
                    key = candidate_key(candidate)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(candidate)
                    counts[source.source.value] = counts.get(source.source.value, 0) + 1

        contributing = [
            LiteratureSource(source)
            for source, count in counts.items()
            if count > 0
        ]
        gate_status = self._gate_status(candidates, errors, unavailable)
        return candidates, LiteratureSearchReport(
            requested_sources=requested,
            enabled_sources=requested,
            contributing_sources=contributing,
            contribution_counts=counts,
            source_errors=errors,
            unavailable_sources=unavailable,
            candidate_count=len(candidates),
            gate_status=gate_status,
        )

    async def close(self) -> None:
        for source in self.sources:
            close = getattr(source, "close", None)
            if close is not None:
                await close()

    async def __aenter__(self) -> "LiteratureSearchCoordinator":
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        await self.close()

    def _gate_status(
        self,
        candidates: list[LiteratureCandidate],
        errors: list[LiteratureSourceError],
        unavailable: dict[str, str],
    ) -> LiteratureGateStatus:
        if candidates and (errors or unavailable):
            return LiteratureGateStatus.WARN
        if candidates:
            return LiteratureGateStatus.PASS
        if not errors:
            return LiteratureGateStatus.BLOCKED
        transient_kinds = {
            LiteratureErrorKind.RATE_LIMITED,
            LiteratureErrorKind.TRANSIENT_ERROR,
        }
        if all(error.kind in transient_kinds for error in errors):
            return LiteratureGateStatus.PENDING
        return LiteratureGateStatus.BLOCKED

    def _exception_error(
        self,
        source: LiteratureSource,
        query: str,
        exc: Exception,
    ) -> LiteratureSourceError:
        kind = (
            LiteratureErrorKind.TRANSIENT_ERROR
            if isinstance(exc, (TimeoutError, ConnectionError))
            else LiteratureErrorKind.UNAVAILABLE
        )
        message = f"{source.value} source failed with {type(exc).__name__}"
        return LiteratureSourceError(
            source=source,
            kind=kind,
            message=message[:200],
            query=query,
        )
