"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getRun,
  getPainPoints,
  getIdeaCards,
  spawnRun,
  type Run,
  type PainPoint,
  type IdeaCard,
} from "@/lib/api";
import IdeaCardDisplay from "@/components/IdeaCardDisplay";

export default function DivergentPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;

  const [run, setRun] = useState<Run | null>(null);
  const [painPoints, setPainPoints] = useState<PainPoint[]>([]);
  const [ideaCards, setIdeaCards] = useState<IdeaCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [spawning, setSpawning] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const runData = await getRun(runId);
        setRun(runData);

        const results = await Promise.allSettled([
          getPainPoints(runId),
          getIdeaCards(runId),
        ]);

        if (results[0].status === "fulfilled") setPainPoints(results[0].value.items ?? []);
        if (results[1].status === "fulfilled") setIdeaCards(results[1].value.items ?? []);
      } catch (e) {
        console.error("Failed to fetch divergent data", e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [runId]);

  const flaggedIdeas = ideaCards.filter(
    (ic) => ic.prior_art_check_status === "flagged",
  );
  const safeIdeas = ideaCards.filter(
    (ic) => ic.prior_art_check_status !== "flagged",
  );

  const handleSpawnFrontier = async () => {
    if (!run) return;
    setSpawning(true);
    try {
      const newRun = (await spawnRun(runId, {
        mode: "frontier",
        title: `Prior Art Check: ${run.topic}`,
        topic: run.topic,
      })) as { id: string };
      router.push(`/runs/${newRun.id}`);
    } catch (e) {
      console.error("Failed to spawn frontier run", e);
    } finally {
      setSpawning(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4 animate-fade-in">
          <div className="w-8 h-8 rounded-full border-2 border-[var(--accent-amber)] border-t-transparent animate-spin" />
          <p className="text-sm text-[var(--text-muted)]">Loading divergent data...</p>
        </div>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center animate-fade-in">
          <p className="text-[var(--accent-red)] text-sm mb-4">Run not found</p>
          <Link href="/" className="btn-secondary">Back to Dashboard</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6 space-y-6">
      {/* Header */}
      <div className="glass-card-static p-6 animate-fade-up">
        <div className="flex items-center gap-2 mb-3">
          <span
            className="text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider"
            style={{
              background: "rgba(245, 158, 11, 0.1)",
              color: "var(--accent-amber)",
              border: "1px solid rgba(245, 158, 11, 0.2)",
            }}
          >
            C: Divergent
          </span>
          <span
            className="text-[10px] px-2 py-0.5 rounded-full capitalize font-medium"
            style={{
              background:
                run.status === "running"
                  ? "rgba(6, 182, 212, 0.1)"
                  : run.status === "completed"
                    ? "rgba(16, 185, 129, 0.1)"
                    : "rgba(148, 163, 184, 0.08)",
              color:
                run.status === "running"
                  ? "var(--accent-cyan)"
                  : run.status === "completed"
                    ? "var(--accent-green)"
                    : "var(--text-secondary)",
            }}
          >
            {run.status}
          </span>
        </div>
        <h1 className="text-2xl font-extrabold text-[var(--text-primary)] mb-2">
          {run.title}
        </h1>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-2xl">
          {run.topic}
        </p>

        <div className="flex items-center gap-6 mt-4 pt-3 border-t border-[var(--border-subtle)]">
          <div className="text-center">
            <p className="text-lg font-bold tabular-nums text-[var(--accent-amber)]" style={{ fontFamily: "var(--font-mono)" }}>
              {ideaCards.length}
            </p>
            <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">Idea Cards</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold tabular-nums text-[var(--accent-purple)]" style={{ fontFamily: "var(--font-mono)" }}>
              {painPoints.length}
            </p>
            <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">Pain Points</p>
          </div>
          {flaggedIdeas.length > 0 && (
            <div className="text-center">
              <p className="text-lg font-bold tabular-nums text-[var(--accent-red)]" style={{ fontFamily: "var(--font-mono)" }}>
                {flaggedIdeas.length}
              </p>
              <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">Prior Art Warnings</p>
            </div>
          )}
        </div>
      </div>

      {/* Problem signature (pain points) */}
      {painPoints.length > 0 && (
        <div className="animate-fade-up delay-100">
          <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
            Problem Signature
          </h3>
          <div className="glass-card-static p-4">
            <div className="space-y-3">
              {painPoints.map((pp) => (
                <div key={pp.id} className="flex items-start gap-3">
                  <span
                    className="h-2 w-2 rounded-full shrink-0 mt-1.5"
                    style={{ background: "var(--accent-amber)" }}
                  />
                  <div>
                    <p className="text-xs text-[var(--text-primary)]">{pp.statement}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[9px] text-[var(--text-muted)] capitalize">
                        {pp.pain_type.replace(/_/g, " ")}
                      </span>
                      <span
                        className="text-[9px] tabular-nums"
                        style={{ color: "var(--accent-red)", fontFamily: "var(--font-mono)" }}
                      >
                        severity: {Math.round(pp.severity_score * 100)}%
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Prior art warnings */}
      {flaggedIdeas.length > 0 && (
        <div className="animate-fade-up delay-200">
          <h3 className="text-[10px] font-semibold text-[var(--accent-red)] uppercase tracking-widest mb-3">
            Prior Art Warnings ({flaggedIdeas.length})
          </h3>
          <div className="glass-card-static p-4 border-l-2" style={{ borderLeftColor: "var(--accent-red)" }}>
            <div className="space-y-3">
              {flaggedIdeas.map((idea) => (
                <div key={idea.id} className="flex items-start gap-3">
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="shrink-0 mt-0.5">
                    <path d="M7 1L13 12H1L7 1Z" stroke="var(--accent-red)" strokeWidth="1.2" strokeLinejoin="round" />
                    <path d="M7 5V8" stroke="var(--accent-red)" strokeWidth="1.2" strokeLinecap="round" />
                    <circle cx="7" cy="10" r="0.5" fill="var(--accent-red)" />
                  </svg>
                  <div>
                    <p className="text-xs font-medium text-[var(--text-primary)]">{idea.title}</p>
                    <p className="text-[10px] text-[var(--text-secondary)] mt-0.5">
                      This idea may overlap with existing work. Additional prior art check recommended.
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Idea cards */}
      {safeIdeas.length > 0 && (
        <div className="animate-fade-up delay-300">
          <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
            Innovation Ideas ({safeIdeas.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {safeIdeas.map((idea, idx) => (
              <IdeaCardDisplay key={idea.id} idea={idea} index={idx} />
            ))}
          </div>
        </div>
      )}

      {ideaCards.length === 0 && painPoints.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 animate-fade-up delay-200">
          <div className="w-16 h-16 rounded-full border border-[var(--border-subtle)] flex items-center justify-center mb-4">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="text-[var(--text-muted)]">
              <path d="M12 2V12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M12 12L20 20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M12 12L4 20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">No divergent results yet.</p>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            Results will appear as the run progresses.
          </p>
        </div>
      )}

      {/* CTA */}
      <div className="glass-card-static p-6 text-center animate-fade-up delay-400">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
          Want to verify these ideas?
        </h3>
        <p className="text-xs text-[var(--text-secondary)] mb-4 max-w-md mx-auto">
          Spawn a Mode B (Frontier) run to do a deeper prior art check on the most promising ideas.
        </p>
        <button
          onClick={handleSpawnFrontier}
          disabled={spawning}
          className="btn-primary"
          style={{ background: "linear-gradient(135deg, var(--accent-purple), #6d28d9)" }}
        >
          {spawning ? (
            <span className="flex items-center gap-2">
              <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              Spawning...
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5" />
                <path d="M7 4V7L9 8.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
              Check prior art further
            </span>
          )}
        </button>
      </div>
    </div>
  );
}
