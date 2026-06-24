# Submission Audit Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require explicit paper-claim and adversarial audit reports before a submission package can be marked ready.

**Architecture:** Extend `submission_package` with two audit report JSON fields, have `gate_submission_package()` load or request those reports, and queue a dedicated submission audit coding task when either report is missing. Existing revision tasks remain responsible for fixing known blockers after required audit reports exist.

**Tech Stack:** Python 3.10, asyncpg facade, Pydantic v2, PostgreSQL JSONB, pytest, existing production orchestrator coding task flow.

---

## File Structure

- Create `scripts/migration/012_submission_audit_gates.sql` for new submission audit fields.
- Modify `libs/schemas/production.py` to add request and response fields.
- Modify `apps/api/db/production.py` to include the new fields in inserts, updates, and response columns.
- Modify `apps/web/src/lib/api.ts` to expose the new fields to the frontend.
- Modify `apps/worker/production/orchestrator.py` to load audit reports, block readiness, queue audit tasks, and regate after completion.
- Extend `tests/production/test_production_db.py`.
- Extend `tests/production/test_production_schemas.py`.
- Extend `tests/production/test_orchestrator.py`.

## Task 1: Create Isolated Worktree

- [ ] **Step 1: Start after research memory is merged**

Run from `/root/research-os`:

```bash
git checkout main
git pull --ff-only
git worktree add .worktrees/submission-audit-gates -b feat/submission-audit-gates main
cd .worktrees/submission-audit-gates
```

Expected: worktree is created on `feat/submission-audit-gates` and contains the previous quality-gate changes.

- [ ] **Step 2: Run production baseline tests**

Run:

```bash
PYTHONPATH=. pytest tests/production/test_production_db.py tests/production/test_production_schemas.py tests/production/test_orchestrator.py -q
```

Expected: tests pass or any pre-existing failure is recorded before implementation starts.

## Task 2: Add Submission Audit Fields

**Files:**
- Create: `scripts/migration/012_submission_audit_gates.sql`
- Modify: `libs/schemas/production.py`
- Modify: `apps/api/db/production.py`
- Modify: `apps/web/src/lib/api.ts`
- Test: `tests/production/test_production_db.py`
- Test: `tests/production/test_production_schemas.py`

- [ ] **Step 1: Add migration**

Create `scripts/migration/012_submission_audit_gates.sql`:

```sql
-- Submission gate reports that require independent audit artifacts.
ALTER TABLE submission_package
    ADD COLUMN IF NOT EXISTS paper_claim_audit_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS adversarial_audit_report_json JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'submission_package_paper_claim_audit_object_check'
    ) THEN
        ALTER TABLE submission_package
            ADD CONSTRAINT submission_package_paper_claim_audit_object_check
            CHECK (jsonb_typeof(paper_claim_audit_report_json) = 'object');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'submission_package_adversarial_audit_object_check'
    ) THEN
        ALTER TABLE submission_package
            ADD CONSTRAINT submission_package_adversarial_audit_object_check
            CHECK (jsonb_typeof(adversarial_audit_report_json) = 'object');
    END IF;
END $$;
```

- [ ] **Step 2: Write failing schema test**

Append to `tests/production/test_production_schemas.py`:

```python
def test_submission_package_has_independent_audit_reports():
    from libs.schemas.production import SubmissionPackageCreate

    package = SubmissionPackageCreate(
        manuscript_package_id="00000000-0000-0000-0000-000000000001",
        venue="ICLR",
        paper_claim_audit_report_json={"passed": True},
        adversarial_audit_report_json={"passed": False, "blockers": ["missing ablation"]},
    )

    assert package.paper_claim_audit_report_json["passed"] is True
    assert package.adversarial_audit_report_json["blockers"] == ["missing ablation"]
```

Run:

```bash
PYTHONPATH=. pytest tests/production/test_production_schemas.py::test_submission_package_has_independent_audit_reports -q
```

Expected: fails because the fields are not yet defined.

- [ ] **Step 3: Add Pydantic fields**

In `libs/schemas/production.py`, update `SubmissionPackageCreate`:

```python
class SubmissionPackageCreate(BaseModel):
    """Request payload for a submission package."""

    manuscript_package_id: UUID
    venue: NonBlankStr
    deadline: datetime | None = None
    submission_dir: str | None = None
    checklist_json: dict[str, Any] = Field(default_factory=dict)
    anonymity_report_json: dict[str, Any] = Field(default_factory=dict)
    compile_report_json: dict[str, Any] = Field(default_factory=dict)
    claim_audit_report_json: dict[str, Any] = Field(default_factory=dict)
    citation_audit_report_json: dict[str, Any] = Field(default_factory=dict)
    artifact_provenance_report_json: dict[str, Any] = Field(default_factory=dict)
    paper_claim_audit_report_json: dict[str, Any] = Field(default_factory=dict)
    adversarial_audit_report_json: dict[str, Any] = Field(default_factory=dict)
    status: SubmissionPackageStatus = SubmissionPackageStatus.PREPARING
```

- [ ] **Step 4: Write failing DB test**

Append to `tests/production/test_production_db.py`:

```python
@pytest.mark.asyncio
async def test_create_submission_package_includes_independent_audit_fields(monkeypatch):
    from apps.api.db import production

    captured = {}

    class Pool:
        async def fetchrow(self, sql, *values):
            captured["sql"] = sql
            captured["values"] = values
            return {
                "id": "00000000-0000-0000-0000-000000000010",
                "paper_claim_audit_report_json": {"passed": True},
                "adversarial_audit_report_json": {"passed": False},
            }

    async def fake_pool():
        return Pool()

    monkeypatch.setattr(production.db_pool, "get_pool", fake_pool)
    monkeypatch.setattr(production.db_pool, "record_to_dict", dict)

    await production.create_submission_package({
        "manuscript_package_id": "00000000-0000-0000-0000-000000000001",
        "venue": "ICLR",
        "paper_claim_audit_report_json": {"passed": True},
        "adversarial_audit_report_json": {"passed": False},
    })

    assert "paper_claim_audit_report_json" in captured["sql"]
    assert "adversarial_audit_report_json" in captured["sql"]
```

Run:

```bash
PYTHONPATH=. pytest tests/production/test_production_db.py::test_create_submission_package_includes_independent_audit_fields -q
```

Expected: fails because `SUBMISSION_PACKAGE_COLUMNS` does not include the new fields.

- [ ] **Step 5: Add DB columns and defaults**

In `apps/api/db/production.py`, update `SUBMISSION_PACKAGE_COLUMNS`:

```python
SUBMISSION_PACKAGE_COLUMNS = (
    "manuscript_package_id",
    "venue",
    "deadline",
    "submission_dir",
    "checklist_json",
    "anonymity_report_json",
    "compile_report_json",
    "claim_audit_report_json",
    "citation_audit_report_json",
    "artifact_provenance_report_json",
    "paper_claim_audit_report_json",
    "adversarial_audit_report_json",
    "status",
)
```

In `create_submission_package()`, add defaults:

```python
        "paper_claim_audit_report_json": {},
        "adversarial_audit_report_json": {},
```

- [ ] **Step 6: Add frontend type fields**

In `apps/web/src/lib/api.ts`, extend the `SubmissionPackage` interface:

```ts
export interface SubmissionPackage {
  id: string;
  manuscript_package_id: string;
  venue: string;
  deadline?: string | null;
  submission_dir?: string | null;
  checklist_json?: Record<string, unknown>;
  anonymity_report_json?: Record<string, unknown>;
  compile_report_json?: Record<string, unknown>;
  claim_audit_report_json?: Record<string, unknown>;
  citation_audit_report_json?: Record<string, unknown>;
  artifact_provenance_report_json?: Record<string, unknown>;
  paper_claim_audit_report_json?: Record<string, unknown>;
  adversarial_audit_report_json?: Record<string, unknown>;
  status?: string;
  created_at?: string;
  updated_at?: string;
}
```

- [ ] **Step 7: Run schema and DB tests, then commit**

Run:

```bash
PYTHONPATH=. pytest tests/production/test_production_schemas.py::test_submission_package_has_independent_audit_reports tests/production/test_production_db.py::test_create_submission_package_includes_independent_audit_fields -q
```

Expected: both tests pass.

Commit:

```bash
git add scripts/migration/012_submission_audit_gates.sql libs/schemas/production.py apps/api/db/production.py apps/web/src/lib/api.ts tests/production/test_production_schemas.py tests/production/test_production_db.py
git commit -m "feat: add submission audit report fields"
```

## Task 3: Load Paper-Claim And Adversarial Reports

**Files:**
- Modify: `apps/worker/production/orchestrator.py`
- Test: `tests/production/test_orchestrator.py`

- [ ] **Step 1: Write failing report loader tests**

Append to `tests/production/test_orchestrator.py`:

```python
def test_submission_paper_claim_audit_report_reads_file(tmp_path):
    from apps.worker.production.orchestrator import _submission_paper_claim_audit_report

    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "PAPER_CLAIM_AUDIT.json").write_text(
        '{"passed": true, "checked_claims": 3, "blockers": []}',
        encoding="utf-8",
    )

    report = _submission_paper_claim_audit_report(paper_dir)

    assert report["passed"] is True
    assert report["checked_claims"] == 3


def test_submission_adversarial_audit_report_missing_blocks(tmp_path):
    from apps.worker.production.orchestrator import _submission_adversarial_audit_report

    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()

    report = _submission_adversarial_audit_report(paper_dir)

    assert report["passed"] is False
    assert report["missing"] is True
    assert report["required_file"] == "KILL_ARGUMENT.json"
```

Run:

```bash
PYTHONPATH=. pytest tests/production/test_orchestrator.py::test_submission_paper_claim_audit_report_reads_file tests/production/test_orchestrator.py::test_submission_adversarial_audit_report_missing_blocks -q
```

Expected: fails because the helper functions do not exist.

- [ ] **Step 2: Add JSON report loader**

In `apps/worker/production/orchestrator.py`, add near the existing submission report helpers:

```python
def _load_submission_json_report(
    paper_dir: Path | None,
    filename: str,
    *,
    report_name: str,
) -> dict[str, Any]:
    if paper_dir is None:
        return {
            "passed": False,
            "missing": True,
            "required_file": filename,
            "blockers": [f"{report_name} cannot run because paper_dir is unavailable."],
        }
    report_path = paper_dir / filename
    if not report_path.exists():
        return {
            "passed": False,
            "missing": True,
            "required_file": filename,
            "blockers": [f"{filename} is required before submission can be ready."],
        }
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "passed": False,
            "missing": False,
            "required_file": filename,
            "blockers": [f"{filename} is not valid JSON: {exc.msg}"],
        }
    if not isinstance(payload, dict):
        return {
            "passed": False,
            "missing": False,
            "required_file": filename,
            "blockers": [f"{filename} must contain a JSON object."],
        }
    blockers = payload.get("blockers", [])
    if not isinstance(blockers, list):
        blockers = ["blockers must be a list."]
    return {
        "passed": bool(payload.get("passed")) and not blockers,
        "missing": False,
        "required_file": filename,
        **payload,
        "blockers": blockers,
    }
```

Add the two report helpers:

```python
def _submission_paper_claim_audit_report(paper_dir: Path | None) -> dict[str, Any]:
    return _load_submission_json_report(
        paper_dir,
        "PAPER_CLAIM_AUDIT.json",
        report_name="paper-claim audit",
    )


def _submission_adversarial_audit_report(paper_dir: Path | None) -> dict[str, Any]:
    return _load_submission_json_report(
        paper_dir,
        "KILL_ARGUMENT.json",
        report_name="adversarial audit",
    )
```

- [ ] **Step 3: Run report loader tests and commit**

Run:

```bash
PYTHONPATH=. pytest tests/production/test_orchestrator.py::test_submission_paper_claim_audit_report_reads_file tests/production/test_orchestrator.py::test_submission_adversarial_audit_report_missing_blocks -q
```

Expected: tests pass.

Commit:

```bash
git add apps/worker/production/orchestrator.py tests/production/test_orchestrator.py
git commit -m "feat: load submission audit reports"
```

## Task 4: Queue Audit Tasks Before Revision Tasks

**Files:**
- Modify: `apps/worker/production/orchestrator.py`
- Test: `tests/production/test_orchestrator.py`

- [ ] **Step 1: Write failing queue test**

Append to `tests/production/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_submission_gate_queues_audit_task_when_audit_reports_are_missing(tmp_path, monkeypatch):
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb(tmp_path)
    fake_db.claim_ledger = [
        {
            "id": "claim-1",
            "statement": "The method improves citation reliability.",
            "status": "supported",
            "evidence_json": [{"type": "experiment", "ref": "table-1"}],
        }
    ]
    monkeypatch.setattr(orchestrator, "db", fake_db)

    submission_id = fake_db.submission_package["id"]

    result = await orchestrator.gate_submission_package(submission_id)

    assert result["status"] == "gated"
    assert fake_db.submission_updates[-1]["paper_claim_audit_report_json"]["missing"] is True
    assert fake_db.submission_updates[-1]["adversarial_audit_report_json"]["missing"] is True
    assert fake_db.created_coding_tasks[-1]["metadata_json"]["stage"] == "submission_audit"
    assert "PAPER_CLAIM_AUDIT.json" in fake_db.created_coding_tasks[-1]["user_prompt"]
    assert "KILL_ARGUMENT.json" in fake_db.created_coding_tasks[-1]["user_prompt"]
```

Run:

```bash
PYTHONPATH=. pytest tests/production/test_orchestrator.py::test_submission_gate_queues_audit_task_when_audit_reports_are_missing -q
```

Expected: fails because missing audit reports do not affect gate status or task creation.

- [ ] **Step 2: Add missing-audit detector**

In `apps/worker/production/orchestrator.py`, add:

```python
def _has_missing_audit_report(reports: dict[str, Any]) -> bool:
    return bool(
        reports.get("paper_claim_audit_report_json", {}).get("missing")
        or reports.get("adversarial_audit_report_json", {}).get("missing")
    )
```

- [ ] **Step 3: Add audit task queue function**

Add near `_queue_submission_revision_task()`:

```python
async def _queue_submission_audit_task(
    *,
    submission: dict[str, Any],
    manuscript: dict[str, Any],
    reports: dict[str, Any],
) -> dict[str, Any] | None:
    if await _has_active_stage_task(
        project_id=manuscript["project_id"],
        stage="submission_audit",
        submission_id=str(submission["id"]),
    ):
        return None
    project = await db.get_project(manuscript["project_id"])
    if project is None:
        return None
    paper_dir = _paper_dir(manuscript, resolve_project_workspace_path(project))
    if paper_dir is None:
        return None
    missing_files = [
        report.get("required_file")
        for report in (
            reports.get("paper_claim_audit_report_json", {}),
            reports.get("adversarial_audit_report_json", {}),
        )
        if report.get("missing") and report.get("required_file")
    ]
    prompt = (
        "Create the missing independent submission audit reports for Research OS.\\n"
        f"Venue: {submission.get('venue')}.\\n"
        f"Missing report files: {json.dumps(missing_files, indent=2)}\\n"
        "Read paper.md, references, claim ledger exports, experiment artifacts, and local report files in this directory.\\n"
        "Write PAPER_CLAIM_AUDIT.json when requested with keys passed, checked_claims, unsupported_claims, blockers, and notes.\\n"
        "Write KILL_ARGUMENT.json when requested with keys passed, strongest_rejection_argument, required_rebuttal, blockers, and notes.\\n"
        "Set passed to false and include blockers when the paper cannot withstand the audit."
    )
    return await create_coding_task(
        {
            "project_id": manuscript["project_id"],
            "provider": "codex",
            "workspace_path": str(paper_dir),
            "thread_name": f"submission-audit-{submission['id']}",
            "system_prompt": "You are the independent submission audit agent for Research OS.",
            "user_prompt": prompt,
            "metadata_json": {
                "stage": "submission_audit",
                "submission_id": str(submission["id"]),
                "manuscript_id": str(manuscript["id"]),
                "reports": reports,
            },
            "status": "queued",
        }
    )
```

- [ ] **Step 4: Update gate logic**

In `gate_submission_package()`, after `workspace_root` is defined, add:

```python
    paper_dir = _paper_dir(manuscript, workspace_root)
```

After `provenance_report` is built, add:

```python
    paper_claim_audit_report = _submission_paper_claim_audit_report(paper_dir)
    adversarial_audit_report = _submission_adversarial_audit_report(paper_dir)
```

Update `blocker_count`:

```python
    blocker_count = (
        len(audit["blockers"])
        + len(checklist_report["missing_required_files"])
        + (0 if compile_report["passed"] else 1)
        + (0 if anonymity_report["passed"] else 1)
        + (0 if citation_report["passed"] else 1)
        + (0 if provenance_report["passed"] else 1)
        + (0 if paper_claim_audit_report["passed"] else 1)
        + (0 if adversarial_audit_report["passed"] else 1)
    )
```

Update `reports`:

```python
    reports = {
        "claim_audit_report_json": audit,
        "checklist_json": checklist_report,
        "compile_report_json": compile_report,
        "anonymity_report_json": anonymity_report,
        "citation_audit_report_json": citation_report,
        "artifact_provenance_report_json": provenance_report,
        "paper_claim_audit_report_json": paper_claim_audit_report,
        "adversarial_audit_report_json": adversarial_audit_report,
    }
```

Replace the final queue block with:

```python
    if next_status != "ready":
        if _has_missing_audit_report(reports):
            await _queue_submission_audit_task(
                submission=row or {**submission, "status": next_status},
                manuscript=manuscript,
                reports=reports,
            )
        else:
            await _queue_submission_revision_task(
                submission=row or {**submission, "status": next_status},
                manuscript=manuscript,
                reports=reports,
            )
```

- [ ] **Step 5: Run queue test and commit**

Run:

```bash
PYTHONPATH=. pytest tests/production/test_orchestrator.py::test_submission_gate_queues_audit_task_when_audit_reports_are_missing -q
```

Expected: test passes.

Commit:

```bash
git add apps/worker/production/orchestrator.py tests/production/test_orchestrator.py
git commit -m "feat: queue submission audits before revisions"
```

## Task 5: Pass Gate When Audit Files Pass

**Files:**
- Modify: `tests/production/test_orchestrator.py`

- [ ] **Step 1: Write gate pass test**

Append to `tests/production/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_submission_gate_ready_when_independent_audits_pass(tmp_path, monkeypatch):
    from apps.worker.production import orchestrator

    fake_db = FakeProductionDb(tmp_path)
    fake_db.claim_ledger = [
        {
            "id": "claim-1",
            "statement": "The method improves citation reliability.",
            "status": "supported",
            "evidence_json": [{"type": "experiment", "ref": "table-1"}],
        }
    ]
    paper_dir = fake_db.paper_dir
    (paper_dir / "PAPER_CLAIM_AUDIT.json").write_text(
        '{"passed": true, "checked_claims": 1, "unsupported_claims": [], "blockers": []}',
        encoding="utf-8",
    )
    (paper_dir / "KILL_ARGUMENT.json").write_text(
        '{"passed": true, "strongest_rejection_argument": "No fatal issue found.", "required_rebuttal": [], "blockers": []}',
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestrator, "db", fake_db)

    result = await orchestrator.gate_submission_package(fake_db.submission_package["id"])

    assert result["status"] == "ready"
    assert fake_db.submission_updates[-1]["paper_claim_audit_report_json"]["passed"] is True
    assert fake_db.submission_updates[-1]["adversarial_audit_report_json"]["passed"] is True
    assert fake_db.created_coding_tasks == []
```

Run:

```bash
PYTHONPATH=. pytest tests/production/test_orchestrator.py::test_submission_gate_ready_when_independent_audits_pass -q
```

Expected: test passes if Task 4 is correct.

- [ ] **Step 2: Commit passing test**

Commit:

```bash
git add tests/production/test_orchestrator.py
git commit -m "test: require passing submission audit files"
```

## Task 6: Regate After Audit Task Completion

**Files:**
- Modify: `apps/worker/production/orchestrator.py`
- Test: `tests/production/test_orchestrator.py`

- [ ] **Step 1: Write failing regate test**

Append to `tests/production/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_submission_audit_task_reruns_submission_gate_after_completion(monkeypatch):
    from apps.worker.production import orchestrator

    called = []

    async def fake_gate_submission_package(submission_id):
        called.append(str(submission_id))
        return {"id": submission_id, "status": "gated"}

    monkeypatch.setattr(orchestrator, "gate_submission_package", fake_gate_submission_package)

    await orchestrator._maybe_regate_submission_after_coding_task({
        "status": "completed",
        "metadata_json": {
            "stage": "submission_audit",
            "submission_id": "00000000-0000-0000-0000-000000000001",
        },
    })

    assert called == ["00000000-0000-0000-0000-000000000001"]
```

Run:

```bash
PYTHONPATH=. pytest tests/production/test_orchestrator.py::test_submission_audit_task_reruns_submission_gate_after_completion -q
```

Expected: fails because `_maybe_regate_submission_after_coding_task()` only accepts `submission_revision`.

- [ ] **Step 2: Extend regate stage filter**

In `_maybe_regate_submission_after_coding_task()`, replace:

```python
    if metadata.get("stage") != "submission_revision":
        return
```

with:

```python
    if metadata.get("stage") not in {"submission_revision", "submission_audit"}:
        return
```

- [ ] **Step 3: Run regate test and commit**

Run:

```bash
PYTHONPATH=. pytest tests/production/test_orchestrator.py::test_submission_audit_task_reruns_submission_gate_after_completion -q
```

Expected: test passes.

Commit:

```bash
git add apps/worker/production/orchestrator.py tests/production/test_orchestrator.py
git commit -m "feat: regate after submission audit tasks"
```

## Task 7: Final Verification And Branch Handoff

- [ ] **Step 1: Run production suite**

Run:

```bash
PYTHONPATH=. pytest tests/production/test_production_db.py tests/production/test_production_schemas.py tests/production/test_orchestrator.py -q
```

Expected: all selected production tests pass.

- [ ] **Step 2: Run diff check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Show branch state**

Run:

```bash
git status --short
git log --oneline main..HEAD
```

Expected: working tree is clean and the branch contains the commits from this plan.

