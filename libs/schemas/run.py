"""
Research OS - Run State Models

Core state models for the autonomous research workflow.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    """Research run status states."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Run step status states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class GoalType(str, Enum):
    """Research goal types."""

    SURVEY = "survey"
    SURVEY_PLUS_INNOVATIONS = "survey_plus_innovations"
    INNOVATION_CARDS = "innovation_cards"
    EXPERIMENT_PLAN = "experiment_plan"
    PROPOSAL = "proposal"


class AutonomyMode(str, Enum):
    """Autonomy mode for the research run."""

    DEFAULT_AUTONOMOUS = "default_autonomous"
    SUPERVISED = "supervised"
    BATCH = "batch"


class Severity(str, Enum):
    """Event severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ============================================
# Budget & Policy Models
# ============================================


class Budget(BaseModel):
    """Budget constraints for a research run."""

    max_runtime_minutes: int = Field(default=90, ge=5, le=480)
    max_new_papers: int = Field(default=150, ge=10, le=1000)
    max_fulltext_reads: int = Field(default=40, ge=5, le=200)
    max_tool_calls: int = Field(default=80, ge=10, le=500)
    max_estimated_cost_usd: float = Field(default=30.0, ge=1.0, le=500.0)


class Policy(BaseModel):
    """Auto-pause policy configuration."""

    auto_pause_on_missing_key_fulltext: bool = True
    auto_pause_on_low_confidence_hypothesis: bool = True
    auto_pause_on_budget_hit: bool = True
    auto_pause_on_retrieval_drift: bool = True
    auto_pause_on_high_cost_action: bool = True


# ============================================
# Query & Retrieval Models
# ============================================


class QueryIntent(str, Enum):
    """Intent type for search queries."""

    SEED_EXPAND = "seed_expand"
    CITATION_EXPAND = "citation_expand"
    GAP_FILL = "gap_fill"
    PRIOR_ART_CHECK = "prior_art_check"
    CONTRADICTION_PROBE = "contradiction_probe"


class QueryPlan(BaseModel):
    """A planned search query."""

    query_text: str = Field(..., min_length=1)
    source_names: list[str] = Field(default_factory=lambda: ["semantic_scholar", "openalex"])
    intent: QueryIntent = QueryIntent.SEED_EXPAND
    priority: int = Field(default=1, ge=1, le=10)
    filters: dict[str, Any] = Field(default_factory=dict)


class CoverageTarget(BaseModel):
    """A coverage target dimension."""

    dimension: str  # task, method, dataset, metric, year, venue
    key: str
    min_papers: int = Field(default=3, ge=1)


# ============================================
# Candidate Paper Models
# ============================================


class ScoreSignals(BaseModel):
    """Scoring signals for a candidate paper."""

    semantic: float = Field(default=0.0, ge=0.0, le=1.0)
    keyword: float = Field(default=0.0, ge=0.0, le=1.0)
    citation: float = Field(default=0.0, ge=0.0, le=1.0)
    impact: float = Field(default=0.0, ge=0.0, le=1.0)
    recency: float = Field(default=0.0, ge=0.0, le=1.0)
    diversity: float = Field(default=0.0, ge=0.0, le=1.0)
    trust: float = Field(default=0.0, ge=0.0, le=1.0)
    access: float = Field(default=0.0, ge=0.0, le=1.0)
    contradiction: float = Field(default=0.0, ge=0.0, le=1.0)


class CandidatePaper(BaseModel):
    """A candidate paper for deep reading."""

    paper_id: UUID | None = None
    title: str
    doi: str | None = None
    s2_paper_id: str | None = None
    openalex_id: str | None = None
    year: int | None = None
    source_name: str
    score_signals: ScoreSignals = Field(default_factory=ScoreSignals)
    final_score: float = Field(default=0.0, ge=0.0, le=1.0)
    has_fulltext: bool = False
    is_oa: bool = False


# ============================================
# Hypothesis Models
# ============================================


class HypothesisType(str, Enum):
    """Types of research hypotheses."""

    BRIDGE = "bridge"
    ASSUMPTION_RELAXATION = "assumption_relaxation"
    METRIC_GAP = "metric_gap"
    TRANSFER = "transfer"
    NEGATIVE_RESULT_EXPLOITATION = "negative_result_exploitation"


class HypothesisStatus(str, Enum):
    """Status of a hypothesis."""

    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class HypothesisCandidate(BaseModel):
    """A candidate innovation point / hypothesis."""

    id: UUID | None = None
    title: str
    statement: str
    type: HypothesisType
    support_evidence_ids: list[UUID] = Field(default_factory=list)
    oppose_evidence_ids: list[UUID] = Field(default_factory=list)
    novelty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    feasibility_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    status: HypothesisStatus = HypothesisStatus.CANDIDATE
    why_now: str | None = None
    expected_experiments: list[str] = Field(default_factory=list)
    likely_rejection_risks: list[str] = Field(default_factory=list)


# ============================================
# Run State Model
# ============================================


class RunState(BaseModel):
    """
    The complete state of a research run.

    This is the primary state object passed between LangGraph nodes.
    """

    # Identity
    run_id: UUID
    topic: str
    goal_type: GoalType

    # Configuration
    user_constraints: dict[str, Any] = Field(default_factory=dict)
    budget: Budget = Field(default_factory=Budget)
    policy: Policy = Field(default_factory=Policy)
    autonomy_mode: AutonomyMode = AutonomyMode.DEFAULT_AUTONOMOUS

    # Seed papers
    seed_paper_ids: list[UUID] = Field(default_factory=list)
    positive_seed_paper_ids: list[UUID] = Field(default_factory=list)
    negative_seed_paper_ids: list[UUID] = Field(default_factory=list)

    # Research planning
    research_questions: list[str] = Field(default_factory=list)
    query_queue: list[QueryPlan] = Field(default_factory=list)
    coverage_targets: list[CoverageTarget] = Field(default_factory=list)

    # Retrieval state
    candidate_papers: list[CandidatePaper] = Field(default_factory=list)
    selected_paper_ids: list[UUID] = Field(default_factory=list)
    papers_read_count: int = 0

    # Coverage tracking
    coverage_map: dict[str, dict[str, int]] = Field(default_factory=dict)
    saturation_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # Analysis state
    active_cluster_ids: list[UUID] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)

    # Hypotheses
    hypotheses: list[HypothesisCandidate] = Field(default_factory=list)

    # Control state
    current_step: str | None = None
    pause_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)

    # Metrics
    metrics: dict[str, Any] = Field(default_factory=dict)
    total_cost_usd: float = Field(default=0.0)
    total_tool_calls: int = 0

    def should_pause(self) -> bool:
        """Check if the run should pause based on policy."""
        if self.pause_reason:
            return True

        # Budget checks
        if self.policy.auto_pause_on_budget_hit:
            if self.total_cost_usd >= self.budget.max_estimated_cost_usd:
                return True
            if self.total_tool_calls >= self.budget.max_tool_calls:
                return True
            if self.papers_read_count >= self.budget.max_fulltext_reads:
                return True

        return False

    def compute_pause_reason(self) -> str | None:
        """Compute the reason for pausing."""
        if self.total_cost_usd >= self.budget.max_estimated_cost_usd:
            return "budget_cost_exceeded"
        if self.total_tool_calls >= self.budget.max_tool_calls:
            return "budget_tool_calls_exceeded"
        if self.papers_read_count >= self.budget.max_fulltext_reads:
            return "budget_fulltext_reads_exceeded"
        return self.pause_reason


# ============================================
# Event Models
# ============================================


class RunEvent(BaseModel):
    """An event in the research run event stream."""

    run_id: UUID
    event_type: str
    severity: Severity = Severity.INFO
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# API Request/Response Models
# ============================================


class CreateRunRequest(BaseModel):
    """Request to create a new research run."""

    title: str = Field(..., min_length=3, max_length=500)
    topic: str = Field(..., min_length=10, max_length=5000)
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    seed_papers: list[dict[str, str]] = Field(default_factory=list)
    goal_type: GoalType = GoalType.SURVEY_PLUS_INNOVATIONS
    budget: Budget = Field(default_factory=Budget)
    policy: Policy = Field(default_factory=Policy)
    autonomy_mode: AutonomyMode = AutonomyMode.DEFAULT_AUTONOMOUS


class RunResponse(BaseModel):
    """Response for a research run."""

    id: UUID
    title: str
    topic: str
    status: RunStatus
    goal_type: GoalType
    progress_pct: Decimal = Decimal("0")
    current_step: str | None = None
    pause_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class PauseRequest(BaseModel):
    """Request to pause a research run."""

    mode: str = Field(default="soft", pattern="^(soft|hard)$")


class ResumeRequest(BaseModel):
    """Request to resume a paused run."""

    patch: dict[str, Any] | None = None
