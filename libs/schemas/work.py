from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ResearchPhase = Literal["atlas", "frontier", "divergent"]
ExecutionKind = Literal["standard", "validation"]
ExecutionStatus = Literal["queued", "running", "paused", "failed", "completed", "cancelled"]
ArtifactSelectionState = Literal["unselected", "selected", "used"]
ArtifactStatus = Literal["active", "archived", "deleted"]


class WorkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    topic: str = Field(min_length=10)
    project_id: UUID | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)


class WorkResponse(BaseModel):
    id: UUID
    title: str
    topic: str
    status: str
    active_phase: str | None = None
    root_run_id: UUID | None = None
    project_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class PhaseExecutionCreate(BaseModel):
    phase: ResearchPhase
    execution_kind: ExecutionKind = "standard"
    manual_input: dict[str, Any] = Field(default_factory=dict)
    source_card_ids: list[UUID] = Field(default_factory=list)


class PhaseExecutionResponse(BaseModel):
    id: UUID
    work_id: UUID
    phase: ResearchPhase
    execution_kind: ExecutionKind
    status: ExecutionStatus
    backing_run_id: UUID | None = None
    output_bundle_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactCardCreate(BaseModel):
    phase: ResearchPhase
    artifact_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    body: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source_execution_id: UUID | None = None
    source_card_ids: list[UUID] = Field(default_factory=list)


class ArtifactCardPatch(BaseModel):
    _NON_NULL_FIELDS: ClassVar[set[str]] = {
        "title",
        "payload",
        "status",
        "selection_state",
    }

    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = None
    payload: dict[str, Any] | None = None
    status: ArtifactStatus | None = None
    selection_state: ArtifactSelectionState | None = None

    @model_validator(mode="after")
    def reject_explicit_null_for_non_nullable_fields(self) -> "ArtifactCardPatch":
        for field in self._NON_NULL_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ArtifactCardResponse(BaseModel):
    id: UUID
    work_id: UUID
    phase: ResearchPhase
    artifact_type: str
    title: str
    body: str | None = None
    payload: dict[str, Any]
    status: ArtifactStatus
    selection_state: ArtifactSelectionState
    source_execution_id: UUID | None = None
    source_card_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PhaseInputSelectionUpdate(BaseModel):
    source_card_ids: list[UUID] = Field(default_factory=list)
    manual_input: dict[str, Any] = Field(default_factory=dict)
