"""Tests for export service."""
import json
import pytest
from services.export import (
    generate_markdown_report,
    generate_json_export,
    generate_csv_export,
    generate_bibtex_export,
)


@pytest.fixture
def sample_run():
    from uuid import uuid4
    from datetime import datetime
    return {
        "id": uuid4(),
        "title": "Test Run",
        "topic": "Multi-agent coordination",
        "status": "completed",
        "goal_type": "survey_plus_innovations",
        "budget_json": {"max_new_papers": 50, "max_fulltext_reads": 10},
        "created_at": datetime(2026, 3, 20),
    }

@pytest.fixture
def sample_papers():
    from uuid import uuid4
    return [
        {
            "id": uuid4(),
            "canonical_title": "Paper One: Multi-Agent Memory",
            "doi": "10.1234/test1",
            "arxiv_id": "2301.00001",
            "publication_year": 2023,
            "venue": "NeurIPS",
            "citation_count": 45,
            "is_oa": True,
            "oa_url": "https://example.com/paper1.pdf",
        },
        {
            "id": uuid4(),
            "canonical_title": "Paper Two: Communication Protocols",
            "doi": "10.1234/test2",
            "publication_year": 2024,
            "venue": "ICML",
            "citation_count": 12,
            "is_oa": False,
        },
    ]

@pytest.fixture
def sample_hypotheses():
    from uuid import uuid4
    return [
        {
            "id": uuid4(),
            "title": "Shared Memory with Attention",
            "statement": "Combining attention mechanisms with shared memory pools improves multi-agent coordination by 20%.",
            "type": "bridge",
            "status": "verified",
            "novelty_score": 0.85,
            "feasibility_score": 0.7,
            "evidence_score": 0.6,
            "risk_score": 0.3,
        },
    ]


class TestMarkdownExport:
    @pytest.mark.asyncio
    async def test_generates_report(self, sample_run, sample_papers, sample_hypotheses):
        report = await generate_markdown_report(sample_run, sample_hypotheses, sample_papers, [])
        assert "# Research Report" in report
        assert sample_run["title"] in report
        assert "Paper One" in report
        assert "Shared Memory with Attention" in report

    @pytest.mark.asyncio
    async def test_handles_empty_data(self):
        report = await generate_markdown_report(
            {"title": "Empty", "topic": "Nothing", "status": "completed"},
            [], [], []
        )
        assert "# Research Report" in report


class TestJsonExport:
    @pytest.mark.asyncio
    async def test_generates_valid_json(self, sample_run, sample_papers, sample_hypotheses):
        result = await generate_json_export(sample_run, sample_hypotheses, sample_papers)
        data = json.loads(result)
        assert "run" in data
        assert "papers" in data
        assert "hypotheses" in data
        assert len(data["papers"]) == 2


class TestCsvExport:
    @pytest.mark.asyncio
    async def test_generates_csv(self, sample_papers):
        result = await generate_csv_export(sample_papers)
        assert "Title" in result
        assert "Paper One" in result
        assert "10.1234/test1" in result


class TestBibtexExport:
    @pytest.mark.asyncio
    async def test_generates_bibtex(self, sample_papers):
        result = await generate_bibtex_export(sample_papers)
        assert "@article{" in result
        assert "10.1234/test1" in result
        assert "2301.00001" in result
        assert "archiveprefix = {arXiv}" in result
