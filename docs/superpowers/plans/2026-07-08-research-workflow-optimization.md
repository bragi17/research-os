# Research Workflow Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Divergent terminal, add full-results scroll navigation, and expose full artifact card CRUD on the work page.

**Architecture:** Keep the existing work page as the phase workspace. Extend `ArtifactCardDeck` for card CRUD, make `PhaseRunPanel` render optional next actions, and add a shared `ResultPageNav` component for the long result pages.

**Tech Stack:** Next.js App Router, React client components, Tailwind utility classes, existing Python static tests with `pytest`.

---

### Task 1: Static Tests For Workflow And Result Navigation

**Files:**
- Modify: `tests/test_web_work_page_static.py`
- Modify: `tests/test_web_run_page_static.py`
- Modify: `tests/test_web_frontier_page_static.py`

- [ ] **Step 1: Write failing tests**

Add assertions that require:

```python
# tests/test_web_work_page_static.py
assert "export interface ArtifactCardCreate" in source
assert "export const createArtifactCard" in source
assert "Validate selected ideas with Frontier" not in source
assert "executionKind: \"validation\"" not in source
assert "nextActionLabel(phase)" in source
assert "nextAction &&" in source
assert "Delete" in source
assert "Payload JSON" in source
assert "createArtifactCard" in source
```

Add assertions that require:

```python
# tests/test_web_run_page_static.py
for path in (ATLAS_PAGE, FRONTIER_PAGE, DIVERGENT_PAGE):
    source = path.read_text()
    assert "ResultPageNav" in source
    assert "BottomBackToRun" in source
    assert source.count("Back to run") >= 2
```

Add assertions that require:

```python
# tests/test_web_frontier_page_static.py
assert "ResultPageNav" in source
assert "BottomBackToRun" in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_web_work_page_static.py tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py -q
```

Expected: FAIL because create-card helper, optional next action, result navigation, and bottom Back to run are not implemented yet.

### Task 2: API Helper And Terminal Divergent Action

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/app/works/[id]/page.tsx`
- Modify: `apps/web/src/components/work/PhaseRunPanel.tsx`

- [ ] **Step 1: Implement create-card helper**

Add `ArtifactCardCreate` beside the existing `ArtifactCardPatch` type:

```typescript
export interface ArtifactCardCreate {
  phase: ResearchPhase;
  artifact_type: string;
  title: string;
  body?: string | null;
  payload?: Record<string, unknown>;
  source_execution_id?: string | null;
  source_card_ids?: string[];
}
```

Add:

```typescript
export const createArtifactCard = (workId: string, data: ArtifactCardCreate) =>
  apiFetch<ArtifactCard>(`/api/v1/works/${workId}/artifact-cards`, {
    method: "POST",
    body: JSON.stringify(data),
  });
```

- [ ] **Step 2: Make next action optional**

Change `nextPhaseTarget` to return `null` for Divergent:

```typescript
function nextPhaseTarget(phase: ResearchPhase): { phase: ResearchPhase } | null {
  if (phase === "atlas") return { phase: "frontier" };
  if (phase === "frontier") return { phase: "divergent" };
  return null;
}
```

Guard `runNextPhase`:

```typescript
const target = nextPhaseTarget(activePhase);
if (!target) return;
```

Pass a nullable next label to `PhaseRunPanel`.

- [ ] **Step 3: Update `PhaseRunPanel`**

Make `nextActionLabel` return `string | null`, and render the next button only when the label exists:

```tsx
const nextAction = nextActionLabel(phase);
...
{nextAction && (
  <button type="button" ...>
    {nextAction}
  </button>
)}
```

- [ ] **Step 4: Run tests to verify this slice passes**

Run:

```bash
pytest tests/test_web_work_page_static.py -q
```

Expected: PASS for workflow/API assertions that were just implemented.

### Task 3: Artifact Card CRUD UI

**Files:**
- Modify: `apps/web/src/components/work/ArtifactCardDeck.tsx`
- Modify: `apps/web/src/app/works/[id]/page.tsx`

- [ ] **Step 1: Add active phase prop**

Pass `phase={activePhase}` from the work page to `ArtifactCardDeck`.

- [ ] **Step 2: Add form state and JSON helpers**

Extend card drafts to include:

```typescript
interface CardDraft {
  title: string;
  body: string;
  artifact_type: string;
  payloadJson: string;
}
```

Add helpers:

```typescript
function defaultArtifactType(phase: ResearchPhase): string { ... }
function formatPayload(payload: Record<string, unknown>): string { ... }
function parsePayloadJson(value: string): Record<string, unknown> { ... }
```

- [ ] **Step 3: Implement add/edit/delete**

Use `createArtifactCard` for add. Use `updateArtifactCard` for save and soft delete:

```typescript
await updateArtifactCard(workId, card.id, { status: "deleted" });
```

Invalid JSON sets an inline error and does not call the API.

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_web_work_page_static.py -q
```

Expected: PASS for card CRUD static assertions.

### Task 4: Shared Result Page Navigation

**Files:**
- Create: `apps/web/src/components/ResultPageNav.tsx`
- Modify: `apps/web/src/app/runs/[id]/atlas/page.tsx`
- Modify: `apps/web/src/app/runs/[id]/frontier/page.tsx`
- Modify: `apps/web/src/app/runs/[id]/divergent/page.tsx`

- [ ] **Step 1: Create `ResultPageNav`**

Implement scroll buttons:

```tsx
export default function ResultPageNav() {
  const scrollToTop = () => window.scrollTo({ top: 0, behavior: "smooth" });
  const scrollToBottom = () => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  return (...);
}
```

- [ ] **Step 2: Add bottom Back to run helper**

In each result page, add:

```tsx
function BottomBackToRun({ runId }: { runId: string }) {
  return (
    <div className="border-t border-[var(--border-subtle)] pt-4">
      <Link href={`/runs/${runId}`} className="inline-flex ...">
        Back to run
      </Link>
    </div>
  );
}
```

- [ ] **Step 3: Render navigation and bottom link**

Import `ResultPageNav`, render `<ResultPageNav />` near the top of the returned content, and render `<BottomBackToRun runId={runId} />` after the final content block.

- [ ] **Step 4: Run result-page tests**

Run:

```bash
pytest tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py -q
```

Expected: PASS.

### Task 5: Full Verification

**Files:**
- All files changed above.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_web_work_page_static.py tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend lint or type check if available**

Run:

```bash
cd apps/web && npm run lint
```

Expected: PASS, or report if the project has no lint script or missing dependencies.

- [ ] **Step 3: Review diff**

Run:

```bash
git diff --stat
git diff -- apps/web/src/lib/api.ts apps/web/src/app/works/[id]/page.tsx apps/web/src/components/work/PhaseRunPanel.tsx apps/web/src/components/work/ArtifactCardDeck.tsx apps/web/src/components/ResultPageNav.tsx apps/web/src/app/runs/[id]/atlas/page.tsx apps/web/src/app/runs/[id]/frontier/page.tsx apps/web/src/app/runs/[id]/divergent/page.tsx
```

Expected: Changes match the approved spec and no unrelated files are modified.
