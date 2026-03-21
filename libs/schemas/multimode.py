"""
Research OS - Multi-Mode Schema Models

Pydantic models for multi-mode research workflow entities:
ResearchMode, RunStage, PainPoint, IdeaCard, ContextBundle,
ModeConfig, and SpawnRunRequest.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ResearchMode(str, Enum):
    """Available research modes."""

    INTAKE = "intake"
    ATLAS = "atlas"
    FRONTIER = "frontier"
    DIVERGENT = "divergent"
    REVIEW = "review"


class RunStage(str, Enum):
    """Stages within a research run."""

    INIT = "init"
    SEARCH = "search"
    READ = "read"
    ANALYZE = "analyze"
    SYNTHESIZE = "synthesize"
    OUTPUT = "output"


# ============================================
# Pain Point
# ============================================


class PainPoint(BaseModel):
    """A research pain point identified during analysis."""

    statement: str = Field(..., min_length=1)
    pain_type: str = Field(default="general")
    severity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    novelty_potential: float = Field(default=0.0, ge=0.0, le=1.0)
    supporting_paper_ids: list[UUID] = Field(default_factory=list)


# ============================================
# Idea Card
# ============================================


class IdeaCard(BaseModel):
    """An idea card capturing a potential research direction."""

    title: str = Field(..., min_length=1)
    problem_statement: str = Field(..., min_length=1)
    status: str = Field(default="candidate")
    prior_art_check_status: str = Field(default="pending")
    borrowed_methods: list[str] = Field(default_factory=list)
    supporting_paper_ids: list[UUID] = Field(default_factory=list)
    pain_point_ids: list[UUID] = Field(default_factory=list)


# ============================================
# Context Bundle
# ============================================


class ContextBundle(BaseModel):
    """A bundle of context passed between research modes."""

    source_mode: str = Field(..., min_length=1)
    selected_paper_ids: list[UUID] = Field(default_factory=list)
    pain_point_ids: list[UUID] = Field(default_factory=list)
    idea_card_ids: list[UUID] = Field(default_factory=list)
    mindmap_json: dict[str, Any] = Field(default_factory=dict)
    summary_text: str | None = None


# ============================================
# Mode Config
# ============================================


class ModeConfig(BaseModel):
    """Configuration for a specific research mode run."""

    mode: ResearchMode
    topic: str = Field(..., min_length=1)
    keywords: list[str] = Field(default_factory=list)
    seed_paper_ids: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)


# ============================================
# Spawn Run Request
# ============================================


class SpawnRunRequest(BaseModel):
    """Request to spawn a new run in a target mode."""

    target_mode: ResearchMode
    context_bundle_id: UUID | None = None
    selection: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=1, ge=1, le=10)
