"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getWorkPhases,
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
  const [sourceExecutionId, setSourceExecutionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(workId));
  const [error, setError] = useState<string | null>(null);

  const fetchCards = useCallback(async () => {
    if (!workId) return;
    setLoading(true);
    setError(null);
    try {
      const [phaseData, cardData] = await Promise.all([
        getWorkPhases(workId),
        listArtifactCards(workId, phase),
      ]);
      const phaseExecution = phaseData.executions?.find(
        (execution) => execution.phase === phase && execution.backing_run_id === run.id,
      );
      const sourceExecutionId = phaseExecution?.id;
      setSourceExecutionId(sourceExecutionId ?? null);
      setCards(
        sourceExecutionId
          ? (cardData.items ?? []).filter(
              (card) => card.source_execution_id === sourceExecutionId,
            )
          : [],
      );
    } catch (err) {
      console.error(err);
      setSourceExecutionId(null);
      setCards([]);
      setError(err instanceof Error ? err.message : "Failed to load editable cards.");
    } finally {
      setLoading(false);
    }
  }, [phase, run.id, workId]);

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
        sourceExecutionId={sourceExecutionId}
      />
    </div>
  );
}
