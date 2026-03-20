"""Tests for Mode 0: Intent Router."""
import pytest
from libs.schemas.multimode import ResearchMode
from apps.worker.modes.router import (
    classify_mode,
    ATLAS_KEYWORDS,
    FRONTIER_KEYWORDS,
    DIVERGENT_KEYWORDS,
)


class TestRuleBasedClassification:
    """Test keyword-based routing (no LLM needed)."""

    def test_atlas_keywords(self):
        assert classify_mode("I'm new to this field, what are the classics?") == ResearchMode.ATLAS

    def test_atlas_onboarding(self):
        assert classify_mode("Help me understand the landscape of 3D anomaly detection") == ResearchMode.ATLAS

    def test_atlas_survey(self):
        assert classify_mode("Give me a survey of multi-agent systems") == ResearchMode.ATLAS

    def test_frontier_recent(self):
        assert classify_mode("Find recent top-conference papers on 3D AD") == ResearchMode.FRONTIER

    def test_frontier_benchmark(self):
        assert classify_mode("What are the best methods on MVTec 3D-AD benchmark?") == ResearchMode.FRONTIER

    def test_frontier_pain_points(self):
        assert classify_mode("What are the pain points in this sub-field?") == ResearchMode.FRONTIER

    def test_divergent_innovation(self):
        assert classify_mode("Help me find innovation points for my research") == ResearchMode.DIVERGENT

    def test_divergent_cross_domain(self):
        assert classify_mode("Can we transfer methods from NLP to solve this 3D problem?") == ResearchMode.DIVERGENT

    def test_divergent_brainstorm(self):
        assert classify_mode("I want to brainstorm new ideas based on these pain points") == ResearchMode.DIVERGENT

    def test_review_summarize(self):
        assert classify_mode("Summarize the results into a report") == ResearchMode.REVIEW

    def test_review_export(self):
        assert classify_mode("Export this as a proposal for my advisor") == ResearchMode.REVIEW

    def test_ambiguous_defaults_to_atlas(self):
        # When no keywords match clearly, default to atlas (safest)
        assert classify_mode("3D anomaly detection") == ResearchMode.ATLAS

    def test_empty_input_defaults_to_atlas(self):
        assert classify_mode("") == ResearchMode.ATLAS


class TestModeConfigGeneration:
    """Test that router produces valid ModeConfig."""

    def test_generates_config(self):
        from apps.worker.modes.router import build_mode_config
        config = build_mode_config(
            user_input="Find recent papers on 3D anomaly detection",
            keywords=["3D AD", "anomaly"],
            seed_paper_ids=["2301.00001"],
        )
        assert config.mode == ResearchMode.FRONTIER
        assert config.topic == "Find recent papers on 3D anomaly detection"
        assert len(config.seed_paper_ids) == 1
