from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from apps.worker.modes import base, frontier
from apps.worker.modes.base import ModeGraphState


@pytest.mark.asyncio
async def test_verify_paper_candidates_for_run_persists_and_returns_by_candidate_id(
    monkeypatch,
):
    monkeypatch.delenv("S2_API_KEY", raising=False)
    monkeypatch.delenv("CROSSREF_EMAIL", raising=False)
    monkeypatch.delenv("OPENALEX_EMAIL", raising=False)
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
    assert records["s2-paper-1"]["source_run_id"] == str(run_id)
    assert persisted[0]["candidate_id"] == "s2-paper-1"
    assert persisted[0]["source_run_id"] == run_id
    assert isinstance(persisted[0]["source_run_id"], UUID)
    assert verified_candidates[0].title == "Verified Paper"
    assert verified_candidates[0].source == "frontier"
    assert verifiers[0].kwargs == {
        "s2_api_key": None,
        "crossref_email": None,
        "openalex_email": None,
    }
    assert verifiers[0].closed is True


@pytest.mark.asyncio
async def test_verify_paper_candidates_for_run_empty_input_skips_verifier(monkeypatch):
    constructed = False

    class StubVerifier:
        def __init__(self, **kwargs):
            nonlocal constructed
            constructed = True

    monkeypatch.setattr("services.paper_verification.PaperVerifier", StubVerifier)

    records = await base.verify_paper_candidates_for_run(uuid4(), [])

    assert records == {}
    assert constructed is False


@pytest.mark.asyncio
async def test_verify_paper_candidates_for_run_validates_run_id_before_verifier(
    monkeypatch,
):
    constructed = False

    class StubVerifier:
        def __init__(self, **kwargs):
            nonlocal constructed
            constructed = True

    monkeypatch.setattr("services.paper_verification.PaperVerifier", StubVerifier)

    with pytest.raises(ValueError):
        await base.verify_paper_candidates_for_run("not-a-uuid", ["s2-paper-1"])

    assert constructed is False


@pytest.mark.asyncio
async def test_verify_paper_candidates_for_run_uses_python_payload_for_db(
    monkeypatch,
):
    run_id = uuid4()
    verified_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    persisted: list[dict] = []
    verified_candidates = []

    class StubRecord:
        def __init__(self, candidate):
            self.candidate = candidate

        def model_dump(self, mode="json"):
            payload = {
                "candidate_key": f"s2:{self.candidate.candidate_id}",
                "candidate_id": self.candidate.candidate_id,
                "canonical_title": "Verified Paper",
                "verification_status": "verified",
                "verification_method": "semantic_scholar",
                "verified_at": verified_at,
            }
            if mode == "json":
                payload["verified_at"] = verified_at.isoformat()
            return payload

    class StubVerifier:
        def __init__(self, **kwargs):
            pass

        async def verify(self, candidate):
            verified_candidates.append(candidate.candidate_id)
            return StubRecord(candidate)

        async def close(self):
            pass

    async def fake_upsert(payload):
        persisted.append(payload)
        return payload

    monkeypatch.setattr("services.paper_verification.PaperVerifier", StubVerifier)
    monkeypatch.setattr("apps.api.database.upsert_paper_verification", fake_upsert)

    records = await base.verify_paper_candidates_for_run(
        run_id,
        ["s2-paper-1", "s2-paper-1"],
    )

    assert verified_candidates == ["s2-paper-1"]
    assert len(persisted) == 1
    assert persisted[0]["source_run_id"] == run_id
    assert isinstance(persisted[0]["source_run_id"], UUID)
    assert persisted[0]["verified_at"] == verified_at
    assert isinstance(persisted[0]["verified_at"], datetime)
    assert records["s2-paper-1"]["source_run_id"] == str(run_id)
    assert records["s2-paper-1"]["verified_at"] == verified_at.isoformat()


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


@pytest.mark.asyncio
async def test_candidate_retrieval_dedupes_candidates_before_verify_and_append(
    monkeypatch,
):
    run_id = uuid4()
    verified_candidate_ids: list[list[str]] = []

    async def fake_emit_progress(*args, **kwargs):
        return None

    async def fake_search_academic_sources(**kwargs):
        return (
            ["s2-paper-1", "s2-paper-1", "s2-paper-2"],
            ["graph retrieval"],
            [],
            {
                "s2-paper-1": "Graph Retrieval Paper",
                "s2-paper-2": "Another Graph Paper",
            },
        )

    async def fake_rerank_search_results(**kwargs):
        return kwargs["paper_ids"]

    async def fake_verify_paper_candidates_for_run(
        run_id_arg,
        candidate_ids,
        title_map=None,
        source=None,
    ):
        verified_candidate_ids.append(candidate_ids)
        return {
            candidate_id: {
                "candidate_id": candidate_id,
                "verification_status": "verified",
            }
            for candidate_id in candidate_ids
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
        library_seeds=[{"paper_id": "s2-paper-1"}],
    )

    updates = await frontier.candidate_retrieval(state)

    assert verified_candidate_ids == [["s2-paper-1", "s2-paper-2"]]
    assert updates["candidate_paper_ids"] == ["s2-paper-1", "s2-paper-2"]
    assert list(updates["context_bundle"]["paper_verification"]) == [
        "s2-paper-1",
        "s2-paper-2",
    ]
