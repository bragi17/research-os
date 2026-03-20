"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getRun,
  getRunEvents,
  pauseRun,
  resumeRun,
  cancelRun,
  startRun,
  subscribeToEvents,
  type Run,
  type RunEvent,
} from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import EventTimeline from "@/components/EventTimeline";
import CircularProgress from "@/components/CircularProgress";
import RightDrawer from "@/components/RightDrawer";
import { MODE_CONFIG } from "@/components/WorkspaceHeader";

function formatElapsed(startStr: string | null): string {
  if (!startStr) return "00:00:00";
  const diff = Date.now() - new Date(startStr).getTime();
  const secs = Math.floor(diff / 1000);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function RunConsole() {
  const params = useParams();
  const runId = params.id as string;
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [elapsed, setElapsed] = useState("00:00:00");
  const esRef = useRef<EventSource | null>(null);

  const fetchData = async () => {
    try {
      const [runData, eventsData] = await Promise.all([
        getRun(runId),
        getRunEvents(runId),
      ]);
      setRun(runData);
      setEvents(eventsData.events || []);
    } catch (e) {
      console.error("Failed to fetch run data", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);

    // SSE subscription
    try {
      const es = subscribeToEvents(runId, (data) => {
        setEvents((prev) => [data, ...prev]);
        fetchData();
      });
      esRef.current = es;
    } catch {
      // SSE not available
    }

    return () => {
      clearInterval(interval);
      esRef.current?.close();
    };
  }, [runId]);

  // Elapsed time ticker
  useEffect(() => {
    if (!run?.started_at || ["completed", "failed", "cancelled"].includes(run.status)) {
      if (run?.started_at) {
        setElapsed(formatElapsed(run.started_at));
      }
      return;
    }
    const tick = setInterval(() => {
      setElapsed(formatElapsed(run.started_at));
    }, 1000);
    return () => clearInterval(tick);
  }, [run?.started_at, run?.status]);

  const handleAction = async (action: string) => {
    try {
      if (action === "start") await startRun(runId);
      else if (action === "pause") await pauseRun(runId);
      else if (action === "resume") await resumeRun(runId);
      else if (action === "cancel") {
        if (confirm("Cancel this run?")) await cancelRun(runId);
      }
      fetchData();
    } catch (e) {
      console.error(e);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4 animate-fade-in">
          <div className="w-8 h-8 rounded-full border-2 border-[var(--accent-cyan)] border-t-transparent animate-spin" />
          <p className="text-sm text-[var(--text-muted)]">Loading mission data...</p>
        </div>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center animate-fade-in">
          <p className="text-[var(--accent-red)] text-sm mb-4">Run not found</p>
          <Link href="/" className="btn-secondary">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const progressPct = parseFloat(run.progress_pct) || 0;
  const isTerminal = ["completed", "failed", "cancelled"].includes(run.status);
  const modeConfig = MODE_CONFIG[run.mode ?? ""] ?? null;

  // Count events by severity
  const infoCount = events.filter((e) => e.severity === "info").length;
  const warningCount = events.filter((e) => e.severity === "warning").length;
  const errorCount = events.filter((e) => e.severity === "error").length;

  // Mode-specific links
  const modeLink = run.mode
    ? `/runs/${runId}/${run.mode}`
    : null;

  return (
    <div className="flex h-full">
      {/* Main content area */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {/* Top bar */}
        <div className="flex items-center justify-between mb-6 animate-fade-up">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M9 11L5 7L9 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Dashboard
            </Link>
            <span className="text-[var(--text-muted)]">/</span>
            <h1 className="text-lg font-bold text-[var(--text-primary)] truncate max-w-md">
              {run.title}
            </h1>
          </div>

          <div className="flex items-center gap-3">
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
            <StatusBadge status={run.status} size="md" />
            <span
              className="text-sm tabular-nums text-[var(--text-secondary)]"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {elapsed}
            </span>
          </div>
        </div>

        {/* Mode-specific results link */}
        {modeLink && (
          <div className="mb-5 animate-fade-up delay-75">
            <Link
              href={modeLink}
              className="glass-card p-4 flex items-center justify-between group"
            >
              <div className="flex items-center gap-3">
                {modeConfig && (
                  <div
                    className="h-10 w-10 rounded-xl flex items-center justify-center text-sm font-bold"
                    style={{
                      background: `${modeConfig.color}15`,
                      color: modeConfig.color,
                    }}
                  >
                    {modeConfig.letter}
                  </div>
                )}
                <div>
                  <p className="text-sm font-semibold text-[var(--text-primary)]">
                    View {modeConfig?.label ?? "Mode"} Results
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    See mode-specific analysis and outputs
                  </p>
                </div>
              </div>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-[var(--text-muted)] group-hover:text-[var(--text-primary)] transition-colors">
                <path d="M6 4L10 8L6 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </Link>
          </div>
        )}

        {/* 2-column layout: progress + event timeline */}
        <div className="grid grid-cols-12 gap-5" style={{ minHeight: "calc(100vh - 280px)" }}>
          {/* Left sidebar: Progress + controls */}
          <div className="col-span-3 space-y-4 animate-slide-in-left">
            {/* Circular progress */}
            <div className="glass-card-static p-5 flex flex-col items-center">
              <CircularProgress value={progressPct} size={100} strokeWidth={5} label="complete" />
              {run.current_step && (
                <p
                  className="text-[11px] text-[var(--text-muted)] mt-3 text-center truncate max-w-full"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {run.current_step}
                </p>
              )}
            </div>

            {/* Metrics */}
            <div className="glass-card-static p-4 space-y-3">
              <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
                Metrics
              </h3>
              <MetricRow label="Events" value={String(events.length)} color="var(--accent-cyan)" />
              <MetricRow label="Info" value={String(infoCount)} color="var(--accent-cyan)" />
              <MetricRow label="Warnings" value={String(warningCount)} color="var(--accent-amber)" />
              <MetricRow label="Errors" value={String(errorCount)} color="var(--accent-red)" />
            </div>

            {/* Controls */}
            <div className="space-y-2">
              {run.status === "queued" && (
                <button onClick={() => handleAction("start")} className="btn-primary w-full text-xs">
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M3 1.5L10 6L3 10.5V1.5Z" fill="currentColor" />
                  </svg>
                  Start
                </button>
              )}
              {run.status === "running" && (
                <button onClick={() => handleAction("pause")} className="btn-secondary w-full text-xs">
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <rect x="2.5" y="2" width="2.5" height="8" rx="0.5" fill="currentColor" />
                    <rect x="7" y="2" width="2.5" height="8" rx="0.5" fill="currentColor" />
                  </svg>
                  Pause
                </button>
              )}
              {run.status === "paused" && (
                <button onClick={() => handleAction("resume")} className="btn-primary w-full text-xs">
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M3 1.5L10 6L3 10.5V1.5Z" fill="currentColor" />
                  </svg>
                  Resume
                </button>
              )}
              {!isTerminal && (
                <button onClick={() => handleAction("cancel")} className="btn-danger w-full text-xs">
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <rect x="2.5" y="2.5" width="7" height="7" rx="1" fill="currentColor" />
                  </svg>
                  Cancel
                </button>
              )}
              <Link
                href={`/runs/${runId}/hypotheses`}
                className="btn-secondary w-full flex items-center justify-center text-xs"
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <circle cx="6" cy="4" r="2.5" stroke="currentColor" strokeWidth="1" />
                  <path d="M6 6.5V8.5M4.5 10H7.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                </svg>
                Hypotheses
              </Link>
            </div>
          </div>

          {/* Center: Event timeline */}
          <div className="col-span-9 animate-fade-up delay-100">
            <div className="glass-card-static p-5 h-full flex flex-col">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-widest">
                  Event Timeline
                </h3>
                <span
                  className="text-[11px] tabular-nums text-[var(--text-muted)]"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {events.length} events
                </span>
              </div>
              <div className="flex-1 min-h-0">
                <EventTimeline events={events} />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right drawer */}
      <RightDrawer run={run} onAction={handleAction} />
    </div>
  );
}

/* -- Metric Row -- */
function MetricRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-[var(--text-muted)]">{label}</span>
      <span
        className="text-xs font-semibold tabular-nums"
        style={{ color, fontFamily: "var(--font-mono)" }}
      >
        {value}
      </span>
    </div>
  );
}
