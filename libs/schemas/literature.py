"""Literature source settings and search schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class LiteratureSource(str, Enum):
    LOCAL_LIBRARY = "local_library"
    ZOTERO = "zotero"
    OBSIDIAN = "obsidian"
    WEB_SEARCH = "web_search"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    DEEPXIV = "deepxiv"


class LiteratureErrorKind(str, Enum):
    CREDENTIAL_ERROR = "credential_error"
    RATE_LIMITED = "rate_limited"
    TRANSIENT_ERROR = "transient_error"
    CONFIGURATION_ERROR = "configuration_error"
    UNAVAILABLE = "unavailable"


class LiteratureGateStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    PENDING = "pending"
    BLOCKED = "blocked"


class LiteratureCredentialPreview(BaseModel):
    id: UUID | str | None = None
    label: str = "primary"
    preview: str = ""
    is_active: bool = True
    last_status: str | None = None
    last_error: str | None = None
    last_used_at: datetime | None = None
    cooldown_until: datetime | None = None


class LiteratureSourceSettings(BaseModel):
    source: LiteratureSource
    label: str
    enabled: bool = False
    configured: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    credentials: list[LiteratureCredentialPreview] = Field(default_factory=list)
    last_test_status: str | None = None
    last_test_error: str | None = None
    last_test_at: datetime | None = None


class LiteratureSourceUpdate(BaseModel):
    enabled: bool | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    new_credentials: list[str] = Field(default_factory=list)
    clear_credential_ids: list[str] = Field(default_factory=list)


class LiteratureCandidate(BaseModel):
    candidate_id: str
    title: str
    source: LiteratureSource
    doi: str | None = None
    arxiv_id: str | None = None
    s2_id: str | None = None
    openalex_id: str | None = None
    url: str | None = None
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    authors: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class LiteratureSourceError(BaseModel):
    source: LiteratureSource
    kind: LiteratureErrorKind
    message: str
    query: str | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None


class LiteratureSearchReport(BaseModel):
    requested_sources: list[LiteratureSource] = Field(default_factory=list)
    enabled_sources: list[LiteratureSource] = Field(default_factory=list)
    contributing_sources: list[LiteratureSource] = Field(default_factory=list)
    contribution_counts: dict[str, int] = Field(default_factory=dict)
    source_errors: list[LiteratureSourceError] = Field(default_factory=list)
    unavailable_sources: dict[str, str] = Field(default_factory=dict)
    candidate_count: int = 0
    gate_status: LiteratureGateStatus
