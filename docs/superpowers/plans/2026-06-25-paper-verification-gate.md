# Paper Verification Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify paper candidates before deep reading, prior-art judgment, citation use, or downstream idea scoring.

**Architecture:** Add a service-native paper verifier that wraps existing S2, OpenAlex, CrossRef, and arXiv checks. Persist verification records in a small table and attach per-run verification maps to mode `context_bundle` data without changing `search_academic_sources()` return shape.

**Tech Stack:** Python 3.10, FastAPI-compatible async services, asyncpg facade, Pydantic v2, pytest, existing academic adapters.

---

## File Structure

- Create `scripts/migration/009_paper_verification.sql` for durable verification records.
- Create `libs/schemas/paper_verification.py` for Pydantic models and enums.
- Create `services/paper_verification.py` for verification logic and adapter orchestration.
- Modify `apps/api/db/results.py` to upsert and fetch verification records.
- Modify `apps/api/database.py` to export the new DB helpers.
- Modify `apps/worker/modes/base.py` to add a shared verification helper.
- Modify `apps/worker/modes/frontier.py` to verify candidates after retrieval.
- Modify `apps/worker/modes/divergent.py` to verify prior-art candidates before novelty assessment.
- Add `tests/test_paper_verification.py`.
- Extend `tests/test_database_v2.py`.
- Add focused mode tests in `tests/test_frontier_paper_verification.py` and `tests/test_divergent_prior_art_verification.py`.

## Task 1: Create Isolated Worktree

- [ ] **Step 1: Create the worktree**

Run:

```bash
git worktree add .worktrees/paper-verification-gate -b feat/paper-verification-gate main
cd .worktrees/paper-verification-gate
```

Expected: worktree is created on `feat/paper-verification-gate`.

- [ ] **Step 2: Run focused baseline tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_database_v2.py tests/test_e2e_modes.py::TestFrontierMinimalInput -q
```

Expected: tests pass or any pre-existing failure is recorded before implementation starts.

## Task 2: Add Verification Schema And DB Helpers

**Files:**
- Create: `scripts/migration/009_paper_verification.sql`
- Create: `libs/schemas/paper_verification.py`
- Modify: `apps/api/db/results.py`
- Modify: `apps/api/database.py`
- Test: `tests/test_database_v2.py`

- [ ] **Step 1: Add migration**

Create `scripts/migration/009_paper_verification.sql`:

```sql
-- Paper verification records for search candidates and prior-art hits.
CREATE TABLE IF NOT EXISTS paper_verification (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    candidate_key TEXT NOT NULL,
    candidate_id TEXT,
    source TEXT,
    input_title TEXT,
    canonical_title TEXT,
    canonical_doi TEXT,
    canonical_arxiv_id TEXT,
    canonical_s2_id TEXT,
    canonical_openalex_id TEXT,
    verification_status TEXT NOT NULL DEFAULT 'verify_pending',
    verification_method TEXT NOT NULL DEFAULT 'none',
    verification_reason TEXT,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT paper_verification_status_check
        CHECK (verification_status IN ('verified', 'unverified', 'verify_pending', 'error')),
    CONSTRAINT paper_verification_raw_object_check
        CHECK (jsonb_typeof(raw_json) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_verification_run_key
    ON paper_verification(COALESCE(source_run_id, '00000000-0000-0000-0000-000000000000'::uuid), candidate_key);
CREATE INDEX IF NOT EXISTS idx_paper_verification_status ON paper_verification(verification_status);
CREATE INDEX IF NOT EXISTS idx_paper_verification_arxiv ON paper_verification(canonical_arxiv_id);
CREATE INDEX IF NOT EXISTS idx_paper_verification_doi ON paper_verification(canonical_doi);
```

- [ ] **Step 2: Add Pydantic models**

Create `libs/schemas/paper_verification.py`:

```python
"""Paper candidate verification schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PaperVerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    VERIFY_PENDING = "verify_pending"
    ERROR = "error"


class PaperVerificationMethod(str, Enum):
    ARXIV = "arxiv"
    CROSSREF = "crossref"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    TITLE_MATCH = "title_match"
    NONE = "none"


class PaperCandidate(BaseModel):
    candidate_id: str
    title: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    s2_id: str | None = None
    openalex_id: str | None = None
    source: str | None = None


class PaperVerificationRecord(BaseModel):
    source_run_id: UUID | None = None
    candidate_key: str
    candidate_id: str | None = None
    source: str | None = None
    input_title: str | None = None
    canonical_title: str | None = None
    canonical_doi: str | None = None
    canonical_arxiv_id: str | None = None
    canonical_s2_id: str | None = None
    canonical_openalex_id: str | None = None
    verification_status: PaperVerificationStatus = PaperVerificationStatus.VERIFY_PENDING
    verification_method: PaperVerificationMethod = PaperVerificationMethod.NONE
    verification_reason: str | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)
    verified_at: datetime | None = None
```

- [ ] **Step 3: Write failing DB tests**

Append to `tests/test_database_v2.py`:

```python
class TestPaperVerification:
    @pytest.mark.asyncio
    async def test_upserts_verification_record(self, mock_pool):
        fake = _make_record({
            "id": uuid4(),
            "source_run_id": RUN_ID,
            "candidate_key": "s2:abc",
            "candidate_id": "abc",
            "verification_status": "verified",
            "verification_method": "semantic_scholar",
        })
        mock_pool.fetchrow.return_value = fake

        from apps.api.database import upsert_paper_verification

        result = await upsert_paper_verification({
            "source_run_id": RUN_ID,
            "candidate_key": "s2:abc",
            "candidate_id": "abc",
            "verification_status": "verified",
            "verification_method": "semantic_scholar",
        })

        sql = mock_pool.fetchrow.call_args.args[0]
        assert "INSERT INTO paper_verification" in sql
        assert "ON CONFLICT" in sql
        assert result["candidate_key"] == "s2:abc"

    @pytest.mark.asyncio
    async def test_lists_verification_records_for_run(self, mock_pool):
        mock_pool.fetch.return_value = [
            _make_record({"candidate_key": "s2:abc", "verification_status": "verified"}),
        ]

        from apps.api.database import list_paper_verifications

        result = await list_paper_verifications(RUN_ID)

        sql = mock_pool.fetch.call_args.args[0]
        assert "FROM paper_verification" in sql
        assert "source_run_id = $1" in sql
        assert result[0]["verification_status"] == "verified"
```

Run:

```bash
PYTHONPATH=. pytest tests/test_database_v2.py::TestPaperVerification -q
```

Expected: fails because helpers are not implemented.

- [ ] **Step 4: Implement DB helpers**

Add to `apps/api/db/results.py`:

```python
async def upsert_paper_verification(data: dict[str, Any]) -> dict[str, Any]:
    """Insert or update one paper verification record."""
    pool = await db_pool.get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO paper_verification (
            source_run_id, candidate_key, candidate_id, source, input_title,
            canonical_title, canonical_doi, canonical_arxiv_id,
            canonical_s2_id, canonical_openalex_id, verification_status,
            verification_method, verification_reason, raw_json, verified_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8,
            $9, $10, $11,
            $12, $13, $14, $15
        )
        ON CONFLICT (COALESCE(source_run_id, '00000000-0000-0000-0000-000000000000'::uuid), candidate_key)
        DO UPDATE SET
            candidate_id = EXCLUDED.candidate_id,
            source = EXCLUDED.source,
            input_title = EXCLUDED.input_title,
            canonical_title = EXCLUDED.canonical_title,
            canonical_doi = EXCLUDED.canonical_doi,
            canonical_arxiv_id = EXCLUDED.canonical_arxiv_id,
            canonical_s2_id = EXCLUDED.canonical_s2_id,
            canonical_openalex_id = EXCLUDED.canonical_openalex_id,
            verification_status = EXCLUDED.verification_status,
            verification_method = EXCLUDED.verification_method,
            verification_reason = EXCLUDED.verification_reason,
            raw_json = EXCLUDED.raw_json,
            verified_at = EXCLUDED.verified_at,
            updated_at = NOW()
        RETURNING *
        """,
        data.get("source_run_id"),
        data["candidate_key"],
        data.get("candidate_id"),
        data.get("source"),
        data.get("input_title"),
        data.get("canonical_title"),
        data.get("canonical_doi"),
        data.get("canonical_arxiv_id"),
        data.get("canonical_s2_id"),
        data.get("canonical_openalex_id"),
        data.get("verification_status", "verify_pending"),
        data.get("verification_method", "none"),
        data.get("verification_reason"),
        orjson.dumps(data.get("raw_json", {})).decode("utf-8"),
        data.get("verified_at"),
    )
    return db_pool.record_to_dict(row)


async def list_paper_verifications(run_id: UUID) -> list[dict[str, Any]]:
    """Return paper verification records for one run."""
    pool = await db_pool.get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM paper_verification
        WHERE source_run_id = $1
        ORDER BY created_at ASC
        """,
        run_id,
    )
    return [db_pool.record_to_dict(row) for row in rows]
```

Also import and export both helpers in `apps/api/database.py`.

- [ ] **Step 5: Run DB tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_database_v2.py::TestPaperVerification -q
```

Expected: pass.

## Task 3: Implement Verification Service

**Files:**
- Create: `services/paper_verification.py`
- Test: `tests/test_paper_verification.py`

- [ ] **Step 1: Write service tests**

Create `tests/test_paper_verification.py`:

```python
from __future__ import annotations

import pytest

from libs.schemas.paper_verification import PaperCandidate, PaperVerificationStatus
from services.paper_verification import PaperVerifier, candidate_key


class StubVerifier(PaperVerifier):
    async def _verify_arxiv(self, candidate):
        if candidate.arxiv_id == "2505.24431":
            return self._verified(candidate, method="arxiv", title="Verified arXiv Paper", arxiv_id="2505.24431")
        return None

    async def _verify_doi(self, candidate):
        if candidate.doi == "10.1000/test":
            return self._verified(candidate, method="crossref", title="Verified DOI Paper", doi="10.1000/test")
        return None

    async def _verify_s2(self, candidate):
        if candidate.s2_id == "abc":
            return self._verified(candidate, method="semantic_scholar", title="Verified S2 Paper", s2_id="abc")
        return None

    async def _verify_openalex(self, candidate):
        return None

    async def _verify_title(self, candidate):
        if candidate.title == "Known Title":
            return self._verified(candidate, method="title_match", title="Known Title")
        return None


def test_candidate_key_prefers_stable_identifier():
    assert candidate_key(PaperCandidate(candidate_id="x", arxiv_id="2505.24431")) == "arxiv:2505.24431"
    assert candidate_key(PaperCandidate(candidate_id="x", doi="10.1000/test")) == "doi:10.1000/test"
    assert candidate_key(PaperCandidate(candidate_id="x", s2_id="abc")) == "s2:abc"


@pytest.mark.asyncio
async def test_verifies_by_arxiv():
    record = await StubVerifier().verify(PaperCandidate(candidate_id="p", arxiv_id="2505.24431"))
    assert record.verification_status == PaperVerificationStatus.VERIFIED
    assert record.verification_method == "arxiv"


@pytest.mark.asyncio
async def test_unverified_when_all_layers_miss():
    record = await StubVerifier().verify(PaperCandidate(candidate_id="p", title="Unknown"))
    assert record.verification_status == PaperVerificationStatus.UNVERIFIED
    assert record.verification_method == "none"


@pytest.mark.asyncio
async def test_malformed_candidate_is_error():
    record = await StubVerifier().verify(PaperCandidate(candidate_id=""))
    assert record.verification_status == PaperVerificationStatus.ERROR
```

Run:

```bash
PYTHONPATH=. pytest tests/test_paper_verification.py -q
```

Expected: fails because service is missing.

- [ ] **Step 2: Implement service**

Create `services/paper_verification.py`:

```python
"""Paper candidate verification across academic metadata sources."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from libs.adapters.crossref import CrossrefAdapter
from libs.adapters.openalex import OpenAlexAdapter
from libs.adapters.semantic_scholar import SemanticScholarAdapter
from libs.schemas.paper_verification import (
    PaperCandidate,
    PaperVerificationRecord,
    PaperVerificationStatus,
)


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().removeprefix("arXiv:").removeprefix("ARXIV:")
    raw = re.sub(r"v\d+$", "", raw)
    return raw or None


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return raw.lower() or None


def candidate_key(candidate: PaperCandidate) -> str:
    arxiv_id = normalize_arxiv_id(candidate.arxiv_id)
    doi = normalize_doi(candidate.doi)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if doi:
        return f"doi:{doi}"
    if candidate.s2_id:
        return f"s2:{candidate.s2_id}"
    if candidate.openalex_id:
        return f"openalex:{candidate.openalex_id}"
    if candidate.title:
        normalized = " ".join(candidate.title.lower().split())
        return f"title:{normalized[:160]}"
    return f"candidate:{candidate.candidate_id}"


def candidate_from_id(candidate_id: str, title: str | None = None, source: str | None = None) -> PaperCandidate:
    if candidate_id.startswith("OA:"):
        return PaperCandidate(candidate_id=candidate_id, openalex_id=candidate_id[3:], title=title, source=source or "openalex")
    arxiv_id = normalize_arxiv_id(candidate_id) if "." in candidate_id and len(candidate_id) < 32 else None
    return PaperCandidate(candidate_id=candidate_id, s2_id=None if arxiv_id else candidate_id, arxiv_id=arxiv_id, title=title, source=source or "semantic_scholar")


class PaperVerifier:
    def __init__(
        self,
        *,
        s2: SemanticScholarAdapter | None = None,
        crossref: CrossrefAdapter | None = None,
        openalex: OpenAlexAdapter | None = None,
    ) -> None:
        self.s2 = s2
        self.crossref = crossref
        self.openalex = openalex

    async def verify(self, candidate: PaperCandidate) -> PaperVerificationRecord:
        if not candidate.candidate_id:
            return PaperVerificationRecord(
                candidate_key="candidate:",
                candidate_id=candidate.candidate_id,
                input_title=candidate.title,
                verification_status=PaperVerificationStatus.ERROR,
                verification_reason="candidate_id is required",
            )
        try:
            for verifier in (self._verify_arxiv, self._verify_doi, self._verify_s2, self._verify_openalex, self._verify_title):
                record = await verifier(candidate)
                if record is not None:
                    return record
            return PaperVerificationRecord(
                candidate_key=candidate_key(candidate),
                candidate_id=candidate.candidate_id,
                source=candidate.source,
                input_title=candidate.title,
                verification_status=PaperVerificationStatus.UNVERIFIED,
                verification_method="none",
                verification_reason="No metadata source confirmed this candidate",
                verified_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return PaperVerificationRecord(
                candidate_key=candidate_key(candidate),
                candidate_id=candidate.candidate_id,
                source=candidate.source,
                input_title=candidate.title,
                verification_status=PaperVerificationStatus.VERIFY_PENDING,
                verification_method="none",
                verification_reason=str(exc),
            )

    def _verified(self, candidate: PaperCandidate, *, method: str, title: str | None = None, doi: str | None = None, arxiv_id: str | None = None, s2_id: str | None = None, openalex_id: str | None = None, raw: dict[str, Any] | None = None) -> PaperVerificationRecord:
        return PaperVerificationRecord(
            candidate_key=candidate_key(candidate),
            candidate_id=candidate.candidate_id,
            source=candidate.source,
            input_title=candidate.title,
            canonical_title=title or candidate.title,
            canonical_doi=normalize_doi(doi or candidate.doi),
            canonical_arxiv_id=normalize_arxiv_id(arxiv_id or candidate.arxiv_id),
            canonical_s2_id=s2_id or candidate.s2_id,
            canonical_openalex_id=openalex_id or candidate.openalex_id,
            verification_status=PaperVerificationStatus.VERIFIED,
            verification_method=method,
            verification_reason=f"Verified via {method}",
            raw_json=raw or {},
            verified_at=datetime.now(timezone.utc),
        )

    async def _verify_arxiv(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.arxiv_id:
            return None
        return self._verified(candidate, method="arxiv", arxiv_id=candidate.arxiv_id)

    async def _verify_doi(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.doi or self.crossref is None:
            return None
        work = await self.crossref.get_work(candidate.doi)
        return self._verified(candidate, method="crossref", title=work.title, doi=candidate.doi, raw=work.model_dump())

    async def _verify_s2(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.s2_id or self.s2 is None:
            return None
        paper = await self.s2.get_paper(candidate.s2_id, fields=["title", "externalIds"])
        external = paper.externalIds or {}
        return self._verified(candidate, method="semantic_scholar", title=paper.title, doi=external.get("DOI"), arxiv_id=external.get("ArXiv"), s2_id=paper.paperId, raw=paper.model_dump())

    async def _verify_openalex(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        if not candidate.openalex_id or self.openalex is None:
            return None
        work = await self.openalex.get_work(candidate.openalex_id)
        return self._verified(candidate, method="openalex", title=work.display_name, doi=work.doi, openalex_id=candidate.openalex_id, raw=work.model_dump())

    async def _verify_title(self, candidate: PaperCandidate) -> PaperVerificationRecord | None:
        return None
```

- [ ] **Step 3: Run service tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_paper_verification.py -q
```

Expected: pass.

## Task 4: Integrate With Mode Workflows

**Files:**
- Modify: `apps/worker/modes/base.py`
- Modify: `apps/worker/modes/frontier.py`
- Modify: `apps/worker/modes/divergent.py`
- Test: `tests/test_frontier_paper_verification.py`
- Test: `tests/test_divergent_prior_art_verification.py`

- [ ] **Step 1: Add shared mode helper**

Add to `apps/worker/modes/base.py`:

```python
async def verify_paper_candidates_for_run(
    run_id: UUID | str,
    candidate_ids: list[str],
    title_map: dict[str, str] | None = None,
    source: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Verify paper candidates and persist verification records when possible."""
    from apps.api.database import upsert_paper_verification
    from services.paper_verification import PaperVerifier, candidate_from_id

    title_map = title_map or {}
    verifier = PaperVerifier(
        s2=SemanticScholarAdapter(api_key=os.getenv("S2_API_KEY")),
        openalex=OpenAlexAdapter(email=os.getenv("OPENALEX_EMAIL")),
    )
    records: dict[str, dict[str, Any]] = {}
    try:
        for candidate_id in candidate_ids:
            candidate = candidate_from_id(candidate_id, title=title_map.get(candidate_id), source=source)
            record = await verifier.verify(candidate)
            payload = record.model_dump(mode="json")
            payload["source_run_id"] = UUID(str(run_id))
            records[candidate_id] = payload
            try:
                await upsert_paper_verification(payload)
            except Exception as exc:
                logger.debug("paper_verification.persist_failed", candidate_id=candidate_id, error=str(exc))
    finally:
        if verifier.s2 is not None:
            await verifier.s2.close()
        if verifier.openalex is not None:
            await verifier.openalex.close()
    return records
```

- [ ] **Step 2: Attach verification in Frontier retrieval**

In `apps/worker/modes/frontier.py`, after `all_new = library_ids + new_candidates + chain_candidates`, add:

```python
    verification_map = await verify_paper_candidates_for_run(
        state.run_id,
        all_new,
        title_map=title_map,
    )
```

Then add to context bundle:

```python
    paper_verification = ctx.get("paper_verification", {})
    paper_verification.update(verification_map)
    ctx["paper_verification"] = paper_verification
```

Also add `verify_paper_candidates_for_run` to the existing import from `apps.worker.modes.base`.

- [ ] **Step 3: Attach verification in Divergent prior-art check**

In `apps/worker/modes/divergent.py`, after `search_academic_sources()` returns in `prior_art_check`, capture `_titles` instead of discarding it and verify:

```python
        found, _executed, search_errors, title_map = await search_academic_sources(
            topic=state.topic,
            queries=search_queries[:10],
            existing_titles=existing_titles,
        )
        prior_art_papers = found
        prior_art_verification = await verify_paper_candidates_for_run(
            state.run_id,
            prior_art_papers,
            title_map=title_map,
            source="prior_art",
        )
```

Include verified records in the LLM input:

```python
        f"## Verified Prior Art Records\n"
        f"{json.dumps(prior_art_verification, default=str)[:8000]}\n\n"
```

Store them in the context bundle:

```python
    updated_bundle = dict(state.context_bundle)
    paper_verification = updated_bundle.get("paper_verification", {})
    paper_verification.update(prior_art_verification)
    updated_bundle["paper_verification"] = paper_verification
    updates["context_bundle"] = updated_bundle
```

- [ ] **Step 4: Add focused integration tests**

Create `tests/test_frontier_paper_verification.py`:

```python
from __future__ import annotations

from uuid import uuid4

import pytest

from apps.worker.modes.base import ModeGraphState


@pytest.mark.asyncio
async def test_candidate_retrieval_stores_verification_map(monkeypatch):
    from apps.worker.modes import frontier

    async def fake_search_academic_sources(**kwargs):
        return ["s2-paper"], ["query"], [], {"s2-paper": "A Verified Paper"}

    async def fake_verify(run_id, candidate_ids, title_map=None, source=None):
        return {"s2-paper": {"candidate_key": "s2:s2-paper", "verification_status": "verified"}}

    monkeypatch.setattr(frontier, "search_academic_sources", fake_search_academic_sources)
    monkeypatch.setattr(frontier, "verify_paper_candidates_for_run", fake_verify)
    monkeypatch.setattr(frontier, "rerank_search_results", lambda **kwargs: [])

    state = ModeGraphState(
        run_id=uuid4(),
        mode="frontier",
        topic="3D anomaly detection",
        pending_queries=[{"query": "3D anomaly detection", "source": "both"}],
    )

    updates = await frontier.candidate_retrieval(state)

    assert updates["context_bundle"]["paper_verification"]["s2-paper"]["verification_status"] == "verified"
```

Create `tests/test_divergent_prior_art_verification.py`:

```python
from __future__ import annotations

from uuid import uuid4

import pytest

from apps.worker.modes.base import ModeGraphState


@pytest.mark.asyncio
async def test_prior_art_check_passes_verified_records_to_context(monkeypatch):
    from apps.worker.modes import divergent

    async def fake_search_academic_sources(**kwargs):
        return ["prior-paper"], ["query"], [], {"prior-paper": "Closest Prior Work"}

    async def fake_verify(run_id, candidate_ids, title_map=None, source=None):
        return {"prior-paper": {"candidate_key": "s2:prior-paper", "verification_status": "verified"}}

    async def fake_json(*args, **kwargs):
        return ([{
            "idea_title": "Idea",
            "prior_art_found": True,
            "similar_works": [{"title": "Closest Prior Work", "similarity_reason": "same mechanism"}],
            "adjusted_novelty_score": 0.2,
        }], 0.0, [])

    monkeypatch.setattr(divergent, "search_academic_sources", fake_search_academic_sources)
    monkeypatch.setattr(divergent, "verify_paper_candidates_for_run", fake_verify)
    monkeypatch.setattr(divergent, "generate_llm_json", fake_json)

    state = ModeGraphState(
        run_id=uuid4(),
        mode="divergent",
        topic="3D anomaly detection",
        idea_cards=[{"title": "Idea", "borrowed_method": "contrastive learning"}],
    )

    updates = await divergent.prior_art_check(state)

    assert updates["context_bundle"]["paper_verification"]["prior-paper"]["verification_status"] == "verified"
    assert updates["idea_cards"][0]["prior_art_found"] is True
```

- [ ] **Step 5: Run mode tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_frontier_paper_verification.py tests/test_divergent_prior_art_verification.py -q
```

Expected: pass.

## Task 5: Verify And Commit

- [ ] **Step 1: Run targeted test suite**

Run:

```bash
PYTHONPATH=. pytest tests/test_paper_verification.py tests/test_database_v2.py::TestPaperVerification tests/test_frontier_paper_verification.py tests/test_divergent_prior_art_verification.py -q
```

Expected: pass.

- [ ] **Step 2: Run broader smoke tests**

Run:

```bash
PYTHONPATH=. pytest tests/test_e2e_modes.py tests/test_mode_router.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

Run:

```bash
git add scripts/migration/009_paper_verification.sql libs/schemas/paper_verification.py services/paper_verification.py apps/api/db/results.py apps/api/database.py apps/worker/modes/base.py apps/worker/modes/frontier.py apps/worker/modes/divergent.py tests/test_paper_verification.py tests/test_database_v2.py tests/test_frontier_paper_verification.py tests/test_divergent_prior_art_verification.py
git commit -m "feat: add paper verification gate"
```

Expected: branch contains one focused feature commit ready to merge first.
