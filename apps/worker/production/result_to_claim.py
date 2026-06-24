"""Convert experiment job results into claim ledger payloads."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from apps.worker.production.workspaces import resolve_path_reference


NUMERIC_METRIC_RE = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9_./-]*)\s*=\s*(?P<value>-?\d+(?:\.\d+)?)")


def _numeric_metrics(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    metrics: dict[str, float] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            metrics[str(key)] = float(item)
    return metrics


def _read_json_metrics(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    try:
        return _numeric_metrics(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _read_log_metrics(path: Path | None) -> dict[str, float]:
    if path is None or not path.is_file():
        return {}
    try:
        content = path.read_text(encoding="utf-8", errors="replace")[-65536:]
    except OSError:
        return {}
    return {
        match.group("name"): float(match.group("value"))
        for match in NUMERIC_METRIC_RE.finditer(content)
    }


def _safe_workspace_path(
    workspace_root: Path,
    raw: Any,
    *,
    field_name: str,
) -> Path | None:
    try:
        return resolve_path_reference(workspace_root, raw, field_name=field_name)
    except ValueError:
        return None


def _metric_claim(
    *,
    job: dict[str, Any],
    metric_name: str,
    metric_value: float,
    baseline_value: float | None,
) -> dict[str, Any]:
    supported = baseline_value is None or metric_value >= baseline_value
    claim_status = "supported" if supported else "contradicted"
    summary = f"{metric_name}={metric_value:g}"
    if baseline_value is not None:
        summary = f"{summary}; baseline_{metric_name}={baseline_value:g}"
    return {
        "project_id": job["project_id"],
        "experiment_plan_id": job.get("experiment_plan_id"),
        "claim_text": (
            f"{job.get('phase_name', 'experiment')} / {job.get('job_name', 'job')} "
            f"reports {metric_name}={metric_value:g}"
            + (f" against baseline {baseline_value:g}." if baseline_value is not None else ".")
        ),
        "claim_type": "comparison" if baseline_value is not None else "main",
        "status": claim_status,
        "support_level": 0.95 if supported else 0.0,
        "evidence_summary": summary,
        "reviewer_model": "research-os-result-to-claim",
        "human_decision": None,
    }


def claim_payload_from_job(job: dict[str, Any]) -> dict[str, Any]:
    """Build a conservative claim payload from one experiment job result."""

    metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
    found = metrics.get("expected_outputs_found") or []
    missing = metrics.get("missing_expected_outputs") or []
    status = str(job.get("status") or "unknown")
    if status == "completed" and not missing:
        claim_status = "supported"
        support_level = 1.0
    elif status == "completed":
        claim_status = "partially_supported"
        support_level = 0.65
    else:
        claim_status = "unsupported"
        support_level = 0.0
    summary_parts = [
        f"job status={status}",
        f"returncode={metrics.get('returncode')}",
        f"found_outputs={len(found)}",
        f"missing_outputs={len(missing)}",
    ]
    if job.get("failure_reason"):
        summary_parts.append(f"failure_reason={job['failure_reason']}")
    return {
        "project_id": job["project_id"],
        "experiment_plan_id": job.get("experiment_plan_id"),
        "claim_text": f"{job.get('phase_name', 'experiment')} / {job.get('job_name', 'job')} result is {claim_status.replace('_', ' ')}.",
        "claim_type": "main" if claim_status != "unsupported" else "negative",
        "status": claim_status,
        "support_level": support_level,
        "evidence_summary": "; ".join(summary_parts),
        "reviewer_model": "research-os-result-to-claim",
        "human_decision": None,
    }


def claim_payloads_from_job_audit(
    *,
    job: dict[str, Any],
    workspace_root: Path,
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build claim payloads from job status, metrics, logs, and artifact registry."""

    payloads = [claim_payload_from_job(job)]
    metrics = job.get("metrics_json") if isinstance(job.get("metrics_json"), dict) else {}
    found_outputs = metrics.get("expected_outputs_found") or []
    parsed_metrics: dict[str, float] = {}

    for output in found_outputs:
        candidate = _safe_workspace_path(workspace_root, output, field_name="expected_outputs_found")
        if candidate is None:
            continue
        if candidate.suffix.lower() == ".json":
            parsed_metrics.update(_read_json_metrics(candidate))

    stdout_log = job.get("stdout_log_path")
    if stdout_log:
        parsed_metrics.update(
            _read_log_metrics(
                _safe_workspace_path(workspace_root, stdout_log, field_name="stdout_log_path")
            )
        )

    for metric_name, metric_value in sorted(parsed_metrics.items()):
        if metric_name.startswith("baseline_"):
            continue
        baseline_value = parsed_metrics.get(f"baseline_{metric_name}")
        payloads.append(
            _metric_claim(
                job=job,
                metric_name=metric_name,
                metric_value=metric_value,
                baseline_value=baseline_value,
            )
        )

    for artifact in artifacts:
        summary = artifact.get("summary") or artifact.get("path") or "artifact"
        payloads.append(
            {
                "project_id": job["project_id"],
                "experiment_plan_id": job.get("experiment_plan_id"),
                "claim_text": f"{job.get('phase_name', 'experiment')} / {job.get('job_name', 'job')} produced artifact {artifact.get('path')}.",
                "claim_type": "main",
                "status": "supported" if artifact.get("validation_status") != "failed" else "unsupported",
                "support_level": 0.8 if artifact.get("validation_status") != "failed" else 0.0,
                "evidence_summary": str(summary),
                "reviewer_model": "research-os-result-to-claim",
                "human_decision": None,
            }
        )
    return payloads


def claim_evidence_payload(
    *,
    claim: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    """Build evidence attached to a generated claim."""

    return {
        "claim_id": claim["id"],
        "source_type": "experiment_job",
        "source_id": job["id"],
        "quote_or_metric": claim.get("evidence_summary"),
        "artifact_path": job.get("artifact_dir"),
        "support_relation": "supports" if claim["status"] in {"supported", "partially_supported"} else "contradicts",
    }


def audit_claims(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize claim support for writing and submission gates."""

    blockers = [
        {
            "claim_id": str(claim["id"]),
            "claim_text": claim["claim_text"],
            "status": claim["status"],
            "support_level": claim.get("support_level"),
        }
        for claim in claims
        if claim.get("status") in {"unsupported", "contradicted"}
    ]
    return {
        "total_claims": len(claims),
        "supported_claims": sum(1 for claim in claims if claim.get("status") == "supported"),
        "partial_claims": sum(1 for claim in claims if claim.get("status") == "partially_supported"),
        "unsupported_claims": len(blockers),
        "blockers": blockers,
    }
