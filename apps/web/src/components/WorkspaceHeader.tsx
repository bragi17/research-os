"use client";

import Link from "next/link";
import type { Run, RunMode } from "@/lib/api";

interface WorkspaceHeaderProps {
  currentRun?: Run | null;
}

const MODE_CONFIG: Record<string, { color: string; label: string; letter: string }> = {
  atlas: { color: "var(--accent-cyan)", label: "Atlas", letter: "A" },
  frontier: { color: "var(--accent-purple)", label: "Frontier", letter: "B" },
  divergent: { color: "var(--accent-amber)", label: "Divergent", letter: "C" },
  review: { color: "var(--text-secondary)", label: "Review", letter: "X" },
};

function ModeBadge({ mode }: { mode?: RunMode | string }) {
  const config = MODE_CONFIG[mode ?? ""] ?? null;
  if (!config) return null;

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider"
      style={{
        background: `${config.color}15`,
        color: config.color,
        border: `1px solid ${config.color}30`,
      }}
    >
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: config.color }}
      />
      {config.letter}: {config.label}
    </span>
  );
}

export default function WorkspaceHeader({ currentRun }: WorkspaceHeaderProps) {
  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border-subtle)] bg-[rgba(8,8,16,0.85)] backdrop-blur-xl">
      <div className="flex h-14 items-center justify-between px-4">
        {/* Left: Logo + run context */}
        <div className="flex items-center gap-4 min-w-0">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2.5 group shrink-0">
            <div className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--accent-cyan)] to-[var(--accent-purple)] shadow-[0_0_20px_rgba(6,182,212,0.3)]">
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                className="text-white"
              >
                <path
                  d="M8 1L14.5 4.75V12.25L8 16L1.5 12.25V4.75L8 1Z"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  fill="none"
                />
                <circle cx="8" cy="8.5" r="2" fill="currentColor" />
              </svg>
              <span className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-[var(--accent-green)] shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-status-pulse" />
            </div>
            <span className="text-sm font-bold tracking-tight text-[var(--text-primary)] group-hover:text-white transition-colors hidden sm:inline">
              Research OS
            </span>
          </Link>

          {/* Separator */}
          {currentRun && (
            <>
              <span className="h-5 w-px bg-[var(--border-subtle)]" />
              <ModeBadge mode={currentRun.mode} />
              <span className="text-sm font-medium text-[var(--text-primary)] truncate max-w-[200px] lg:max-w-[300px]">
                {currentRun.title}
              </span>
              <span
                className="text-[10px] px-2 py-0.5 rounded-full capitalize font-medium"
                style={{
                  background:
                    currentRun.status === "running"
                      ? "rgba(6, 182, 212, 0.1)"
                      : currentRun.status === "completed"
                        ? "rgba(16, 185, 129, 0.1)"
                        : "rgba(148, 163, 184, 0.08)",
                  color:
                    currentRun.status === "running"
                      ? "var(--accent-cyan)"
                      : currentRun.status === "completed"
                        ? "var(--accent-green)"
                        : "var(--text-secondary)",
                }}
              >
                {currentRun.status}
              </span>
            </>
          )}
        </div>

        {/* Center: Search placeholder */}
        <div className="hidden md:flex flex-1 max-w-sm mx-4">
          <div className="relative w-full">
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
            >
              <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.3" />
              <path d="M9.5 9.5L12.5 12.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              placeholder="Search runs, papers, ideas..."
              className="w-full h-8 pl-9 pr-3 rounded-lg text-xs bg-[rgba(15,23,42,0.6)] border border-[var(--border-subtle)] text-[var(--text-secondary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-cyan)] focus:shadow-[0_0_0_2px_rgba(6,182,212,0.1)] transition-all"
            />
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <Link
            href="/"
            className="px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] rounded-lg hover:bg-[rgba(148,163,184,0.06)] transition-all"
          >
            Dashboard
          </Link>
          <Link href="/new" className="btn-primary text-xs px-3 py-1.5">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M6 2V10M2 6H10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            New Research
          </Link>
        </div>
      </div>
    </header>
  );
}

export { ModeBadge, MODE_CONFIG };
