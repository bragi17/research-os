"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listRuns } from "@/lib/api";
import type { Run } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import CircularProgress from "@/components/CircularProgress";
import { MODE_CONFIG } from "@/components/WorkspaceHeader";

function timeAgo(dateStr: string): string {
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  } catch {
    return "";
  }
}

const QUICK_START = [
  {
    mode: "atlas",
    label: "Explore Field",
    description: "Map an entire research landscape",
    color: "var(--accent-cyan)",
    letter: "A",
  },
  {
    mode: "frontier",
    label: "Analyze Sub-field",
    description: "Deep-dive into methods and benchmarks",
    color: "var(--accent-purple)",
    letter: "B",
  },
  {
    mode: "divergent",
    label: "Find Innovations",
    description: "Cross-domain idea generation",
    color: "var(--accent-amber)",
    letter: "C",
  },
];

export default function Dashboard() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchRuns = async () => {
    try {
      const data = await listRuns();
      setRuns(data.items ?? []);
    } catch (e) {
      console.error("Failed to fetch runs", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
    const interval = setInterval(fetchRuns, 10000);
    return () => clearInterval(interval);
  }, []);

  const activeRuns = runs.filter((r) => r.status === "running").length;
  const completedRuns = runs.filter((r) => r.status === "completed").length;
  const totalRuns = runs.length;

  // Group runs by mode
  const groupedByMode: Record<string, Run[]> = {};
  for (const run of runs) {
    const mode = run.mode ?? "review";
    if (!groupedByMode[mode]) groupedByMode[mode] = [];
    groupedByMode[mode].push(run);
  }

  return (
    <div className="max-w-[1200px] mx-auto px-6 py-8">
      {/* Welcome section */}
      <div className="mb-10 animate-fade-up">
        <h1 className="text-3xl font-extrabold tracking-tight">
          <span className="gradient-text">Mission Control</span>
        </h1>
        <p className="mt-2 text-[var(--text-secondary)] text-sm max-w-lg">
          Autonomous Research Operating System — orchestrating AI-powered scientific discovery.
        </p>

        {/* Stats */}
        {!loading && runs.length > 0 && (
          <div className="grid grid-cols-3 gap-4 mt-6">
            <StatCard label="Total Runs" value={totalRuns} color="var(--accent-cyan)" />
            <StatCard label="Active" value={activeRuns} color="var(--accent-green)" />
            <StatCard label="Completed" value={completedRuns} color="var(--accent-purple)" />
          </div>
        )}
      </div>

      {/* Quick-start buttons */}
      <div className="mb-10 animate-fade-up delay-100">
        <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-4">
          Quick Start
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {QUICK_START.map((item, idx) => (
            <Link
              key={item.mode}
              href={`/new?mode=${item.mode}`}
              className="glass-card p-4 group animate-fade-up"
              style={{ animationDelay: `${150 + idx * 75}ms` }}
            >
              <div className="flex items-center gap-3 mb-2">
                <span
                  className="flex items-center justify-center h-8 w-8 rounded-lg text-xs font-bold"
                  style={{
                    background: `${item.color}15`,
                    color: item.color,
                  }}
                >
                  {item.letter}
                </span>
                <span className="text-sm font-semibold text-[var(--text-primary)]">
                  {item.label}
                </span>
              </div>
              <p className="text-[11px] text-[var(--text-secondary)]">{item.description}</p>
            </Link>
          ))}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
          <div className="w-8 h-8 rounded-full border-2 border-[var(--accent-cyan)] border-t-transparent animate-spin" />
          <p className="mt-4 text-sm text-[var(--text-muted)]">Loading research runs...</p>
        </div>
      ) : runs.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-8">
          {/* Recent runs grouped by mode */}
          {Object.entries(groupedByMode).map(([mode, modeRuns]) => {
            const config = MODE_CONFIG[mode] ?? { color: "var(--text-secondary)", label: mode, letter: "?" };
            return (
              <div key={mode} className="animate-fade-up">
                <div className="flex items-center gap-2 mb-3">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: config.color }}
                  />
                  <h2
                    className="text-xs font-semibold uppercase tracking-widest"
                    style={{ color: config.color }}
                  >
                    {config.label} ({modeRuns.length})
                  </h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {modeRuns.map((run, idx) => (
                    <RunCard key={run.id} run={run} index={idx} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* -- Stat Card -- */
function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="glass-card-static px-5 py-4 flex items-center gap-4">
      <div
        className="flex items-center justify-center h-10 w-10 rounded-xl"
        style={{ background: `${color}12` }}
      >
        <span className="text-lg font-bold tabular-nums" style={{ color }}>
          {value}
        </span>
      </div>
      <p className="text-xs text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
    </div>
  );
}

/* -- Run Card -- */
function RunCard({ run, index }: { run: Run; index: number }) {
  const progress =
    typeof run.progress_pct === "number"
      ? run.progress_pct
      : parseFloat(String(run.progress_pct)) || 0;
  const modeConfig = MODE_CONFIG[run.mode ?? ""] ?? null;

  return (
    <Link href={`/runs/${run.id}`}>
      <div
        className="glass-card p-5 h-full flex flex-col animate-fade-up cursor-pointer"
        style={{ animationDelay: `${100 + index * 75}ms` }}
      >
        {/* Top row: mode + status + time */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {modeConfig && (
              <span
                className="text-[9px] font-bold px-1.5 py-0.5 rounded"
                style={{
                  background: `${modeConfig.color}18`,
                  color: modeConfig.color,
                }}
              >
                {modeConfig.letter}
              </span>
            )}
            <StatusBadge status={run.status} />
          </div>
          <span className="text-[11px] text-[var(--text-muted)]">
            {timeAgo(run.updated_at || run.created_at)}
          </span>
        </div>

        {/* Title */}
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1 leading-snug">
          {run.title}
        </h3>
        <p className="text-xs text-[var(--text-secondary)] line-clamp-2 mb-4 flex-1">
          {run.topic}
        </p>

        {/* Bottom: progress ring + step */}
        <div className="flex items-center gap-4 pt-3 border-t border-[var(--border-subtle)]">
          <CircularProgress value={progress} size={44} strokeWidth={3} />
          <div className="min-w-0 flex-1">
            <p
              className="text-[11px] text-[var(--text-muted)] truncate"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {run.current_step || "Waiting..."}
            </p>
          </div>
        </div>
      </div>
    </Link>
  );
}

/* -- Empty State -- */
function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 animate-fade-up">
      <div className="relative w-28 h-28 mb-8">
        <div className="absolute inset-0 rounded-full border border-[var(--border-subtle)] animate-[spin_20s_linear_infinite]" />
        <div className="absolute inset-4 rounded-full border border-[rgba(6,182,212,0.15)]">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-[var(--accent-cyan)]" />
        </div>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-3 h-3 rounded-full bg-gradient-to-br from-[var(--accent-cyan)] to-[var(--accent-purple)] shadow-[0_0_20px_rgba(6,182,212,0.4)]" />
        </div>
      </div>
      <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">
        No research runs yet
      </h3>
      <p className="text-sm text-[var(--text-secondary)] mb-6 max-w-sm text-center">
        Create your first autonomous research task to begin AI-powered scientific discovery.
      </p>
      <Link href="/new" className="btn-primary">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M8 3V13M3 8H13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        Start Research
      </Link>
    </div>
  );
}
