from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from pydantic import ValidationError

from libs.schemas.production import ExperimentManifestPayload


class ManifestValidationError(ValueError):
    """Raised when an experiment manifest is structurally invalid."""


@dataclass(frozen=True)
class ExpandedManifestJob:
    phase_name: str
    job_name: str
    cmd: str
    cwd: str
    expected_outputs: list[str]
    phase_dependencies: list[str]
    timeout_sec: int
    max_attempts: int
    oom_retry: bool
    phase_index: int
    job_index: int


def expand_manifest_jobs(
    manifest: dict[str, Any] | ExperimentManifestPayload,
) -> list[ExpandedManifestJob]:
    payload = _coerce_manifest(manifest)
    _validate_manifest_payload(payload)

    jobs: list[ExpandedManifestJob] = []
    for phase_index, phase in enumerate(payload.phases):
        seen_job_names: set[str] = set()
        if not phase.jobs:
            raise ManifestValidationError(f"phase '{phase.name}' contains empty jobs")

        for job_index, job in enumerate(phase.jobs):
            if job.name in seen_job_names:
                raise ManifestValidationError(
                    f"duplicate job name '{job.name}' in phase '{phase.name}'"
                )
            seen_job_names.add(job.name)
            if not job.cmd.strip():
                raise ManifestValidationError(
                    f"job '{job.name}' in phase '{phase.name}' has empty cmd"
                )
            _validate_workspace_relative_path(
                job.cwd,
                field_name="cwd",
                phase_name=phase.name,
                job_name=job.name,
            )
            for expected_output in job.expected_outputs:
                _validate_workspace_relative_path(
                    expected_output,
                    field_name="expected_outputs",
                    phase_name=phase.name,
                    job_name=job.name,
                )

            jobs.append(
                ExpandedManifestJob(
                    phase_name=phase.name,
                    job_name=job.name,
                    cmd=job.cmd,
                    cwd=job.cwd,
                    expected_outputs=list(job.expected_outputs),
                    phase_dependencies=list(phase.depends_on),
                    timeout_sec=job.timeout_sec,
                    max_attempts=job.retry.max_attempts,
                    oom_retry=job.retry.oom_retry,
                    phase_index=phase_index,
                    job_index=job_index,
                )
            )

    return jobs


def _coerce_manifest(
    manifest: dict[str, Any] | ExperimentManifestPayload,
) -> ExperimentManifestPayload:
    if isinstance(manifest, ExperimentManifestPayload):
        return manifest
    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest must be a dict or ExperimentManifestPayload")
    try:
        return ExperimentManifestPayload.model_validate(manifest)
    except ValidationError as exc:
        raise ManifestValidationError(_validation_error_message(exc)) from exc


def _validate_manifest_payload(payload: ExperimentManifestPayload) -> None:
    if not payload.project.strip():
        raise ManifestValidationError("manifest project is required")
    if not payload.workspace.strip():
        raise ManifestValidationError("manifest workspace is required")
    if not payload.phases:
        raise ManifestValidationError("manifest must include at least one phase")

    phase_index_by_name: dict[str, int] = {}
    for index, phase in enumerate(payload.phases):
        if phase.name in phase_index_by_name:
            raise ManifestValidationError(f"duplicate phase name '{phase.name}'")
        phase_index_by_name[phase.name] = index

    for index, phase in enumerate(payload.phases):
        if not phase.jobs:
            raise ManifestValidationError(f"phase '{phase.name}' contains empty jobs")

        for dependency in phase.depends_on:
            if dependency not in phase_index_by_name:
                raise ManifestValidationError(
                    f"phase '{phase.name}' has unknown dependency '{dependency}'"
                )
            dependency_index = phase_index_by_name[dependency]
            if dependency_index == index:
                raise ManifestValidationError(
                    f"phase '{phase.name}' has self-dependency '{dependency}'"
                )
            if dependency_index > index:
                raise ManifestValidationError(
                    f"phase '{phase.name}' depends on later phase '{dependency}'"
                )


def _validation_error_message(exc: ValidationError) -> str:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = error.get("msg", "invalid value")
        if location:
            messages.append(f"{location}: {message}")
        else:
            messages.append(message)
    return "; ".join(messages)


def _validate_workspace_relative_path(
    value: str,
    *,
    field_name: str,
    phase_name: str,
    job_name: str,
) -> None:
    path = PurePosixPath(value)
    if not value.strip():
        raise ManifestValidationError(
            f"job '{job_name}' in phase '{phase_name}' has empty {field_name}"
        )
    if path.is_absolute() or ".." in path.parts:
        raise ManifestValidationError(
            f"job '{job_name}' in phase '{phase_name}' has unsafe {field_name}: {value}"
        )
