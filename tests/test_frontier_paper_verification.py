from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from apps.worker.modes import base, frontier
from apps.worker.modes.base import ModeGraphState


@pytest.mark.asyncio
async def test_verify_paper_candidates_for_run_persists_and_returns_by_candidate_id(
    monkeypatch,
):
    run_id = uuid4()
    persisted: list[dict] = []
    verified_candidates = []
    verifiers = []

    class StubRecord:
        def __init__(self, candidate):
            self.candidate = candidate

        def model_dump(self, mode="json"):
            return {
                "candidate_key": f"s2:{self.candidate.candidate_id}",
                "candidate_id": self.candidate.candidate_id,
                "source": self.candidate.source,
                "input_title": self.candidate.title,
                "canonical_title": self.candidate.title,
                "verification_status": "verified",
                "verification_method": "semantic_scholar",
            }

    class StubVerifier:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            verifiers.append(self)

        async def verify(self, candidate):
            verified_candidates.append(candidate)
            return StubRecord(candidate)

        async def close(self):
            self.closed = True

    async def fake_upsert(payload):
        persisted.append(payload)
        return payload

    monkeypatch.setattr("services.paper_verification.PaperVerifier", StubVerifier)
    monkeypatch.setattr("apps.api.database.upsert_paper_verification", fake_upsert)

    records = await base.verify_paper_candidates_for_run(
        run_id,
        ["s2-paper-1"],
        title_map={"s2-paper-1": "Verified Paper"},
        source="frontier",
    )

    assert records["s2-paper-1"]["candidate_id"] == "s2-paper-1"
    assert records["s2-paper-1"]["source_run_id"] == run_id
    assert isinstance(records["s2-paper-1"]["source_run_id"], UUID)
    assert persisted == [records["s2-paper-1"]]
    assert verified_candidates[0].title == "Verified Paper"
    assert verified_candidates[0].source == "frontier"
    assert verifiers[0].kwargs == {
        "s2_api_key": None,
        "crossref_email": None,
        "openalex_email": None,
    }
    assert verifiers[0].closed is True


@pytest.mark.asyncio
async def test_candidate_retrieval_attaches_paper_verification(monkeypatch):
    run_id = uuid4()

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        return (
            ["s2-paper-1"],
            ["graph retrieval"],
            [],
            {"s2-paper-1": "Graph Retrieval Paper"},
        )

    async def fake_rerank_search_results(**kwargs):
        return kwargs["paper_ids"]

    async def fake_verify_paper_candidates_for_run(
        run_id_arg,
        candidate_ids,
        title_map=None,
        source=None,
    ):
        assert run_id_arg == run_id
        assert candidate_ids == ["s2-paper-1"]
        assert title_map == {"s2-paper-1": "Graph Retrieval Paper"}
        assert source is None
        return {
            "s2-paper-1": {
                "candidate_id": "s2-paper-1",
                "canonical_title": "Graph Retrieval Paper",
                "verification_status": "verified",
            }
        }

    monkeypatch.setattr(frontier, "emit_progress", fake_emit_progress)
    monkeypatch.setattr(frontier, "search_academic_sources", fake_search_academic_sources)
    monkeypatch.setattr(frontier, "rerank_search_results", fake_rerank_search_results)
    monkeypatch.setattr(
        frontier,
        "verify_paper_candidates_for_run",
        fake_verify_paper_candidates_for_run,
    )

    state = ModeGraphState(
        run_id=run_id,
        topic="graph retrieval",
        pending_queries=[{"query": "graph retrieval", "source": "both"}],
    )

    updates = await frontier.candidate_retrieval(state)

    assert updates["context_bundle"]["paper_verification"] == {
        "s2-paper-1": {
            "candidate_id": "s2-paper-1",
            "canonical_title": "Graph Retrieval Paper",
            "verification_status": "verified",
        }
    }
