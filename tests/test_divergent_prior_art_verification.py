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


@pytest.mark.asyncio
async def test_prior_art_check_keeps_verification_records_per_idea(monkeypatch):
    run_id = uuid4()

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        queries = kwargs["queries"]
        found: list[str] = []
        title_map: dict[str, str] = {}

        for query in queries:
            query_text = query["query"]
            if "Idea Alpha" in query_text:
                found.append("s2-alpha")
                title_map["s2-alpha"] = "Alpha Prior Work"
            if "Idea Beta" in query_text:
                found.append("s2-beta")
                title_map["s2-beta"] = "Beta Prior Work"

        return found, [query["query"] for query in queries], [], title_map

    async def fake_verify_paper_candidates_for_run(
        run_id_arg,
        candidate_ids,
        title_map=None,
        source=None,
    ):
        assert run_id_arg == run_id
        assert source == "prior_art"
        records = {
            "s2-alpha": {
                "candidate_id": "s2-alpha",
                "candidate_key": "s2:s2-alpha",
                "canonical_title": "Alpha Prior Work",
                "verification_status": "verified",
                "source": "prior_art",
            },
            "s2-beta": {
                "candidate_id": "s2-beta",
                "candidate_key": "s2:s2-beta",
                "canonical_title": "Beta Prior Work",
                "verification_status": "verified",
                "source": "prior_art",
            },
        }
        return {
            candidate_id: records[candidate_id]
            for candidate_id in candidate_ids
        }

    async def fake_generate_llm_json(system_prompt, user_content, gateway, tier, schema=None):
        return (
            [
                {
                    "idea_title": "Idea Alpha",
                    "prior_art_found": True,
                    "similar_works": [{"title": "Alpha Prior Work"}],
                    "adjusted_novelty_score": 0.1,
                },
                {
                    "idea_title": "Idea Beta",
                    "prior_art_found": True,
                    "similar_works": [{"title": "Beta Prior Work"}],
                    "adjusted_novelty_score": 0.2,
                },
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
                "title": "Idea Alpha",
                "borrowed_method": "alpha method",
                "dedup_key": "idea-alpha",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            },
            {
                "id": "idea-1",
                "title": "Idea Beta",
                "borrowed_method": "beta method",
                "dedup_key": "idea-beta",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            },
        ],
    )

    updates = await divergent.prior_art_check(state)

    assert [
        record["candidate_id"]
        for record in updates["idea_cards"][0]["prior_art_details"]
    ] == ["s2-alpha"]
    assert [
        record["candidate_id"]
        for record in updates["idea_cards"][1]["prior_art_details"]
    ] == ["s2-beta"]
    assert updates["idea_cards"][0]["closest_prior_work"] == [
        {
            "title": "Alpha Prior Work",
            "doi": None,
            "arxiv_id": None,
            "candidate_key": "s2:s2-alpha",
        }
    ]
    assert updates["idea_cards"][1]["closest_prior_work"] == [
        {
            "title": "Beta Prior Work",
            "doi": None,
            "arxiv_id": None,
            "candidate_key": "s2:s2-beta",
        }
    ]
    assert set(updates["context_bundle"]["paper_verification"]) == {
        "s2-alpha",
        "s2-beta",
    }
