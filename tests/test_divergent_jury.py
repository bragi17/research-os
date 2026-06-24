from __future__ import annotations

import re

from apps.worker.modes import divergent


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
            "candidate_key": "s2-verified-key",
        }
    ]
    assert updated_cards[1]["prior_art_details"] == [fallback_verified_record]
    assert updated_cards[1]["closest_prior_work"] == [
        {
            "title": "Fallback Work",
            "doi": None,
            "arxiv_id": None,
            "candidate_key": None,
        }
    ]
