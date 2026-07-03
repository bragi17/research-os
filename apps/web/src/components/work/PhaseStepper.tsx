"use client";

import type { ResearchPhase } from "@/lib/api";

const PHASES: { id: ResearchPhase; label: string }[] = [
  { id: "atlas", label: "Atlas" },
  { id: "frontier", label: "Frontier" },
  { id: "divergent", label: "Divergent" },
];

export default function PhaseStepper({
  activePhase,
  onChange,
}: {
  activePhase: ResearchPhase;
  onChange: (phase: ResearchPhase) => void;
}) {
  return (
    <nav
      className="flex items-center gap-1 border-b border-[var(--border-subtle)]"
      aria-label="Research phases"
    >
      {PHASES.map((phase) => {
        const active = activePhase === phase.id;
        return (
          <button
            key={phase.id}
            type="button"
            onClick={() => onChange(phase.id)}
            className={`px-4 py-3 text-[13px] font-medium border-b-2 transition-colors ${
              active
                ? "border-[var(--accent)] text-[var(--accent)]"
                : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            }`}
            aria-current={active ? "step" : undefined}
          >
            {phase.label}
          </button>
        );
      })}
    </nav>
  );
}
