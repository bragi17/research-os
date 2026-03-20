"use client";

import type { PainPoint } from "@/lib/api";

interface PainPointCardProps {
  painPoint: PainPoint;
  index: number;
}

const TYPE_COLORS: Record<string, string> = {
  scalability: "var(--accent-red)",
  accuracy: "var(--accent-amber)",
  efficiency: "var(--accent-purple)",
  generalization: "var(--accent-cyan)",
  interpretability: "var(--accent-green)",
};

export default function PainPointCard({ painPoint, index }: PainPointCardProps) {
  const color = TYPE_COLORS[painPoint.pain_type] ?? "var(--accent-cyan)";
  const severityPct = Math.round(painPoint.severity_score * 100);
  const noveltyPct = Math.round(painPoint.novelty_potential * 100);

  return (
    <div
      className="glass-card p-4 animate-fade-up"
      style={{
        animationDelay: `${100 + index * 60}ms`,
        borderLeftWidth: "3px",
        borderLeftColor: color,
      }}
    >
      {/* Type tag */}
      <div className="flex items-center gap-2 mb-2">
        <span
          className="text-[9px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded"
          style={{ background: `${color}18`, color }}
        >
          {painPoint.pain_type.replace(/_/g, " ")}
        </span>
      </div>

      {/* Statement */}
      <p className="text-xs text-[var(--text-primary)] leading-relaxed mb-3">
        {painPoint.statement}
      </p>

      {/* Severity bar */}
      <div className="space-y-2">
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-[var(--text-muted)]">Severity</span>
            <span
              className="text-[10px] font-semibold tabular-nums"
              style={{ color, fontFamily: "var(--font-mono)" }}
            >
              {severityPct}%
            </span>
          </div>
          <div className="h-1 rounded-full bg-[rgba(148,163,184,0.08)] overflow-hidden">
            <div
              className="h-full rounded-full animate-bar-fill"
              style={{
                width: `${severityPct}%`,
                background: color,
              }}
            />
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-[var(--text-muted)]">Novelty Potential</span>
            <span
              className="text-[10px] font-semibold tabular-nums"
              style={{ color: "var(--accent-purple)", fontFamily: "var(--font-mono)" }}
            >
              {noveltyPct}%
            </span>
          </div>
          <div className="h-1 rounded-full bg-[rgba(148,163,184,0.08)] overflow-hidden">
            <div
              className="h-full rounded-full animate-bar-fill"
              style={{
                width: `${noveltyPct}%`,
                background: "linear-gradient(90deg, var(--accent-purple), var(--accent-cyan))",
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
