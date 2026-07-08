"use client";

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
  sourceExecutionId?: string | null;
}

interface CardDraft {
  title: string;
  body: string;
  artifact_type: string;
  payloadJson: string;
}

function labelize(value: string): string {
  return value.replaceAll("_", " ");
}

function selectionLabel(selectionState: ArtifactSelectionState): string {
  if (selectionState === "selected") return "Selected";
  if (selectionState === "used") return "Used";
  return "Unselected";
}

function badgeClass(value: string): string {
  if (value === "selected") {
    return "bg-[var(--accent-green-soft)] text-[var(--accent-green)]";
  }
  if (value === "used") {
    return "bg-[var(--accent-amber-soft)] text-[var(--accent-amber)]";
  }
  return "bg-[var(--bg-secondary)] text-[var(--text-muted)]";
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

export default function ArtifactCardDeck({
  workId,
  phase,
  cards,
  onCardsChanged,
  loading = false,
  sourceExecutionId = null,
}: ArtifactCardDeckProps) {
  const [draftsByCard, setDraftsByCard] = useState<Record<string, CardDraft>>({});
  const [savingByCard, setSavingByCard] = useState<Record<string, boolean>>({});
  const [errorsByCard, setErrorsByCard] = useState<Record<string, string>>({});
  const [newDraft, setNewDraft] = useState<CardDraft | null>(null);
  const [creating, setCreating] = useState(false);
  const [deckError, setDeckError] = useState<string | null>(null);

  const setCardSaving = (cardId: string, saving: boolean) => {
    setSavingByCard((previous) => ({ ...previous, [cardId]: saving }));
  };

  const setCardError = (cardId: string, message: string | null) => {
    setErrorsByCard((previous) => {
      const next = { ...previous };
      if (message) {
        next[cardId] = message;
      } else {
        delete next[cardId];
      }
      return next;
    });
  };

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

  const cancelEditing = (cardId: string) => {
    setDraftsByCard((previous) => {
      const next = { ...previous };
      delete next[cardId];
      return next;
    });
    setCardError(cardId, null);
  };

  const updateDraft = (cardId: string, patch: Partial<CardDraft>) => {
    setDraftsByCard((previous) => ({
      ...previous,
      [cardId]: {
        ...(previous[cardId] ?? {
          title: "",
          body: "",
          artifact_type: defaultArtifactType(phase),
          payloadJson: "{}",
        }),
        ...patch,
      },
    }));
  };

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
        source_execution_id: sourceExecutionId,
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

  const toggleSelection = async (card: ArtifactCard) => {
    const selection_state: ArtifactSelectionState =
      card.selection_state === "selected" ? "unselected" : "selected";

    setCardSaving(card.id, true);
    setCardError(card.id, null);
    try {
      await updateArtifactCard(workId, card.id, { selection_state });
      await onCardsChanged();
    } catch (error) {
      console.error(error);
      setCardError(
        card.id,
        error instanceof Error ? error.message : "Failed to update selection.",
      );
    } finally {
      setCardSaving(card.id, false);
    }
  };

  return (
    <section className="card-static p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-medium text-[var(--text-primary)]">
            Artifact cards
          </h2>
          <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
            {cards.length} total ·{" "}
            {cards.filter((card) => card.selection_state === "selected").length} selected
          </p>
        </div>
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
      </div>

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

      {loading ? (
        <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">
          Loading cards...
        </div>
      ) : cards.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border-subtle)] px-4 py-8 text-center text-[13px] text-[var(--text-muted)]">
          No cards for this phase.
        </div>
      ) : (
        <div className="divide-y divide-[var(--border-subtle)]">
          {cards.map((card) => {
            const draft = draftsByCard[card.id];
            const isEditing = Boolean(draft);
            const isSaving = Boolean(savingByCard[card.id]);
            const isSelected = card.selection_state === "selected";
            const error = errorsByCard[card.id];
            const selectionButtonClass = isSelected
              ? "btn-secondary px-3 py-1.5 text-[12px]"
              : "btn-primary px-3 py-1.5 text-[12px]";
            const selectionButtonLabel = isSaving
              ? "Saving..."
              : isSelected
                ? "Deselect"
                : "Select";

            return (
              <article key={card.id} className="py-4 first:pt-0 last:pb-0">
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="rounded-full bg-[var(--bg-secondary)] px-2 py-0.5 text-[10px] font-semibold uppercase text-[var(--text-muted)]">
                        {labelize(card.phase)}
                      </span>
                      <span className="rounded-full bg-[var(--bg-secondary)] px-2 py-0.5 text-[10px] font-semibold uppercase text-[var(--text-muted)]">
                        {labelize(card.artifact_type)}
                      </span>
                      <span className="rounded-full bg-[var(--bg-secondary)] px-2 py-0.5 text-[10px] font-medium capitalize text-[var(--text-muted)]">
                        {card.status}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${badgeClass(
                          card.selection_state,
                        )}`}
                      >
                        {selectionLabel(card.selection_state)}
                      </span>
                    </div>

                    {isEditing && draft ? (
                      <div className="space-y-2">
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
                          className="input-field min-h-[112px] resize-y py-2 text-[12px] leading-5"
                          value={draft.payloadJson}
                          onChange={(event) =>
                            updateDraft(card.id, { payloadJson: event.target.value })
                          }
                          disabled={isSaving}
                          aria-label="Card payload JSON"
                        />
                      </div>
                    ) : (
                      <div className="min-w-0">
                        <h3 className="break-words text-[14px] font-medium text-[var(--text-primary)]">
                          {card.title}
                        </h3>
                        {card.body ? (
                          <p className="mt-1 whitespace-pre-wrap break-words text-[12px] leading-5 text-[var(--text-secondary)]">
                            {card.body}
                          </p>
                        ) : (
                          <p className="mt-1 text-[12px] text-[var(--text-muted)]">
                            No body text.
                          </p>
                        )}
                        {payloadHasContent(card.payload) && (
                          <details className="mt-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-secondary)]/40 px-3 py-2">
                            <summary className="cursor-pointer text-[11px] font-medium text-[var(--text-muted)]">
                              Payload
                            </summary>
                            <pre className="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap break-words text-[11px] leading-5 text-[var(--text-secondary)]">
                              {formatPayload(card.payload)}
                            </pre>
                          </details>
                        )}
                      </div>
                    )}

                    {error && (
                      <p className="text-[12px] text-[var(--accent-red)]">{error}</p>
                    )}
                  </div>

                  <div className="flex flex-wrap items-start justify-start gap-2 lg:justify-end">
                    {isEditing ? (
                      <>
                        <button
                          type="button"
                          className="btn-primary px-3 py-1.5 text-[12px]"
                          onClick={() => void saveCard(card)}
                          disabled={isSaving}
                        >
                          {isSaving ? "Saving..." : "Save"}
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-3 py-1.5 text-[12px]"
                          onClick={() => cancelEditing(card.id)}
                          disabled={isSaving}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1.5 text-[12px]"
                        onClick={() => startEditing(card)}
                        disabled={isSaving}
                      >
                        Edit
                      </button>
                    )}
                    <button
                      type="button"
                      className={selectionButtonClass}
                      onClick={() => void toggleSelection(card)}
                      disabled={isSaving}
                    >
                      {selectionButtonLabel}
                    </button>
                    <button
                      type="button"
                      className="btn-danger px-3 py-1.5 text-[12px]"
                      onClick={() => void deleteCard(card)}
                      disabled={isSaving}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
