"""Paper candidate verification service."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from structlog import get_logger

from libs.adapters.crossref import CrossrefAdapter
from libs.adapters.openalex import OpenAlexAdapter
from libs.adapters.semantic_scholar import SemanticScholarAdapter
from libs.schemas.paper_verification import (
    PaperCandidate,
    PaperVerificationMethod,
    PaperVerificationRecord,
    PaperVerificationStatus,
)

logger = get_logger(__name__)

_ARXIV_RE = re.compile(r"(?i)([a-z\-\.]+/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)")
_OPENALEX_URL_PREFIX = "https://openalex.org/"


def normalize_arxiv_id(value: str | None) -> str | None:
    """Normalize an arXiv identifier or URL."""
    if not value:
        return None

    clean = value.strip()
    if not clean:
        return None

    if clean.lower().startswith("arxiv:"):
        clean = clean.split(":", 1)[1].strip()

    clean = clean.replace("/pdf/", "/abs/")
    if clean.lower().endswith(".pdf"):
        clean = clean[:-4]

    match = _ARXIV_RE.search(clean)
    if not match:
        return None
    return re.sub(r"(?i)v\d+$", "", match.group(1))


def normalize_doi(value: str | None) -> str | None:
    """Normalize a DOI to its lowercase bare identifier."""
    if not value:
        return None

    clean = value.strip()
    if not clean:
        return None

    lower = clean.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lower.startswith(prefix):
            clean = clean[len(prefix) :].strip()
            break

    clean = clean.rstrip(".,;")
    if not clean.lower().startswith("10.") or "/" not in clean:
        return None
    return clean.lower()


def candidate_key(candidate: PaperCandidate) -> str:
    """Return the stable deduplication key for a candidate."""
    arxiv_id = normalize_arxiv_id(candidate.arxiv_id)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"

    doi = normalize_doi(candidate.doi)
    if doi:
        return f"doi:{doi}"

    if candidate.s2_id and candidate.s2_id.strip():
        return f"s2:{candidate.s2_id.strip()}"

    openalex_id = _normalize_openalex_id(candidate.openalex_id)
    if openalex_id:
        return f"openalex:{openalex_id}"

    if candidate.candidate_id and candidate.candidate_id.strip():
        return f"candidate:{candidate.candidate_id.strip()}"

    if candidate.title and candidate.title.strip():
        return f"title:{_normalize_title(candidate.title)}"

    return "candidate:unknown"


def candidate_from_id(
    candidate_id: str,
    title: str | None = None,
    source: str | None = None,
) -> PaperCandidate:
    """Build a paper candidate by inferring identifier type from an ID string."""
    clean = candidate_id.strip()
    lower = clean.lower()
    fields: dict[str, Any] = {
        "candidate_id": candidate_id,
        "title": title,
        "source": source,
    }

    if lower.startswith("arxiv:"):
        fields["arxiv_id"] = normalize_arxiv_id(clean.split(":", 1)[1])
    elif "arxiv.org/" in lower:
        fields["arxiv_id"] = normalize_arxiv_id(clean)
    elif lower.startswith("doi:") or lower.startswith(
        ("https://doi.org/", "http://doi.org/")
    ):
        fields["doi"] = normalize_doi(clean)
    elif lower.startswith("10."):
        fields["doi"] = normalize_doi(clean)
    elif lower.startswith(("oa:", "openalex:")) or lower.startswith(_OPENALEX_URL_PREFIX):
        fields["openalex_id"] = _normalize_openalex_id(clean)
    elif lower.startswith(("s2:", "semanticscholar:")):
        fields["s2_id"] = clean.split(":", 1)[1].strip()
    elif lower.startswith("title:"):
        fields["title"] = title or clean.split(":", 1)[1].strip()
    elif arxiv_id := normalize_arxiv_id(clean):
        fields["arxiv_id"] = arxiv_id
    elif clean:
        fields["s2_id"] = clean

    return PaperCandidate(**fields)


class PaperVerifier:
    """Verify paper candidates against external scholarly metadata sources."""

    def __init__(
        self,
        *,
        s2: SemanticScholarAdapter | None = None,
        semantic_scholar: SemanticScholarAdapter | None = None,
        crossref: CrossrefAdapter | None = None,
        openalex: OpenAlexAdapter | None = None,
        s2_api_key: str | None = None,
        crossref_email: str | None = None,
        openalex_email: str | None = None,
    ) -> None:
        s2_adapter = s2 or semantic_scholar
        self._owns_s2 = s2_adapter is None
        self._owns_crossref = crossref is None
        self._owns_openalex = openalex is None

        self.s2 = s2_adapter or SemanticScholarAdapter(api_key=s2_api_key)
        self.semantic_scholar = self.s2
        self.crossref = crossref or CrossrefAdapter(email=crossref_email)
        self.openalex = openalex or OpenAlexAdapter(email=openalex_email)

    async def verify(self, candidate: PaperCandidate) -> PaperVerificationRecord:
        """Verify a candidate using identifiers first, then title matching."""
        if not candidate.candidate_id or not candidate.candidate_id.strip():
            return self._error(candidate, reason="candidate_id is required")

        normalized = _normalize_candidate(candidate)
        verifiers = (
            ("arxiv", self._verify_arxiv),
            ("doi", self._verify_doi),
            ("semantic_scholar", self._verify_s2),
            ("openalex", self._verify_openalex),
            ("title_match", self._verify_title),
        )

        for layer, verifier in verifiers:
            try:
                record = await verifier(normalized)
            except Exception as exc:
                logger.warning(
                    "paper_verification.pending",
                    candidate_key=candidate_key(normalized),
                    layer=layer,
                    error=str(exc),
                )
                return self._pending(
                    normalized,
                    reason=f"{layer} verification failed: {exc}",
                    raw_json={"layer": layer, "error": str(exc)},
                )
            if record is not None:
                return record

        return self._unverified(normalized, reason="No verification source matched candidate")

    def _verified(
        self,
        candidate: PaperCandidate,
        *,
        method: str | PaperVerificationMethod,
        title: str | None,
        doi: str | None = None,
        arxiv_id: str | None = None,
        s2_id: str | None = None,
        openalex_id: str | None = None,
        raw_json: dict[str, Any] | None = None,
    ) -> PaperVerificationRecord:
        """Create a verified record for a candidate."""
        now = datetime.now(timezone.utc)
        return PaperVerificationRecord(
            candidate_key=candidate_key(candidate),
            candidate_id=candidate.candidate_id,
            source=candidate.source,
            input_title=candidate.title,
            canonical_title=title or candidate.title,
            canonical_doi=normalize_doi(doi) or normalize_doi(candidate.doi),
            canonical_arxiv_id=normalize_arxiv_id(arxiv_id)
            or normalize_arxiv_id(candidate.arxiv_id),
            canonical_s2_id=(s2_id or candidate.s2_id),
            canonical_openalex_id=_normalize_openalex_id(openalex_id)
            or _normalize_openalex_id(candidate.openalex_id),
            verification_status=PaperVerificationStatus.VERIFIED,
            verification_method=method,
            raw_json=_jsonable(raw_json or {}),
            verified_at=now,
        )

    async def _verify_arxiv(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.arxiv_id:
            return None

        paper = await self.s2.get_paper(
            f"ARXIV:{candidate.arxiv_id}",
            fields=["paperId", "title", "externalIds"],
        )
        external_ids = paper.external_ids or {}
        return self._verified(
            candidate,
            method=PaperVerificationMethod.ARXIV,
            title=paper.title,
            doi=external_ids.get("DOI"),
            arxiv_id=external_ids.get("ArXiv") or candidate.arxiv_id,
            s2_id=paper.paper_id,
            raw_json=_model_dump(paper),
        )

    async def _verify_doi(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.doi:
            return None

        work = await self.crossref.get_work(candidate.doi)
        return self._verified(
            candidate,
            method=PaperVerificationMethod.CROSSREF,
            title=work.display_title or candidate.title,
            doi=work.doi or candidate.doi,
            raw_json=_model_dump(work),
        )

    async def _verify_s2(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.s2_id:
            return None

        paper = await self.s2.get_paper(
            candidate.s2_id,
            fields=["paperId", "title", "externalIds"],
        )
        external_ids = paper.external_ids or {}
        return self._verified(
            candidate,
            method=PaperVerificationMethod.SEMANTIC_SCHOLAR,
            title=paper.title,
            doi=external_ids.get("DOI"),
            arxiv_id=external_ids.get("ArXiv"),
            s2_id=paper.paper_id,
            raw_json=_model_dump(paper),
        )

    async def _verify_openalex(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.openalex_id:
            return None

        work = await self.openalex.get_work(
            candidate.openalex_id,
            select=["id", "doi", "title", "display_name"],
        )
        return self._verified(
            candidate,
            method=PaperVerificationMethod.OPENALEX,
            title=work.display_name or work.title or candidate.title,
            doi=work.doi,
            openalex_id=work.openalex_id or candidate.openalex_id,
            raw_json=_model_dump(work),
        )

    async def _verify_title(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.title:
            return None

        match = await self.s2.match_paper(candidate.title)
        paper_id = match.get("paperId")
        if not paper_id:
            return None

        paper = await self.s2.get_paper(
            paper_id,
            fields=["paperId", "title", "externalIds"],
        )
        external_ids = paper.external_ids or {}
        return self._verified(
            candidate,
            method=PaperVerificationMethod.TITLE_MATCH,
            title=paper.title,
            doi=external_ids.get("DOI"),
            arxiv_id=external_ids.get("ArXiv"),
            s2_id=paper.paper_id,
            raw_json={
                "match": _jsonable(match),
                "paper": _model_dump(paper),
            },
        )

    async def close(self) -> None:
        """Close owned adapter clients."""
        if self._owns_s2:
            await self.s2.close()
        if self._owns_crossref:
            await self.crossref.close()
        if self._owns_openalex:
            await self.openalex.close()

    def _unverified(self, candidate: PaperCandidate, *, reason: str) -> PaperVerificationRecord:
        return PaperVerificationRecord(
            candidate_key=candidate_key(candidate),
            candidate_id=candidate.candidate_id,
            source=candidate.source,
            input_title=candidate.title,
            verification_status=PaperVerificationStatus.UNVERIFIED,
            verification_method=PaperVerificationMethod.NONE,
            verification_reason=reason,
        )

    def _pending(
        self,
        candidate: PaperCandidate,
        *,
        reason: str,
        raw_json: dict[str, Any] | None = None,
    ) -> PaperVerificationRecord:
        return PaperVerificationRecord(
            candidate_key=candidate_key(candidate),
            candidate_id=candidate.candidate_id,
            source=candidate.source,
            input_title=candidate.title,
            verification_status=PaperVerificationStatus.VERIFY_PENDING,
            verification_method=PaperVerificationMethod.NONE,
            verification_reason=reason,
            raw_json=_jsonable(raw_json or {}),
        )

    def _error(self, candidate: PaperCandidate, *, reason: str) -> PaperVerificationRecord:
        return PaperVerificationRecord(
            candidate_key=candidate_key(candidate),
            candidate_id=candidate.candidate_id or None,
            source=candidate.source,
            input_title=candidate.title,
            verification_status=PaperVerificationStatus.ERROR,
            verification_method=PaperVerificationMethod.NONE,
            verification_reason=reason,
        )


def _normalize_candidate(candidate: PaperCandidate) -> PaperCandidate:
    return candidate.model_copy(
        update={
            "title": candidate.title.strip()
            if candidate.title and candidate.title.strip()
            else None,
            "doi": normalize_doi(candidate.doi),
            "arxiv_id": normalize_arxiv_id(candidate.arxiv_id),
            "s2_id": candidate.s2_id.strip()
            if candidate.s2_id and candidate.s2_id.strip()
            else None,
            "openalex_id": _normalize_openalex_id(candidate.openalex_id),
        }
    )


def _normalize_openalex_id(value: str | None) -> str | None:
    if not value:
        return None

    clean = value.strip()
    if not clean:
        return None

    lower = clean.lower()
    if lower.startswith(("oa:", "openalex:")):
        clean = clean.split(":", 1)[1].strip()
    elif lower.startswith(_OPENALEX_URL_PREFIX):
        clean = clean[len(_OPENALEX_URL_PREFIX) :].strip()

    return clean or None


def _normalize_title(title: str) -> str:
    return " ".join(title.casefold().split())


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return _jsonable(value)
    return _jsonable({"value": value})


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_jsonable(item) for item in value]
        if isinstance(value, tuple):
            return [_jsonable(item) for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", by_alias=True)
        return str(value)


__all__ = [
    "PaperVerifier",
    "candidate_from_id",
    "candidate_key",
    "normalize_arxiv_id",
    "normalize_doi",
]
