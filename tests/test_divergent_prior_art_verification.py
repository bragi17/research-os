from __future__ import annotations

from uuid import uuid4

import pytest

from apps.worker.modes import divergent
from apps.worker.modes.base import ModeGraphState
from libs.schemas.literature import LiteratureGateStatus, LiteratureSource


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
@pytest.mark.parametrize(
    ("gate_status", "expected_card_status"),
    [
        (LiteratureGateStatus.BLOCKED.value, "retrieval_failed"),
        (LiteratureGateStatus.PENDING.value, "retrieval_pending"),
    ],
)
async def test_prior_art_check_stops_when_literature_gate_blocks_all_jobs(
    monkeypatch,
    gate_status,
    expected_card_status,
):
    run_id = uuid4()

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        assert kwargs["return_report"] is True
        query_text = kwargs["queries"][0]["query"]
        return (
            [],
            [query_text],
            ["semantic_scholar credential_error: forbidden"],
            {},
            {
                "requested_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                "enabled_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                "contributing_sources": [],
                "contribution_counts": {LiteratureSource.SEMANTIC_SCHOLAR.value: 0},
                "source_errors": [
                    {
                        "source": LiteratureSource.SEMANTIC_SCHOLAR.value,
                        "kind": "credential_error",
                        "message": "forbidden",
                        "query": query_text,
                    }
                ],
                "unavailable_sources": {},
                "candidate_count": 0,
                "gate_status": gate_status,
            },
        )

    async def fake_verify_paper_candidates_for_run(*args, **kwargs):
        raise AssertionError("blocked retrieval must not call paper verification")

    async def fake_generate_llm_json(*args, **kwargs):
        raise AssertionError("blocked retrieval must not call verifier LLM")

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

    card = updates["idea_cards"][0]
    assert card["prior_art_check_status"] == expected_card_status
    assert card["prior_art_found"] is None
    assert "paper_verification" in updates["context_bundle"]
    assert updates["context_bundle"]["paper_verification"] == {
        "existing": {"candidate_id": "existing"}
    }
    reports = updates["context_bundle"]["literature_search_reports"]
    report = reports[card["dedup_key"]]
    assert report["gate_status"] == gate_status
    assert report["source_errors"][0]["message"] == "forbidden"
    assert updates["errors"] == ["semantic_scholar credential_error: forbidden"]


@pytest.mark.asyncio
async def test_prior_art_check_marks_all_gated_cards_with_per_card_status(
    monkeypatch,
):
    run_id = uuid4()

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        assert kwargs["return_report"] is True
        query_text = kwargs["queries"][0]["query"]
        gate_status = (
            LiteratureGateStatus.BLOCKED.value
            if "Alpha" in query_text
            else LiteratureGateStatus.PENDING.value
        )
        return (
            [],
            [query_text],
            [f"semantic_scholar {gate_status}: unavailable"],
            {},
            {
                "requested_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                "enabled_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                "contributing_sources": [],
                "contribution_counts": {LiteratureSource.SEMANTIC_SCHOLAR.value: 0},
                "source_errors": [],
                "unavailable_sources": {},
                "candidate_count": 0,
                "gate_status": gate_status,
            },
        )

    async def fake_verify_paper_candidates_for_run(*args, **kwargs):
        raise AssertionError("gated retrieval must not call paper verification")

    async def fake_generate_llm_json(*args, **kwargs):
        raise AssertionError("all-gated retrieval must not call verifier LLM")

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
                "id": "idea-alpha",
                "title": "Idea Alpha",
                "borrowed_method": "alpha method",
                "dedup_key": "idea-alpha",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            },
            {
                "id": "idea-beta",
                "title": "Idea Beta",
                "borrowed_method": "beta method",
                "dedup_key": "idea-beta",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            },
            {
                "id": "idea-empty",
                "title": "",
                "borrowed_method": "",
                "dedup_key": "idea-empty",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            },
        ],
    )

    updates = await divergent.prior_art_check(state)

    cards = {card["dedup_key"]: card for card in updates["idea_cards"]}
    assert cards["idea-alpha"]["prior_art_check_status"] == "retrieval_failed"
    assert cards["idea-alpha"]["prior_art_found"] is None
    assert cards["idea-beta"]["prior_art_check_status"] == "retrieval_pending"
    assert cards["idea-beta"]["prior_art_found"] is None
    assert cards["idea-empty"]["prior_art_check_status"] == "pending"
    assert "prior_art_found" not in cards["idea-empty"]
    assert {
        key: report["gate_status"]
        for key, report in updates["context_bundle"]["literature_search_reports"].items()
    } == {
        "idea-alpha": LiteratureGateStatus.BLOCKED.value,
        "idea-beta": LiteratureGateStatus.PENDING.value,
    }


@pytest.mark.asyncio
async def test_prior_art_check_excludes_gated_cards_from_mixed_verifier_payload(
    monkeypatch,
):
    run_id = uuid4()
    seen_payload: list[list[dict[str, object]]] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        assert kwargs["return_report"] is True
        query_text = kwargs["queries"][0]["query"]
        if "Idea Alpha" in query_text:
            return (
                ["S2:alpha"],
                [query_text],
                [],
                {"S2:alpha": "Alpha Prior Work"},
                {
                    "requested_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                    "enabled_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                    "contributing_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                    "contribution_counts": {
                        LiteratureSource.SEMANTIC_SCHOLAR.value: 1
                    },
                    "source_errors": [],
                    "unavailable_sources": {},
                    "candidate_count": 1,
                    "gate_status": LiteratureGateStatus.PASS.value,
                },
            )
        return (
            [],
            [query_text],
            ["semantic_scholar credential_error: forbidden"],
            {},
            {
                "requested_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                "enabled_sources": [LiteratureSource.SEMANTIC_SCHOLAR.value],
                "contributing_sources": [],
                "contribution_counts": {LiteratureSource.SEMANTIC_SCHOLAR.value: 0},
                "source_errors": [],
                "unavailable_sources": {},
                "candidate_count": 0,
                "gate_status": LiteratureGateStatus.BLOCKED.value,
            },
        )

    async def fake_verify_paper_candidates_for_run(
        run_id_arg,
        candidate_ids,
        title_map=None,
        source=None,
    ):
        assert run_id_arg == run_id
        assert candidate_ids == ["S2:alpha"]
        assert title_map == {"S2:alpha": "Alpha Prior Work"}
        assert source == "prior_art"
        return {
            "S2:alpha": {
                "candidate_id": "S2:alpha",
                "candidate_key": "s2:alpha",
                "canonical_title": "Alpha Prior Work",
                "verification_status": "verified",
                "source": "prior_art",
            }
        }

    async def fake_generate_llm_json(system_prompt, user_content, gateway, tier, schema=None):
        payload_json = user_content.split(
            "## Idea Cards With Per-Card Prior Art\n",
            1,
        )[1].split("\n\nFor EACH idea card", 1)[0]
        payload = divergent.json.loads(payload_json)
        seen_payload.append(payload)
        assert [item["dedup_key"] for item in payload] == ["idea-alpha"]
        assert "Idea Beta" not in divergent.json.dumps(payload)
        return (
            [
                {
                    "dedup_key": "idea-alpha",
                    "idea_title": "Idea Alpha",
                    "prior_art_found": False,
                    "similar_works": [],
                    "adjusted_novelty_score": 0.9,
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
                "id": "idea-alpha",
                "title": "Idea Alpha",
                "borrowed_method": "alpha method",
                "dedup_key": "idea-alpha",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            },
            {
                "id": "idea-beta",
                "title": "Idea Beta",
                "borrowed_method": "beta method",
                "dedup_key": "idea-beta",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
            },
        ],
    )

    updates = await divergent.prior_art_check(state)

    assert len(seen_payload) == 1
    cards = {card["dedup_key"]: card for card in updates["idea_cards"]}
    assert cards["idea-alpha"]["prior_art_check_status"] == "checked"
    assert cards["idea-alpha"]["prior_art_found"] is False
    assert cards["idea-beta"]["prior_art_check_status"] == "retrieval_failed"
    assert cards["idea-beta"]["prior_art_found"] is None
    assert set(updates["context_bundle"]["paper_verification"]) == {"S2:alpha"}
