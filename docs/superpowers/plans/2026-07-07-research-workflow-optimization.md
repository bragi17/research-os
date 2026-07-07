# Research Workflow Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Divergent the terminal research phase, add full-result page scroll navigation, and expose complete artifact card CRUD so edited cards flow into the next phase.

**Architecture:** Keep the existing work page as the three-phase research workbench. Extend the existing API helper and artifact deck UI instead of adding a new workspace. Add one shared result-page navigation component and import it from the three full-result pages.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, Tailwind utility classes, FastAPI-backed REST helpers, pytest static checks.

---

## File Structure

- Modify `apps/web/src/app/works/[id]/page.tsx`: remove Divergent-to-Frontier validation from next-phase behavior, pass the active phase into the artifact deck, and only provide a next action when the active phase is Atlas or Frontier.
- Modify `apps/web/src/components/work/PhaseRunPanel.tsx`: support an optional next action and render no next button for Divergent.
- Modify `apps/web/src/lib/api.ts`: add the frontend `ArtifactCardCreate` type and `createArtifactCard` helper.
- Modify `apps/web/src/components/work/ArtifactCardDeck.tsx`: add create, update, payload JSON, soft delete, and selection UI for cards in the active phase.
- Create `apps/web/src/components/ResultPageNav.tsx`: shared top/bottom scroll controls using `lucide-react`.
- Modify `apps/web/src/app/runs/[id]/atlas/page.tsx`: render `ResultPageNav` and a bottom Back to run link.
- Modify `apps/web/src/app/runs/[id]/frontier/page.tsx`: render `ResultPageNav` and a bottom Back to run link.
- Modify `apps/web/src/app/runs/[id]/divergent/page.tsx`: render `ResultPageNav` and a bottom Back to run link.
- Modify `tests/test_web_work_page_static.py`: static coverage for terminal Divergent behavior and card CRUD UI.
- Modify `tests/test_web_run_page_static.py`: static coverage for shared result navigation and bottom Back to run links.

## Task 1: Make Divergent Terminal on the Work Page

**Files:**
- Modify: `tests/test_web_work_page_static.py`
- Modify: `apps/web/src/components/work/PhaseRunPanel.tsx`
- Modify: `apps/web/src/app/works/[id]/page.tsx`

- [ ] **Step 1: Write the failing static tests**

In `tests/test_web_work_page_static.py`, replace `test_phase_run_panel_has_independent_and_next_phase_actions` with:

```python
def test_phase_run_panel_has_independent_and_next_phase_actions() -> None:
    source = PHASE_RUN_PANEL.read_text()

    assert "Run this phase" in source
    assert "Start Frontier from selected Atlas cards" in source
    assert "Start Divergent from selected gaps" in source
    assert "Validate selected ideas with Frontier" not in source
```

Add this test after `test_phase_run_panel_disables_next_action_without_selection`:

```python
def test_phase_run_panel_renders_next_action_only_when_available() -> None:
    source = PHASE_RUN_PANEL.read_text()

    assert "nextActionLabel(phase)" in source
    assert "nextAction !== null" in source
    assert "onRunNext?" in source
    assert "onRunNext &&" in source
```

Add this test after `test_work_page_next_phase_action_requires_selected_cards`:

```python
def test_work_page_treats_divergent_as_terminal_phase() -> None:
    source = WORK_PAGE.read_text()

    assert 'if (phase === "atlas") return { phase: "frontier" };' in source
    assert 'if (phase === "frontier") return { phase: "divergent" };' in source
    assert 'return null;' in source
    assert 'executionKind: "validation"' not in source
    assert 'activePhase === "divergent" ? undefined : runNextPhase' in source
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest tests/test_web_work_page_static.py::test_phase_run_panel_has_independent_and_next_phase_actions tests/test_web_work_page_static.py::test_phase_run_panel_renders_next_action_only_when_available tests/test_web_work_page_static.py::test_work_page_treats_divergent_as_terminal_phase -q
```

Expected: FAIL because `PhaseRunPanel.tsx` still contains `Validate selected ideas with Frontier`, `onRunNext` is required, and `page.tsx` still maps Divergent to Frontier validation.

- [ ] **Step 3: Implement terminal Divergent behavior**

In `apps/web/src/components/work/PhaseRunPanel.tsx`, update `nextActionLabel` and props to this shape:

```tsx
function nextActionLabel(phase: ResearchPhase): string | null {
  if (phase === "atlas") return "Start Frontier from selected Atlas cards";
  if (phase === "frontier") return "Start Divergent from selected gaps";
  return null;
}
```

Change the prop type so `onRunNext` is optional:

```tsx
  onRunNext?: () => void;
```

Inside the component, replace the next-action constants with:

```tsx
  const nextAction = nextActionLabel(phase);
  const hasNextAction = nextAction !== null && onRunNext !== undefined;
  const nextDisabled = running || selectedCount === 0;
  const nextActionTitle =
    selectedCount === 0 ? "Select cards before starting this action." : nextAction;
  const nextActionAriaLabel =
    selectedCount === 0 && nextAction
      ? `${nextAction} unavailable until cards are selected`
      : nextAction;
```

Wrap the next button so it only renders when present:

```tsx
        {hasNextAction && nextAction && onRunNext && (
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-[13px]"
            onClick={onRunNext}
            disabled={nextDisabled}
            title={nextActionTitle ?? undefined}
            aria-label={nextActionAriaLabel ?? undefined}
          >
            {nextAction}
          </button>
        )}
```

In `apps/web/src/app/works/[id]/page.tsx`, change the helper return type and body:

```tsx
function nextPhaseTarget(phase: ResearchPhase): {
  phase: ResearchPhase;
  executionKind?: StartPhaseExecutionData["execution_kind"];
} | null {
  if (phase === "atlas") return { phase: "frontier" };
  if (phase === "frontier") return { phase: "divergent" };
  return null;
}
```

In `runNextPhase`, guard the nullable target before creating request data:

```tsx
    const target = nextPhaseTarget(activePhase);
    if (!target) {
      setActionError("Divergent is the final research phase.");
      return;
    }

    setRunningAction("next");
    const data: StartPhaseExecutionData = {
      source_card_ids: sourceCardIds,
    };
```

When rendering `PhaseRunPanel`, pass no next handler for Divergent:

```tsx
          onRunNext={activePhase === "divergent" ? undefined : runNextPhase}
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
pytest tests/test_web_work_page_static.py::test_phase_run_panel_has_independent_and_next_phase_actions tests/test_web_work_page_static.py::test_phase_run_panel_renders_next_action_only_when_available tests/test_web_work_page_static.py::test_work_page_treats_divergent_as_terminal_phase -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add tests/test_web_work_page_static.py apps/web/src/components/work/PhaseRunPanel.tsx apps/web/src/app/works/[id]/page.tsx
git commit -m "feat: make divergent terminal in work flow"
```

## Task 2: Add Artifact Card CRUD in the Workbench

**Files:**
- Modify: `tests/test_web_work_page_static.py`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/app/works/[id]/page.tsx`
- Modify: `apps/web/src/components/work/ArtifactCardDeck.tsx`

- [ ] **Step 1: Write the failing static tests**

In `tests/test_web_work_page_static.py`, add `createArtifactCard` and `ArtifactCardCreate` to `test_work_api_types_and_helpers_exist`:

```python
        "export interface ArtifactCardCreate",
        "export const createArtifactCard",
```

Replace `test_artifact_deck_supports_edit_and_selection` with:

```python
def test_artifact_deck_supports_crud_payload_and_selection() -> None:
    source = ARTIFACT_DECK.read_text()

    assert "createArtifactCard" in source
    assert "updateArtifactCard" in source
    assert "Add card" in source
    assert "Edit" in source
    assert "Save" in source
    assert "Delete" in source
    assert "JSON.parse" in source
    assert "Payload JSON" in source
    assert 'status: "deleted"' in source
    assert "selection_state" in source
    assert "Selected" in source
```

In `test_work_page_renders_artifact_deck_with_active_phase_cards`, add:

```python
    assert "phase={activePhase}" in source
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest tests/test_web_work_page_static.py::test_work_api_types_and_helpers_exist tests/test_web_work_page_static.py::test_artifact_deck_supports_crud_payload_and_selection tests/test_web_work_page_static.py::test_work_page_renders_artifact_deck_with_active_phase_cards -q
```

Expected: FAIL because the API helper does not export create support, the artifact deck lacks add/delete/payload controls, and the work page does not pass `phase`.

- [ ] **Step 3: Add create-card API support**

In `apps/web/src/lib/api.ts`, add this interface immediately after `ArtifactCard`:

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

Add this helper between `listArtifactCards` and `updateArtifactCard`:

```typescript
export const createArtifactCard = (workId: string, data: ArtifactCardCreate) =>
  apiFetch<ArtifactCard>(`/api/v1/works/${workId}/artifact-cards`, {
    method: "POST",
    body: JSON.stringify(data),
  });
```

- [ ] **Step 4: Pass active phase into the card deck**

In `apps/web/src/app/works/[id]/page.tsx`, add this prop to `<ArtifactCardDeck />`:

```tsx
          phase={activePhase}
```

- [ ] **Step 5: Extend `ArtifactCardDeck` props and draft model**

In `apps/web/src/components/work/ArtifactCardDeck.tsx`, update imports:

```tsx
import { useState } from "react";
import {
  createArtifactCard,
  updateArtifactCard,
  type ArtifactCard,
  type ArtifactSelectionState,
  type ResearchPhase,
} from "@/lib/api";
```

Update props and draft types:

```tsx
interface ArtifactCardDeckProps {
  workId: string;
  phase: ResearchPhase;
  cards: ArtifactCard[];
  onCardsChanged: () => void | Promise<void>;
  loading?: boolean;
}

interface CardDraft {
  title: string;
  body: string;
  artifactType: string;
  payloadText: string;
}
```

Add these helpers below `badgeClass`:

```tsx
function defaultArtifactType(phase: ResearchPhase): string {
  if (phase === "atlas") return "atlas_direction";
  if (phase === "frontier") return "frontier_gap";
  return "divergent_idea";
}

function formatPayload(payload: Record<string, unknown>): string {
  if (!payload || Object.keys(payload).length === 0) return "";
  return JSON.stringify(payload, null, 2);
}

function parsePayloadJson(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Payload must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function emptyDraft(phase: ResearchPhase): CardDraft {
  return {
    title: "",
    body: "",
    artifactType: defaultArtifactType(phase),
    payloadText: "",
  };
}
```

- [ ] **Step 6: Implement create, edit, payload save, and soft delete handlers**

In `ArtifactCardDeck`, destructure `phase`:

```tsx
export default function ArtifactCardDeck({
  workId,
  phase,
  cards,
  onCardsChanged,
  loading = false,
}: ArtifactCardDeckProps) {
```

Add state near the existing state:

```tsx
  const [newDraft, setNewDraft] = useState<CardDraft | null>(null);
  const [creating, setCreating] = useState(false);
  const [deckError, setDeckError] = useState<string | null>(null);
```

Update `startEditing` to include payload and artifact type:

```tsx
  const startEditing = (card: ArtifactCard) => {
    setDraftsByCard((previous) => ({
      ...previous,
      [card.id]: {
        title: card.title,
        body: card.body ?? "",
        artifactType: card.artifact_type,
        payloadText: formatPayload(card.payload),
      },
    }));
    setCardError(card.id, null);
  };
```

Add a helper for new draft changes:

```tsx
  const updateNewDraft = (patch: Partial<CardDraft>) => {
    setNewDraft((previous) => ({
      ...(previous ?? emptyDraft(phase)),
      ...patch,
    }));
  };
```

Update `saveCard` so it validates title, artifact type, and payload:

```tsx
    const artifactType = draft.artifactType.trim();
    if (!artifactType) {
      setCardError(card.id, "Artifact type is required.");
      return;
    }

    let payload: Record<string, unknown>;
    try {
      payload = parsePayloadJson(draft.payloadText);
    } catch (error) {
      setCardError(
        card.id,
        error instanceof Error ? error.message : "Payload must be valid JSON.",
      );
      return;
    }
```

Then call:

```tsx
      await updateArtifactCard(workId, card.id, { title, body, payload });
```

Do not patch `artifact_type` because the backend patch schema does not support changing type. Keep `artifactType` visible in edit mode for created cards only; for existing cards, render it as a disabled input or omit editing it.

Add `createCard`:

```tsx
  const createCard = async () => {
    const draft = newDraft ?? emptyDraft(phase);
    const title = draft.title.trim();
    const artifactType = draft.artifactType.trim();
    if (!title) {
      setDeckError("Title is required.");
      return;
    }
    if (!artifactType) {
      setDeckError("Artifact type is required.");
      return;
    }

    let payload: Record<string, unknown>;
    try {
      payload = parsePayloadJson(draft.payloadText);
    } catch (error) {
      setDeckError(error instanceof Error ? error.message : "Payload must be valid JSON.");
      return;
    }

    setCreating(true);
    setDeckError(null);
    try {
      await createArtifactCard(workId, {
        phase,
        artifact_type: artifactType,
        title,
        body: draft.body.trim() || null,
        payload,
      });
      setNewDraft(null);
      await onCardsChanged();
    } catch (error) {
      console.error(error);
      setDeckError(error instanceof Error ? error.message : "Failed to create card.");
    } finally {
      setCreating(false);
    }
  };
```

Add `deleteCard`:

```tsx
  const deleteCard = async (card: ArtifactCard) => {
    if (!confirm(`Delete "${card.title}"?`)) return;
    setCardSaving(card.id, true);
    setCardError(card.id, null);
    try {
      await updateArtifactCard(workId, card.id, { status: "deleted" });
      await onCardsChanged();
    } catch (error) {
      console.error(error);
      setCardError(
        card.id,
        error instanceof Error ? error.message : "Failed to delete card.",
      );
    } finally {
      setCardSaving(card.id, false);
    }
  };
```

- [ ] **Step 7: Add the create form and card controls**

In the deck header right side, add:

```tsx
        <button
          type="button"
          className="btn-secondary px-3 py-1.5 text-[12px]"
          onClick={() => {
            setNewDraft(emptyDraft(phase));
            setDeckError(null);
          }}
          disabled={loading || creating}
        >
          Add card
        </button>
```

Render this form before the card list when `newDraft` is set:

```tsx
      {newDraft && (
        <div className="mb-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-secondary)]/50 p-3">
          <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_180px]">
            <input
              className="input-field h-9 text-[13px] font-medium"
              value={newDraft.title}
              onChange={(event) => updateNewDraft({ title: event.target.value })}
              disabled={creating}
              placeholder="Card title"
              aria-label="New card title"
            />
            <input
              className="input-field h-9 text-[12px]"
              value={newDraft.artifactType}
              onChange={(event) => updateNewDraft({ artifactType: event.target.value })}
              disabled={creating}
              aria-label="New card artifact type"
            />
          </div>
          <textarea
            className="input-field mt-2 min-h-[88px] resize-y py-2 text-[12px] leading-5"
            value={newDraft.body}
            onChange={(event) => updateNewDraft({ body: event.target.value })}
            disabled={creating}
            placeholder="Card body"
            aria-label="New card body"
          />
          <textarea
            className="input-field mt-2 min-h-[96px] resize-y py-2 font-mono text-[11px] leading-5"
            value={newDraft.payloadText}
            onChange={(event) => updateNewDraft({ payloadText: event.target.value })}
            disabled={creating}
            placeholder='Payload JSON, for example {"significance":"high"}'
            aria-label="Payload JSON"
          />
          {deckError && <p className="mt-2 text-[12px] text-[var(--accent-red)]">{deckError}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary px-3 py-1.5 text-[12px]"
              onClick={() => void createCard()}
              disabled={creating}
            >
              {creating ? "Creating..." : "Create card"}
            </button>
            <button
              type="button"
              className="btn-secondary px-3 py-1.5 text-[12px]"
              onClick={() => {
                setNewDraft(null);
                setDeckError(null);
              }}
              disabled={creating}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
```

In edit mode, add the payload textarea below the body textarea:

```tsx
                        <textarea
                          className="input-field min-h-[104px] resize-y py-2 font-mono text-[11px] leading-5"
                          value={draft.payloadText}
                          onChange={(event) =>
                            updateDraft(card.id, { payloadText: event.target.value })
                          }
                          disabled={isSaving}
                          aria-label="Payload JSON"
                        />
```

In read mode, add a compact payload preview when payload is not empty:

```tsx
                        {Object.keys(card.payload ?? {}).length > 0 && (
                          <pre className="mt-2 max-h-[120px] overflow-auto rounded-md border border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-3 py-2 font-mono text-[11px] leading-5 text-[var(--text-muted)]">
                            {formatPayload(card.payload)}
                          </pre>
                        )}
```

In the non-editing action area, render Delete next to Edit:

```tsx
                      <>
                        <button
                          type="button"
                          className="btn-secondary px-3 py-1.5 text-[12px]"
                          onClick={() => startEditing(card)}
                          disabled={isSaving}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-3 py-1.5 text-[12px] text-[var(--accent-red)]"
                          onClick={() => void deleteCard(card)}
                          disabled={isSaving}
                        >
                          Delete
                        </button>
                      </>
```

- [ ] **Step 8: Run the focused tests and verify GREEN**

Run:

```bash
pytest tests/test_web_work_page_static.py::test_work_api_types_and_helpers_exist tests/test_web_work_page_static.py::test_artifact_deck_supports_crud_payload_and_selection tests/test_web_work_page_static.py::test_work_page_renders_artifact_deck_with_active_phase_cards -q
```

Expected: PASS.

- [ ] **Step 9: Run the web production build**

Run:

```bash
cd apps/web && npm run build
```

Expected: PASS with no TypeScript or build errors.

- [ ] **Step 10: Commit Task 2**

Run:

```bash
git add tests/test_web_work_page_static.py apps/web/src/lib/api.ts apps/web/src/app/works/[id]/page.tsx apps/web/src/components/work/ArtifactCardDeck.tsx
git commit -m "feat: add artifact card crud controls"
```

## Task 3: Add Result Page Top/Bottom Navigation

**Files:**
- Modify: `tests/test_web_run_page_static.py`
- Create: `apps/web/src/components/ResultPageNav.tsx`
- Modify: `apps/web/src/app/runs/[id]/atlas/page.tsx`
- Modify: `apps/web/src/app/runs/[id]/frontier/page.tsx`
- Modify: `apps/web/src/app/runs/[id]/divergent/page.tsx`

- [ ] **Step 1: Write the failing static tests**

In `tests/test_web_run_page_static.py`, add:

```python
ATLAS_PAGE = Path("apps/web/src/app/runs/[id]/atlas/page.tsx")
FRONTIER_PAGE = Path("apps/web/src/app/runs/[id]/frontier/page.tsx")
RESULT_PAGE_NAV = Path("apps/web/src/components/ResultPageNav.tsx")
```

Add these tests after `test_run_results_paper_list_is_collapsible_and_closed_by_default`:

```python
def test_result_page_nav_component_has_scroll_controls() -> None:
    source = RESULT_PAGE_NAV.read_text()

    assert "export default function ResultPageNav" in source
    assert "scrollTo({ top: 0" in source
    assert "document.documentElement.scrollHeight" in source
    assert "ArrowUp" in source
    assert "ArrowDown" in source
    assert "Back to top" in source
    assert "Go to bottom" in source


def test_full_result_pages_render_scroll_nav_and_bottom_back_link() -> None:
    for path in (ATLAS_PAGE, FRONTIER_PAGE, DIVERGENT_PAGE):
        source = path.read_text()

        assert 'import ResultPageNav from "@/components/ResultPageNav"' in source
        assert "<ResultPageNav />" in source
        assert source.count("Back to run") >= 2
        assert "border-t border-[var(--border-subtle)]" in source
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest tests/test_web_run_page_static.py::test_result_page_nav_component_has_scroll_controls tests/test_web_run_page_static.py::test_full_result_pages_render_scroll_nav_and_bottom_back_link -q
```

Expected: FAIL because `ResultPageNav.tsx` does not exist and the result pages do not import it.

- [ ] **Step 3: Create the shared result-page navigation component**

Create `apps/web/src/components/ResultPageNav.tsx`:

```tsx
"use client";

import { ArrowDown, ArrowUp } from "lucide-react";

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function scrollToBottom() {
  window.scrollTo({
    top: document.documentElement.scrollHeight,
    behavior: "smooth",
  });
}

export default function ResultPageNav() {
  return (
    <div className="fixed bottom-5 right-5 z-30 flex flex-col gap-2 md:bottom-auto md:top-1/2 md:-translate-y-1/2">
      <button
        type="button"
        onClick={scrollToTop}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)]/95 text-[var(--text-muted)] shadow-sm backdrop-blur transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"
        aria-label="Back to top"
        title="Back to top"
      >
        <ArrowUp size={15} strokeWidth={1.8} />
      </button>
      <button
        type="button"
        onClick={scrollToBottom}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)]/95 text-[var(--text-muted)] shadow-sm backdrop-blur transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"
        aria-label="Go to bottom"
        title="Go to bottom"
      >
        <ArrowDown size={15} strokeWidth={1.8} />
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Import and render `ResultPageNav` in all full result pages**

In each of these files:

- `apps/web/src/app/runs/[id]/atlas/page.tsx`
- `apps/web/src/app/runs/[id]/frontier/page.tsx`
- `apps/web/src/app/runs/[id]/divergent/page.tsx`

Add:

```tsx
import ResultPageNav from "@/components/ResultPageNav";
```

Render it as the first child inside the top-level returned container:

```tsx
      <ResultPageNav />
```

- [ ] **Step 5: Add bottom Back to run links**

In each full result page, add this block near the bottom, before the closing top-level `</div>`:

```tsx
      <div className="flex justify-center border-t border-[var(--border-subtle)] pt-5">
        <Link
          href={`/runs/${runId}`}
          className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path
              d="M9 11L5 7L9 3"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Back to run
        </Link>
      </div>
```

For Atlas, place this block after the "Deep dive into this direction" CTA. For Frontier, place this block after the topic work CTA. For Divergent, place this block after the topic work CTA.

- [ ] **Step 6: Run the focused tests and verify GREEN**

Run:

```bash
pytest tests/test_web_run_page_static.py::test_result_page_nav_component_has_scroll_controls tests/test_web_run_page_static.py::test_full_result_pages_render_scroll_nav_and_bottom_back_link -q
```

Expected: PASS.

- [ ] **Step 7: Run the web production build**

Run:

```bash
cd apps/web && npm run build
```

Expected: PASS with no TypeScript or build errors.

- [ ] **Step 8: Commit Task 3**

Run:

```bash
git add tests/test_web_run_page_static.py apps/web/src/components/ResultPageNav.tsx apps/web/src/app/runs/[id]/atlas/page.tsx apps/web/src/app/runs/[id]/frontier/page.tsx apps/web/src/app/runs/[id]/divergent/page.tsx
git commit -m "feat: add result page scroll navigation"
```

## Task 4: Final Integration Verification

**Files:**
- Modify only if verification exposes a defect in files touched by Tasks 1-3.

- [ ] **Step 1: Run the relevant static test suite**

Run:

```bash
pytest tests/test_web_work_page_static.py tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py -q
```

Expected: PASS.

- [ ] **Step 2: Run backend work phase API tests**

Run:

```bash
pytest tests/test_work_phase_api.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the web production build**

Run:

```bash
cd apps/web && npm run build
```

Expected: PASS.

- [ ] **Step 4: Inspect git history and status**

Run:

```bash
git log --oneline -5
git status --short
```

Expected: latest commits include the three feature commits, and `git status --short` is empty.

- [ ] **Step 5: Commit any verification-only fixes**

If Step 1, Step 2, or Step 3 required fixes, commit only those fixes:

```bash
git add <fixed-files>
git commit -m "fix: stabilize research workflow optimization"
```

If no fixes were needed, do not create an empty commit.
