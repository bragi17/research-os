from __future__ import annotations

import re
from uuid import uuid4

import pytest

from apps.worker.modes import divergent
from apps.worker.modes.base import ModeGraphState
from libs.schemas.paper_verification import (
    PaperVerificationRecord,
    PaperVerificationStatus,
)


def test_idea_dedup_key_uses_title_and_problem_statement():
    card = {
        "title": "  Novel Method!! ",
        "problem_statement": "Solves 3D AD? with weak labels.",
    }

    assert (
        divergent._idea_dedup_key(card)
        == "novel-method-solves-3d-ad-with-weak-labels"
    )


def test_idea_dedup_key_falls_back_and_limits_length():
    assert divergent._idea_dedup_key({}) == "untitled-idea"
    punctuation_only_key = divergent._idea_dedup_key(
        {"title": "!!!", "problem_statement": "???"}
    )

    assert punctuation_only_key == "untitled-idea"

    key = divergent._idea_dedup_key(
        {"title": "A" * 200, "problem_statement": "B" * 200}
    )

    assert len(key) <= 140
    assert re.fullmatch(r"a+-[0-9a-f]{8}", key)


def test_dedupe_idea_cards_does_not_reject_long_keys_with_shared_prefix():
    cards = [
        {"title": "A" * 150, "problem_statement": "first distinct suffix"},
        {"title": "A" * 150, "problem_statement": "second distinct suffix"},
    ]

    deduped = divergent._dedupe_idea_cards(cards)
    first = deduped[0]["dedup_key"]
    second = deduped[1]["dedup_key"]

    assert first != second
    assert len(first) <= 140
    assert len(second) <= 140
    assert re.fullmatch(r"a+-[0-9a-f]{8}", first)
    assert re.fullmatch(r"a+-[0-9a-f]{8}", second)
    assert [card["novelty_verdict"] for card in deduped] == ["unclear", "unclear"]
    assert [card["quality_verdict"] for card in deduped] == ["hold", "hold"]


def test_dedupe_idea_cards_marks_later_duplicates_for_rejection():
    cards = [
        {
            "id": "idea-0",
            "title": "Transfer Contrastive Learning",
            "problem_statement": "3D anomaly detection lacks labels",
        },
        {
            "id": "idea-1",
            "title": "Transfer Contrastive Learning!",
            "problem_statement": "3D anomaly detection lacks labels.",
            "novelty_verdict": "unclear",
            "quality_verdict": "hold",
            "jury_status": "pending",
            "strongest_objection": "Needs clearer benchmark.",
        },
    ]

    deduped = divergent._dedupe_idea_cards(cards)

    assert deduped[0]["dedup_key"] != deduped[1]["dedup_key"]
    assert len({card["dedup_key"] for card in deduped}) == len(deduped)
    assert deduped[0]["novelty_verdict"] == "unclear"
    assert deduped[0]["quality_verdict"] == "hold"
    assert deduped[0]["jury_status"] == "pending"
    assert deduped[1]["novelty_verdict"] == "duplicate"
    assert deduped[1]["quality_verdict"] == "reject"
    assert deduped[1]["jury_status"] == "reviewed"
    assert deduped[1]["dedup_key"] == f"{deduped[0]['dedup_key']}-dup-2"
    assert deduped[1]["duplicate_of_dedup_key"] == deduped[0]["dedup_key"]
    assert "Duplicate of idea" in deduped[1]["strongest_objection"]


def test_dedupe_idea_cards_points_duplicates_to_actual_assigned_key():
    cards = [
        {"title": "Alpha", "problem_statement": "Beta"},
        {"title": "Alpha!", "problem_statement": "Beta."},
        {"title": "Alpha Beta Dup 2", "problem_statement": ""},
        {"title": "Alpha Beta Dup 2!", "problem_statement": ""},
    ]

    deduped = divergent._dedupe_idea_cards(cards)
    dedup_keys = [card["dedup_key"] for card in deduped]

    assert len(set(dedup_keys)) == len(dedup_keys)
    assert deduped[1]["dedup_key"] == "alpha-beta-dup-2"
    assert deduped[2]["dedup_key"] != "alpha-beta-dup-2"
    assert deduped[1]["novelty_verdict"] == "duplicate"
    assert deduped[1]["quality_verdict"] == "reject"
    assert deduped[2]["novelty_verdict"] == "unclear"
    assert deduped[2]["quality_verdict"] == "hold"
    assert deduped[3]["novelty_verdict"] == "duplicate"
    assert deduped[3]["duplicate_of_dedup_key"] == deduped[2]["dedup_key"]


def test_dedupe_idea_cards_returns_copies_without_mutating_input():
    cards = [
        {"title": "Idea A", "problem_statement": "Problem"},
        {"title": "Idea A", "problem_statement": "Problem"},
    ]
    original_cards = [dict(card) for card in cards]

    deduped = divergent._dedupe_idea_cards(cards)

    assert cards == original_cards
    assert deduped is not cards
    assert all(
        deduped_card is not input_card
        for deduped_card, input_card in zip(deduped, cards)
    )


def test_attach_prior_art_details_keeps_only_verified_records():
    cards = [
        {
            "title": "Idea A",
            "problem_statement": "Problem A",
            "dedup_key": "idea-a",
        },
        {
            "title": "Idea B",
            "problem_statement": "Problem B",
        },
    ]
    original_cards = [dict(card) for card in cards]
    idea_b_key = divergent._idea_dedup_key(cards[1])
    verified_record = {
        "candidate_id": "s2-verified",
        "candidate_key": "s2-verified-key",
        "title": "Verified Work",
        "canonical_title": "Canonical Verified Work",
        "doi": "10.1234/example",
        "arxiv_id": "2401.00001",
        "verification_status": "verified",
    }
    unverified_record = {
        "candidate_id": "s2-unverified",
        "title": "Unverified Work",
        "verification_status": "unverified",
    }
    fallback_verified_record = {
        "candidate_id": "s2-fallback",
        "canonical_title": "Fallback Work",
        "verification_status": "verified",
    }

    updated_cards = divergent._attach_prior_art_details(
        cards,
        {
            "idea-a": [verified_record, unverified_record],
            idea_b_key: [fallback_verified_record],
        },
    )

    assert cards == original_cards
    assert updated_cards is not cards
    assert all(
        updated_card is not input_card
        for updated_card, input_card in zip(updated_cards, cards)
    )
    assert updated_cards[0]["prior_art_details"] == [verified_record]
    assert updated_cards[0]["closest_prior_work"] == [
        {
            "title": "Canonical Verified Work",
            "doi": "10.1234/example",
            "arxiv_id": "2401.00001",
            "candidate_id": "s2-verified",
            "candidate_key": "s2-verified-key",
            "s2_id": None,
            "openalex_id": None,
            "input_title": None,
        }
    ]
    assert updated_cards[1]["prior_art_details"] == [fallback_verified_record]
    assert updated_cards[1]["closest_prior_work"] == [
        {
            "title": "Fallback Work",
            "doi": None,
            "arxiv_id": None,
            "candidate_id": "s2-fallback",
            "candidate_key": None,
            "s2_id": None,
            "openalex_id": None,
            "input_title": None,
        }
    ]


def test_attach_prior_art_details_accepts_paper_verification_records():
    record = PaperVerificationRecord(
        candidate_key="s2:s2-record",
        candidate_id="s2-record",
        input_title="Input Record Title",
        canonical_title="Canonical Record Title",
        canonical_doi="10.5555/canonical",
        canonical_arxiv_id="2501.00001",
        canonical_s2_id="S2-CANONICAL",
        canonical_openalex_id="OA-CANONICAL",
        verification_status=PaperVerificationStatus.VERIFIED,
    )
    unverified_record = PaperVerificationRecord(
        candidate_key="s2:s2-unverified",
        candidate_id="s2-unverified",
        canonical_title="Unverified Record",
        verification_status=PaperVerificationStatus.UNVERIFIED,
    )

    updated_cards = divergent._attach_prior_art_details(
        [
            {
                "title": "Idea Record",
                "problem_statement": "Problem",
                "dedup_key": "idea-record",
            }
        ],
        {"idea-record": [record, unverified_record]},
    )

    assert updated_cards[0]["prior_art_details"] == [
        {
            "id": None,
            "source_run_id": None,
            "candidate_key": "s2:s2-record",
            "candidate_id": "s2-record",
            "source": None,
            "input_title": "Input Record Title",
            "canonical_title": "Canonical Record Title",
            "canonical_doi": "10.5555/canonical",
            "canonical_arxiv_id": "2501.00001",
            "canonical_s2_id": "S2-CANONICAL",
            "canonical_openalex_id": "OA-CANONICAL",
            "verification_status": "verified",
            "verification_method": "none",
            "verification_reason": None,
            "raw_json": {},
            "verified_at": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    assert updated_cards[0]["closest_prior_work"] == [
        {
            "title": "Canonical Record Title",
            "doi": "10.5555/canonical",
            "arxiv_id": "2501.00001",
            "candidate_id": "s2-record",
            "candidate_key": "s2:s2-record",
            "s2_id": "S2-CANONICAL",
            "openalex_id": "OA-CANONICAL",
            "input_title": "Input Record Title",
        }
    ]


def test_attach_prior_art_details_preserves_existing_when_key_absent():
    card = {
        "title": "Idea With Existing Details",
        "problem_statement": "Problem",
        "dedup_key": "idea-existing",
        "prior_art_details": [{"candidate_id": "existing"}],
        "closest_prior_work": [{"title": "Existing Work"}],
    }

    updated_cards = divergent._attach_prior_art_details([card], {})

    assert updated_cards[0]["prior_art_details"] == [{"candidate_id": "existing"}]
    assert updated_cards[0]["closest_prior_work"] == [{"title": "Existing Work"}]
    assert card["prior_art_details"] == [{"candidate_id": "existing"}]


def test_attach_prior_art_details_preserves_existing_when_no_verified_records():
    card = {
        "title": "Idea With Existing Details",
        "problem_statement": "Problem",
        "dedup_key": "idea-existing",
        "prior_art_details": [{"candidate_id": "existing"}],
        "closest_prior_work": [{"title": "Existing Work"}],
    }

    updated_cards = divergent._attach_prior_art_details(
        [card],
        {
            "idea-existing": [
                {
                    "candidate_id": "s2-unverified",
                    "verification_status": "unverified",
                }
            ]
        },
    )

    assert updated_cards[0]["prior_art_details"] == [{"candidate_id": "existing"}]
    assert updated_cards[0]["closest_prior_work"] == [{"title": "Existing Work"}]


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

    async def fake_generate_llm_json(
        system_prompt,
        user_content,
        gateway,
        tier,
        schema=None,
    ):
        return (
            [
                {
                    "dedup_key": "idea-alpha",
                    "idea_title": "Idea Alpha",
                    "prior_art_found": True,
                    "similar_works": [{"title": "Alpha Prior Work"}],
                    "adjusted_novelty_score": 0.1,
                },
                {
                    "dedup_key": "idea-beta",
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
    monkeypatch.setattr(
        divergent,
        "search_academic_sources",
        fake_search_academic_sources,
    )
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
            "candidate_id": "s2-alpha",
            "candidate_key": "s2:s2-alpha",
            "s2_id": None,
            "openalex_id": None,
            "input_title": None,
        }
    ]
    assert updates["idea_cards"][1]["closest_prior_work"] == [
        {
            "title": "Beta Prior Work",
            "doi": None,
            "arxiv_id": None,
            "candidate_id": "s2-beta",
            "candidate_key": "s2:s2-beta",
            "s2_id": None,
            "openalex_id": None,
            "input_title": None,
        }
    ]
    assert set(updates["context_bundle"]["paper_verification"]) == {
        "s2-alpha",
        "s2-beta",
    }


@pytest.mark.asyncio
async def test_prior_art_check_uses_per_card_payload_and_preserves_similar_works(
    monkeypatch,
):
    run_id = uuid4()
    seen_payload: list[list[dict[str, object]]] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        query_text = kwargs["queries"][0]["query"]
        if "Idea Alpha" in query_text:
            return (
                ["s2-alpha"],
                [query_text],
                [],
                {"s2-alpha": "Alpha Prior Work"},
            )
        return [], [query_text], [], {}

    async def fake_verify_paper_candidates_for_run(
        run_id_arg,
        candidate_ids,
        title_map=None,
        source=None,
    ):
        assert run_id_arg == run_id
        assert source == "prior_art"
        if not candidate_ids:
            return {}
        return {
            "s2-alpha": {
                "candidate_id": "s2-alpha",
                "candidate_key": "s2:s2-alpha",
                "canonical_title": "Alpha Prior Work",
                "verification_status": "verified",
                "source": "prior_art",
            }
        }

    async def fake_generate_llm_json(
        system_prompt,
        user_content,
        gateway,
        tier,
        schema=None,
    ):
        match = re.search(
            r"## Idea Cards With Per-Card Prior Art\n(.*?)\n\nFor EACH idea card",
            user_content,
            re.S,
        )
        assert match is not None
        payload = divergent.json.loads(match.group(1))
        seen_payload.append(payload)

        alpha_payload = next(
            item for item in payload if item["idea_card"]["title"] == "Idea Alpha"
        )
        beta_payload = next(
            item for item in payload if item["idea_card"]["title"] == "Idea Beta"
        )
        assert [r["candidate_id"] for r in alpha_payload["prior_art_details"]] == [
            "s2-alpha"
        ]
        assert beta_payload["prior_art_details"] == []
        assert "Alpha Prior Work" not in divergent.json.dumps(beta_payload)

        return (
            [
                {
                    "dedup_key": "idea-alpha",
                    "idea_title": "Idea Alpha",
                    "prior_art_found": True,
                    "similar_works": [{"title": "LLM Alpha Work"}],
                    "adjusted_novelty_score": 0.1,
                },
                {
                    "dedup_key": "idea-beta",
                    "idea_title": "Idea Beta",
                    "prior_art_found": False,
                    "similar_works": [{"title": "LLM Beta Work"}],
                    "adjusted_novelty_score": 0.7,
                },
            ],
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(
        divergent,
        "search_academic_sources",
        fake_search_academic_sources,
    )
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
                "similar_works": [{"title": "Existing Alpha Work"}],
            },
            {
                "id": "idea-1",
                "title": "Idea Beta",
                "borrowed_method": "beta method",
                "dedup_key": "idea-beta",
                "prior_art_check_status": "pending",
                "novelty_score": 0.8,
                "similar_works": [{"title": "Existing Beta Work"}],
            },
        ],
    )

    updates = await divergent.prior_art_check(state)

    assert len(seen_payload) == 1
    assert updates["idea_cards"][0]["similar_works"] == [
        {"title": "Existing Alpha Work"}
    ]
    assert updates["idea_cards"][1]["similar_works"] == [
        {"title": "Existing Beta Work"}
    ]
    assert updates["idea_cards"][0]["prior_art_similar_works"] == [
        {"title": "LLM Alpha Work"}
    ]
    assert updates["idea_cards"][1]["prior_art_similar_works"] == [
        {"title": "LLM Beta Work"}
    ]


@pytest.mark.asyncio
async def test_prior_art_check_matches_duplicate_titles_by_dedup_key(monkeypatch):
    run_id = uuid4()

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        query_text = kwargs["queries"][0]["query"]
        if "alpha method" in query_text:
            return ["s2-alpha"], [query_text], [], {"s2-alpha": "Alpha Prior Work"}
        return ["s2-beta"], [query_text], [], {"s2-beta": "Beta Prior Work"}

    async def fake_verify_paper_candidates_for_run(
        run_id_arg,
        candidate_ids,
        title_map=None,
        source=None,
    ):
        records = {
            "s2-alpha": {
                "candidate_id": "s2-alpha",
                "candidate_key": "s2:s2-alpha",
                "canonical_title": "Alpha Prior Work",
                "verification_status": "verified",
            },
            "s2-beta": {
                "candidate_id": "s2-beta",
                "candidate_key": "s2:s2-beta",
                "canonical_title": "Beta Prior Work",
                "verification_status": "verified",
            },
        }
        return {candidate_id: records[candidate_id] for candidate_id in candidate_ids}

    async def fake_generate_llm_json(*args, **kwargs):
        return (
            [
                {
                    "dedup_key": "same-title-alpha",
                    "idea_title": "Same Title",
                    "prior_art_found": True,
                    "similar_works": [{"title": "Alpha Prior Work"}],
                    "adjusted_novelty_score": 0.1,
                },
                {
                    "dedup_key": "same-title-beta",
                    "idea_title": "Same Title",
                    "prior_art_found": False,
                    "similar_works": [],
                    "adjusted_novelty_score": 0.8,
                },
            ],
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(
        divergent,
        "search_academic_sources",
        fake_search_academic_sources,
    )
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
                "title": "Same Title",
                "borrowed_method": "alpha method",
                "dedup_key": "same-title-alpha",
                "novelty_score": 0.5,
            },
            {
                "id": "idea-1",
                "title": "Same Title",
                "borrowed_method": "beta method",
                "dedup_key": "same-title-beta",
                "novelty_score": 0.5,
            },
        ],
    )

    updates = await divergent.prior_art_check(state)

    assert updates["idea_cards"][0]["prior_art_found"] is True
    assert updates["idea_cards"][0]["novelty_score"] == 0.1
    assert updates["idea_cards"][1]["prior_art_found"] is False
    assert updates["idea_cards"][1]["novelty_score"] == 0.8


@pytest.mark.asyncio
async def test_prior_art_check_uses_computed_keys_for_legacy_cards(monkeypatch):
    run_id = uuid4()
    seen_payload: list[list[dict[str, object]]] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        return [], [kwargs["queries"][0]["query"]], [], {}

    async def fake_verify_paper_candidates_for_run(*args, **kwargs):
        return {}

    async def fake_generate_llm_json(system_prompt, user_content, gateway, tier):
        match = re.search(
            r"## Idea Cards With Per-Card Prior Art\n(.*?)\n\nFor EACH idea card",
            user_content,
            re.S,
        )
        assert match is not None
        payload = divergent.json.loads(match.group(1))
        seen_payload.append(payload)

        alpha_key = payload[0]["dedup_key"]
        beta_key = payload[1]["dedup_key"]
        assert alpha_key
        assert beta_key
        assert alpha_key != beta_key
        assert payload[0]["idea_card"]["dedup_key"] == alpha_key
        assert payload[1]["idea_card"]["dedup_key"] == beta_key

        return (
            [
                {
                    "dedup_key": alpha_key,
                    "idea_title": "Same Title",
                    "prior_art_found": True,
                    "adjusted_novelty_score": 0.2,
                },
                {
                    "dedup_key": beta_key,
                    "idea_title": "Same Title",
                    "prior_art_found": False,
                    "adjusted_novelty_score": 0.9,
                },
            ],
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(
        divergent,
        "search_academic_sources",
        fake_search_academic_sources,
    )
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
                "title": "Same Title",
                "problem_statement": "Alpha problem",
                "borrowed_method": "alpha method",
                "novelty_score": 0.5,
            },
            {
                "id": "idea-1",
                "title": "Same Title",
                "problem_statement": "Beta problem",
                "borrowed_method": "beta method",
                "novelty_score": 0.5,
            },
        ],
    )

    updates = await divergent.prior_art_check(state)

    assert len(seen_payload) == 1
    assert updates["idea_cards"][0]["dedup_key"] == seen_payload[0][0]["dedup_key"]
    assert updates["idea_cards"][1]["dedup_key"] == seen_payload[0][1]["dedup_key"]
    assert updates["idea_cards"][0]["prior_art_found"] is True
    assert updates["idea_cards"][1]["prior_art_found"] is False


@pytest.mark.asyncio
async def test_prior_art_check_does_not_title_fallback_duplicate_titles(monkeypatch):
    run_id = uuid4()

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        return [], [kwargs["queries"][0]["query"]], [], {}

    async def fake_verify_paper_candidates_for_run(*args, **kwargs):
        return {}

    async def fake_generate_llm_json(*args, **kwargs):
        return (
            [
                {
                    "idea_title": "Same Title",
                    "prior_art_found": True,
                    "adjusted_novelty_score": 0.1,
                }
            ],
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(
        divergent,
        "search_academic_sources",
        fake_search_academic_sources,
    )
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
                "title": "Same Title",
                "problem_statement": "Alpha problem",
                "borrowed_method": "alpha method",
                "novelty_score": 0.5,
            },
            {
                "id": "idea-1",
                "title": "Same Title",
                "problem_statement": "Beta problem",
                "borrowed_method": "beta method",
                "novelty_score": 0.5,
            },
        ],
    )

    updates = await divergent.prior_art_check(state)

    assert updates["idea_cards"][0]["prior_art_found"] is False
    assert updates["idea_cards"][1]["prior_art_found"] is False
    assert updates["idea_cards"][0]["novelty_score"] == 0.5
    assert updates["idea_cards"][1]["novelty_score"] == 0.5


def test_build_prior_art_verifier_payload_is_bounded_valid_json_without_raw_json():
    records_by_key = {
        "large-idea-problem": [
            {
                "candidate_id": f"s2-{idx}",
                "candidate_key": f"s2:s2-{idx}",
                "canonical_title": f"Prior Work {idx}",
                "verification_status": "verified",
                "verification_reason": "same setup",
                "raw_json": {"abstract": "x" * 2000},
            }
            for idx in range(20)
        ]
    }

    payload = divergent._build_prior_art_verifier_payload(
        [
            {
                "id": "idea-0",
                "title": "Large Idea",
                "problem_statement": "Problem",
                "raw_json": {"abstract": "y" * 2000},
                "notes": "z" * 9000,
            }
        ],
        records_by_key,
    )
    rendered = divergent.json.dumps(payload, default=str)

    assert divergent.json.loads(rendered) == payload
    assert len(rendered) < 8000
    assert "raw_json" not in rendered
    assert "notes" not in rendered
    assert payload[0]["dedup_key"] == "large-idea-problem"
    assert payload[0]["idea_card"]["dedup_key"] == "large-idea-problem"
    assert len(payload[0]["prior_art_details"]) == 5
