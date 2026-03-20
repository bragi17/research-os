"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getRunHypotheses, getRun } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import ScoreBar from "@/components/ScoreBar";

interface Hypothesis {
  id: string;
  title: string;
  statement: string;
  type: string;
  status: string;
  novelty_score: number;
  feasibility_score: number;
  evidence_score: number;
  risk_score: number;
}

const TYPE_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  bridge: {
    border: "var(--accent-cyan)",
    bg: "rgba(6, 182, 212, 0.08)",
    text: "var(--accent-cyan)",
  },
  assumption_relaxation: {
    border: "var(--accent-purple)",
    bg: "rgba(139, 92, 246, 0.08)",
    text: "var(--accent-purple)",
  },
  metric_gap: {
    border: "var(--accent-amber)",
    bg: "rgba(245, 158, 11, 0.08)",
    text: "var(--accent-amber)",
  },
  transfer: {
    border: "var(--accent-green)",
    bg: "rgba(16, 185, 129, 0.08)",
    text: "var(--accent-green)",
  },
  negative_result_exploitation: {
    border: "var(--accent-red)",
    bg: "rgba(239, 68, 68, 0.08)",
    text: "var(--accent-red)",
  },
};

const DEFAULT_TYPE_COLOR = {
  border: "var(--text-muted)",
  bg: "rgba(148, 163, 184, 0.08)",
  text: "var(--text-secondary)",
};

export default function HypothesesPage() {
  const params = useParams();
  const runId = params.id as string;
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [runTitle, setRunTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [hyps, run] = await Promise.all([
          getRunHypotheses(runId) as Promise<Hypothesis[]>,
          getRun(runId) as Promise<{ title: string }>,
        ]);
        setHypotheses(hyps);
        setRunTitle(run.title);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    })();
  }, [runId]);

  const uniqueTypes = Array.from(new Set(hypotheses.map((h) => h.type)));
  const uniqueStatuses = Array.from(new Set(hypotheses.map((h) => h.status)));

  const filtered = hypotheses.filter((h) => {
    if (filterType && h.type !== filterType) return false;
    if (filterStatus && h.status !== filterStatus) return false;
    return true;
  });

  const toggleExpanded = useCallback(
    (id: string) => setExpanded((prev) => (prev === id ? null : id)),
    [],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4 animate-fade-in">
          <div className="w-8 h-8 rounded-full border-2 border-[var(--accent-purple)] border-t-transparent animate-spin" />
          <p className="text-sm text-[var(--text-muted)]">Loading hypotheses...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-8">
      {/* Header */}
      <div className="mb-8 animate-fade-up">
        <Link
          href={`/runs/${runId}`}
          className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors mb-4"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M9 11L5 7L9 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back to {runTitle}
        </Link>
        <h1 className="text-3xl font-extrabold tracking-tight">
          <span className="gradient-text">Innovation Hypotheses</span>
        </h1>
        <p className="text-[var(--text-secondary)] text-sm mt-1">
          {hypotheses.length} hypothesis{hypotheses.length !== 1 ? "es" : ""} generated
        </p>
      </div>

      {hypotheses.length === 0 ? (
        /* Empty state */
        <div className="flex flex-col items-center justify-center py-24 animate-fade-up">
          <div className="relative w-24 h-24 mb-6">
            <div className="absolute inset-0 rounded-full border border-[var(--border-subtle)]" />
            <div className="absolute inset-0 flex items-center justify-center">
              <svg width="32" height="32" viewBox="0 0 32 32" fill="none" className="text-[var(--text-muted)]">
                <circle cx="16" cy="12" r="6" stroke="currentColor" strokeWidth="1.5" />
                <path d="M16 18V24M12 28H20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </div>
          </div>
          <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">
            No hypotheses yet
          </h3>
          <p className="text-sm text-[var(--text-secondary)] max-w-sm text-center">
            Hypotheses are generated during the deep reading and analysis phases of the research run.
          </p>
        </div>
      ) : (
        <>
          {/* Filter pills */}
          <div className="flex flex-wrap gap-2 mb-6 animate-fade-up delay-100">
            {/* Type filters */}
            <FilterPill
              label="All Types"
              active={filterType === null}
              onClick={() => setFilterType(null)}
            />
            {uniqueTypes.map((t) => (
              <FilterPill
                key={t}
                label={t.replace(/_/g, " ")}
                active={filterType === t}
                color={(TYPE_COLORS[t] ?? DEFAULT_TYPE_COLOR).text}
                onClick={() => setFilterType(filterType === t ? null : t)}
              />
            ))}

            <span className="w-px h-6 bg-[var(--border-subtle)] mx-1 self-center" />

            {/* Status filters */}
            {uniqueStatuses.map((s) => (
              <FilterPill
                key={s}
                label={s}
                active={filterStatus === s}
                onClick={() => setFilterStatus(filterStatus === s ? null : s)}
              />
            ))}
          </div>

          {/* Cards grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((h, idx) => {
              const typeColor = TYPE_COLORS[h.type] ?? DEFAULT_TYPE_COLOR;
              const isExpanded = expanded === h.id;

              return (
                <div
                  key={h.id}
                  className="glass-card p-0 overflow-hidden cursor-pointer animate-fade-up"
                  style={{
                    animationDelay: `${100 + idx * 60}ms`,
                    borderTopWidth: "2px",
                    borderTopColor: typeColor.border,
                  }}
                  onClick={() => toggleExpanded(h.id)}
                >
                  <div className="p-5">
                    {/* Tags row */}
                    <div className="flex items-center gap-2 mb-3 flex-wrap">
                      <span
                        className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md"
                        style={{
                          background: typeColor.bg,
                          color: typeColor.text,
                        }}
                      >
                        {h.type.replace(/_/g, " ")}
                      </span>
                      <StatusBadge status={h.status} />
                    </div>

                    {/* Title */}
                    <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2 leading-snug">
                      {h.title}
                    </h3>

                    {/* Statement preview */}
                    {!isExpanded && (
                      <p className="text-xs text-[var(--text-secondary)] line-clamp-2 mb-4">
                        {h.statement}
                      </p>
                    )}

                    {/* Expanded content */}
                    {isExpanded && (
                      <div className="mb-4 animate-fade-in">
                        <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                          {h.statement}
                        </p>
                      </div>
                    )}

                    {/* Score bars */}
                    <div className="space-y-2.5 pt-3 border-t border-[var(--border-subtle)]">
                      <ScoreBar label="Novelty" value={h.novelty_score} />
                      <ScoreBar label="Feasibility" value={h.feasibility_score} />
                      <ScoreBar label="Evidence" value={h.evidence_score} />
                      <ScoreBar label="Risk" value={h.risk_score} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Filter Pill ── */
function FilterPill({
  label,
  active,
  color,
  onClick,
}: {
  label: string;
  active: boolean;
  color?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-3 py-1 rounded-full text-[11px] font-medium capitalize transition-all duration-200 border"
      style={{
        background: active
          ? `${color ?? "var(--accent-cyan)"}18`
          : "transparent",
        borderColor: active
          ? `${color ?? "var(--accent-cyan)"}40`
          : "var(--border-subtle)",
        color: active
          ? color ?? "var(--accent-cyan)"
          : "var(--text-muted)",
      }}
    >
      {label}
    </button>
  );
}
