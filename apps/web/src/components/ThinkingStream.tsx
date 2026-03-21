"use client";

import { useMemo, useRef, useEffect } from "react";
import type { RunEvent } from "@/lib/api";

interface ThinkingStreamProps {
  events: RunEvent[];
  runStatus: string;
  currentStep: string | null;
  progressPct: number;
  mode?: string;
}

/* ── Stage display names ── */
const STAGE_LABELS: Record<string, string> = {
  scope_definition: "Defining scope",
  candidate_retrieval: "Searching papers",
  scope_pruning: "Filtering candidates",
  deep_reading: "Reading papers",
  comparison_build: "Building comparison",
  pain_mining: "Mining pain points",
  frontier_summary: "Generating summary",
  plan_atlas: "Planning exploration",
  retrieve_classics: "Finding classics",
  build_timeline: "Building timeline",
  build_taxonomy: "Building taxonomy",
  read_representatives: "Reading papers",
  extract_figures: "Extracting figures",
  generate_reading_path: "Creating reading path",
  synthesize_atlas: "Synthesizing atlas",
  normalize_pain_package: "Normalizing pain points",
  analogical_retrieval: "Cross-domain search",
  method_transfer_screening: "Screening methods",
  idea_composition: "Composing ideas",
  prior_art_check: "Checking prior art",
  feasibility_review: "Reviewing feasibility",
  idea_portfolio: "Building portfolio",
};

/* ── Action icons ── */
function ActionIcon({ action }: { action: string }) {
  if (action === "searching" || action === "search" || action === "citation_chain")
    return <span className="text-[13px]">🔍</span>;
  if (action === "reading")
    return <span className="text-[13px]">📖</span>;
  if (action === "llm_call" || action === "analyzing")
    return <span className="text-[13px]">🧠</span>;
  if (action === "done" || action === "search_done" || action === "result")
    return <span className="text-[13px]">✓</span>;
  if (action === "start")
    return <span className="text-[13px]">→</span>;
  if (action === "seeds" || action === "keywords")
    return <span className="text-[13px]">📌</span>;
  return <span className="text-[13px]">·</span>;
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return ""; }
}

export default function ThinkingStream({ events, runStatus, currentStep, progressPct, mode }: ThinkingStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isTerminal = ["completed", "failed", "cancelled"].includes(runStatus);

  // Filter to progress events only (fine-grained actions)
  const progressEvents = useMemo(() => {
    return events
      .filter((e) => e.event_type.startsWith("progress."))
      .reverse(); // oldest first
  }, [events]);

  // Derive current stage from latest progress event or currentStep
  const currentStage = useMemo(() => {
    if (progressEvents.length > 0) {
      const latest = progressEvents[progressEvents.length - 1];
      return latest.payload?.stage as string || "";
    }
    return currentStep?.replace(/_init$/, "") || "";
  }, [progressEvents, currentStep]);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [progressEvents.length]);

  if (runStatus === "queued") {
    return (
      <div className="card-static p-5">
        <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
          <span className="h-2 w-2 rounded-full bg-[var(--text-muted)]" />
          Queued — waiting for worker...
        </div>
      </div>
    );
  }

  return (
    <div className="card-static overflow-hidden">
      {/* Header with current stage */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2.5">
          {runStatus === "running" && (
            <div className="h-4 w-4 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
          )}
          {isTerminal && runStatus === "completed" && (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="7" fill="var(--accent-green-soft)" />
              <path d="M5 8L7 10L11 6" stroke="var(--accent-green)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
          {isTerminal && runStatus === "failed" && (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="7" fill="var(--accent-red-soft)" />
              <path d="M5.5 5.5L10.5 10.5M10.5 5.5L5.5 10.5" stroke="var(--accent-red)" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          )}
          <div>
            <span className="text-[13px] font-medium text-[var(--text-primary)]">
              {isTerminal
                ? runStatus === "completed" ? "Research complete" : `Research ${runStatus}`
                : STAGE_LABELS[currentStage] || "Processing..."
              }
            </span>
          </div>
        </div>
        {progressPct > 0 && (
          <span className="text-[11px] text-[var(--text-muted)]" style={{ fontFamily: "var(--font-mono)" }}>
            {Math.round(progressPct)}%
          </span>
        )}
      </div>

      {/* Action log — live stream of fine-grained events */}
      <div ref={scrollRef} className="max-h-[280px] overflow-y-auto px-5 py-3">
        {progressEvents.length === 0 && !isTerminal ? (
          <div className="flex items-center gap-2 py-3 text-[12px] text-[var(--text-muted)] italic">
            <div className="h-3 w-3 rounded-full border border-[var(--accent)] border-t-transparent animate-spin" />
            Initializing research pipeline...
          </div>
        ) : (
          <div className="space-y-0.5">
            {progressEvents.map((ev, idx) => {
              const stage = (ev.payload?.stage as string) || "";
              const action = (ev.payload?.action as string) || "";
              const message = (ev.payload?.message as string) || ev.event_type;
              const isDone = action === "done" || action === "search_done" || action === "result";
              const isStart = action === "start";

              return (
                <div
                  key={`${ev.event_type}-${ev.timestamp}-${idx}`}
                  className={`flex items-start gap-2 py-1 ${isStart ? "mt-2 first:mt-0" : ""}`}
                >
                  {/* Icon */}
                  <div className="w-5 shrink-0 flex items-center justify-center mt-0.5">
                    <ActionIcon action={action} />
                  </div>

                  {/* Message */}
                  <span className={`text-[12px] leading-relaxed flex-1 ${
                    isDone ? "text-[var(--accent-green)] font-medium" :
                    isStart ? "text-[var(--text-primary)] font-medium" :
                    "text-[var(--text-muted)]"
                  }`}>
                    {message}
                  </span>

                  {/* Timestamp */}
                  <span className="text-[10px] text-[var(--text-muted)] shrink-0 mt-0.5" style={{ fontFamily: "var(--font-mono)" }}>
                    {formatTime(ev.timestamp)}
                  </span>
                </div>
              );
            })}

            {/* Active indicator at bottom when running */}
            {runStatus === "running" && (
              <div className="flex items-center gap-2 py-1 mt-1">
                <div className="w-5 shrink-0 flex items-center justify-center">
                  <div className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-pulse-dot" />
                </div>
                <span className="text-[12px] text-[var(--text-muted)] italic">
                  working...
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer with stats */}
      {events.length > 0 && (
        <div className="px-5 py-2 border-t border-[var(--border-subtle)] flex items-center gap-3 text-[10px] text-[var(--text-muted)]">
          <span>{progressEvents.length} actions</span>
          {(() => {
            // Find latest token count from progress events
            const withTokens = progressEvents.filter(e => e.payload?.tokens);
            const latestTokens = withTokens.length > 0 ? (withTokens[withTokens.length - 1].payload?.tokens as number) : 0;
            // Also check run.completed event for final token count
            const completed = events.find(e => e.event_type === "run.completed");
            const finalTokens = (completed?.payload?.total_tokens as number) || latestTokens;
            return finalTokens > 0 ? (
              <span style={{ fontFamily: "var(--font-mono)" }}>
                {finalTokens.toLocaleString()} tokens
              </span>
            ) : null;
          })()}
          {events.filter(e => e.severity === "error").length > 0 && (
            <span className="text-[var(--accent-red)]">
              {events.filter(e => e.severity === "error").length} errors
            </span>
          )}
        </div>
      )}
    </div>
  );
}
