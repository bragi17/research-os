"""Paper candidate verification schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PaperVerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    VERIFY_PENDING = "verify_pending"
    ERROR = "error"


class PaperVerificationMethod(str, Enum):
    ARXIV = "arxiv"
    CROSSREF = "crossref"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    TITLE_MATCH = "title_match"
    NONE = "none"


class PaperCandidate(BaseModel):
    candidate_id: str
    title: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    s2_id: str | None = None
    openalex_id: str | None = None
    source: str | None = None


class PaperVerificationRecord(BaseModel):
    id: UUID | None = None
    source_run_id: UUID | None = None
    candidate_key: str
    candidate_id: str | None = None
    source: str | None = None
    input_title: str | None = None
    canonical_title: str | None = None
    canonical_doi: str | None = None
    canonical_arxiv_id: str | None = None
    canonical_s2_id: str | None = None
    canonical_openalex_id: str | None = None
    verification_status: PaperVerificationStatus = PaperVerificationStatus.VERIFY_PENDING
    verification_method: PaperVerificationMethod = PaperVerificationMethod.NONE
    verification_reason: str | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)
    verified_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
