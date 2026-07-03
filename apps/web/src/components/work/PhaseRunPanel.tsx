"use client";

import type { PhaseExecution, ResearchPhase } from "@/lib/api";

const PHASE_LABELS: Record<ResearchPhase, string> = {
  atlas: "Atlas",
  frontier: "Frontier",
  divergent: "Divergent",
};

function nextActionLabel(phase: ResearchPhase): string {
  if (phase === "atlas") return "Start Frontier from selected Atlas cards";
  if (phase === "frontier") return "Start Divergent from selected gaps";
  return "Validate selected ideas with Frontier";
}

export default function PhaseRunPanel({
  phase,
  selectedCount,
  canRunPhase,
  running,
  latestExecution,
  onRunPhase,
  onRunNext,
}: {
  phase: ResearchPhase;
  selectedCount: number;
  canRunPhase: boolean;
  running: boolean;
  latestExecution?: PhaseExecution;
  onRunPhase: () => void;
  onRunNext: () => void;
}) {
  const phaseDisabled = running || !canRunPhase;
  const phaseActionTitle = canRunPhase
    ? "Run this phase"
    : "Select cards before running this phase.";
  const phaseActionAriaLabel = canRunPhase
    ? "Run this phase"
    : "Run this phase unavailable until cards are selected";
  const nextAction = nextActionLabel(phase);
  const nextDisabled = running || selectedCount === 0;
  const nextActionTitle =
    selectedCount === 0 ? "Select cards before starting this action." : nextAction;
  const nextActionAriaLabel =
    selectedCount === 0 ? `${nextAction} unavailable until cards are selected` : nextAction;

  return (
    <div className="card-static p-4 flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[14px] font-medium text-[var(--text-primary)]">
            {PHASE_LABELS[phase]} phase
          </h2>
          {latestExecution && (
            <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[11px] font-medium capitalize text-[var(--accent)]">
              {latestExecution.status}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
          {selectedCount} card{selectedCount === 1 ? "" : "s"} selected
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-secondary px-3 py-1.5 text-[13px]"
          onClick={onRunPhase}
          disabled={phaseDisabled}
          title={phaseActionTitle}
          aria-label={phaseActionAriaLabel}
        >
          Run this phase
        </button>
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
      </div>
    </div>
  );
}
