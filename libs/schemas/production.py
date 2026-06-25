"""
Research OS - automated research production schemas.

Shared Pydantic models for project, experiment, coding task, manifest, job,
claim, writing, and submission contracts.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SAFE_DOCKER_IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")
SAFE_DOCKER_MEMORY = re.compile(r"^[1-9][0-9]*[bkmgBKMG]?$")
SAFE_DOCKER_CPUS = re.compile(r"^(?:[1-9][0-9]*|[1-9][0-9]*\.[0-9]+|0\.[0-9]*[1-9][0-9]*)$")


def _validate_workspace_relative_path(value: str | None, field_name: str) -> str | None:
    """Reject absolute paths and traversal for command-execution fields."""

    if value is None:
        return value
    raw = str(value).strip()
    if raw == "":
        return "."
    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field_name} must be a workspace-relative path")
    return raw


def _validate_terminal_shell(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if raw == "":
        return None
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError("unsafe shell value")
    if raw.startswith("-"):
        raise ValueError("unsafe shell value")
    path = PurePosixPath(raw.replace("\\", "/"))
    if ".." in path.parts:
        raise ValueError("unsafe shell value")
    if not path.is_absolute() and "/" in raw:
        raise ValueError("unsafe shell value")
    return raw


def _validate_docker_image_reference(value: str) -> str:
    raw = str(value).strip()
    if (
        not raw
        or raw.startswith("-")
        or any(character.isspace() or ord(character) < 32 for character in raw)
        or SAFE_DOCKER_IMAGE_REFERENCE.fullmatch(raw) is None
    ):
        raise ValueError("docker image reference is unsafe")
    return raw


def _validate_docker_memory(value: str) -> str:
    raw = str(value).strip()
    if (
        not raw
        or raw.startswith("-")
        or any(character.isspace() or ord(character) < 32 for character in raw)
        or SAFE_DOCKER_MEMORY.fullmatch(raw) is None
    ):
        raise ValueError("docker memory value is unsafe")
    unit = raw[-1].lower() if raw[-1].isalpha() else "b"
    amount = int(raw[:-1] if raw[-1].isalpha() else raw)
    multiplier_by_unit = {
        "b": 1,
        "k": 1024,
        "m": 1024**2,
        "g": 1024**3,
    }
    if amount * multiplier_by_unit[unit] > 1024**4:
        raise ValueError("docker memory value is outside allowed range")
    return raw


def _validate_docker_cpus(value: str) -> str:
    raw = str(value).strip()
    if (
        not raw
        or raw.startswith("-")
        or any(character.isspace() or ord(character) < 32 for character in raw)
        or SAFE_DOCKER_CPUS.fullmatch(raw) is None
    ):
        raise ValueError("docker cpus value is unsafe")
    cpus = float(raw)
    if cpus <= 0 or cpus > 256:
        raise ValueError("docker cpus value is outside allowed range")
    return raw


DOCKER_METRIC_KEYS = {"gpu_count", "job_image", "memory", "cpus", "network"}


def validate_docker_job_metrics(
    metrics: dict[str, Any],
    *,
    require_all: bool = False,
) -> dict[str, Any]:
    """Validate Docker executor metadata carried in experiment job metrics."""

    values = dict(metrics)
    if require_all or "gpu_count" in values:
        gpu_count = values.get("gpu_count", 1)
        try:
            gpu_count_int = int(gpu_count)
        except (TypeError, ValueError) as exc:
            raise ValueError("docker gpu_count must be an integer") from exc
        if gpu_count_int < 1:
            raise ValueError("docker gpu_count must be at least 1")
        values["gpu_count"] = gpu_count_int

    if require_all or "job_image" in values:
        job_image = values["job_image"] if "job_image" in values else "research-os-job-runtime:latest"
        values["job_image"] = _validate_docker_image_reference(str(job_image))
    if require_all or "memory" in values:
        memory = values["memory"] if "memory" in values else "16g"
        values["memory"] = _validate_docker_memory(str(memory))
    if require_all or "cpus" in values:
        cpus = values["cpus"] if "cpus" in values else "4"
        values["cpus"] = _validate_docker_cpus(str(cpus))
    if require_all or "network" in values:
        network_value = values["network"] if "network" in values else "none"
        network = str(network_value).strip()
        if network != "none":
            raise ValueError("docker network must be none")
        values["network"] = network
    return values


class ProjectStatus(str, Enum):
    """Research project lifecycle states."""

    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    COMPLETED = "completed"


class NoveltyVerdict(str, Enum):
    """Novelty review verdicts."""

    NOVEL = "novel"
    INCREMENTAL = "incremental"
    DUPLICATE = "duplicate"
    UNCLEAR = "unclear"


class ExperimentPlanStatus(str, Enum):
    """Experiment plan lifecycle states."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    IMPLEMENTING = "implementing"
    CODE_READY = "code_ready"
    SANITY_RUNNING = "sanity_running"
    SANITY_PASSED = "sanity_passed"
    FULL_RUNNING = "full_running"
    ANALYZING = "analyzing"
    CLAIM_CHECKED = "claim_checked"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CODE_FAILED = "code_failed"
    SANITY_FAILED = "sanity_failed"
    EXPERIMENT_RESEARCH = "experiment_research"
    MANIFEST_REVISION = "manifest_revision"
    JOB_FAILED = "job_failed"
    STOPPED = "stopped"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    WRITING_WITH_LIMITED_CLAIMS = "writing_with_limited_claims"


class CodingAgentProvider(str, Enum):
    """Supported local coding agent providers."""

    CODEX = "codex"
    CLAUDE = "claude"
    COPILOT = "copilot"
    CURSOR = "cursor"
    OPENCODE = "opencode"


class CodingTaskStatus(str, Enum):
    """Coding task lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class CodingAgentEventType(str, Enum):
    """Normalized coding agent event stream types."""

    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    STATUS = "status"
    ERROR = "error"
    LOG = "log"


class CodingEventLogLevel(str, Enum):
    """Coding event log severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class CodeArtifactType(str, Enum):
    """Code artifact types stored from coding tasks."""

    DIFF = "diff"
    FILE_SNAPSHOT = "file_snapshot"
    MANIFEST = "manifest"
    TEST_OUTPUT = "test_output"
    REVIEW_REPORT = "review_report"


class CodeArtifactValidationStatus(str, Enum):
    """Code artifact validation states."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ExperimentManifestStatus(str, Enum):
    """Experiment manifest lifecycle states."""

    DRAFT = "draft"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExperimentJobExecutorType(str, Enum):
    """Experiment job executor backends."""

    LOCAL = "local"
    SSH = "ssh"
    DOCKER_GPU = "docker_gpu"


class ExperimentJobStatus(str, Enum):
    """Experiment job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    FAILED_OOM = "failed_oom"
    TIMEOUT = "timeout"
    STUCK = "stuck"
    CANCELLED = "cancelled"


class ResultObservationType(str, Enum):
    """Result observation categories."""

    METRIC = "metric"
    TABLE = "table"
    FIGURE = "figure"
    LOG_SIGNAL = "log_signal"
    ANOMALY = "anomaly"
    FAILURE = "failure"


class ClaimType(str, Enum):
    """Claim ledger claim categories."""

    MAIN = "main"
    ABLATION = "ablation"
    LIMITATION = "limitation"
    NEGATIVE = "negative"
    COMPARISON = "comparison"


class ClaimStatus(str, Enum):
    """Claim ledger support states."""

    PROPOSED = "proposed"
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class ClaimEvidenceSourceType(str, Enum):
    """Claim evidence source categories."""

    EXPERIMENT_JOB = "experiment_job"
    ARTIFACT = "artifact"
    PAPER = "paper"
    CHUNK = "chunk"
    MANUAL_NOTE = "manual_note"


class ClaimEvidenceSupportRelation(str, Enum):
    """Claim evidence support relations."""

    SUPPORTS = "supports"
    WEAKLY_SUPPORTS = "weakly_supports"
    CONTRADICTS = "contradicts"
    CONTEXTUALIZES = "contextualizes"


class ManuscriptPackageStatus(str, Enum):
    """Manuscript package lifecycle states."""

    OUTLINE = "outline"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"
    REVISING = "revising"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    RESUBMITTING = "resubmitting"


class SubmissionPackageStatus(str, Enum):
    """Submission package lifecycle states."""

    PREPARING = "preparing"
    GATED = "gated"
    READY = "ready"
    SUBMITTED = "submitted"
    FAILED = "failed"


class RemoteHostStatus(str, Enum):
    """Remote SSH host reachability states."""

    UNKNOWN = "unknown"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"


class RemoteHostAuthType(str, Enum):
    """Remote SSH host authentication types."""

    KEY = "key"
    AGENT = "agent"
    PASSWORD_REF = "password_ref"


class TerminalSessionType(str, Enum):
    """Embedded terminal transport types."""

    LOCAL = "local"
    SSH = "ssh"


class TerminalSessionStatus(str, Enum):
    """Embedded terminal session states."""

    OPENING = "opening"
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"


class ProjectCreate(BaseModel):
    """Request payload to create a durable research project."""

    title: NonBlankStr
    description: str | None = None
    primary_topic: NonBlankStr
    status: ProjectStatus = ProjectStatus.ACTIVE
    owner_user_id: UUID | None = None
    workspace_id: UUID | None = None
    default_library_pool_ids: list[UUID] = Field(default_factory=list)
    default_workspace_path: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ProjectResponse(ProjectCreate):
    """Persisted research project."""

    id: UUID
    created_at: datetime
    updated_at: datetime


REQUIRED_ACCEPTANCE_CRITERIA_KEYS: tuple[str, ...] = (
    "sanity_checks",
    "minimum_artifacts",
    "metric_thresholds",
    "negative_controls",
    "reproducibility_requirements",
    "claim_support_requirements",
)


class ExperimentPlanCreate(BaseModel):
    """Request payload to create an experiment plan after novelty review."""

    project_id: UUID
    idea_id: UUID | None = None
    source_run_id: UUID | None = None
    title: NonBlankStr
    hypothesis: NonBlankStr
    method_plan_markdown: NonBlankStr
    implementation_plan_markdown: NonBlankStr
    datasets_json: dict[str, Any] = Field(default_factory=dict)
    baselines_json: dict[str, Any] = Field(default_factory=dict)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    ablation_plan_json: dict[str, Any] = Field(default_factory=dict)
    resource_plan_json: dict[str, Any] = Field(default_factory=dict)
    expected_outputs_json: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria_json: dict[str, Any]
    risk_register_json: dict[str, Any] = Field(default_factory=dict)
    status: ExperimentPlanStatus = ExperimentPlanStatus.DRAFT

    @model_validator(mode="after")
    def validate_acceptance_criteria(self) -> ExperimentPlanCreate:
        missing = [
            key
            for key in REQUIRED_ACCEPTANCE_CRITERIA_KEYS
            if key not in self.acceptance_criteria_json
        ]
        if missing:
            missing_keys = ", ".join(missing)
            raise ValueError(f"acceptance_criteria_json missing keys: {missing_keys}")
        return self


class ExperimentResources(BaseModel):
    """Execution resources section from an experiment manifest."""

    local_first: bool = True
    gpu_required: bool = False
    remote_host_id: UUID | None = None
    executor_type: Literal["local", "ssh", "docker_gpu"] | None = None
    gpu_count: int = Field(default=1, ge=1)
    job_image: str = "research-os-job-runtime:latest"
    memory: str = "16g"
    cpus: str = "4"
    network: Literal["none"] = "none"
    max_parallel: int = Field(default=1, ge=1)

    @field_validator("job_image")
    @classmethod
    def validate_job_image(cls, value: str) -> str:
        return _validate_docker_image_reference(value)

    @field_validator("memory")
    @classmethod
    def validate_memory(cls, value: str) -> str:
        return _validate_docker_memory(value)

    @field_validator("cpus")
    @classmethod
    def validate_cpus(cls, value: str) -> str:
        return _validate_docker_cpus(value)

    @model_validator(mode="after")
    def validate_docker_metrics(self) -> ExperimentResources:
        validate_docker_job_metrics(
            {
                "gpu_count": self.gpu_count,
                "job_image": self.job_image,
                "memory": self.memory,
                "cpus": self.cpus,
                "network": self.network,
            },
            require_all=True,
        )
        return self


class ExperimentEnvironment(BaseModel):
    """Environment section from an experiment manifest."""

    python: str | None = None
    conda: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    install: list[str] = Field(default_factory=list)


class ExperimentRetryPolicy(BaseModel):
    """Retry policy for one manifest job."""

    max_attempts: int = Field(default=1, ge=1)
    oom_retry: bool = False


class ExperimentJobSpec(BaseModel):
    """One executable job in a manifest phase."""

    name: NonBlankStr
    cmd: NonBlankStr
    cwd: str = "."
    expected_outputs: list[str] = Field(default_factory=list)
    timeout_sec: int = Field(default=1800, ge=1)
    retry: ExperimentRetryPolicy = Field(default_factory=ExperimentRetryPolicy)


class ExperimentPhase(BaseModel):
    """A manifest phase containing ordered experiment jobs."""

    name: NonBlankStr
    depends_on: list[str] = Field(default_factory=list)
    jobs: list[ExperimentJobSpec] = Field(default_factory=list)


class ExperimentManifestPayload(BaseModel):
    """Structured experiment manifest payload."""

    project: NonBlankStr
    workspace: NonBlankStr
    environment: ExperimentEnvironment = Field(default_factory=ExperimentEnvironment)
    resources: ExperimentResources = Field(default_factory=ExperimentResources)
    phases: list[ExperimentPhase] = Field(default_factory=list)


class CodingTaskCreate(BaseModel):
    """Request payload to create a local coding agent task."""

    project_id: UUID
    run_id: UUID | None = None
    experiment_plan_id: UUID | None = None
    provider: CodingAgentProvider = CodingAgentProvider.CODEX
    workspace_path: str | None = None
    thread_name: str | None = None
    system_prompt: str | None = None
    user_prompt: NonBlankStr
    model: str | None = None
    timeout_sec: int | None = Field(default=None, ge=1)
    semantic_inactivity_timeout_sec: int | None = Field(default=None, ge=1)
    extra_args: list[str] = Field(default_factory=list)
    custom_args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    mcp_config: dict[str, Any] | None = None
    thinking_level: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ProjectQueryPackCreate(BaseModel):
    """Request payload for reusable project research context."""

    project_id: UUID
    source_run_id: UUID | None = None
    topic: str | None = None
    query_pack_json: dict[str, Any] = Field(default_factory=dict)


class ProjectQueryPackResponse(ProjectQueryPackCreate):
    """Persisted project query pack."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class NoveltyReportCreate(BaseModel):
    """Request payload for novelty-check results."""

    project_id: UUID | None = None
    idea_id: UUID | None = None
    search_queries_json: list[Any] = Field(default_factory=list)
    competing_work_json: list[Any] = Field(default_factory=list)
    claim_overlap_json: dict[str, Any] = Field(default_factory=dict)
    novelty_verdict: NoveltyVerdict = NoveltyVerdict.UNCLEAR
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reviewer_model: str | None = None
    human_decision: str | None = None


class NoveltyReportResponse(NoveltyReportCreate):
    """Persisted novelty report."""

    id: UUID
    created_at: datetime


class ExperimentPlanResponse(BaseModel):
    """Persisted experiment plan."""

    id: UUID
    project_id: UUID
    idea_id: UUID | None = None
    source_run_id: UUID | None = None
    title: NonBlankStr
    hypothesis: NonBlankStr
    method_plan_markdown: NonBlankStr
    implementation_plan_markdown: NonBlankStr
    datasets_json: dict[str, Any] = Field(default_factory=dict)
    baselines_json: dict[str, Any] = Field(default_factory=dict)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    ablation_plan_json: dict[str, Any] = Field(default_factory=dict)
    resource_plan_json: dict[str, Any] = Field(default_factory=dict)
    expected_outputs_json: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria_json: dict[str, Any]
    risk_register_json: dict[str, Any] = Field(default_factory=dict)
    status: ExperimentPlanStatus = ExperimentPlanStatus.DRAFT
    created_at: datetime
    updated_at: datetime


class CodingTaskResponse(BaseModel):
    """Persisted coding-agent task."""

    id: UUID
    project_id: UUID
    run_id: UUID | None = None
    experiment_plan_id: UUID | None = None
    provider: CodingAgentProvider = CodingAgentProvider.CODEX
    provider_session_id: str | None = None
    workspace_path: str | None = None
    thread_name: str | None = None
    system_prompt: str | None = None
    user_prompt: NonBlankStr
    model: str | None = None
    timeout_sec: int | None = Field(default=None, ge=1)
    semantic_inactivity_timeout_sec: int | None = Field(default=None, ge=1)
    env_json: dict[str, str] = Field(default_factory=dict)
    mcp_config_json: dict[str, Any] = Field(default_factory=dict)
    thinking_level: str | None = None
    prompt_hash: str | None = None
    status: CodingTaskStatus = CodingTaskStatus.QUEUED
    failure_reason: str | None = None
    failure_detail: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    token_usage_json: dict[str, Any] = Field(default_factory=dict)
    extra_args: list[str] = Field(default_factory=list)
    custom_args: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CodingEventCreate(BaseModel):
    """Request payload for a normalized coding-agent stream event."""

    coding_task_id: UUID
    run_id: UUID | None = None
    event_type: CodingAgentEventType
    content: str | None = None
    tool: str | None = None
    call_id: str | None = None
    input_json: dict[str, Any] | None = None
    output_text: str | None = None
    status_text: str | None = None
    level: CodingEventLogLevel | None = None
    provider_raw_json: dict[str, Any] = Field(default_factory=dict)


class CodingEventResponse(CodingEventCreate):
    """Persisted coding-agent stream event."""

    id: int
    created_at: datetime


class CodeArtifactCreate(BaseModel):
    """Request payload for a coding-task artifact."""

    coding_task_id: UUID | None = None
    project_id: UUID
    experiment_plan_id: UUID | None = None
    artifact_type: CodeArtifactType
    path: NonBlankStr
    content_hash: str | None = None
    summary: str | None = None
    validation_status: CodeArtifactValidationStatus = CodeArtifactValidationStatus.PENDING
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_workspace_relative_path(value, "path") or "."


class CodeArtifactResponse(CodeArtifactCreate):
    """Persisted coding-task artifact."""

    id: UUID
    created_at: datetime


class ExperimentManifestCreate(BaseModel):
    """Request payload for an experiment manifest."""

    experiment_plan_id: UUID
    project_id: UUID
    manifest_json: dict[str, Any] = Field(default_factory=dict)
    manifest_version: str = "1"
    generated_by_coding_task_id: UUID | None = None
    status: ExperimentManifestStatus = ExperimentManifestStatus.DRAFT


class ExperimentManifestResponse(ExperimentManifestCreate):
    """Persisted experiment manifest."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class ExperimentJobCreate(BaseModel):
    """Request payload for an executable experiment job."""

    manifest_id: UUID
    experiment_plan_id: UUID
    project_id: UUID
    phase_name: NonBlankStr
    job_name: NonBlankStr
    executor_type: ExperimentJobExecutorType = ExperimentJobExecutorType.LOCAL
    remote_host_id: UUID | None = None
    cmd: NonBlankStr
    cwd: str = "."
    pid: int | None = None
    status: ExperimentJobStatus = ExperimentJobStatus.PENDING
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=1, ge=1)
    expected_outputs_json: list[Any] = Field(default_factory=list)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    stdout_log_path: str | None = None
    stderr_log_path: str | None = None
    artifact_dir: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_job(self) -> ExperimentJobCreate:
        if self.attempt > self.max_attempts:
            raise ValueError("attempt must be less than or equal to max_attempts")
        if self.executor_type == ExperimentJobExecutorType.DOCKER_GPU:
            validate_docker_job_metrics(self.metrics_json, require_all=True)
        return self

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        return _validate_workspace_relative_path(value, "cwd") or "."

    @field_validator("expected_outputs_json")
    @classmethod
    def validate_expected_outputs(cls, value: list[Any]) -> list[Any]:
        for item in value:
            if isinstance(item, str):
                _validate_workspace_relative_path(item, "expected_outputs_json")
        return value

    @field_validator("metrics_json")
    @classmethod
    def validate_metrics_log_dir(cls, value: dict[str, Any]) -> dict[str, Any]:
        log_dir = value.get("log_dir")
        if isinstance(log_dir, str):
            _validate_workspace_relative_path(log_dir, "metrics_json.log_dir")
        return value


class ExperimentJobResponse(ExperimentJobCreate):
    """Persisted experiment job."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class ExperimentPlanStatusPatch(BaseModel):
    """Typed status patch for an experiment plan."""

    model_config = ConfigDict(extra="ignore")

    status: ExperimentPlanStatus


class CodingTaskPatch(BaseModel):
    """Typed patch payload for a coding-agent task."""

    model_config = ConfigDict(extra="ignore")

    provider_session_id: str | None = None
    workspace_path: str | None = None
    thread_name: str | None = None
    system_prompt: str | None = None
    user_prompt: NonBlankStr | None = None
    model: str | None = None
    timeout_sec: int | None = Field(default=None, ge=1)
    semantic_inactivity_timeout_sec: int | None = Field(default=None, ge=1)
    env_json: dict[str, str] | None = None
    mcp_config_json: dict[str, Any] | None = None
    thinking_level: str | None = None
    prompt_hash: str | None = None
    status: CodingTaskStatus | None = None
    failure_reason: str | None = None
    failure_detail: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    token_usage_json: dict[str, Any] | None = None
    extra_args: list[str] | None = None
    custom_args: list[str] | None = None
    metadata_json: dict[str, Any] | None = None


class ExperimentJobPatch(BaseModel):
    """Typed patch payload for an experiment job."""

    model_config = ConfigDict(extra="ignore")

    phase_name: NonBlankStr | None = None
    job_name: NonBlankStr | None = None
    executor_type: ExperimentJobExecutorType | None = None
    remote_host_id: UUID | None = None
    cmd: NonBlankStr | None = None
    cwd: str | None = None
    pid: int | None = None
    status: ExperimentJobStatus | None = None
    attempt: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)
    expected_outputs_json: list[Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    failure_reason: str | None = None
    metrics_json: dict[str, Any] | None = None
    stdout_log_path: str | None = None
    stderr_log_path: str | None = None
    artifact_dir: str | None = None

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str | None) -> str | None:
        return _validate_workspace_relative_path(value, "cwd")

    @field_validator("expected_outputs_json")
    @classmethod
    def validate_expected_outputs(cls, value: list[Any] | None) -> list[Any] | None:
        if value is None:
            return None
        for item in value:
            if isinstance(item, str):
                _validate_workspace_relative_path(item, "expected_outputs_json")
        return value

    @field_validator("metrics_json")
    @classmethod
    def validate_metrics_log_dir(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        log_dir = value.get("log_dir")
        if isinstance(log_dir, str):
            _validate_workspace_relative_path(log_dir, "metrics_json.log_dir")
        return value

    @field_validator("stdout_log_path", "stderr_log_path", "artifact_dir")
    @classmethod
    def validate_workspace_relative_stored_paths(cls, value: str | None) -> str | None:
        return _validate_workspace_relative_path(value, "experiment job path")

    @model_validator(mode="after")
    def validate_attempt_bounds(self) -> ExperimentJobPatch:
        if self.attempt is not None and self.max_attempts is not None and self.attempt > self.max_attempts:
            raise ValueError("attempt must be less than or equal to max_attempts")
        if self.metrics_json is not None:
            validate_docker_metrics = (
                self.executor_type == ExperimentJobExecutorType.DOCKER_GPU
                or any(key in self.metrics_json for key in DOCKER_METRIC_KEYS)
            )
            if validate_docker_metrics:
                validate_docker_job_metrics(
                    self.metrics_json,
                    require_all=self.executor_type == ExperimentJobExecutorType.DOCKER_GPU,
                )
        return self


class ResultObservationCreate(BaseModel):
    """Request payload for one result observation."""

    experiment_job_id: UUID
    experiment_plan_id: UUID
    project_id: UUID
    observation_type: ResultObservationType
    payload_json: dict[str, Any] = Field(default_factory=dict)
    source_artifact_path: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ResultObservationResponse(ResultObservationCreate):
    """Persisted result observation."""

    id: UUID
    created_at: datetime


class ClaimLedgerCreate(BaseModel):
    """Request payload for a claim ledger entry."""

    project_id: UUID
    experiment_plan_id: UUID | None = None
    claim_text: NonBlankStr
    claim_type: ClaimType = ClaimType.MAIN
    status: ClaimStatus = ClaimStatus.PROPOSED
    support_level: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_summary: str | None = None
    reviewer_model: str | None = None
    human_decision: str | None = None


class ClaimLedgerResponse(ClaimLedgerCreate):
    """Persisted claim ledger entry."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class ClaimEvidenceCreate(BaseModel):
    """Request payload for evidence attached to a claim."""

    claim_id: UUID
    source_type: ClaimEvidenceSourceType
    source_id: UUID | None = None
    quote_or_metric: str | None = None
    artifact_path: str | None = None
    support_relation: ClaimEvidenceSupportRelation


class ClaimEvidenceResponse(ClaimEvidenceCreate):
    """Persisted claim evidence entry."""

    id: UUID
    created_at: datetime


class ManuscriptPackageCreate(BaseModel):
    """Request payload for a manuscript package."""

    project_id: UUID
    title: NonBlankStr
    venue_target: str | None = None
    paper_dir: str | None = None
    status: ManuscriptPackageStatus = ManuscriptPackageStatus.OUTLINE
    claim_ledger_snapshot_id: UUID | None = None
    bib_snapshot_id: UUID | None = None
    artifact_snapshot_id: UUID | None = None

    @field_validator("paper_dir")
    @classmethod
    def validate_paper_dir(cls, value: str | None) -> str | None:
        return _validate_workspace_relative_path(value, "paper_dir")


class ManuscriptPackageResponse(ManuscriptPackageCreate):
    """Persisted manuscript package."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class SubmissionPackageCreate(BaseModel):
    """Request payload for a submission package."""

    manuscript_package_id: UUID
    venue: NonBlankStr
    deadline: datetime | None = None
    submission_dir: str | None = None
    checklist_json: dict[str, Any] = Field(default_factory=dict)
    anonymity_report_json: dict[str, Any] = Field(default_factory=dict)
    compile_report_json: dict[str, Any] = Field(default_factory=dict)
    claim_audit_report_json: dict[str, Any] = Field(default_factory=dict)
    citation_audit_report_json: dict[str, Any] = Field(default_factory=dict)
    artifact_provenance_report_json: dict[str, Any] = Field(default_factory=dict)
    paper_claim_audit_report_json: dict[str, Any] = Field(default_factory=dict)
    adversarial_audit_report_json: dict[str, Any] = Field(default_factory=dict)
    status: SubmissionPackageStatus = SubmissionPackageStatus.PREPARING

    @field_validator("submission_dir")
    @classmethod
    def validate_submission_dir(cls, value: str | None) -> str | None:
        return _validate_workspace_relative_path(value, "submission_dir")


class SubmissionPackageResponse(SubmissionPackageCreate):
    """Persisted submission package."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class RemoteHostCreate(BaseModel):
    """Request payload for a lightweight SSH remote host."""

    name: NonBlankStr
    owner_user_id: UUID | None = None
    host: NonBlankStr
    port: int = Field(default=22, ge=1, le=65535)
    username: str | None = None
    auth_type: RemoteHostAuthType = RemoteHostAuthType.AGENT
    key_ref: str | None = None
    default_workdir: str | None = None
    default_env_json: dict[str, Any] = Field(default_factory=dict)
    capabilities_json: dict[str, Any] = Field(default_factory=dict)
    status: RemoteHostStatus = RemoteHostStatus.UNKNOWN
    last_checked_at: datetime | None = None


class RemoteHostResponse(RemoteHostCreate):
    """Persisted remote host."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class TerminalSessionCreate(BaseModel):
    """Request payload for an embedded terminal session."""

    project_id: UUID | None = None
    run_id: UUID | None = None
    experiment_job_id: UUID | None = None
    session_type: TerminalSessionType = TerminalSessionType.LOCAL
    remote_host_id: UUID | None = None
    cwd: str | None = None
    shell: str | None = None
    status: TerminalSessionStatus = TerminalSessionStatus.OPENING
    created_by: UUID | None = None
    closed_at: datetime | None = None

    @field_validator("shell")
    @classmethod
    def validate_shell(cls, value: str | None) -> str | None:
        return _validate_terminal_shell(value)


class TerminalSessionResponse(BaseModel):
    """Persisted terminal session."""

    project_id: UUID | None = None
    run_id: UUID | None = None
    experiment_job_id: UUID | None = None
    session_type: TerminalSessionType = TerminalSessionType.LOCAL
    remote_host_id: UUID | None = None
    cwd: str | None = None
    shell: str | None = None
    status: TerminalSessionStatus = TerminalSessionStatus.OPENING
    created_by: UUID | None = None
    closed_at: datetime | None = None
    id: UUID
    created_at: datetime


class TerminalSessionPatch(BaseModel):
    """Typed patch payload for an embedded terminal session."""

    model_config = ConfigDict(extra="ignore")

    remote_host_id: UUID | None = None
    cwd: str | None = None
    shell: str | None = None
    status: TerminalSessionStatus | None = None
    closed_at: datetime | None = None

    @field_validator("shell")
    @classmethod
    def validate_shell(cls, value: str | None) -> str | None:
        return _validate_terminal_shell(value)


class TerminalResizeRequest(BaseModel):
    """Terminal resize request."""

    rows: int = Field(default=24, ge=1, le=500)
    cols: int = Field(default=80, ge=1, le=1000)
