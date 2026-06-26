from __future__ import annotations

from apps.worker.run_persistence import (
    _listify_idea_value,
    _normalize_idea_card_payload,
)


def test_normalize_idea_card_payload_preserves_existing_plural_fields() -> None:
    payload = _normalize_idea_card_payload(
        {
            "title": "Verifier-Guided Retrieval",
            "borrowed_method": "structured audit",
            "borrowed_methods": ["existing audit"],
            "source_domain": ("software verification", "retrieval"),
        }
    )

    assert payload == {
        "title": "Verifier-Guided Retrieval",
        "borrowed_method": "structured audit",
        "borrowed_methods": ["existing audit"],
        "source_domain": ("software verification", "retrieval"),
        "source_domains": ["software verification", "retrieval"],
    }


def test_listify_idea_value_drops_empty_values() -> None:
    assert _listify_idea_value(None) == []
    assert _listify_idea_value("structured audit") == ["structured audit"]
    assert _listify_idea_value(["structured audit", None, ""]) == ["structured audit"]
