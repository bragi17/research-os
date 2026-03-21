"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getRun, getRunEvents, getRunPapers,
  pauseRun, resumeRun, cancelRun, startRun,
  subscribeToEvents,
  type Run, type RunEvent, type Paper,
} from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import ThinkingStream from "@/components/ThinkingStream";
import ResearchPlan from "@/components/ResearchPlan";

function formatElapsed(startStr: string | null): string {
  if (!startStr) return "0:00";
  const diff = Date.now() - new Date(startStr).getTime();
  const secs = Math.floor(diff / 1000);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

const MODE_LABELS: Record<string, string> = {
  atlas: "Atlas", frontier: "Frontier", divergent: "Divergent", review: "Review",
};

export default function RunConsole() {
  const params = useParams();
  const runId = params.id as string;
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [elapsed, setElapsed] = useState("0:00");
  const esRef = useRef<EventSource | null>(null);

  const fetchData = async () => {
    try {
      const [runData, eventsData] = await Promise.all([getRun(runId), getRunEvents(runId)]);
      setRun(runData);
      setEvents(eventsData.events || []);
      if (runData.status === "running" || runData.status === "completed") {
        try { setPapers((await getRunPapers(runId)) ?? []); } catch {}
      }
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    try {
      const es = subscribeToEvents(runId, (data) => { setEvents((prev) => [data, ...prev]); fetchData(); });
      esRef.current = es;
    } catch {}
    return () => { clearInterval(interval); esRef.current?.close(); };
  }, [runId]);

  useEffect(() => {
    if (!run?.started_at || ["completed", "failed", "cancelled"].includes(run.status)) {
      if (run?.started_at) setElapsed(formatElapsed(run.started_at));
      return;
    }
    const tick = setInterval(() => setElapsed(formatElapsed(run.started_at)), 1000);
    return () => clearInterval(tick);
  }, [run?.started_at, run?.status]);

  const handleAction = async (action: string) => {
    try {
      if (action === "start") await startRun(runId);
      else if (action === "pause") await pauseRun(runId);
      else if (action === "resume") await resumeRun(runId);
      else if (action === "cancel") { if (confirm("Cancel this run?")) await cancelRun(runId); }
      fetchData();
    } catch (e) { console.error(e); }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-5 w-5 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <p className="text-[var(--accent-red)] text-sm mb-4">Run not found</p>
          <Link href="/" className="btn-secondary">Back</Link>
        </div>
      </div>
    );
  }

  const progressPct = parseFloat(String(run.progress_pct)) || 0;
  const isTerminal = ["completed", "failed", "cancelled"].includes(run.status);
  const modeLink = run.mode ? `/runs/${runId}/${run.mode}` : null;

  return (
        <div className="max-w-[700px] mx-auto px-8 py-8">
          {/* Header */}
          <div className="flex items-start justify-between mb-6 animate-fade-up">
            <div className="flex-1 min-w-0">
              <h1
                className="text-[22px] font-medium text-[var(--text-primary)] mb-1"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {run.title}
              </h1>
              <div className="flex items-center gap-3 text-[13px] text-[var(--text-muted)]">
                {run.mode && (
                  <span className="font-medium" style={{ color: "var(--accent)" }}>
                    {MODE_LABELS[run.mode] ?? run.mode}
                  </span>
                )}
                <StatusBadge status={run.status} size="sm" />
                <span style={{ fontFamily: "var(--font-mono)" }}>{elapsed}</span>
              </div>
            </div>
          </div>

          {/* Research Plan */}
          <div className="mb-5 animate-fade-up delay-75">
            <ResearchPlan mode={run.mode ?? "review"} topic={run.topic} isExecuting={run.status === "running"} />
          </div>

          {/* Thinking Stream */}
          <div className="mb-5 animate-fade-up delay-150">
            <ThinkingStream events={events} runStatus={run.status} currentStep={run.current_step} progressPct={progressPct} mode={run.mode ?? undefined} />
          </div>

          {/* Results */}
          {(papers.length > 0 || isTerminal || modeLink) && (
            <div className="card-static p-5 mb-5 animate-fade-up delay-200">
              <h3 className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
                Results
              </h3>
              {papers.length > 0 && (
                <div className="space-y-2 mb-4">
                  <p className="text-[12px] text-[var(--text-secondary)]">
                    {papers.length} paper{papers.length !== 1 ? "s" : ""} found
                  </p>
                  {papers.slice(0, 5).map((paper) => (
                    <div key={paper.id} className="p-3 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--accent)] transition-colors">
                      <h4 className="text-[13px] font-medium text-[var(--text-primary)] leading-snug mb-1">{paper.title}</h4>
                      <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
                        {paper.authors?.length > 0 && <span className="truncate max-w-[200px]">{paper.authors.slice(0, 3).join(", ")}{paper.authors.length > 3 ? " et al." : ""}</span>}
                        {paper.year && <span style={{ fontFamily: "var(--font-mono)" }}>{paper.year}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {modeLink && (
                <Link href={modeLink} className="flex items-center justify-between p-3 rounded-lg border border-[var(--border-subtle)] hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] transition-all group">
                  <span className="text-[13px] font-medium text-[var(--text-primary)]">
                    View full {MODE_LABELS[run.mode ?? ""] ?? "mode"} results
                  </span>
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-[var(--text-muted)] group-hover:text-[var(--accent)] transition-colors">
                    <path d="M5 3L9 7L5 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </Link>
              )}
              {papers.length === 0 && !isTerminal && (
                <p className="text-[12px] text-[var(--text-muted)] text-center py-4">
                  Results will appear here as they are generated...
                </p>
              )}
            </div>
          )}

          {/* Controls */}
          <div className="flex items-center gap-2 animate-fade-up delay-300">
            {run.status === "queued" && <button onClick={() => handleAction("start")} className="btn-primary text-[13px]">Start</button>}
            {run.status === "running" && <button onClick={() => handleAction("pause")} className="btn-secondary text-[13px]">Pause</button>}
            {run.status === "paused" && <button onClick={() => handleAction("resume")} className="btn-primary text-[13px]">Resume</button>}
            {!isTerminal && <button onClick={() => handleAction("cancel")} className="btn-danger text-[13px]">Cancel</button>}
          </div>
        </div>
  );
}
