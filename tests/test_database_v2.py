"""
Tests for database_v2.py — mock-based (no real DB required).

Uses unittest.mock.AsyncMock to simulate asyncpg pool behaviour and verifies
that each CRUD function issues the correct SQL against the correct table with
the right parameters and returns the expected data structures.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID


# ---------------------------------------------------------------------------
# Helpers — fake asyncpg.Record
# ---------------------------------------------------------------------------


class FakeRecord(dict):
    """Dict subclass that mimics asyncpg.Record access patterns."""

    def __getitem__(self, key):
        return super().__getitem__(key)


def _make_record(mapping: dict) -> FakeRecord:
    return FakeRecord(mapping)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RUN_ID = uuid4()
PAPER_ID = uuid4()
IDEA_ID = uuid4()
BUNDLE_ID = uuid4()
DOMAIN_ID = uuid4()
DOMAIN_PARENT_ID = uuid4()


@pytest.fixture()
def mock_pool():
    """Return an AsyncMock that behaves like an asyncpg.Pool."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    pool.execute = AsyncMock()
    return pool


@pytest.fixture(autouse=True)
def _patch_get_pool(mock_pool):
    """Patch get_pool so every test uses the mock pool."""
    with patch("apps.api.database.get_pool", return_value=mock_pool):
        yield


# ===================================================================
# Pain Point tests
# ===================================================================


class TestCreatePainPoint:
    @pytest.mark.asyncio
    async def test_creates_row(self, mock_pool):
        fake = _make_record({
            "id": uuid4(),
            "run_id": RUN_ID,
            "statement": "Poor generalisation",
            "pain_type": "general",
            "severity_score": 0.5,
            "novelty_potential": 0.3,
            "supporting_paper_ids": [],
            "counter_evidence_paper_ids": [],
            "cluster_id": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import create_pain_point

        result = await create_pain_point(RUN_ID, {"statement": "Poor generalisation"})

        mock_pool.fetchrow.assert_awaited_once()
        sql = mock_pool.fetchrow.call_args[0][0]
        assert "INSERT INTO pain_point" in sql
        assert "run_id" in sql
        assert "statement" in sql
        assert result["statement"] == "Poor generalisation"


class TestListPainPoints:
    @pytest.mark.asyncio
    async def test_returns_list(self, mock_pool):
        mock_pool.fetch.return_value = [
            _make_record({"id": uuid4(), "run_id": RUN_ID, "statement": "a"}),
            _make_record({"id": uuid4(), "run_id": RUN_ID, "statement": "b"}),
        ]

        from apps.api.database import list_pain_points

        result = await list_pain_points(RUN_ID, limit=10, offset=0)

        mock_pool.fetch.assert_awaited_once()
        sql = mock_pool.fetch.call_args[0][0]
        assert "pain_point" in sql
        assert "run_id" in sql
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_pool):
        mock_pool.fetch.return_value = []

        from apps.api.database import list_pain_points

        result = await list_pain_points(RUN_ID)
        assert result == []


class TestCountPainPoints:
    @pytest.mark.asyncio
    async def test_returns_count(self, mock_pool):
        mock_pool.fetchrow.return_value = _make_record({"cnt": 7})

        from apps.api.database import count_pain_points

        result = await count_pain_points(RUN_ID)

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "COUNT" in sql
        assert "pain_point" in sql
        assert result == 7


# ===================================================================
# Idea Card tests
# ===================================================================


class TestCreateIdeaCard:
    @pytest.mark.asyncio
    async def test_creates_row(self, mock_pool):
        fake = _make_record({
            "id": IDEA_ID,
            "run_id": RUN_ID,
            "title": "Transfer contrastive",
            "problem_statement": "test",
            "status": "candidate",
            "prior_art_check_status": "pending",
            "source_pain_point_ids": [],
            "borrowed_methods": [],
            "source_domains": [],
            "mechanism_of_transfer": None,
            "expected_benefit": None,
            "risks": [],
            "required_experiments": [],
            "novelty_score": None,
            "feasibility_score": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import create_idea_card

        result = await create_idea_card(RUN_ID, {"title": "Transfer contrastive"})

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "INSERT INTO idea_card" in sql
        assert "title" in sql
        assert "problem_statement" in sql
        assert result["title"] == "Transfer contrastive"


class TestListIdeaCards:
    @pytest.mark.asyncio
    async def test_returns_list(self, mock_pool):
        mock_pool.fetch.return_value = [
            _make_record({"id": uuid4(), "run_id": RUN_ID, "title": "A"}),
        ]

        from apps.api.database import list_idea_cards

        result = await list_idea_cards(RUN_ID)

        sql = mock_pool.fetch.call_args[0][0]
        assert "idea_card" in sql
        assert len(result) == 1


class TestCountIdeaCards:
    @pytest.mark.asyncio
    async def test_returns_count(self, mock_pool):
        mock_pool.fetchrow.return_value = _make_record({"cnt": 3})

        from apps.api.database import count_idea_cards

        result = await count_idea_cards(RUN_ID)

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "idea_card" in sql
        assert result == 3


class TestUpdateIdeaCard:
    @pytest.mark.asyncio
    async def test_updates_columns(self, mock_pool):
        fake = _make_record({
            "id": IDEA_ID,
            "run_id": RUN_ID,
            "title": "Updated",
            "status": "accepted",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import update_idea_card

        result = await update_idea_card(IDEA_ID, {"status": "accepted"})

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "UPDATE idea_card" in sql
        assert "status = $1" in sql
        assert result["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_empty_updates_returns_current(self, mock_pool):
        fake = _make_record({"id": IDEA_ID, "title": "Unchanged"})
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import update_idea_card

        result = await update_idea_card(IDEA_ID, {})

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "SELECT" in sql
        assert result["title"] == "Unchanged"

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, mock_pool):
        mock_pool.fetchrow.return_value = None

        from apps.api.database import update_idea_card

        result = await update_idea_card(IDEA_ID, {"status": "rejected"})
        assert result is None


# ===================================================================
# Context Bundle tests
# ===================================================================


class TestCreateContextBundle:
    @pytest.mark.asyncio
    async def test_creates_row(self, mock_pool):
        fake = _make_record({
            "id": BUNDLE_ID,
            "source_run_id": RUN_ID,
            "source_mode": "frontier",
            "summary_text": "test",
            "selected_paper_ids": [],
            "cluster_ids": [],
            "figure_ids": [],
            "pain_point_ids": [],
            "idea_card_ids": [],
            "benchmark_data": None,
            "mindmap_json": None,
            "user_annotations": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import create_context_bundle

        result = await create_context_bundle({"source_mode": "frontier", "summary_text": "test"})

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "INSERT INTO context_bundle" in sql
        assert "source_mode" in sql
        assert "mindmap_json" in sql
        assert result["source_mode"] == "frontier"


class TestGetContextBundle:
    @pytest.mark.asyncio
    async def test_found(self, mock_pool):
        fake = _make_record({"id": BUNDLE_ID, "source_mode": "atlas"})
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import get_context_bundle

        result = await get_context_bundle(BUNDLE_ID)

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "context_bundle" in sql
        assert result["source_mode"] == "atlas"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_pool):
        mock_pool.fetchrow.return_value = None

        from apps.api.database import get_context_bundle

        result = await get_context_bundle(BUNDLE_ID)
        assert result is None


# ===================================================================
# Figure Asset tests
# ===================================================================


class TestCreateFigureAsset:
    @pytest.mark.asyncio
    async def test_creates_row(self, mock_pool):
        fake = _make_record({
            "id": uuid4(),
            "paper_id": PAPER_ID,
            "source_type": "pdf_extraction",
            "page_no": 3,
            "caption": "Figure 1",
            "image_path": "/figures/fig1.png",
            "figure_type": "chart",
            "related_section": "Results",
            "license_note": None,
            "extraction_confidence": 0.95,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import create_figure_asset

        result = await create_figure_asset(PAPER_ID, {
            "source_type": "pdf_extraction",
            "page_no": 3,
            "caption": "Figure 1",
        })

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "INSERT INTO figure_asset" in sql
        assert "paper_id" in sql
        assert "caption" in sql
        assert result["page_no"] == 3


class TestListFiguresByPaper:
    @pytest.mark.asyncio
    async def test_returns_list(self, mock_pool):
        mock_pool.fetch.return_value = [
            _make_record({"id": uuid4(), "paper_id": PAPER_ID, "caption": "Fig 1"}),
        ]

        from apps.api.database import list_figures_by_paper

        result = await list_figures_by_paper(PAPER_ID)

        sql = mock_pool.fetch.call_args[0][0]
        assert "figure_asset" in sql
        assert "paper_id" in sql
        assert len(result) == 1


class TestListFiguresByRun:
    @pytest.mark.asyncio
    async def test_returns_list(self, mock_pool):
        mock_pool.fetch.return_value = [
            _make_record({"id": uuid4(), "paper_id": PAPER_ID, "caption": "Fig 2"}),
        ]

        from apps.api.database import list_figures_by_run

        result = await list_figures_by_run(RUN_ID)

        sql = mock_pool.fetch.call_args[0][0]
        assert "figure_asset" in sql
        assert "topic_cluster" in sql
        assert "run_id" in sql
        assert len(result) == 1


# ===================================================================
# Research Domain tests
# ===================================================================


class TestCreateDomain:
    @pytest.mark.asyncio
    async def test_creates_row(self, mock_pool):
        fake = _make_record({
            "id": DOMAIN_ID,
            "name": "Computer Vision",
            "aliases": ["CV"],
            "parent_domain_id": None,
            "description_short": "Study of images",
            "description_detailed": None,
            "keywords": ["vision"],
            "representative_venues": [],
            "representative_datasets": [],
            "representative_methods": [],
            "canonical_paper_ids": [],
            "recent_frontier_paper_ids": [],
            "prerequisite_domain_ids": [],
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import create_domain

        result = await create_domain({"name": "Computer Vision", "aliases": ["CV"]})

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "INSERT INTO research_domain" in sql
        assert "name" in sql
        assert "aliases" in sql
        assert result["name"] == "Computer Vision"


class TestGetDomain:
    @pytest.mark.asyncio
    async def test_found(self, mock_pool):
        fake = _make_record({"id": DOMAIN_ID, "name": "NLP"})
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import get_domain

        result = await get_domain(DOMAIN_ID)

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "research_domain" in sql
        assert result["name"] == "NLP"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_pool):
        mock_pool.fetchrow.return_value = None

        from apps.api.database import get_domain

        result = await get_domain(DOMAIN_ID)
        assert result is None


class TestListDomains:
    @pytest.mark.asyncio
    async def test_all_domains(self, mock_pool):
        mock_pool.fetch.return_value = [
            _make_record({"id": uuid4(), "name": "A"}),
            _make_record({"id": uuid4(), "name": "B"}),
        ]

        from apps.api.database import list_domains

        result = await list_domains()

        sql = mock_pool.fetch.call_args[0][0]
        assert "research_domain" in sql
        assert "ORDER BY name" in sql
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filtered_by_parent(self, mock_pool):
        mock_pool.fetch.return_value = [
            _make_record({"id": uuid4(), "name": "Child", "parent_domain_id": DOMAIN_PARENT_ID}),
        ]

        from apps.api.database import list_domains

        result = await list_domains(parent_id=DOMAIN_PARENT_ID)

        sql = mock_pool.fetch.call_args[0][0]
        assert "parent_domain_id" in sql
        assert len(result) == 1


# ===================================================================
# Reading Path tests
# ===================================================================


class TestCreateReadingPath:
    @pytest.mark.asyncio
    async def test_creates_row(self, mock_pool):
        fake = _make_record({
            "id": uuid4(),
            "run_id": RUN_ID,
            "domain_id": DOMAIN_ID,
            "difficulty_level": "intermediate",
            "ordered_units": [{"paper_id": str(uuid4()), "order": 1}],
            "estimated_hours": 12.5,
            "goal": "Learn 3D AD",
            "generated_rationale": "Start from basics",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import create_reading_path

        result = await create_reading_path(RUN_ID, {
            "domain_id": DOMAIN_ID,
            "difficulty_level": "intermediate",
            "ordered_units": [{"paper_id": "abc", "order": 1}],
            "estimated_hours": 12.5,
            "goal": "Learn 3D AD",
        })

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "INSERT INTO reading_path" in sql
        assert "run_id" in sql
        assert "ordered_units" in sql
        assert result["goal"] == "Learn 3D AD"


class TestGetReadingPath:
    @pytest.mark.asyncio
    async def test_found(self, mock_pool):
        fake = _make_record({
            "id": uuid4(),
            "run_id": RUN_ID,
            "goal": "Survey the field",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import get_reading_path

        result = await get_reading_path(RUN_ID)

        sql = mock_pool.fetchrow.call_args[0][0]
        assert "reading_path" in sql
        assert "run_id" in sql
        assert result["goal"] == "Survey the field"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_pool):
        mock_pool.fetchrow.return_value = None

        from apps.api.database import get_reading_path

        result = await get_reading_path(RUN_ID)
        assert result is None
