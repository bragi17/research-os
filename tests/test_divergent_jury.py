from __future__ import annotations

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

    assert len(key) == 140
    assert key == "a" * 140


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

    assert deduped[0]["dedup_key"] == deduped[1]["dedup_key"]
    assert deduped[0]["novelty_verdict"] == "unclear"
    assert deduped[0]["quality_verdict"] == "hold"
    assert deduped[0]["jury_status"] == "pending"
    assert deduped[1]["novelty_verdict"] == "duplicate"
    assert deduped[1]["quality_verdict"] == "reject"
    assert deduped[1]["jury_status"] == "reviewed"
    assert "Duplicate of idea" in deduped[1]["strongest_objection"]


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
