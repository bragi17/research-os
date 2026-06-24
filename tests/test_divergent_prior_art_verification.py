from __future__ import annotations

from uuid import uuid4

import pytest

from apps.worker.modes import divergent
from apps.worker.modes.base import ModeGraphState


@pytest.mark.asyncio
async def test_prior_art_check_attaches_verification_and_updates_cards(monkeypatch):
    run_id = uuid4()
    seen_user_content: list[str] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        return (
            ["s2-prior-1"],
            ["transfer title borrowed method"],
            [],
            {"s2-prior-1": "Prior Art Paper"},
        )

    async def fake_verify_paper_candidates_for_run(
        run_id_arg,
        candidate_ids,
        title_map=None,
        source=None,
    ):
        assert run_id_arg == run_id
        assert candidate_ids == ["s2-prior-1"]
        assert title_map == {"s2-prior-1": "Prior Art Paper"}
        assert source == "prior_art"
        return {
            "s2-prior-1": {
                "candidate_id": "s2-prior-1",
                "canonical_title": "Prior Art Paper",
                "verification_status": "verified",
                "source": "prior_art",
            }
        }

    async def fake_generate_llm_json(system_prompt, user_content, gateway, tier, schema=None):
        seen_user_content.append(user_content)
        return (
            [
                {
                    "idea_title": "Transfer Title",
                    "verdict": "reject",
                    "prior_art_found": True,
                    "similar_works": [
                        {
                            "title": "Prior Art Paper",
                            "similarity_reason": "same method and task",
                        }
                    ],
                    "adjusted_novelty_score": 0.2,
                    "rationale": "substantially similar prior work exists",
                }
            ],
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "search_academic_sources", fake_search_academic_sources)
    monkeypatch.setattr(
        divergent,
        "verify_paper_candidates_for_run",
        fake_verify_paper_candidates_for_run,
    )
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=run_id,
        topic="target task",
        idea_cards=[
            {
                "id": "idea-0",
                "title": "Transfer Title",
                "borrowed_method": "borrowed method",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            }
        ],
        context_bundle={"paper_verification": {"existing": {"candidate_id": "existing"}}},
    )

    updates = await divergent.prior_art_check(state)

    assert updates["context_bundle"]["paper_verification"]["existing"] == {
        "candidate_id": "existing"
    }
    assert updates["context_bundle"]["paper_verification"]["s2-prior-1"] == {
        "candidate_id": "s2-prior-1",
        "canonical_title": "Prior Art Paper",
        "verification_status": "verified",
        "source": "prior_art",
    }
    assert "## Verified Prior Art Records" in seen_user_content[0]
    assert "Prior Art Paper" in seen_user_content[0]
    assert updates["idea_cards"][0]["prior_art_check_status"] == "high_risk"
    assert updates["idea_cards"][0]["prior_art_found"] is True
    assert updates["idea_cards"][0]["novelty_score"] == 0.2
