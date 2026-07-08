# Research Workflow Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Divergent the terminal research phase, add full-result page navigation, and expose full artifact-card CRUD so edited cards become the source for downstream phase execution.

**Architecture:** Keep the existing work-phase model. The work page owns phase execution and selected card IDs, `ArtifactCardDeck` owns card CRUD UI, `api.ts` owns frontend work API helpers, and full result pages share small navigation/editable-card components. Use soft delete through the existing `status: "deleted"` patch path so backend revision and filtering behavior stays intact.

**Tech Stack:** Next.js 15 App Router, React 19 client components, TypeScript, Tailwind utility classes, lucide-react icons, existing FastAPI work routes, pytest static web tests.

---

## Workspace Note

At plan creation time, the worktree already contains uncommitted changes in the files named below, including `ResultPageNav.tsx` and `RunArtifactCardsPanel.tsx`. Treat those as user/workspace changes. Do not revert them. During execution, inspect the current file before editing and apply only the missing pieces from each task.

## File Structure

- `apps/web/src/app/works/[id]/page.tsx`: phase state, selected card IDs, current phase execution, next phase execution.
- `apps/web/src/components/work/PhaseRunPanel.tsx`: current-phase action and optional next-phase action.
- `apps/web/src/lib/api.ts`: `ArtifactCardCreate` type and `createArtifactCard` helper.
- `apps/web/src/components/work/ArtifactCardDeck.tsx`: add/edit/delete/select card UI for a single work phase.
- `apps/web/src/components/work/RunArtifactCardsPanel.tsx`: bridge from a run result page to work artifact cards when the run has `work_id`.
- `apps/web/src/components/ResultPageNav.tsx`: shared scroll-to-top and scroll-to-bottom controls.
- `apps/web/src/app/runs/[id]/atlas/page.tsx`: Atlas full result page imports shared result controls and editable cards.
- `apps/web/src/app/runs/[id]/frontier/page.tsx`: Frontier full result page imports shared result controls and editable cards.
- `apps/web/src/app/runs/[id]/divergent/page.tsx`: Divergent full result page imports shared result controls and editable cards.
- `tests/test_web_work_page_static.py`: static tests for work API helpers, phase progression, and artifact deck CRUD affordances.
- `tests/test_web_run_page_static.py`: static tests for result-page navigation and editable result cards.
- `tests/test_web_frontier_page_static.py`: Frontier-specific static regression tests.

### Task 1: Make Divergent Terminal

**Files:**
- Modify: `tests/test_web_work_page_static.py`
- Modify: `apps/web/src/app/works/[id]/page.tsx`
- Modify: `apps/web/src/components/work/PhaseRunPanel.tsx`

- [ ] **Step 1: Write the failing static tests**

In `tests/test_web_work_page_static.py`, update `test_phase_run_panel_has_independent_and_next_phase_actions` and `test_work_page_next_phase_action_requires_selected_cards` to assert that Divergent no longer maps back to Frontier validation:

```python
def test_phase_run_panel_has_independent_and_next_phase_actions() -> None:
    source = PHASE_RUN_PANEL.read_text()

    assert "Run this phase" in source
    assert "Start Frontier from selected Atlas cards" in source
    assert "Start Divergent from selected gaps" in source
    assert "Validate selected ideas with Frontier" not in source
    assert "nextActionLabel(phase)" in source
    assert "nextAction &&" in source


def test_work_page_next_phase_action_requires_selected_cards() -> None:
    source = WORK_PAGE.read_text()
    guard_index = source.index("if (sourceCardIds.length === 0)")
    start_index = source.index("startPhaseExecution(workId, target.phase")

    assert guard_index < start_index
    assert "executionKind: \"validation\"" not in source
    assert "target.executionKind" not in source
    assert "if (!target) return;" in source
    assert "setRunningAction(\"next\")" not in source[:guard_index]
    assert "source_card_ids: sourceCardIds" in source
    assert "source_card_ids: selectedCards.map" not in source
    assert "source_card_ids: []" not in source
```

- [ ] **Step 2: Run the targeted tests and verify they fail on the old behavior**

Run:

```bash
pytest tests/test_web_work_page_static.py::test_phase_run_panel_has_independent_and_next_phase_actions tests/test_web_work_page_static.py::test_work_page_next_phase_action_requires_selected_cards -q
```

Expected on the old baseline: FAIL because `Validate selected ideas with Frontier`, `executionKind: "validation"`, or `target.executionKind` is still present.

- [ ] **Step 3: Remove the Divergent next-phase target**

In `apps/web/src/app/works/[id]/page.tsx`, replace `nextPhaseTarget` with:

```tsx
function nextPhaseTarget(phase: ResearchPhase): {
  phase: ResearchPhase;
} | null {
  if (phase === "atlas") return { phase: "frontier" };
  if (phase === "frontier") return { phase: "divergent" };
  return null;
}
```

Then replace the start of `runNextPhase` with:

```tsx
const runNextPhase = async () => {
  setActionError(null);
  const target = nextPhaseTarget(activePhase);
  if (!target) return;

  const sourceCardIds = selectedCards.map((card) => card.id);
  if (sourceCardIds.length === 0) {
    setActionError("Select cards before starting the next phase.");
    return;
  }

  setRunningAction("next");
  const data: StartPhaseExecutionData = {
    source_card_ids: sourceCardIds,
  };
```

Leave the existing `try` block below it, using `target.phase` for `startPhaseExecution`, `rememberWorkPhase`, `setActivePhase`, and `fetchCards`.

- [ ] **Step 4: Make the next action optional in the run panel**

In `apps/web/src/components/work/PhaseRunPanel.tsx`, replace `nextActionLabel` with:

```tsx
function nextActionLabel(phase: ResearchPhase): string | null {
  if (phase === "atlas") return "Start Frontier from selected Atlas cards";
  if (phase === "frontier") return "Start Divergent from selected gaps";
  return null;
}
```

Then compute the optional label and render the next button only when it exists:

```tsx
const nextAction = nextActionLabel(phase);
const nextDisabled = running || selectedCount === 0;
const nextActionTitle =
  selectedCount === 0 ? "Select cards before starting this action." : nextAction ?? "";
const nextActionAriaLabel =
  selectedCount === 0
    ? `${nextAction ?? "Next action"} unavailable until cards are selected`
    : nextAction ?? "Next action";
```

Use this JSX inside the action button group:

```tsx
{nextAction && (
  <button
    type="button"
    className="btn-primary px-3 py-1.5 text-[13px]"
    onClick={onRunNext}
    disabled={nextDisabled}
    title={nextActionTitle}
    aria-label={nextActionAriaLabel}
  >
    {nextAction}
  </button>
)}
```

- [ ] **Step 5: Run the targeted tests and verify they pass**

Run:

```bash
pytest tests/test_web_work_page_static.py::test_phase_run_panel_has_independent_and_next_phase_actions tests/test_web_work_page_static.py::test_work_page_next_phase_action_requires_selected_cards -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add tests/test_web_work_page_static.py apps/web/src/app/works/[id]/page.tsx apps/web/src/components/work/PhaseRunPanel.tsx
git commit -m "feat: make divergent the terminal research phase"
```

### Task 2: Add Artifact Card Create API and CRUD Deck

**Files:**
- Modify: `tests/test_web_work_page_static.py`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/components/work/ArtifactCardDeck.tsx`
- Modify: `apps/web/src/app/works/[id]/page.tsx`

- [ ] **Step 1: Write the failing static tests**

In `tests/test_web_work_page_static.py`, update `test_work_api_types_and_helpers_exist`, `test_artifact_deck_supports_edit_and_selection`, and `test_work_page_renders_artifact_deck_with_active_phase_cards`:

```python
def test_work_api_types_and_helpers_exist() -> None:
    source = API.read_text()

    expected_exports = [
        "export type ResearchPhase",
        "export interface Work",
        "export interface PhaseExecution",
        "export interface ArtifactCard",
        "export const listWorks",
        "export const getWork",
        "export const getWorkPhases",
        "export const listArtifactCards",
        "export interface ArtifactCardCreate",
        "export const createArtifactCard",
        "export const updateArtifactCard",
        "export const startPhaseExecution",
    ]

    for export in expected_exports:
        assert export in source


def test_artifact_deck_supports_edit_and_selection() -> None:
    source = ARTIFACT_DECK.read_text()

    assert "selection_state" in source
    assert "createArtifactCard" in source
    assert "updateArtifactCard" in source
    assert "Add card" in source
    assert "Edit" in source
    assert "Save" in source
    assert "Delete" in source
    assert "Payload JSON" in source
    assert "Selected" in source


def test_work_page_renders_artifact_deck_with_active_phase_cards() -> None:
    source = WORK_PAGE.read_text()

    assert "import ArtifactCardDeck" in source
    assert "<ArtifactCardDeck" in source
    assert "phase={activePhase}" in source
    assert "cards={cards.filter((card) => card.phase === activePhase)}" in source
    assert "onCardsChanged={fetchCardsForActivePhase}" in source
```

- [ ] **Step 2: Run the targeted tests and verify they fail on the old behavior**

Run:

```bash
pytest tests/test_web_work_page_static.py::test_work_api_types_and_helpers_exist tests/test_web_work_page_static.py::test_artifact_deck_supports_edit_and_selection tests/test_web_work_page_static.py::test_work_page_renders_artifact_deck_with_active_phase_cards -q
```

Expected on the old baseline: FAIL because the create helper, phase prop, payload JSON editor, add card button, or delete button is missing.

- [ ] **Step 3: Add the create-card API type and helper**

In `apps/web/src/lib/api.ts`, add this helper after `listArtifactCards`:

```ts
export const createArtifactCard = (workId: string, data: ArtifactCardCreate) =>
  apiFetch<ArtifactCard>(`/api/v1/works/${workId}/artifact-cards`, {
    method: "POST",
    body: JSON.stringify(data),
  });
```

Add this type before `ArtifactCardPatch`:

```ts
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

- [ ] **Step 4: Pass the active phase into the card deck**

In `apps/web/src/app/works/[id]/page.tsx`, render `ArtifactCardDeck` with `phase={activePhase}`:

```tsx
<ArtifactCardDeck
  workId={workId}
  phase={activePhase}
  cards={cards.filter((card) => card.phase === activePhase)}
  onCardsChanged={fetchCardsForActivePhase}
  loading={cardsLoading}
/>
```

- [ ] **Step 5: Extend the deck props, draft model, and payload helpers**

In `apps/web/src/components/work/ArtifactCardDeck.tsx`, update the imports and top-level helpers to include create, phase, artifact type, and JSON payload parsing:

```tsx
import { useState } from "react";
import {
  createArtifactCard,
  updateArtifactCard,
  type ArtifactCard,
  type ArtifactSelectionState,
  type ResearchPhase,
} from "@/lib/api";

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
  artifact_type: string;
  payloadJson: string;
}

function defaultArtifactType(phase: ResearchPhase): string {
  if (phase === "atlas") return "atlas_direction";
  if (phase === "frontier") return "frontier_gap";
  return "divergent_idea";
}

function formatPayload(payload?: Record<string, unknown> | null): string {
  return JSON.stringify(payload ?? {}, null, 2);
}

function parsePayloadJson(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Payload JSON must be an object.");
  }
  return parsed as Record<string, unknown>;
}

function newCardDraft(phase: ResearchPhase): CardDraft {
  return {
    title: "",
    body: "",
    artifact_type: defaultArtifactType(phase),
    payloadJson: "{}",
  };
}

function payloadHasContent(payload: Record<string, unknown>): boolean {
  return Object.keys(payload ?? {}).length > 0;
}
```

Update the component signature and local state:

```tsx
export default function ArtifactCardDeck({
  workId,
  phase,
  cards,
  onCardsChanged,
  loading = false,
}: ArtifactCardDeckProps) {
  const [draftsByCard, setDraftsByCard] = useState<Record<string, CardDraft>>({});
  const [savingByCard, setSavingByCard] = useState<Record<string, boolean>>({});
  const [errorsByCard, setErrorsByCard] = useState<Record<string, string>>({});
  const [newDraft, setNewDraft] = useState<CardDraft | null>(null);
  const [creating, setCreating] = useState(false);
  const [deckError, setDeckError] = useState<string | null>(null);
```

- [ ] **Step 6: Add create, save, delete, and selection handlers**

In `ArtifactCardDeck`, use this `startEditing` body so existing payload is formatted on entry:

```tsx
const startEditing = (card: ArtifactCard) => {
  setDraftsByCard((previous) => ({
    ...previous,
    [card.id]: {
      title: card.title,
      body: card.body ?? "",
      artifact_type: card.artifact_type,
      payloadJson: formatPayload(card.payload),
    },
  }));
  setCardError(card.id, null);
};
```

Use this `saveCard` body to patch title, body, and payload:

```tsx
const saveCard = async (card: ArtifactCard) => {
  const draft = draftsByCard[card.id];
  if (!draft) return;

  const title = draft.title.trim();
  if (!title) {
    setCardError(card.id, "Title is required.");
    return;
  }

  let payload: Record<string, unknown>;
  try {
    payload = parsePayloadJson(draft.payloadJson);
  } catch (error) {
    setCardError(
      card.id,
      error instanceof Error ? error.message : "Payload JSON is invalid.",
    );
    return;
  }

  const body = draft.body.trim() || null;
  const payloadChanged = formatPayload(payload) !== formatPayload(card.payload);
  if (title === card.title && body === (card.body ?? null) && !payloadChanged) {
    cancelEditing(card.id);
    return;
  }

  setCardSaving(card.id, true);
  setCardError(card.id, null);
  try {
    await updateArtifactCard(workId, card.id, { title, body, payload });
    cancelEditing(card.id);
    await onCardsChanged();
  } catch (error) {
    console.error(error);
    setCardError(
      card.id,
      error instanceof Error ? error.message : "Failed to save card.",
    );
  } finally {
    setCardSaving(card.id, false);
  }
};
```

Add `createCard`:

```tsx
const createCard = async () => {
  if (!newDraft) return;

  const title = newDraft.title.trim();
  const artifactType = newDraft.artifact_type.trim();
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
    payload = parsePayloadJson(newDraft.payloadJson);
  } catch (error) {
    setDeckError(
      error instanceof Error ? error.message : "Payload JSON is invalid.",
    );
    return;
  }

  setCreating(true);
  setDeckError(null);
  try {
    await createArtifactCard(workId, {
      phase,
      artifact_type: artifactType,
      title,
      body: newDraft.body.trim() || null,
      payload,
    });
    setNewDraft(null);
    await onCardsChanged();
  } catch (error) {
    console.error(error);
    setDeckError(
      error instanceof Error ? error.message : "Failed to create card.",
    );
  } finally {
    setCreating(false);
  }
};
```

Add `deleteCard`:

```tsx
const deleteCard = async (card: ArtifactCard) => {
  if (!confirm("Delete this card?")) return;

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

- [ ] **Step 7: Add the deck header create button and inline create form**

In the deck header JSX, add the create button:

```tsx
<button
  type="button"
  className="btn-secondary px-3 py-1.5 text-[12px]"
  onClick={() => {
    setNewDraft(newCardDraft(phase));
    setDeckError(null);
  }}
  disabled={creating || loading}
>
  Add card
</button>
```

Render this inline form before the loading/empty/card-list branch:

```tsx
{newDraft && (
  <div className="mb-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-secondary)]/40 p-3">
    <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_220px]">
      <input
        className="input-field h-9 text-[13px] font-medium"
        value={newDraft.title}
        onChange={(event) =>
          setNewDraft((draft) =>
            draft ? { ...draft, title: event.target.value } : draft,
          )
        }
        disabled={creating}
        aria-label="New card title"
        placeholder="Card title"
      />
      <input
        className="input-field h-9 text-[12px]"
        value={newDraft.artifact_type}
        onChange={(event) =>
          setNewDraft((draft) =>
            draft ? { ...draft, artifact_type: event.target.value } : draft,
          )
        }
        disabled={creating}
        aria-label="New card artifact type"
        placeholder="artifact_type"
      />
    </div>
    <textarea
      className="input-field mt-2 min-h-[84px] resize-y py-2 text-[12px] leading-5"
      value={newDraft.body}
      onChange={(event) =>
        setNewDraft((draft) =>
          draft ? { ...draft, body: event.target.value } : draft,
        )
      }
      disabled={creating}
      aria-label="New card body"
      placeholder="Body"
    />
    <label className="mt-2 block text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
      Payload JSON
    </label>
    <textarea
      className="input-field mt-1 min-h-[96px] resize-y py-2 text-[12px] leading-5"
      value={newDraft.payloadJson}
      onChange={(event) =>
        setNewDraft((draft) =>
          draft ? { ...draft, payloadJson: event.target.value } : draft,
        )
      }
      disabled={creating}
      aria-label="New card payload JSON"
    />
    {deckError && (
      <p className="mt-2 text-[12px] text-[var(--accent-red)]">{deckError}</p>
    )}
    <div className="mt-3 flex flex-wrap items-center gap-2">
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

- [ ] **Step 8: Extend per-card edit and read UI**

When a card is editing, include the artifact type input as disabled text if keeping type immutable for existing cards, and include a payload JSON textarea:

```tsx
<input
  className="input-field h-9 text-[13px] font-medium"
  value={draft.title}
  onChange={(event) =>
    updateDraft(card.id, { title: event.target.value })
  }
  disabled={isSaving}
  aria-label="Card title"
/>
<textarea
  className="input-field min-h-[96px] resize-y py-2 text-[12px] leading-5"
  value={draft.body}
  onChange={(event) =>
    updateDraft(card.id, { body: event.target.value })
  }
  disabled={isSaving}
  aria-label="Card body"
/>
<label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
  Payload JSON
</label>
<textarea
  className="input-field min-h-[110px] resize-y py-2 text-[12px] leading-5"
  value={draft.payloadJson}
  onChange={(event) =>
    updateDraft(card.id, { payloadJson: event.target.value })
  }
  disabled={isSaving}
  aria-label="Card payload JSON"
/>
```

When a card is not editing, render a compact payload preview only when payload has keys:

```tsx
{payloadHasContent(card.payload) && (
  <pre className="mt-2 max-h-40 overflow-auto rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-secondary)]/40 p-2 text-[11px] leading-5 text-[var(--text-muted)]">
    {formatPayload(card.payload)}
  </pre>
)}
```

In the non-editing action group, add delete next to edit and select:

```tsx
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
  className="btn-danger px-3 py-1.5 text-[12px]"
  onClick={() => void deleteCard(card)}
  disabled={isSaving}
>
  Delete
</button>
```

- [ ] **Step 9: Run the targeted tests and verify they pass**

Run:

```bash
pytest tests/test_web_work_page_static.py::test_work_api_types_and_helpers_exist tests/test_web_work_page_static.py::test_artifact_deck_supports_edit_and_selection tests/test_web_work_page_static.py::test_work_page_renders_artifact_deck_with_active_phase_cards -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add tests/test_web_work_page_static.py apps/web/src/lib/api.ts apps/web/src/components/work/ArtifactCardDeck.tsx apps/web/src/app/works/[id]/page.tsx
git commit -m "feat: add editable artifact card CRUD"
```

### Task 3: Add Full Result Page Navigation and Editable Card Surface

**Files:**
- Create: `apps/web/src/components/ResultPageNav.tsx`
- Create: `apps/web/src/components/work/RunArtifactCardsPanel.tsx`
- Modify: `apps/web/src/app/runs/[id]/atlas/page.tsx`
- Modify: `apps/web/src/app/runs/[id]/frontier/page.tsx`
- Modify: `apps/web/src/app/runs/[id]/divergent/page.tsx`
- Modify: `tests/test_web_run_page_static.py`
- Modify: `tests/test_web_frontier_page_static.py`

- [ ] **Step 1: Write the failing static tests**

In `tests/test_web_run_page_static.py`, add page constants and result-page assertions:

```python
ATLAS_PAGE = Path("apps/web/src/app/runs/[id]/atlas/page.tsx")
FRONTIER_PAGE = Path("apps/web/src/app/runs/[id]/frontier/page.tsx")
DIVERGENT_PAGE = Path("apps/web/src/app/runs/[id]/divergent/page.tsx")
```

Add these tests:

```python
def test_full_result_pages_have_scroll_nav_and_bottom_back_to_run() -> None:
    for path in (ATLAS_PAGE, FRONTIER_PAGE, DIVERGENT_PAGE):
        source = path.read_text()

        assert "ResultPageNav" in source
        assert "BottomBackToRun" in source
        assert source.count("Back to run") >= 2


def test_full_result_pages_mount_editable_artifact_cards() -> None:
    for path, phase in (
        (ATLAS_PAGE, "atlas"),
        (FRONTIER_PAGE, "frontier"),
        (DIVERGENT_PAGE, "divergent"),
    ):
        source = path.read_text()

        assert "RunArtifactCardsPanel" in source
        assert f'phase="{phase}"' in source
```

In `tests/test_web_frontier_page_static.py`, add Frontier-specific checks:

```python
def test_frontier_page_uses_shared_result_navigation() -> None:
    source = FRONTIER_PAGE.read_text()

    assert "ResultPageNav" in source
    assert "BottomBackToRun" in source


def test_frontier_page_mounts_editable_artifact_cards() -> None:
    source = FRONTIER_PAGE.read_text()

    assert "RunArtifactCardsPanel" in source
    assert 'phase="frontier"' in source
```

- [ ] **Step 2: Run the targeted tests and verify they fail on the old behavior**

Run:

```bash
pytest tests/test_web_run_page_static.py::test_full_result_pages_have_scroll_nav_and_bottom_back_to_run tests/test_web_run_page_static.py::test_full_result_pages_mount_editable_artifact_cards tests/test_web_frontier_page_static.py::test_frontier_page_uses_shared_result_navigation tests/test_web_frontier_page_static.py::test_frontier_page_mounts_editable_artifact_cards -q
```

Expected on the old baseline: FAIL because the shared navigation component, bottom back link, or editable card panel is missing.

- [ ] **Step 3: Create `ResultPageNav`**

Create `apps/web/src/components/ResultPageNav.tsx`:

```tsx
"use client";

import { ArrowDown, ArrowUp } from "lucide-react";

export default function ResultPageNav() {
  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const scrollToBottom = () => {
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: "smooth",
    });
  };

  const controls = (
    <>
      <button
        type="button"
        onClick={scrollToTop}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)]/95 text-[var(--text-muted)] shadow-sm transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"
        title="Back to top"
        aria-label="Back to top"
      >
        <ArrowUp className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={scrollToBottom}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)]/95 text-[var(--text-muted)] shadow-sm transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"
        title="Go to bottom"
        aria-label="Go to bottom"
      >
        <ArrowDown className="h-4 w-4" aria-hidden="true" />
      </button>
    </>
  );

  return (
    <>
      <div className="fixed right-4 top-1/2 z-30 hidden -translate-y-1/2 flex-col gap-2 md:flex">
        {controls}
      </div>
      <div className="fixed bottom-5 right-5 z-30 flex gap-2 md:hidden">
        {controls}
      </div>
    </>
  );
}
```

- [ ] **Step 4: Create `RunArtifactCardsPanel`**

Create `apps/web/src/components/work/RunArtifactCardsPanel.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  listArtifactCards,
  type ArtifactCard,
  type ResearchPhase,
  type Run,
} from "@/lib/api";
import ArtifactCardDeck from "@/components/work/ArtifactCardDeck";

export default function RunArtifactCardsPanel({
  run,
  phase,
}: {
  run: Run;
  phase: ResearchPhase;
}) {
  const workId = run.work_id;
  const [cards, setCards] = useState<ArtifactCard[]>([]);
  const [loading, setLoading] = useState(Boolean(workId));
  const [error, setError] = useState<string | null>(null);

  const fetchCards = useCallback(async () => {
    if (!workId) return;
    setLoading(true);
    setError(null);
    try {
      const cardData = await listArtifactCards(workId, phase);
      setCards(cardData.items ?? []);
    } catch (err) {
      console.error(err);
      setCards([]);
      setError(err instanceof Error ? err.message : "Failed to load editable cards.");
    } finally {
      setLoading(false);
    }
  }, [phase, workId]);

  useEffect(() => {
    void fetchCards();
  }, [fetchCards]);

  if (!workId) return null;

  return (
    <div className="animate-fade-up delay-75">
      {error && (
        <div className="mb-3 rounded-lg border border-[var(--accent-red)]/30 bg-[var(--accent-red-soft)] px-3 py-2 text-[12px] text-[var(--accent-red)]">
          {error}
        </div>
      )}
      <ArtifactCardDeck
        workId={workId}
        phase={phase}
        cards={cards}
        onCardsChanged={fetchCards}
        loading={loading}
      />
    </div>
  );
}
```

- [ ] **Step 5: Mount shared result controls on Atlas**

In `apps/web/src/app/runs/[id]/atlas/page.tsx`, add imports:

```tsx
import ResultPageNav from "@/components/ResultPageNav";
import RunArtifactCardsPanel from "@/components/work/RunArtifactCardsPanel";
```

Inside the root returned container, render:

```tsx
<ResultPageNav />
```

After the hero card, render:

```tsx
<RunArtifactCardsPanel run={run} phase="atlas" />
```

Before the closing `</div>` of the root container, render:

```tsx
<BottomBackToRun runId={runId} />
```

Add this local helper at the bottom of the file:

```tsx
function BottomBackToRun({ runId }: { runId: string }) {
  return (
    <div className="border-t border-[var(--border-subtle)] pt-4">
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
  );
}
```

- [ ] **Step 6: Mount shared result controls on Frontier**

In `apps/web/src/app/runs/[id]/frontier/page.tsx`, add imports:

```tsx
import ResultPageNav from "@/components/ResultPageNav";
import RunArtifactCardsPanel from "@/components/work/RunArtifactCardsPanel";
```

Inside the root returned container, render:

```tsx
<ResultPageNav />
```

After the header card, render:

```tsx
<RunArtifactCardsPanel run={run} phase="frontier" />
```

Before the closing `</div>` of the root container, render:

```tsx
<BottomBackToRun runId={runId} />
```

Add this local helper at the bottom of the file:

```tsx
function BottomBackToRun({ runId }: { runId: string }) {
  return (
    <div className="border-t border-[var(--border-subtle)] pt-4">
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
  );
}
```

- [ ] **Step 7: Mount shared result controls on Divergent**

In `apps/web/src/app/runs/[id]/divergent/page.tsx`, add imports:

```tsx
import ResultPageNav from "@/components/ResultPageNav";
import RunArtifactCardsPanel from "@/components/work/RunArtifactCardsPanel";
```

Inside the root returned container, render:

```tsx
<ResultPageNav />
```

After the header card, render:

```tsx
<RunArtifactCardsPanel run={run} phase="divergent" />
```

Before the closing `</div>` of the root container, render:

```tsx
<BottomBackToRun runId={runId} />
```

Add this local helper at the bottom of the file:

```tsx
function BottomBackToRun({ runId }: { runId: string }) {
  return (
    <div className="border-t border-[var(--border-subtle)] pt-4">
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
  );
}
```

- [ ] **Step 8: Run the targeted tests and verify they pass**

Run:

```bash
pytest tests/test_web_run_page_static.py::test_full_result_pages_have_scroll_nav_and_bottom_back_to_run tests/test_web_run_page_static.py::test_full_result_pages_mount_editable_artifact_cards tests/test_web_frontier_page_static.py::test_frontier_page_uses_shared_result_navigation tests/test_web_frontier_page_static.py::test_frontier_page_mounts_editable_artifact_cards -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py apps/web/src/components/ResultPageNav.tsx apps/web/src/components/work/RunArtifactCardsPanel.tsx apps/web/src/app/runs/[id]/atlas/page.tsx apps/web/src/app/runs/[id]/frontier/page.tsx apps/web/src/app/runs/[id]/divergent/page.tsx
git commit -m "feat: add result navigation and editable result cards"
```

### Task 4: Final Verification

**Files:**
- Verify: `tests/test_web_work_page_static.py`
- Verify: `tests/test_web_run_page_static.py`
- Verify: `tests/test_web_frontier_page_static.py`
- Verify: `apps/web`

- [ ] **Step 1: Run focused static tests**

Run:

```bash
pytest tests/test_web_work_page_static.py tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run existing work API tests**

Run:

```bash
pytest tests/test_work_phase_api.py -q
```

Expected: all tests PASS. This confirms existing create, patch, revision, and soft-delete contracts remain intact.

- [ ] **Step 3: Build the web app**

Run:

```bash
npm --prefix apps/web run build
```

Expected: Next.js build completes without TypeScript or rendering errors.

- [ ] **Step 4: Review the final diff**

Run:

```bash
git diff --stat HEAD
git diff HEAD -- apps/web/src/app/works/[id]/page.tsx apps/web/src/components/work/PhaseRunPanel.tsx apps/web/src/components/work/ArtifactCardDeck.tsx apps/web/src/lib/api.ts apps/web/src/components/ResultPageNav.tsx apps/web/src/components/work/RunArtifactCardsPanel.tsx apps/web/src/app/runs/[id]/atlas/page.tsx apps/web/src/app/runs/[id]/frontier/page.tsx apps/web/src/app/runs/[id]/divergent/page.tsx tests/test_web_work_page_static.py tests/test_web_run_page_static.py tests/test_web_frontier_page_static.py
```

Expected: diff contains only the planned phase-flow, result-navigation, card-CRUD, and test changes.

- [ ] **Step 5: Commit verification fixes if needed**

If Step 1, Step 2, or Step 3 required small corrections, commit those corrections:

```bash
git add apps/web/src tests
git commit -m "fix: stabilize research workflow optimization"
```

Expected: commit is created only if verification required corrections. If there were no corrections, skip this commit.

## Plan Self-Review

- Spec coverage: Task 1 covers Divergent as final phase. Task 2 covers artifact card add, edit, soft delete, payload JSON, selection, and edited-card propagation through saved cards. Task 3 covers result-page top/bottom navigation and bottom Back to run. Task 4 covers verification.
- Placeholder scan: no deferred implementation slots are intentionally left in this plan.
- Type consistency: `ArtifactCardCreate`, `ArtifactCardPatch`, `ResearchPhase`, `ArtifactCardDeckProps.phase`, and `RunArtifactCardsPanel.phase` all use the same names across tasks.
