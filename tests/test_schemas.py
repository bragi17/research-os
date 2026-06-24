"""Tests for core schemas and data models."""
import pytest
from libs.schemas.run import (
    Budget, Policy, RunState, RunStatus, GoalType,
    CreateRunRequest, ScoreSignals, HypothesisCandidate,
    HypothesisType, HypothesisStatus,
)
from uuid import uuid4


class TestBudget:
    def test_defaults(self):
        b = Budget()
        assert b.max_runtime_minutes == 90
        assert b.max_new_papers == 150
        assert b.max_fulltext_reads == 40
        assert b.max_estimated_cost_usd == 30.0

    def test_validation_min(self):
        with pytest.raises(Exception):
            Budget(max_runtime_minutes=1)  # below minimum of 5


class TestPolicy:
    def test_defaults(self):
        p = Policy()
        assert p.auto_pause_on_budget_hit is True


class TestRunState:
    def test_should_pause_on_cost(self):
        state = RunState(
            run_id=uuid4(),
            topic="test",
            goal_type=GoalType.SURVEY,
            total_cost_usd=35.0,
            budget=Budget(max_estimated_cost_usd=30.0),
        )
        assert state.should_pause() is True

    def test_should_not_pause_under_budget(self):
        state = RunState(
            run_id=uuid4(),
            topic="test",
            goal_type=GoalType.SURVEY,
            total_cost_usd=10.0,
        )
        assert state.should_pause() is False


class TestCreateRunRequest:
    def test_valid_request(self):
        req = CreateRunRequest(
            title="Test Run",
            topic="Multi-agent coordination in distributed systems",
        )
        assert req.goal_type == GoalType.SURVEY_PLUS_INNOVATIONS
        assert req.budget.max_new_papers == 150

    def test_title_too_short(self):
        with pytest.raises(Exception):
            CreateRunRequest(title="AB", topic="A valid topic description here")


class TestScoreSignals:
    def test_defaults_are_zero(self):
        s = ScoreSignals()
        assert s.semantic == 0.0
        assert s.keyword == 0.0

    def test_validation(self):
        with pytest.raises(Exception):
            ScoreSignals(semantic=1.5)  # max is 1.0


class TestHypothesisCandidate:
    def test_creation(self):
        h = HypothesisCandidate(
            title="Test Hypothesis",
            statement="Testing is important",
            type=HypothesisType.BRIDGE,
        )
        assert h.status == HypothesisStatus.CANDIDATE
        assert h.novelty_score == 0.0
