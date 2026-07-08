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
