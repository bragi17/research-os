"""Tests for multi-mode research schemas."""
import pytest
from uuid import uuid4
from libs.schemas.multimode import (
    ResearchMode, RunStage, PainPoint, IdeaCard, ContextBundle,
    ModeConfig, SpawnRunRequest,
)


class TestResearchMode:
    def test_all_modes(self):
        for m in ("intake", "atlas", "frontier", "divergent", "review"):
            assert ResearchMode(m) == m

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            ResearchMode("invalid")


class TestPainPoint:
    def test_creation(self):
        pp = PainPoint(statement="3D AD generalization is poor", pain_type="generalization")
        assert pp.severity_score == 0.0
        assert pp.novelty_potential == 0.0

    def test_with_papers(self):
        pid = uuid4()
        pp = PainPoint(statement="test", supporting_paper_ids=[pid])
        assert len(pp.supporting_paper_ids) == 1


class TestIdeaCard:
    def test_creation(self):
        ic = IdeaCard(title="Transfer contrastive learning to 3D AD", problem_statement="test")
        assert ic.status == "candidate"
        assert ic.prior_art_check_status == "pending"

    def test_with_methods(self):
        ic = IdeaCard(title="t", problem_statement="p", borrowed_methods=["contrastive", "memory bank"])
        assert len(ic.borrowed_methods) == 2


class TestContextBundle:
    def test_creation(self):
        cb = ContextBundle(source_mode="frontier")
        assert cb.selected_paper_ids == []
        assert cb.mindmap_json == {}

    def test_with_data(self):
        cb = ContextBundle(source_mode="atlas", mindmap_json={"root": "test"}, summary_text="hello")
        assert cb.mindmap_json["root"] == "test"


class TestModeConfig:
    def test_creation(self):
        mc = ModeConfig(mode=ResearchMode.ATLAS, topic="3D anomaly detection")
        assert mc.mode == "atlas"
        assert mc.keywords == []

    def test_with_constraints(self):
        mc = ModeConfig(mode=ResearchMode.FRONTIER, topic="test", constraints={"venues": ["CVPR"]})
        assert "venues" in mc.constraints


class TestSpawnRunRequest:
    def test_creation(self):
        bid = uuid4()
        req = SpawnRunRequest(target_mode=ResearchMode.DIVERGENT, context_bundle_id=bid)
        assert req.target_mode == "divergent"
        assert req.context_bundle_id == bid
