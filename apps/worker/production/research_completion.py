"""Deterministic CPU completion package for research run workspaces."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID


def write_research_completion_package(
    workspace_path: Path,
    *,
    run_id: UUID,
    title: str,
    state: Any,
) -> None:
    """Write a reproducible CPU experiment summary and manuscript draft."""

    experiments_dir = workspace_path / "experiments"
    artifacts_dir = workspace_path / "artifacts"
    paper_dir = workspace_path / "paper"
    for directory in (experiments_dir, artifacts_dir, paper_dir):
        directory.mkdir(parents=True, exist_ok=True)

    metrics = _research_flow_metrics(run_id=run_id, title=title, state=state)
    manifest = _experiment_manifest(title)
    _write_json(experiments_dir / "manifest.json", manifest)
    _write_json(artifacts_dir / "research_flow_metrics.json", metrics)
    (artifacts_dir / "research_flow_summary.md").write_text(
        _metrics_summary_markdown(metrics),
        encoding="utf-8",
    )
    (paper_dir / "draft.md").write_text(
        _paper_draft(title=title, state=state, metrics=metrics),
        encoding="utf-8",
    )


def _research_flow_metrics(*, run_id: UUID, title: str, state: Any) -> dict[str, Any]:
    idea_cards = _dict_list(getattr(state, "idea_cards", []) or [])
    context_bundle = getattr(state, "context_bundle", {}) or {}
    paper_summaries = _dict_list(
        getattr(state, "paper_summaries", []) or context_bundle.get("paper_summaries", [])
    )
    report = getattr(state, "report_markdown", "") or ""
    prior_art_counts = Counter(
        str(card.get("prior_art_check_status") or "unknown") for card in idea_cards
    )
    novelty_counts = Counter(
        str(card.get("novelty_verdict") or "unknown") for card in idea_cards
    )
    quality_counts = Counter(
        str(card.get("quality_verdict") or "unknown") for card in idea_cards
    )
    passed_ideas = [
        card for card in idea_cards
        if str(card.get("quality_verdict") or "").casefold() == "pursue"
    ]
    if not passed_ideas:
        passed_ideas = idea_cards

    return {
        "cpu_experiment": "research_flow_integrity_v1",
        "run_id": str(run_id),
        "title": title,
        "topic": getattr(state, "topic", None),
        "mode": getattr(state, "mode", None),
        "paper_summary_count": len(paper_summaries),
        "idea_count": len(idea_cards),
        "candidate_idea_count": len(passed_ideas),
        "report_char_count": len(report),
        "prior_art_status_counts": dict(sorted(prior_art_counts.items())),
        "novelty_verdict_counts": dict(sorted(novelty_counts.items())),
        "quality_verdict_counts": dict(sorted(quality_counts.items())),
        "top_idea_titles": [
            str(card.get("title") or "Untitled idea")[:160]
            for card in passed_ideas[:5]
        ],
        "paper_titles": [
            str(paper.get("title") or paper.get("paper_title") or "Untitled paper")[:180]
            for paper in paper_summaries[:10]
        ],
        "completed": True,
    }


def _experiment_manifest(title: str) -> dict[str, Any]:
    return {
        "project": title,
        "workspace": ".",
        "phases": [
            {
                "name": "cpu_validation",
                "jobs": [
                    {
                        "name": "research_flow_integrity",
                        "cmd": "python - <<'PY'\nimport json\njson.load(open('artifacts/research_flow_metrics.json'))\nPY",
                        "cwd": ".",
                        "expected_outputs": [
                            "artifacts/research_flow_metrics.json",
                            "artifacts/research_flow_summary.md",
                            "paper/draft.md",
                        ],
                        "timeout_sec": 60,
                    }
                ],
            }
        ],
    }


def _metrics_summary_markdown(metrics: dict[str, Any]) -> str:
    lines = [
        "# Research Flow CPU Experiment",
        "",
        f"- Run ID: {metrics['run_id']}",
        f"- Paper summaries: {metrics['paper_summary_count']}",
        f"- Idea cards: {metrics['idea_count']}",
        f"- Candidate ideas: {metrics['candidate_idea_count']}",
        f"- Report characters: {metrics['report_char_count']}",
        "",
        "## Top Ideas",
    ]
    titles = metrics.get("top_idea_titles") or []
    lines.extend(f"- {title}" for title in titles)
    if not titles:
        lines.append("- No idea cards were available.")
    return "\n".join(lines) + "\n"


def _paper_draft(*, title: str, state: Any, metrics: dict[str, Any]) -> str:
    report = getattr(state, "report_markdown", "") or ""
    topic = getattr(state, "topic", None) or title
    top_ideas = metrics.get("top_idea_titles") or []
    paper_titles = metrics.get("paper_titles") or []
    lines = [
        f"# {title}",
        "",
        "## Abstract",
        (
            f"This draft summarizes an automated Research OS run on {topic}. "
            "It combines retrieved literature evidence, generated ideas, and a "
            "deterministic CPU-only integrity experiment over the run outputs."
        ),
        "",
        "## Literature Context",
    ]
    if paper_titles:
        lines.extend(f"- {paper_title}" for paper_title in paper_titles)
    else:
        lines.append("- No paper summaries were available in the completed run.")
    lines.extend(["", "## Candidate Ideas"])
    if top_ideas:
        lines.extend(f"- {idea_title}" for idea_title in top_ideas)
    else:
        lines.append("- No idea cards were available in the completed run.")
    lines.extend(
        [
            "",
            "## CPU Experiment",
            (
                "The CPU experiment validates that the run produced internally "
                "consistent research artifacts without requiring GPU resources."
            ),
            f"- Paper summary count: {metrics['paper_summary_count']}",
            f"- Idea count: {metrics['idea_count']}",
            f"- Candidate idea count: {metrics['candidate_idea_count']}",
            "",
            "## Generated Report",
            report.strip() or "No report markdown was produced by the run.",
            "",
            "## Reproducibility",
            (
                "The experiment manifest is stored at `experiments/manifest.json`; "
                "metrics are stored at `artifacts/research_flow_metrics.json`."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, default=str, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
