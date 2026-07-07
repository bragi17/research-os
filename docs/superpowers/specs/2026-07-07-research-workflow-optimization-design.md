# Research Workflow Optimization Design

## Context

Research OS currently exposes a three-phase topic work flow: Atlas, Frontier, and Divergent. Each phase stores its usable outputs as artifact cards. The work page already starts phase executions from selected card IDs, and the backend builds the next run context from the saved artifact cards.

The current UI has three gaps:

- Divergent still exposes a next-step action that routes selected ideas back through Frontier validation. The user confirmed this should not remain. Divergent is the final research phase.
- Full result pages for Atlas, Frontier, and Divergent can become long, but only expose a top Back to run link.
- Artifact cards can be selected and lightly edited, but the work page does not yet expose full create, read, update, and delete controls for card content.

## Goals

- Make Divergent a clear terminal phase by removing its next-phase action and backend-facing UI path from Divergent to Frontier validation.
- Add elegant, shared navigation affordances to full result pages: top, bottom, and a bottom Back to run action.
- Make artifact cards fully manageable from the work page, including add, edit, soft delete, and selection.
- Ensure edited Frontier cards can be selected and passed to Divergent, and edited Divergent cards remain the accurate final research/coding input.

## Non-Goals

- Do not add a separate artifact workspace page.
- Do not add revision browsing in this iteration.
- Do not change the agent execution algorithms or worker prompts unless existing code requires a narrow integration adjustment.
- Do not hard-delete artifact cards from storage.

## Current Behavior

`apps/web/src/app/works/[id]/page.tsx` uses `nextPhaseTarget` to map Atlas to Frontier, Frontier to Divergent, and Divergent back to Frontier with `executionKind: "validation"`. `PhaseRunPanel` always renders a secondary next action, so Divergent appears to have a continuation.

`apps/web/src/app/runs/[id]/atlas/page.tsx`, `frontier/page.tsx`, and `divergent/page.tsx` each render a top Back to run link. They do not share a result-page navigation component, and they do not consistently provide a bottom Back to run link.

The backend already supports artifact card creation and patching:

- `POST /api/v1/works/{work_id}/artifact-cards`
- `PATCH /api/v1/works/{work_id}/artifact-cards/{card_id}`

The database layer stores revisions when `title`, `body`, or `payload` changes, and list queries filter out `status = 'deleted'`.

## Proposed Design

### Divergent as Final Phase

Remove the Divergent next-phase target from the work page. `nextPhaseTarget` should only be called for Atlas and Frontier, or be replaced with a nullable helper that returns no target for Divergent.

`PhaseRunPanel` should accept whether a next action exists. For Divergent, it renders only the current phase action. The current phase action remains useful because users may rerun Divergent from selected Divergent inputs or corrected upstream context, but there is no "next" action after Divergent.

The labels should be:

- Atlas next action: `Start Frontier from selected Atlas cards`
- Frontier next action: `Start Divergent from selected gaps`
- Divergent: no next action

### Result Page Navigation

Create a small shared component for full result pages, for example `ResultPageNav`. It will render a fixed right-side vertical control group on medium and large screens and a compact sticky bottom-right group on small screens.

Controls:

- Scroll to top
- Scroll to bottom

The component should use buttons, not links, because it controls scroll position. It should use the existing visual language: compact dimensions, subtle border, `var(--bg-primary)` or translucent static-card background, muted icon/text, and accent hover state.

Each full result page should also render a bottom action row with a Back to run link. This bottom link should match the existing top Back to run treatment but be placed after the final content block so users do not need to scroll back up manually.

### Artifact Card CRUD

Extend `ArtifactCardDeck` rather than introducing a new page. The card deck remains the phase-specific card surface inside the work page.

Add API support in `apps/web/src/lib/api.ts`:

- `ArtifactCardCreate`
- `createArtifactCard(workId, data)`

Use existing `updateArtifactCard` for:

- updating `title`
- updating `body`
- updating `payload`
- soft deleting with `status: "deleted"`
- selecting and deselecting with `selection_state`

The deck should support:

- Add card: inline form opened from the card deck header.
- Edit card: title, body, and payload JSON.
- Delete card: soft delete after a browser confirm, then refresh cards.
- Read card: current card display remains compact, showing title, body, phase/type/status/selection badges, and an optional collapsed payload preview.
- Select card: existing selection toggle remains.

Payload editing should use a JSON textarea. Invalid JSON should block saving with a clear inline error. Empty payload should save as `{}`. Existing payload should be formatted with two-space indentation when entering edit mode.

New cards should default to the active phase passed by the work page. The UI should let users set a concise artifact type, defaulting by phase:

- Atlas: `atlas_direction`
- Frontier: `frontier_gap`
- Divergent: `divergent_idea`

### Data Flow

When a card is edited, the frontend saves the changes through `PATCH /artifact-cards/{card_id}`. The backend revision logic records user edits for title, body, and payload.

When the user selects cards and starts the next phase, the work page sends `source_card_ids`. The backend uses `_context_bundle_from_cards` to build the phase context from the saved cards. This means edited Frontier cards are naturally passed into Divergent as the authoritative source.

Since Divergent is final, edited Divergent cards become the final curated output for downstream coding or manual use. They are not routed back into Frontier validation.

## Component Boundaries

- `apps/web/src/app/works/[id]/page.tsx`: owns active phase state, selected cards, phase execution actions, and passes `phase` to `ArtifactCardDeck`.
- `apps/web/src/components/work/PhaseRunPanel.tsx`: renders current-phase action and optional next-phase action.
- `apps/web/src/components/work/ArtifactCardDeck.tsx`: owns add/edit/delete UI state for cards in the active phase.
- `apps/web/src/components/ResultPageNav.tsx`: shared scroll controls for full result pages.
- Full result pages under `apps/web/src/app/runs/[id]/{atlas,frontier,divergent}/page.tsx`: import `ResultPageNav` and render bottom Back to run.
- `apps/web/src/lib/api.ts`: exposes the create-card frontend helper and type.

## Error Handling

- Phase next action on Divergent should not be rendered, so no Divergent-to-Frontier validation request can be triggered from the UI.
- Add/edit forms validate title and artifact type before API calls.
- Payload JSON parse failures are shown inline and do not call the API.
- Card delete failures are shown inline on the affected card or deck.
- Result-page scroll buttons should no-op safely in browser-only contexts and use smooth scrolling.

## Testing

Use static tests for the web UI structure already established in this repository, plus API route tests where behavior touches backend contracts.

Tests should verify:

- `PhaseRunPanel` supports optional next action and does not render one for Divergent usage.
- The work page does not map Divergent to Frontier validation.
- The API helper exports `ArtifactCardCreate` and `createArtifactCard`.
- `ArtifactCardDeck` includes add, edit, payload JSON, delete, and selection controls.
- Result pages import and render the shared result navigation component.
- Atlas, Frontier, and Divergent full result pages include bottom Back to run links.
- Existing backend artifact card create, patch, revision, and soft-delete behavior remains covered by current tests.

## Rollout Notes

This change is backward compatible with stored work data. Existing deleted cards remain hidden because list queries already filter them. Existing phase executions remain visible in the execution history, including any older validation executions, but the UI will no longer offer a new Divergent-to-Frontier validation action.
