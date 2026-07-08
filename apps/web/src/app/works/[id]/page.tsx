"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  getWork,
  getWorkPhases,
  listArtifactCards,
  startPhaseExecution,
  type ArtifactCard,
  type PhaseExecution,
  type ResearchPhase,
  type StartPhaseExecutionData,
  type Work,
} from "@/lib/api";
import ArtifactCardDeck from "@/components/work/ArtifactCardDeck";
import PhaseRunPanel from "@/components/work/PhaseRunPanel";
import PhaseStepper from "@/components/work/PhaseStepper";

const WORK_PHASE_HINTS_STORAGE_KEY = "ros_work_phases";

function nextPhaseTarget(phase: ResearchPhase): {
  phase: ResearchPhase;
} | null {
  if (phase === "atlas") return { phase: "frontier" };
  if (phase === "frontier") return { phase: "divergent" };
  return null;
}

function isResearchPhase(value: string | null): value is ResearchPhase {
  return value === "atlas" || value === "frontier" || value === "divergent";
}

function rememberWorkPhase(workId: string, phase: ResearchPhase) {
  try {
    const stored = JSON.parse(localStorage.getItem(WORK_PHASE_HINTS_STORAGE_KEY) || "{}");
    const next = stored && typeof stored === "object" && !Array.isArray(stored) ? stored : {};
    localStorage.setItem(WORK_PHASE_HINTS_STORAGE_KEY, JSON.stringify({ ...next, [workId]: phase }));
  } catch { /* silent */ }
}

function formatDate(value?: string | null): string {
  if (!value) return "Not started";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function WorkPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const workId = params.id;
  const rawQueryPhase = searchParams.get("phase");
  const queryPhase = isResearchPhase(rawQueryPhase) ? rawQueryPhase : null;
  const phaseStartStatus = searchParams.get("phase_start");
  const phaseInitializedRef = useRef(false);
  const phaseRef = useRef<ResearchPhase>(queryPhase ?? "atlas");
  const cardsRequestSeqRef = useRef(0);
  const [work, setWork] = useState<Work | null>(null);
  const [executions, setExecutions] = useState<PhaseExecution[]>([]);
  const [cards, setCards] = useState<ArtifactCard[]>([]);
  const [activePhase, setActivePhase] = useState<ResearchPhase>(queryPhase ?? "atlas");
  const [loading, setLoading] = useState(true);
  const [cardsLoading, setCardsLoading] = useState(false);
  const [runningAction, setRunningAction] = useState<"phase" | "next" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rememberedPhase, setRememberedPhase] = useState<ResearchPhase | null>(null);
  const [rememberedPhaseLoaded, setRememberedPhaseLoaded] = useState(false);
  const [actionError, setActionError] = useState<string | null>(
    phaseStartStatus === "failed"
      ? "Work created, but the initial phase did not start."
      : null,
  );

  const fetchWork = useCallback(async () => {
    if (!rememberedPhaseLoaded) return;
    setError(null);
    try {
      const [workData, phaseData] = await Promise.all([
        getWork(workId),
        getWorkPhases(workId),
      ]);
      setWork(workData);
      setExecutions(phaseData.executions ?? []);
      const initialPhase = queryPhase ?? workData.active_phase ?? rememberedPhase ?? "atlas";
      if (!phaseInitializedRef.current) {
        setActivePhase(initialPhase);
        phaseInitializedRef.current = true;
      }
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to load work");
    } finally {
      setLoading(false);
    }
  }, [queryPhase, rememberedPhase, rememberedPhaseLoaded, workId]);

  const fetchCards = useCallback(
    async (phase: ResearchPhase) => {
      const requestedPhase = phase;
      const requestId = ++cardsRequestSeqRef.current;
      setCardsLoading(true);
      try {
        const cardData = await listArtifactCards(workId, requestedPhase);
        if (requestId !== cardsRequestSeqRef.current) return;
        if (phaseRef.current !== requestedPhase) return;
        setCards(cardData.items ?? []);
      } catch (err) {
        if (requestId !== cardsRequestSeqRef.current) return;
        if (phaseRef.current !== requestedPhase) return;
        console.error(err);
        setCards([]);
        setActionError(err instanceof Error ? err.message : "Failed to load cards");
      } finally {
        if (requestId !== cardsRequestSeqRef.current) return;
        if (phaseRef.current !== requestedPhase) return;
        setCardsLoading(false);
      }
    },
    [workId],
  );

  useEffect(() => {
    void fetchWork();
  }, [fetchWork]);

  useEffect(() => {
    phaseRef.current = activePhase;
    void fetchCards(activePhase);
  }, [activePhase, fetchCards]);

  useEffect(() => {
    setRememberedPhaseLoaded(false);
    try {
      const stored = JSON.parse(localStorage.getItem(WORK_PHASE_HINTS_STORAGE_KEY) || "{}");
      const phaseHint = stored && typeof stored === "object" && !Array.isArray(stored) ? stored[workId] : null;
      setRememberedPhase(isResearchPhase(phaseHint) ? phaseHint : null);
    } catch {
      setRememberedPhase(null);
    } finally {
      setRememberedPhaseLoaded(true);
    }
  }, [workId]);

  useEffect(() => {
    if (queryPhase) {
      rememberWorkPhase(workId, queryPhase);
      phaseInitializedRef.current = true;
      setActivePhase(queryPhase);
    }
  }, [queryPhase, workId]);

  useEffect(() => {
    if (!queryPhase) {
      rememberWorkPhase(workId, activePhase);
    }
  }, [activePhase, queryPhase, workId]);

  useEffect(() => {
    if (phaseStartStatus === "failed") {
      setActionError("Work created, but the initial phase did not start.");
    }
  }, [phaseStartStatus]);

  const fetchCardsForActivePhase = useCallback(
    () => fetchCards(phaseRef.current),
    [fetchCards],
  );

  const phaseExecutions = useMemo(
    () =>
      executions
        .filter((execution) => execution.phase === activePhase)
        .sort(
          (left, right) =>
            new Date(right.created_at).getTime() -
            new Date(left.created_at).getTime(),
        ),
    [activePhase, executions],
  );
  const latestExecution = phaseExecutions[0];
  const phaseCards = cards.filter((card) => card.phase === activePhase);
  const selectedCards = phaseCards.filter(
    (card) => card.selection_state === "selected",
  );
  const phaseStartRecoveryHref = work && phaseStartStatus === "failed"
    ? `/new?mode=${activePhase}&topic=${encodeURIComponent(work.topic)}`
    : null;

  const onPhaseChange = (phase: ResearchPhase) => {
    rememberWorkPhase(workId, phase);
    setActivePhase(phase);
  };

  const runPhase = async () => {
    setActionError(null);
    const sourceCardIds = selectedCards.map((card) => card.id);
    if (activePhase !== "atlas" && sourceCardIds.length === 0) {
      setActionError("Select cards before running this phase.");
      return;
    }

    const phaseRunData: StartPhaseExecutionData =
      activePhase === "atlas" ? {} : { source_card_ids: sourceCardIds };

    setRunningAction("phase");
    try {
      await startPhaseExecution(workId, activePhase, phaseRunData);
      await fetchWork();
      await fetchCards(activePhase);
    } catch (err) {
      console.error(err);
      setActionError(err instanceof Error ? err.message : "Failed to start phase");
    } finally {
      setRunningAction(null);
    }
  };

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

    try {
      await startPhaseExecution(workId, target.phase, data);
      rememberWorkPhase(workId, target.phase);
      setActivePhase(target.phase);
      await fetchWork();
      await fetchCards(target.phase);
    } catch (err) {
      console.error(err);
      setActionError(err instanceof Error ? err.message : "Failed to start phase");
    } finally {
      setRunningAction(null);
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-5 w-5 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!work) {
    return (
      <div className="flex h-screen items-center justify-center px-6">
        <div className="card-static max-w-[460px] p-5 text-center">
          <h1 className="mb-2 text-[16px] font-medium text-[var(--text-primary)]">
            Work not found
          </h1>
          <p className="text-[13px] text-[var(--text-muted)]">
            {error ?? "The requested work is unavailable."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-[1120px] px-6 py-7">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[11px] font-medium capitalize text-[var(--accent)]">
              {work.status}
            </span>
            <span className="text-[12px] text-[var(--text-muted)]">
              Updated {formatDate(work.updated_at)}
            </span>
          </div>
          <h1
            className="truncate text-[22px] font-medium text-[var(--text-primary)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {work.title}
          </h1>
          <p className="mt-1 max-w-[820px] text-[13px] leading-6 text-[var(--text-secondary)]">
            {work.topic}
          </p>
        </div>
      </header>

      <div className="mb-5">
        <PhaseStepper activePhase={activePhase} onChange={onPhaseChange} />
      </div>

      <div className="space-y-5">
        <PhaseRunPanel
          phase={activePhase}
          selectedCount={selectedCards.length}
          canRunPhase={activePhase === "atlas" || selectedCards.length > 0}
          running={runningAction !== null}
          latestExecution={latestExecution}
          onRunPhase={runPhase}
          onRunNext={runNextPhase}
        />

        {actionError && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--accent-red)]/30 bg-[var(--accent-red-soft)] px-3 py-2 text-[13px] text-[var(--accent-red)]">
            <span>{actionError}</span>
            {phaseStartRecoveryHref && (
              <Link
                href={phaseStartRecoveryHref}
                className="rounded-md border border-[var(--accent-red)]/30 bg-white/70 px-2.5 py-1 text-[12px] font-medium text-[var(--accent-red)] transition-colors hover:bg-white"
              >
                Retry setup
              </Link>
            )}
          </div>
        )}

        <ArtifactCardDeck
          workId={workId}
          cards={cards.filter((card) => card.phase === activePhase)}
          onCardsChanged={fetchCardsForActivePhase}
          loading={cardsLoading}
        />

        <section className="card-static p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-[15px] font-medium text-[var(--text-primary)]">
              Phase executions
            </h2>
            {latestExecution && (
              <span className="text-[12px] text-[var(--text-muted)]">
                Latest {formatDate(latestExecution.created_at)}
              </span>
            )}
          </div>

          {phaseExecutions.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border-subtle)] px-4 py-6 text-center text-[13px] text-[var(--text-muted)]">
              No executions yet.
            </div>
          ) : (
            <div className="divide-y divide-[var(--border-subtle)]">
              {phaseExecutions.slice(0, 5).map((execution) => (
                <div
                  key={execution.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[13px] font-medium capitalize text-[var(--text-primary)]">
                        {execution.execution_kind}
                      </span>
                      <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[11px] font-medium capitalize text-[var(--accent)]">
                        {execution.status}
                      </span>
                    </div>
                    {execution.error_message && (
                      <p className="mt-1 line-clamp-1 text-[12px] text-[var(--accent-red)]">
                        {execution.error_message}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 text-[11px] text-[var(--text-muted)]">
                    {formatDate(execution.created_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
