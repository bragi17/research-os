"""Tests for automated research production schemas."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from libs.schemas.production import (
    ClaimLedgerCreate,
    ClaimLedgerResponse,
    ClaimStatus,
    ClaimEvidenceSourceType,
    ClaimEvidenceSupportRelation,
    ClaimType,
    CodingEventCreate,
    CodingEventLogLevel,
    CodingEventResponse,
    CodeArtifactType,
    CodingAgentEventType,
    CodingTaskCreate,
    CodingTaskResponse,
    CodingTaskStatus,
    ExperimentJobExecutorType,
    ExperimentJobCreate,
    ExperimentJobPatch,
    ExperimentJobResponse,
    ExperimentJobStatus,
    ExperimentManifestPayload,
    ExperimentPlanCreate,
    ExperimentPlanStatus,
    ExperimentResources,
    NoveltyVerdict,
    ProjectCreate,
    ProjectQueryPackCreate,
    ProjectQueryPackResponse,
    RemoteHostCreate,
    RemoteHostResponse,
    RemoteHostAuthType,
    ResultObservationType,
    TerminalSessionCreate,
    TerminalSessionPatch,
    TerminalSessionResponse,
    TerminalSessionType,
)


def complete_acceptance_criteria() -> dict[str, list[str]]:
    return {
        "sanity_checks": ["debug run completes"],
        "minimum_artifacts": ["metrics.json"],
        "metric_thresholds": ["accuracy >= baseline"],
        "negative_controls": ["shuffled-label baseline"],
        "reproducibility_requirements": ["fixed seeds"],
        "claim_support_requirements": ["main claim has metric evidence"],
    }


def test_project_create_defaults_are_active_and_empty_collections() -> None:
    project = ProjectCreate(title="3D anomaly detection", primary_topic="generalization")

    assert project.status == "active"
    assert project.default_library_pool_ids == []
    assert project.metadata_json == {}

    another = ProjectCreate(title="other", primary_topic="other")
    assert project.default_library_pool_ids is not another.default_library_pool_ids
    assert project.metadata_json is not another.metadata_json


def test_nonblank_text_fields_reject_whitespace_only_values() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(title="   ", primary_topic="generalization")

    with pytest.raises(ValidationError):
        CodingTaskCreate(project_id=uuid4(), user_prompt=" \t\n ")


def test_experiment_plan_rejects_empty_acceptance_criteria() -> None:
    with pytest.raises(ValidationError):
        ExperimentPlanCreate(
            project_id=uuid4(),
            title="Memory ablation",
            hypothesis="Memory improves cross-dataset transfer.",
            method_plan_markdown="Run baseline and memory model.",
            implementation_plan_markdown="Implement train/eval scripts.",
            acceptance_criteria_json={},
        )


def test_experiment_plan_accepts_complete_minimal_payload() -> None:
    project_id = uuid4()

    plan = ExperimentPlanCreate(
        project_id=project_id,
        title="Memory ablation",
        hypothesis="Memory improves cross-dataset transfer.",
        method_plan_markdown="Run baseline and memory model.",
        implementation_plan_markdown="Implement train/eval scripts.",
        acceptance_criteria_json=complete_acceptance_criteria(),
    )

    assert plan.project_id == project_id
    assert plan.status == "draft"
    assert set(plan.acceptance_criteria_json) == set(complete_acceptance_criteria())


def test_experiment_resources_defaults_to_local_first_without_gpu() -> None:
    resources = ExperimentResources()

    assert resources.local_first is True
    assert resources.gpu_required is False


def test_coding_task_create_defaults_codex_and_empty_args() -> None:
    task = CodingTaskCreate(
        project_id=uuid4(),
        user_prompt="Create the experiment scaffold.",
    )

    assert task.provider == "codex"
    assert task.extra_args == []
    assert task.custom_args == []

    another = CodingTaskCreate(project_id=uuid4(), user_prompt="Run tests.")
    assert task.extra_args is not another.extra_args
    assert task.custom_args is not another.custom_args


def test_coding_task_response_preserves_execution_config_fields() -> None:
    now = datetime.now(timezone.utc)
    response = CodingTaskResponse(
        id=uuid4(),
        project_id=uuid4(),
        user_prompt="Create the experiment scaffold.",
        model="gpt-5-codex",
        timeout_sec=3600,
        semantic_inactivity_timeout_sec=600,
        env_json={"CUDA_VISIBLE_DEVICES": "0"},
        mcp_config_json={"servers": {}},
        thinking_level="medium",
        created_at=now,
        updated_at=now,
    )

    assert response.model == "gpt-5-codex"
    assert response.timeout_sec == 3600
    assert response.semantic_inactivity_timeout_sec == 600
    assert response.env_json == {"CUDA_VISIBLE_DEVICES": "0"}
    assert response.mcp_config_json == {"servers": {}}
    assert response.thinking_level == "medium"


def test_production_status_enums_cover_target_state_machines() -> None:
    assert [status.value for status in ExperimentPlanStatus] == [
        "draft",
        "reviewed",
        "accepted",
        "implementing",
        "code_ready",
        "sanity_running",
        "sanity_passed",
        "full_running",
        "analyzing",
        "claim_checked",
        "completed",
        "rejected",
        "code_failed",
        "sanity_failed",
        "experiment_research",
        "manifest_revision",
        "job_failed",
        "stopped",
        "insufficient_evidence",
        "writing_with_limited_claims",
    ]
    assert [status.value for status in CodingTaskStatus] == [
        "queued",
        "running",
        "completed",
        "failed",
        "timeout",
        "cancelled",
        "blocked",
    ]
    assert [event_type.value for event_type in CodingAgentEventType] == [
        "text",
        "thinking",
        "tool_use",
        "tool_result",
        "status",
        "error",
        "log",
    ]
    assert [status.value for status in ExperimentJobStatus] == [
        "pending",
        "running",
        "completed",
        "failed",
        "failed_oom",
        "timeout",
        "stuck",
        "cancelled",
    ]
    assert [status.value for status in ClaimStatus] == [
        "proposed",
        "supported",
        "partially_supported",
        "unsupported",
        "contradicted",
        "needs_more_evidence",
    ]


def test_production_constraint_enums_match_design_values() -> None:
    assert [verdict.value for verdict in NoveltyVerdict] == [
        "novel",
        "incremental",
        "duplicate",
        "unclear",
    ]
    assert [artifact_type.value for artifact_type in CodeArtifactType] == [
        "diff",
        "file_snapshot",
        "manifest",
        "test_output",
        "review_report",
    ]
    assert [executor_type.value for executor_type in ExperimentJobExecutorType] == [
        "local",
        "ssh",
        "docker_gpu",
    ]
    assert [observation_type.value for observation_type in ResultObservationType] == [
        "metric",
        "table",
        "figure",
        "log_signal",
        "anomaly",
        "failure",
    ]
    assert [claim_type.value for claim_type in ClaimType] == [
        "main",
        "ablation",
        "limitation",
        "negative",
        "comparison",
    ]
    assert [source_type.value for source_type in ClaimEvidenceSourceType] == [
        "experiment_job",
        "artifact",
        "paper",
        "chunk",
        "manual_note",
    ]
    assert [relation.value for relation in ClaimEvidenceSupportRelation] == [
        "supports",
        "weakly_supports",
        "contradicts",
        "contextualizes",
    ]
    assert [auth_type.value for auth_type in RemoteHostAuthType] == [
        "key",
        "agent",
        "password_ref",
    ]
    assert [session_type.value for session_type in TerminalSessionType] == [
        "local",
        "ssh",
    ]


def test_experiment_manifest_payload_minimal_defaults_and_validation() -> None:
    payload = ExperimentManifestPayload(project="memory-transfer", workspace=".")

    assert payload.environment.env_vars == {}
    assert payload.environment.install == []
    assert payload.resources.local_first is True
    assert payload.resources.gpu_required is False
    assert payload.resources.max_parallel == 1
    assert payload.phases == []

    with pytest.raises(ValidationError):
        ExperimentManifestPayload(project="", workspace=".")


def test_experiment_job_paths_must_be_workspace_relative() -> None:
    base = {
        "manifest_id": uuid4(),
        "experiment_plan_id": uuid4(),
        "project_id": uuid4(),
        "phase_name": "sanity",
        "job_name": "smoke",
        "cmd": "python train.py --debug",
    }

    ExperimentJobCreate(
        **base,
        cwd="experiments/smoke",
        expected_outputs_json=["metrics.json", "plots/curve.png"],
        metrics_json={"log_dir": ".research-os/jobs/smoke/logs"},
    )

    with pytest.raises(ValidationError):
        ExperimentJobCreate(**base, cwd="/tmp/outside")
    with pytest.raises(ValidationError):
        ExperimentJobCreate(**base, expected_outputs_json=["../secret.txt"])
    with pytest.raises(ValidationError):
        ExperimentJobCreate(**base, metrics_json={"log_dir": "/tmp/logs"})


@pytest.mark.parametrize(
    "metrics",
    [
        {"network": "host"},
        {"job_image": "--privileged"},
        {"job_image": ""},
        {"gpu_count": 0},
    ],
)
def test_docker_gpu_job_create_rejects_unsafe_metrics(metrics: dict) -> None:
    with pytest.raises(ValidationError):
        ExperimentJobCreate(
            manifest_id=uuid4(),
            experiment_plan_id=uuid4(),
            project_id=uuid4(),
            phase_name="sanity",
            job_name="smoke",
            executor_type="docker_gpu",
            cmd="python train.py --debug",
            metrics_json=metrics,
        )


def test_docker_gpu_job_patch_rejects_unsafe_metrics_when_executor_type_is_provided() -> None:
    with pytest.raises(ValidationError):
        ExperimentJobPatch(
            executor_type="docker_gpu",
            metrics_json={"network": "host"},
        )


def test_job_patch_allows_metric_names_without_executor_context() -> None:
    patch = ExperimentJobPatch(
        metrics_json={"memory": "avg_peak_by_phase", "network": "host"},
    )

    assert patch.metrics_json == {"memory": "avg_peak_by_phase", "network": "host"}


def test_typed_patch_models_validate_status_and_paths() -> None:
    with pytest.raises(ValidationError):
        ExperimentJobPatch(status="not-a-status")
    with pytest.raises(ValidationError):
        ExperimentJobPatch(cwd="../outside")
    with pytest.raises(ValidationError):
        TerminalSessionPatch(status="not-a-status")

    patch = ExperimentJobPatch(status=ExperimentJobStatus.RUNNING, cwd="experiments")
    assert patch.status == "running"
    assert patch.cwd == "experiments"


def test_table_create_and_response_models_cover_representative_entities() -> None:
    now = datetime.now(timezone.utc)
    project_id = uuid4()
    run_id = uuid4()
    task_id = uuid4()
    manifest_id = uuid4()
    plan_id = uuid4()
    job_id = uuid4()
    remote_host_id = uuid4()
    claim_id = uuid4()
    terminal_id = uuid4()
    user_id = uuid4()

    query_pack = ProjectQueryPackCreate(
        project_id=project_id,
        query_pack_json={"topic": "memory transfer"},
    )
    query_pack_response = ProjectQueryPackResponse(
        id=uuid4(),
        project_id=query_pack.project_id,
        source_run_id=None,
        topic=None,
        query_pack_json=query_pack.query_pack_json,
        created_at=now,
        updated_at=now,
    )
    assert query_pack.query_pack_json["topic"] == "memory transfer"
    assert query_pack_response.id

    coding_event = CodingEventCreate(
        coding_task_id=task_id,
        run_id=run_id,
        event_type=CodingAgentEventType.STATUS,
        status_text="running",
        level="info",
    )
    coding_event_response = CodingEventResponse(
        id=1,
        coding_task_id=coding_event.coding_task_id,
        run_id=coding_event.run_id,
        event_type=coding_event.event_type,
        content=None,
        tool=None,
        call_id=None,
        input_json=None,
        output_text=None,
        status_text=coding_event.status_text,
        level=coding_event.level,
        provider_raw_json={},
        created_at=now,
    )
    assert coding_event_response.id == 1
    assert coding_event_response.event_type == "status"
    assert coding_event_response.level == CodingEventLogLevel.INFO

    experiment_job = ExperimentJobCreate(
        manifest_id=manifest_id,
        experiment_plan_id=plan_id,
        project_id=project_id,
        phase_name="sanity",
        job_name="smoke",
        cmd="python train.py --debug",
    )
    experiment_job_response = ExperimentJobResponse(
        id=job_id,
        manifest_id=experiment_job.manifest_id,
        experiment_plan_id=experiment_job.experiment_plan_id,
        project_id=experiment_job.project_id,
        phase_name=experiment_job.phase_name,
        job_name=experiment_job.job_name,
        executor_type=experiment_job.executor_type,
        remote_host_id=None,
        cmd=experiment_job.cmd,
        cwd=experiment_job.cwd,
        pid=None,
        status=experiment_job.status,
        attempt=experiment_job.attempt,
        max_attempts=experiment_job.max_attempts,
        expected_outputs_json=experiment_job.expected_outputs_json,
        metrics_json=experiment_job.metrics_json,
        stdout_log_path=None,
        stderr_log_path=None,
        artifact_dir=None,
        started_at=None,
        completed_at=None,
        last_heartbeat_at=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )
    assert experiment_job.executor_type == "local"
    assert experiment_job.status == "pending"
    assert experiment_job_response.id == job_id

    claim = ClaimLedgerCreate(project_id=project_id, claim_text="Memory helps transfer.")
    claim_response = ClaimLedgerResponse(
        id=claim_id,
        project_id=claim.project_id,
        experiment_plan_id=None,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        status=claim.status,
        support_level=None,
        evidence_summary=None,
        reviewer_model=None,
        human_decision=None,
        created_at=now,
        updated_at=now,
    )
    assert claim.claim_type == "main"
    assert claim.status == "proposed"
    assert claim_response.id == claim_id

    remote_host = RemoteHostCreate(name="gpu-box", owner_user_id=user_id, host="gpu.example.test")
    remote_host_response = RemoteHostResponse(
        id=remote_host_id,
        name=remote_host.name,
        owner_user_id=remote_host.owner_user_id,
        host=remote_host.host,
        port=remote_host.port,
        username=None,
        auth_type=remote_host.auth_type,
        key_ref=None,
        default_workdir=None,
        default_env_json={},
        capabilities_json={},
        status=remote_host.status,
        last_checked_at=None,
        created_at=now,
        updated_at=now,
    )
    assert remote_host.auth_type == "agent"
    assert remote_host.status == "unknown"
    assert remote_host_response.owner_user_id == user_id
    assert remote_host_response.id == remote_host_id

    terminal_session = TerminalSessionCreate(project_id=project_id, run_id=run_id)
    terminal_response = TerminalSessionResponse(
        id=terminal_id,
        project_id=terminal_session.project_id,
        run_id=terminal_session.run_id,
        experiment_job_id=None,
        session_type=terminal_session.session_type,
        remote_host_id=None,
        cwd=None,
        shell=None,
        status=terminal_session.status,
        created_by=None,
        created_at=now,
        closed_at=None,
    )
    assert terminal_session.session_type == "local"
    assert terminal_session.status == "opening"
    assert terminal_response.id == terminal_id


def test_submission_package_has_independent_audit_reports():
    from libs.schemas.production import SubmissionPackageCreate

    package = SubmissionPackageCreate(
        manuscript_package_id="00000000-0000-0000-0000-000000000001",
        venue="ICLR",
        paper_claim_audit_report_json={"passed": True},
        adversarial_audit_report_json={
            "passed": False,
            "blockers": ["missing ablation"],
        },
    )

    assert package.paper_claim_audit_report_json["passed"] is True
    assert package.adversarial_audit_report_json["blockers"] == [
        "missing ablation"
    ]
