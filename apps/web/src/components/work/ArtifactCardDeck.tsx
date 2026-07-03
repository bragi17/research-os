"use client";

import { useState } from "react";
import {
  updateArtifactCard,
  type ArtifactCard,
  type ArtifactSelectionState,
} from "@/lib/api";

interface ArtifactCardDeckProps {
  workId: string;
  cards: ArtifactCard[];
  onCardsChanged: () => void | Promise<void>;
  loading?: boolean;
}

interface CardDraft {
  title: string;
  body: string;
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

export default function ArtifactCardDeck({
  workId,
  cards,
  onCardsChanged,
  loading = false,
}: ArtifactCardDeckProps) {
  const [draftsByCard, setDraftsByCard] = useState<Record<string, CardDraft>>({});
  const [savingByCard, setSavingByCard] = useState<Record<string, boolean>>({});
  const [errorsByCard, setErrorsByCard] = useState<Record<string, string>>({});

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
        ...(previous[cardId] ?? { title: "", body: "" }),
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

    const body = draft.body.trim() || null;
    if (title === card.title && body === (card.body ?? null)) {
      cancelEditing(card.id);
      return;
    }

    setCardSaving(card.id, true);
    setCardError(card.id, null);
    try {
      await updateArtifactCard(workId, card.id, { title, body });
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
      </div>

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
