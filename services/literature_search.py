"""Coordinator for multi-source literature retrieval and ARIS gate reports."""

from __future__ import annotations

from collections.abc import Iterable

from libs.schemas.literature import (
    LiteratureCandidate,
    LiteratureErrorKind,
    LiteratureGateStatus,
    LiteratureSearchReport,
    LiteratureSource,
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
        errors = []
        unavailable: dict[str, str] = {}
        counts = {source.value: 0 for source in requested}

        for query_spec in queries:
            query_text = str(query_spec.get("query") or topic).strip()
            if not query_text:
                continue
            for source in self.sources:
                result = await source.search(query_text, limit=limit_per_query)
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

    def _gate_status(
        self,
        candidates: list[LiteratureCandidate],
        errors: list[object],
        unavailable: dict[str, str],
    ) -> LiteratureGateStatus:
        if candidates and errors:
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
