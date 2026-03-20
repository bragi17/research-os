"use client";

import type { IdeaCard } from "@/lib/api";

interface IdeaCardDisplayProps {
  idea: IdeaCard;
  index: number;
}

const STATUS_STYLES: Record<string, { background: string; color: string }> = {
  draft: { background: "rgba(148, 163, 184, 0.08)", color: "var(--text-secondary)" },
  validated: { background: "rgba(16, 185, 129, 0.1)", color: "var(--accent-green)" },
  rejected: { background: "rgba(239, 68, 68, 0.1)", color: "var(--accent-red)" },
  promising: { background: "rgba(6, 182, 212, 0.1)", color: "var(--accent-cyan)" },
};

export default function IdeaCardDisplay({ idea, index }: IdeaCardDisplayProps) {
  const noveltyPct = Math.round(idea.novelty_score * 100);
  const feasibilityPct = Math.round(idea.feasibility_score * 100);
  const statusStyle = STATUS_STYLES[idea.status] ?? STATUS_STYLES.draft;

  return (
    <div
      className="glass-card p-5 animate-fade-up"
      style={{
        animationDelay: `${100 + index * 75}ms`,
        borderTopWidth: "2px",
        borderTopColor: "var(--accent-amber)",
      }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span
          className="text-[9px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded"
          style={statusStyle}
        >
          {idea.status}
        </span>
        {idea.prior_art_check_status === "flagged" && (
          <span
            className="text-[9px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded"
            style={{ background: "rgba(239, 68, 68, 0.1)", color: "var(--accent-red)" }}
          >
            Prior Art Risk
          </span>
        )}
      </div>

      {/* Title */}
      <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-2 leading-snug">
        {idea.title}
      </h4>

      {/* Problem */}
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-3">
        {idea.problem_statement}
      </p>

      {/* Transfer info */}
      {idea.borrowed_methods.length > 0 && (
        <div className="mb-3">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
            Borrowed Methods
          </span>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {idea.borrowed_methods.map((m) => (
              <span
                key={m}
                className="text-[10px] px-2 py-0.5 rounded-full"
                style={{
                  background: "rgba(6, 182, 212, 0.08)",
                  color: "var(--accent-cyan)",
                  border: "1px solid rgba(6, 182, 212, 0.15)",
                }}
              >
                {m}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Source domains */}
      {idea.source_domains.length > 0 && (
        <div className="mb-3">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
            Source Domains
          </span>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {idea.source_domains.map((d) => (
              <span
                key={d}
                className="text-[10px] px-2 py-0.5 rounded-full"
                style={{
                  background: "rgba(139, 92, 246, 0.08)",
                  color: "var(--accent-purple)",
                  border: "1px solid rgba(139, 92, 246, 0.15)",
                }}
              >
                {d}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Expected benefit */}
      {idea.expected_benefit && (
        <p className="text-[11px] text-[var(--accent-green)] mb-3 leading-relaxed">
          {idea.expected_benefit}
        </p>
      )}

      {/* Scores */}
      <div className="grid grid-cols-2 gap-3 pt-3 border-t border-[var(--border-subtle)]">
        <ScoreMini label="Novelty" value={noveltyPct} color="var(--accent-amber)" />
        <ScoreMini label="Feasibility" value={feasibilityPct} color="var(--accent-cyan)" />
      </div>
    </div>
  );
}

function ScoreMini({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-[var(--text-muted)]">{label}</span>
        <span
          className="text-[10px] font-semibold tabular-nums"
          style={{ color, fontFamily: "var(--font-mono)" }}
        >
          {value}%
        </span>
      </div>
      <div className="h-1 rounded-full bg-[rgba(148,163,184,0.08)] overflow-hidden">
        <div
          className="h-full rounded-full animate-bar-fill"
          style={{ width: `${value}%`, background: color }}
        />
      </div>
    </div>
  );
}
