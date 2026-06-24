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


def test_build_prior_art_verifier_payload_bounds_compact_fallback():
    cards = [
        {
            "id": f"idea-{idx}-{'i' * 400}",
            "title": f"Long Idea {idx} {'t' * 400}",
            "problem_statement": f"Long Problem {idx} {'p' * 400}",
            "dedup_key": f"long-idea-{idx}-{'k' * 180}",
            "borrowed_method": f"Long Method {idx} {'m' * 400}",
        }
        for idx in range(10)
    ]
    records_by_key = {
        card["dedup_key"]: [
            {
                "candidate_id": f"s2-{idx}-{record_idx}",
                "candidate_key": f"s2:s2-{idx}-{record_idx}",
                "canonical_title": f"Prior Work {idx}-{record_idx} {'x' * 400}",
                "verification_status": "verified",
                "verification_reason": "same setup " + ("r" * 400),
            }
            for record_idx in range(8)
        ]
        for idx, card in enumerate(cards)
    }

    payload = divergent._build_prior_art_verifier_payload(cards, records_by_key)
    rendered = divergent.json.dumps(payload, default=str)

    assert divergent.json.loads(rendered) == payload
    assert len(rendered) <= divergent._VERIFIER_PAYLOAD_MAX_CHARS
    assert len(payload) == 10
    assert all(item["dedup_key"] for item in payload)


def test_build_prior_art_verifier_payload_bounds_oversized_existing_keys():
    cards = [
        {
            "id": f"idea-{idx}",
            "title": f"Legacy Key Idea {idx}",
            "problem_statement": "Problem",
            "dedup_key": f"legacy-key-{idx}-{'k' * 1000}",
        }
        for idx in range(10)
    ]

    payload = divergent._build_prior_art_verifier_payload(cards, {})
    rendered = divergent.json.dumps(payload, default=str)

    assert divergent.json.loads(rendered) == payload
    assert len(rendered) <= divergent._VERIFIER_PAYLOAD_MAX_CHARS
    assert all(len(item["dedup_key"]) <= 140 for item in payload)
    assert len({item["dedup_key"] for item in payload}) == len(payload)


def test_build_prior_art_verifier_payload_sanitizes_closest_prior_work():
    payload = divergent._build_prior_art_verifier_payload(
        [
            {
                "id": "idea-0",
                "title": "Closest Prior Work Idea",
                "problem_statement": "Problem",
                "dedup_key": "closest-prior-work-idea",
                "closest_prior_work": [
                    {
                        "title": "Closest Work",
                        "raw_json": {"abstract": "x" * 2000},
                        "notes": "n" * 2000,
                    }
                ],
                "prior_art_details": [
                    {
                        "candidate_id": "s2-closest",
                        "candidate_key": "s2:s2-closest",
                        "canonical_title": "Closest Work",
                        "verification_status": "verified",
                    }
                ],
            }
        ],
        {},
    )
    rendered = divergent.json.dumps(payload, default=str)

    assert divergent.json.loads(rendered) == payload
    assert "raw_json" not in rendered
    assert "notes" not in rendered
    assert payload[0]["closest_prior_work"] == [
        {
            "title": "Closest Work",
        }
    ]


def test_limit_verifier_payload_bounds_untrusted_fallback_keys():
    payload = [
        {
            "idea_card": {"dedup_key": "x" * 9000},
            "dedup_key": "x" * 9000,
            "prior_art_details": [],
            "closest_prior_work": [],
        }
    ]

    limited = divergent._limit_verifier_payload(payload)
    rendered = divergent.json.dumps(limited, default=str)

    assert divergent.json.loads(rendered) == limited
    assert len(rendered) <= divergent._VERIFIER_PAYLOAD_MAX_CHARS
    assert len(limited[0]["dedup_key"]) <= 140
    assert len(limited[0]["idea_card"]["dedup_key"]) <= 140


def test_build_prior_art_verifier_payload_bounds_many_cards():
    cards = [
        {
            "id": f"idea-{idx}",
            "title": f"Many Card Idea {idx}",
            "problem_statement": f"Problem {idx}",
            "dedup_key": f"many-card-{idx}",
        }
        for idx in range(100)
    ]

    payload = divergent._build_prior_art_verifier_payload(cards, {})
    rendered = divergent.json.dumps(payload, default=str)

    assert divergent.json.loads(rendered) == payload
    assert len(rendered) <= divergent._VERIFIER_PAYLOAD_MAX_CHARS
    assert len(payload) <= divergent._VERIFIER_CARD_MAX_ITEMS


@pytest.mark.asyncio
async def test_novelty_jury_updates_cards_from_grounded_verdict(monkeypatch):
    run_id = uuid4()
    gateway = object()
    progress_events: list[tuple[object, str, str, str]] = []
    seen_payloads: list[dict[str, object]] = []

    async def fake_emit_progress(run_id_arg, stage, status, message):
        progress_events.append((run_id_arg, stage, status, message))

    async def fake_generate_llm_json(*args, **kwargs):
        assert kwargs["schema"]["required"] == ["ideas"]
        assert kwargs["schema"]["properties"]["ideas"]["type"] == "array"
        item_schema = kwargs["schema"]["properties"]["ideas"]["items"]
        assert item_schema["required"] == [
            "dedup_key",
            "novelty_verdict",
            "quality_verdict",
            "strongest_objection",
            "required_validation",
        ]
        system_prompt, user_content, gateway_arg, tier = args
        assert system_prompt == divergent._NOVELTY_JURY_SYSTEM
        assert gateway_arg is gateway
        assert tier == divergent.ModelTier.HIGH
        assert "Do not reward wording changes" in system_prompt
        assert "Return strict JSON with a top-level ideas array" in system_prompt

        match = re.search(
            r"## Grounded Novelty Jury Payload\n(.*?)\n\nReturn",
            user_content,
            re.S,
        )
        assert match is not None
        payload = divergent.json.loads(match.group(1))
        seen_payloads.append(payload)
        assert payload["topic"] == "target task"
        assert payload["ideas"] == [
            {
                "idea_card": {
                    "dedup_key": "idea-alpha",
                    "id": "idea-0",
                    "title": "Idea Alpha",
                    "problem_statement": "Problem Alpha",
                    "mechanism_of_transfer": "Transfer mechanism",
                    "expected_benefit": "Better detection",
                    "novelty_verdict": "unclear",
                    "quality_verdict": "hold",
                },
                "dedup_key": "idea-alpha",
                "prior_art_details": [
                    {
                        "title": "Closest Alpha",
                        "verification_status": "verified",
                        "verification_method": None,
                        "verification_reason": None,
                    }
                ],
                "closest_prior_work": [{"title": "Closest Alpha"}],
            }
        ]

        return (
            {
                "ideas": [
                    {
                        "dedup_key": "idea-alpha",
                        "novelty_verdict": "novel",
                        "quality_verdict": "pursue",
                        "strongest_objection": "Needs ablation against closest prior work.",
                        "required_validation": ["Run target-domain ablation."],
                    }
                ]
            },
            0.03,
            ["jury warning"],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: gateway)
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    input_card = {
        "id": "idea-0",
        "dedup_key": "idea-alpha",
        "title": "Idea Alpha",
        "problem_statement": "Problem Alpha",
        "mechanism_of_transfer": "Transfer mechanism",
        "expected_benefit": "Better detection",
        "closest_prior_work": [{"title": "Closest Alpha"}],
        "prior_art_details": [
            {"canonical_title": "Closest Alpha", "verification_status": "verified"}
        ],
        "quality_verdict": "hold",
        "novelty_verdict": "unclear",
        "jury_status": "pending",
    }
    state = ModeGraphState(
        run_id=run_id,
        topic="target task",
        idea_cards=[input_card],
        current_cost_usd=0.5,
        errors=["existing error"],
    )

    updates = await divergent.novelty_jury(state)

    assert len(seen_payloads) == 1
    assert state.idea_cards == [input_card]
    assert updates["idea_cards"] == [
        {
            **input_card,
            "novelty_verdict": "novel",
            "quality_verdict": "pursue",
            "strongest_objection": "Needs ablation against closest prior work.",
            "required_validation": ["Run target-domain ablation."],
            "jury_status": "reviewed",
        }
    ]
    assert updates["idea_cards"][0] is not input_card
    assert updates["current_cost_usd"] == 0.53
    assert updates["errors"] == ["existing error", "jury warning"]
    assert updates["current_stage"] == "analyze"
    assert updates["current_step"] == "novelty_jury"
    assert updates["messages"] == [
        {"role": "assistant", "content": "Novelty jury reviewed 1 ideas."}
    ]
    assert [event[1:3] for event in progress_events] == [
        ("novelty_jury", "start"),
        ("novelty_jury", "done"),
    ]


@pytest.mark.asyncio
async def test_novelty_jury_preserves_rejects_and_excludes_them(monkeypatch):
    reviewed_keys: list[str] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(*args, **kwargs):
        user_content = args[1]
        assert "rejected-duplicate" not in user_content
        match = re.search(
            r"## Grounded Novelty Jury Payload\n(.*?)\n\nReturn",
            user_content,
            re.S,
        )
        assert match is not None
        payload = divergent.json.loads(match.group(1))
        reviewed_keys.extend(item["dedup_key"] for item in payload["ideas"])
        return (
            {
                "ideas": [
                    {
                        "dedup_key": "reviewable-idea",
                        "novelty_verdict": "duplicate",
                        "quality_verdict": "reject",
                        "strongest_objection": "Already covered by verified prior art.",
                        "required_validation": ["None."],
                    }
                ]
            },
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    rejected_card = {
        "id": "idea-0",
        "dedup_key": "rejected-duplicate",
        "title": "Rejected Duplicate",
        "quality_verdict": "reject",
        "novelty_verdict": "duplicate",
        "jury_status": "reviewed",
        "strongest_objection": "Duplicate of idea idea-1.",
    }
    reviewable_card = {
        "id": "idea-1",
        "dedup_key": "reviewable-idea",
        "title": "Reviewable Idea",
        "quality_verdict": "hold",
    }
    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[rejected_card, reviewable_card],
    )

    updates = await divergent.novelty_jury(state)

    assert reviewed_keys == ["reviewable-idea"]
    assert updates["idea_cards"][0] == rejected_card
    assert updates["idea_cards"][0] is not rejected_card
    assert updates["idea_cards"][1]["quality_verdict"] == "reject"
    assert updates["idea_cards"][1]["jury_status"] == "reviewed"
    assert updates["idea_cards"][1]["strongest_objection"] == (
        "Already covered by verified prior art."
    )
    assert updates["idea_cards"][1]["required_validation"] == ["None."]


@pytest.mark.asyncio
async def test_novelty_jury_normalizes_required_validation_to_list(monkeypatch):
    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(*args, **kwargs):
        return (
            {
                "ideas": [
                    {
                        "dedup_key": "idea-alpha",
                        "novelty_verdict": "incremental",
                        "quality_verdict": "hold",
                        "strongest_objection": "Needs a cleaner control.",
                        "required_validation": "Run a baseline comparison.",
                    }
                ]
            },
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "id": "idea-0",
                "dedup_key": "idea-alpha",
                "title": "Idea Alpha",
                "quality_verdict": "hold",
            }
        ],
    )

    updates = await divergent.novelty_jury(state)

    assert updates["idea_cards"][0]["required_validation"] == [
        "Run a baseline comparison."
    ]


@pytest.mark.asyncio
async def test_novelty_jury_sanitizes_payload_and_uses_stable_legacy_keys(
    monkeypatch,
):
    seen_payloads: list[dict[str, object]] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(
        system_prompt,
        user_content,
        gateway,
        tier,
        schema=None,
    ):
        assert schema is not None
        match = re.search(
            r"## Grounded Novelty Jury Payload\n(.*?)\n\nReturn",
            user_content,
            re.S,
        )
        assert match is not None
        payload = divergent.json.loads(match.group(1))
        rendered_payload = divergent.json.dumps(payload, default=str)
        seen_payloads.append(payload)

        assert "raw_json" not in rendered_payload
        assert "prompt injection" not in rendered_payload
        keys = [item["dedup_key"] for item in payload["ideas"]]
        assert len(keys) == len(set(keys))
        assert keys[0] != keys[1]

        return (
            {
                "ideas": [
                    {
                        "dedup_key": keys[0],
                        "novelty_verdict": "novel",
                        "quality_verdict": "pursue",
                        "strongest_objection": "Needs alpha control.",
                        "required_validation": ["Alpha validation."],
                    },
                    {
                        "dedup_key": keys[1],
                        "novelty_verdict": "incremental",
                        "quality_verdict": "hold",
                        "strongest_objection": "Needs beta control.",
                        "required_validation": ["Beta validation."],
                    },
                ]
            },
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "id": "idea-0",
                "title": "Same Legacy Title",
                "problem_statement": "Same problem",
                "quality_verdict": "hold",
                "prior_art_details": [
                    {
                        "canonical_title": "Alpha Work",
                        "verification_status": "verified",
                        "raw_json": {"abstract": "prompt injection"},
                    }
                ],
                "closest_prior_work": [
                    {"title": "Alpha Work", "raw_json": {"extra": "prompt injection"}}
                ],
            },
            {
                "id": "idea-1",
                "title": "Same Legacy Title",
                "problem_statement": "Same problem",
                "quality_verdict": "hold",
            },
        ],
    )

    updates = await divergent.novelty_jury(state)

    assert len(seen_payloads) == 1
    assert updates["idea_cards"][0]["dedup_key"] != updates["idea_cards"][1]["dedup_key"]
    assert updates["idea_cards"][0]["quality_verdict"] == "pursue"
    assert updates["idea_cards"][1]["quality_verdict"] == "hold"
    assert updates["idea_cards"][0]["strongest_objection"] == "Needs alpha control."
    assert updates["idea_cards"][1]["strongest_objection"] == "Needs beta control."


@pytest.mark.asyncio
async def test_novelty_jury_reviews_all_cards_in_bounded_batches(monkeypatch):
    batches: list[list[str]] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(
        system_prompt,
        user_content,
        gateway,
        tier,
        schema=None,
    ):
        assert schema is not None
        match = re.search(
            r"## Grounded Novelty Jury Payload\n(.*?)\n\nReturn",
            user_content,
            re.S,
        )
        assert match is not None
        payload = divergent.json.loads(match.group(1))
        keys = [item["dedup_key"] for item in payload["ideas"]]
        assert len(keys) <= divergent._VERIFIER_CARD_MAX_ITEMS
        batches.append(keys)
        return (
            {
                "ideas": [
                    {
                        "dedup_key": key,
                        "novelty_verdict": "incremental",
                        "quality_verdict": "hold",
                        "strongest_objection": f"Objection for {key}",
                        "required_validation": [f"Validate {key}"],
                    }
                    for key in keys
                ]
            },
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "id": f"idea-{idx}",
                "dedup_key": f"idea-{idx}",
                "title": f"Idea {idx}",
                "quality_verdict": "hold",
            }
            for idx in range(divergent._VERIFIER_CARD_MAX_ITEMS + 2)
        ],
    )

    updates = await divergent.novelty_jury(state)

    reviewed_keys = [key for batch in batches for key in batch]
    assert reviewed_keys == [f"idea-{idx}" for idx in range(12)]
    assert len(batches) == 2
    assert all(card["jury_status"] == "reviewed" for card in updates["idea_cards"])
    assert updates["idea_cards"][-1]["strongest_objection"] == "Objection for idea-11"


@pytest.mark.asyncio
async def test_novelty_jury_clamps_invalid_or_missing_verdict_fields(monkeypatch):
    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(*args, **kwargs):
        return (
            {
                "ideas": [
                    {
                        "dedup_key": "idea-alpha",
                        "novelty_verdict": "meaningfully_distinct",
                        "quality_verdict": "maybe",
                    }
                ]
            },
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "id": "idea-0",
                "dedup_key": "idea-alpha",
                "title": "Idea Alpha",
                "quality_verdict": "hold",
                "novelty_verdict": "unclear",
            }
        ],
    )

    updates = await divergent.novelty_jury(state)

    assert updates["idea_cards"][0]["novelty_verdict"] == "unclear"
    assert updates["idea_cards"][0]["quality_verdict"] == "hold"
    assert updates["idea_cards"][0]["strongest_objection"] == ""
    assert updates["idea_cards"][0]["required_validation"] == []
    assert updates["idea_cards"][0]["jury_status"] == "reviewed"


@pytest.mark.asyncio
async def test_novelty_jury_normalizes_verdict_case_and_whitespace(monkeypatch):
    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(*args, **kwargs):
        return (
            {
                "ideas": [
                    {
                        "dedup_key": "idea-alpha",
                        "novelty_verdict": " Duplicate ",
                        "quality_verdict": "Reject ",
                        "strongest_objection": "Already covered.",
                        "required_validation": ["None."],
                    }
                ]
            },
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "id": "idea-0",
                "dedup_key": "idea-alpha",
                "title": "Idea Alpha",
                "quality_verdict": "hold",
                "novelty_verdict": "unclear",
            }
        ],
    )

    updates = await divergent.novelty_jury(state)

    assert updates["idea_cards"][0]["novelty_verdict"] == "duplicate"
    assert updates["idea_cards"][0]["quality_verdict"] == "reject"
    assert updates["idea_cards"][0]["jury_status"] == "reviewed"


@pytest.mark.asyncio
async def test_novelty_jury_marks_missing_verdicts_as_errors(monkeypatch):
    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(*args, **kwargs):
        return (
            {
                "ideas": [
                    {
                        "dedup_key": "idea-alpha",
                        "novelty_verdict": "novel",
                        "quality_verdict": "pursue",
                        "strongest_objection": "Needs validation.",
                        "required_validation": ["Run ablation."],
                    }
                ]
            },
            0.01,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "id": "idea-0",
                "dedup_key": "idea-alpha",
                "title": "Idea Alpha",
                "quality_verdict": "hold",
            },
            {
                "id": "idea-1",
                "dedup_key": "idea-beta",
                "title": "Idea Beta",
                "quality_verdict": "hold",
            },
        ],
    )

    updates = await divergent.novelty_jury(state)

    assert updates["idea_cards"][0]["quality_verdict"] == "pursue"
    assert updates["idea_cards"][0]["jury_status"] == "reviewed"
    assert updates["idea_cards"][1]["quality_verdict"] == "reject"
    assert updates["idea_cards"][1]["novelty_verdict"] == "unclear"
    assert updates["idea_cards"][1]["jury_status"] == "error"
    assert updates["idea_cards"][1]["strongest_objection"] == (
        "Novelty jury did not return a verdict."
    )
    assert updates["idea_cards"][1]["required_validation"] == [
        "Rerun novelty jury or manually verify novelty."
    ]


@pytest.mark.asyncio
async def test_novelty_jury_no_reviewable_cards_skips_llm_and_advances(monkeypatch):
    progress_events: list[tuple[str, str]] = []

    async def fake_emit_progress(run_id_arg, stage, status, message):
        progress_events.append((stage, status))

    async def fake_generate_llm_json(*args, **kwargs):
        raise AssertionError("novelty_jury should skip the LLM with no reviewable cards")

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    rejected_card = {
        "id": "idea-0",
        "dedup_key": "rejected-duplicate",
        "title": "Rejected Duplicate",
        "quality_verdict": "reject",
        "novelty_verdict": "duplicate",
        "jury_status": "reviewed",
    }
    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[rejected_card],
        current_cost_usd=0.5,
        errors=["existing error"],
    )

    updates = await divergent.novelty_jury(state)

    assert updates["idea_cards"] == [rejected_card]
    assert updates["idea_cards"][0] is not rejected_card
    assert updates["current_cost_usd"] == 0.5
    assert updates["errors"] == ["existing error"]
    assert updates["current_stage"] == "analyze"
    assert updates["current_step"] == "novelty_jury"
    assert updates["messages"] == [
        {"role": "assistant", "content": "Novelty jury reviewed 0 ideas."}
    ]
    assert progress_events == [
        ("novelty_jury", "start"),
        ("novelty_jury", "done"),
    ]


@pytest.mark.asyncio
async def test_feasibility_review_filters_by_quality_verdict(monkeypatch):
    reviewed_titles: list[str] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(system_prompt, user_content, gateway, tier):
        assert "Pursue Prior Art Idea" in user_content
        assert "Hold Idea" in user_content
        assert "Missing Quality Idea" not in user_content
        assert "Rejected Clean Idea" not in user_content
        reviewed_titles.extend(
            title
            for title in (
                "Pursue Prior Art Idea",
                "Hold Idea",
                "Missing Quality Idea",
                "Rejected Clean Idea",
            )
            if title in user_content
        )
        return (
            [
                {
                    "idea_title": "Pursue Prior Art Idea",
                    "overall_feasibility": 0.8,
                    "data_available": True,
                },
                {
                    "idea_title": "Hold Idea",
                    "overall_feasibility": 0.6,
                    "data_available": True,
                },
            ],
            0.02,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "title": "Pursue Prior Art Idea",
                "quality_verdict": "pursue",
                "jury_status": "reviewed",
                "prior_art_found": True,
                "feasibility_score": 0.1,
            },
            {
                "title": "Hold Idea",
                "quality_verdict": "hold",
                "jury_status": "reviewed",
                "prior_art_found": False,
                "feasibility_score": 0.1,
            },
            {
                "title": "Rejected Clean Idea",
                "quality_verdict": "reject",
                "jury_status": "reviewed",
                "prior_art_found": False,
                "feasibility_score": 0.1,
            },
            {
                "title": "Missing Quality Idea",
                "prior_art_found": False,
                "feasibility_score": 0.1,
            },
        ],
    )

    updates = await divergent.feasibility_review(state)

    assert reviewed_titles == [
        "Pursue Prior Art Idea",
        "Hold Idea",
    ]
    assert updates["idea_cards"][0]["feasibility_score"] == 0.8
    assert updates["idea_cards"][1]["feasibility_score"] == 0.6
    assert updates["idea_cards"][2]["feasibility_score"] == 0.1
    assert updates["idea_cards"][3]["feasibility_score"] == 0.1


@pytest.mark.asyncio
async def test_feasibility_review_does_not_update_rejected_duplicate_titles(monkeypatch):
    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(system_prompt, user_content, gateway, tier):
        assert user_content.count("Shared Title") == 1
        return (
            [
                {
                    "idea_title": "Shared Title",
                    "overall_feasibility": 0.9,
                    "data_available": True,
                },
            ],
            0.02,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "title": "Shared Title",
                "quality_verdict": "hold",
                "jury_status": "reviewed",
                "feasibility_score": 0.1,
            },
            {
                "title": "Shared Title",
                "quality_verdict": "reject",
                "jury_status": "reviewed",
                "feasibility_score": 0.2,
            },
        ],
    )

    updates = await divergent.feasibility_review(state)

    assert updates["idea_cards"][0]["feasibility_score"] == 0.9
    assert updates["idea_cards"][1]["feasibility_score"] == 0.2
    assert "data_available" not in updates["idea_cards"][1]
    assert "compute_reasonable" not in updates["idea_cards"][1]
    assert "experiment_designable" not in updates["idea_cards"][1]
    assert "estimated_weeks" not in updates["idea_cards"][1]
    assert "critical_risks" not in updates["idea_cards"][1]
    assert "go_no_go" not in updates["idea_cards"][1]
    assert "recommended_first_experiment" not in updates["idea_cards"][1]


def test_divergent_graph_routes_prior_art_through_novelty_jury():
    workflow = divergent.create_divergent_graph()

    assert "novelty_jury" in workflow.nodes
    assert ("prior_art_check", "novelty_jury") in workflow.edges
    assert ("novelty_jury", "feasibility_review") in workflow.edges
    assert ("prior_art_check", "feasibility_review") not in workflow.edges


@pytest.mark.asyncio
async def test_idea_portfolio_excludes_rejected_jury_cards(monkeypatch):
    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_generate_llm_json(system_prompt, user_content, gateway, tier):
        assert "Viable Idea" in user_content
        assert "Rejected Duplicate" not in user_content
        return (
            {
                "portfolio_summary": "One viable idea remains.",
                "recommended_next_steps": ["Run validation."],
            },
            0.02,
            [],
        )

    monkeypatch.setattr(divergent, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(divergent, "get_gateway", lambda: object())
    monkeypatch.setattr(divergent, "generate_llm_json", fake_generate_llm_json)

    state = ModeGraphState(
        run_id=uuid4(),
        topic="target task",
        idea_cards=[
            {
                "title": "Rejected Duplicate",
                "quality_verdict": "reject",
                "jury_status": "reviewed",
                "novelty_verdict": "duplicate",
                "novelty_score": 1.0,
                "feasibility_score": 1.0,
            },
            {
                "title": "Viable Idea",
                "quality_verdict": "hold",
                "jury_status": "reviewed",
                "novelty_verdict": "incremental",
                "novelty_score": 0.4,
                "feasibility_score": 0.4,
            },
        ],
    )

    updates = await divergent.idea_portfolio(state)

    assert [card["title"] for card in updates["idea_cards"]] == ["Viable Idea"]
    assert "Viable Idea" in updates["report_markdown"]
    assert "Rejected Duplicate" not in updates["report_markdown"]
