"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listRuns, type Run } from "@/lib/api";
import { MODE_CONFIG } from "./WorkspaceHeader";

interface LeftResearchTreeProps {
  activeRunId?: string;
}

function timeAgo(dateStr: string): string {
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "now";
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    const days = Math.floor(hrs / 24);
    return `${days}d`;
  } catch {
    return "";
  }
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "running"
      ? "var(--accent-cyan)"
      : status === "completed"
        ? "var(--accent-green)"
        : status === "failed"
          ? "var(--accent-red)"
          : status === "paused"
            ? "var(--accent-amber)"
            : "var(--text-muted)";

  return (
    <span
      className={`h-1.5 w-1.5 rounded-full shrink-0 ${status === "running" ? "animate-status-pulse" : ""}`}
      style={{ background: color }}
    />
  );
}

function ModeDot({ mode }: { mode?: string }) {
  const config = MODE_CONFIG[mode ?? ""] ?? null;
  if (!config) return null;

  return (
    <span
      className="text-[8px] font-bold shrink-0 h-4 w-4 rounded flex items-center justify-center"
      style={{
        background: `${config.color}18`,
        color: config.color,
      }}
    >
      {config.letter}
    </span>
  );
}

export default function LeftResearchTree({ activeRunId }: LeftResearchTreeProps) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    running: true,
    completed: true,
    queued: true,
  });

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        const data = await listRuns();
        setRuns(data.items ?? []);
      } catch {
        // Silently fail
      }
    };
    fetchRuns();
    const interval = setInterval(fetchRuns, 15000);
    return () => clearInterval(interval);
  }, []);

  const groups: Record<string, Run[]> = {
    running: runs.filter((r) => r.status === "running"),
    paused: runs.filter((r) => r.status === "paused"),
    queued: runs.filter((r) => r.status === "queued"),
    completed: runs.filter((r) => r.status === "completed"),
    failed: runs.filter((r) => r.status === "failed" || r.status === "cancelled"),
  };

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  if (collapsed) {
    return (
      <aside className="w-12 shrink-0 border-r border-[var(--border-subtle)] bg-[rgba(8,8,16,0.6)] backdrop-blur-md flex flex-col items-center pt-3">
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded-lg hover:bg-[rgba(148,163,184,0.08)] transition-colors text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          title="Expand sidebar"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M5 3L9 7L5 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </aside>
    );
  }

  return (
    <aside className="w-[280px] shrink-0 border-r border-[var(--border-subtle)] bg-[rgba(8,8,16,0.6)] backdrop-blur-md flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
        <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
          Research Runs
        </span>
        <button
          onClick={() => setCollapsed(true)}
          className="p-1 rounded hover:bg-[rgba(148,163,184,0.08)] transition-colors text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          title="Collapse sidebar"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M8 2L4 6L8 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {/* Scrollable tree */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
        {Object.entries(groups).map(([key, groupRuns]) => {
          if (groupRuns.length === 0) return null;
          const isExpanded = expandedSections[key] !== false;

          return (
            <div key={key}>
              <button
                onClick={() => toggleSection(key)}
                className="flex items-center gap-2 w-full px-2 py-1.5 rounded-lg text-left hover:bg-[rgba(148,163,184,0.06)] transition-colors group"
              >
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 10 10"
                  fill="none"
                  className="transition-transform duration-200 shrink-0"
                  style={{ transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)" }}
                >
                  <path
                    d="M3 1.5L7 5L3 8.5"
                    stroke="var(--text-muted)"
                    strokeWidth="1.3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider capitalize">
                  {key}
                </span>
                <span
                  className="text-[9px] text-[var(--text-muted)] ml-auto tabular-nums"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {groupRuns.length}
                </span>
              </button>

              {isExpanded && (
                <div className="ml-1 space-y-0.5 mt-0.5">
                  {groupRuns.map((run) => {
                    const isActive = run.id === activeRunId;
                    return (
                      <Link
                        key={run.id}
                        href={`/runs/${run.id}`}
                        className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-all duration-200 group"
                        style={{
                          background: isActive ? "rgba(6, 182, 212, 0.08)" : "transparent",
                          borderLeft: isActive ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                        }}
                      >
                        <ModeDot mode={run.mode} />
                        <StatusDot status={run.status} />
                        <span
                          className="text-xs truncate flex-1 transition-colors"
                          style={{
                            color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                          }}
                        >
                          {run.title}
                        </span>
                        <span
                          className="text-[9px] text-[var(--text-muted)] shrink-0 tabular-nums"
                          style={{ fontFamily: "var(--font-mono)" }}
                        >
                          {timeAgo(run.updated_at || run.created_at)}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {runs.length === 0 && (
          <div className="text-center py-8">
            <p className="text-xs text-[var(--text-muted)]">No runs yet</p>
            <Link
              href="/new"
              className="text-[11px] text-[var(--accent-cyan)] hover:underline mt-1 inline-block"
            >
              Create your first run
            </Link>
          </div>
        )}
      </div>
    </aside>
  );
}
