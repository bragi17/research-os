"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getRun,
  getPainPoints,
  getComparison,
  getRunPapers,
  spawnRun,
  type Run,
  type PainPoint,
  type Paper,
} from "@/lib/api";
import PainPointCard from "@/components/PainPointCard";
import ComparisonTable from "@/components/ComparisonTable";

export default function FrontierPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;

  const [run, setRun] = useState<Run | null>(null);
  const [painPoints, setPainPoints] = useState<PainPoint[]>([]);
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [spawning, setSpawning] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const runData = await getRun(runId);
        setRun(runData);

        const results = await Promise.allSettled([
          getPainPoints(runId),
          getComparison(runId),
          getRunPapers(runId),
        ]);

        if (results[0].status === "fulfilled") setPainPoints(results[0].value.items ?? []);
        if (results[1].status === "fulfilled") setComparison(results[1].value.comparison ?? null);
        if (results[2].status === "fulfilled") {
          const papersData = results[2].value;
          setPapers(Array.isArray(papersData) ? papersData : []);
        }
      } catch (e) {
        console.error("Failed to fetch frontier data", e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [runId]);

  const handleSpawnDivergent = async () => {
    if (!run) return;
    setSpawning(true);
    try {
      const newRun = (await spawnRun(runId, {
        mode: "divergent",
        title: `Divergent: ${run.topic}`,
        topic: run.topic,
      })) as { id: string };
      router.push(`/runs/${newRun.id}`);
    } catch (e) {
      console.error("Failed to spawn divergent run", e);
    } finally {
      setSpawning(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4 animate-fade-in">
          <div className="w-8 h-8 rounded-full border-2 border-[var(--accent-purple)] border-t-transparent animate-spin" />
          <p className="text-sm text-[var(--text-muted)]">Loading frontier data...</p>
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
      {/* Scope bar */}
      <div className="glass-card-static p-6 animate-fade-up">
        <div className="flex items-center gap-2 mb-3">
          <span
            className="text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider"
            style={{
              background: "rgba(139, 92, 246, 0.1)",
              color: "var(--accent-purple)",
              border: "1px solid rgba(139, 92, 246, 0.2)",
            }}
          >
            B: Frontier
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

        {/* Paper pool overview */}
        <div className="flex items-center gap-6 mt-4 pt-3 border-t border-[var(--border-subtle)]">
          <div className="text-center">
            <p className="text-lg font-bold tabular-nums text-[var(--accent-purple)]" style={{ fontFamily: "var(--font-mono)" }}>
              {papers.length}
            </p>
            <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">Papers</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold tabular-nums text-[var(--accent-amber)]" style={{ fontFamily: "var(--font-mono)" }}>
              {painPoints.length}
            </p>
            <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">Pain Points</p>
          </div>
        </div>
      </div>

      {/* Comparison table */}
      {comparison && (
        <div className="animate-fade-up delay-100">
          <ComparisonTable comparison={comparison} />
        </div>
      )}

      {/* Pain points */}
      {painPoints.length > 0 && (
        <div className="animate-fade-up delay-200">
          <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
            Pain Points ({painPoints.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {painPoints.map((pp, idx) => (
              <PainPointCard key={pp.id} painPoint={pp} index={idx} />
            ))}
          </div>
        </div>
      )}

      {/* Papers list */}
      {papers.length > 0 && (
        <div className="animate-fade-up delay-300">
          <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
            Paper Pool ({papers.length})
          </h3>
          <div className="glass-card-static p-4 max-h-[300px] overflow-y-auto">
            <div className="space-y-2">
              {papers.slice(0, 30).map((paper) => (
                <div
                  key={paper.id}
                  className="flex items-start gap-3 p-2 rounded-lg hover:bg-[rgba(148,163,184,0.04)] transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-[var(--text-primary)] leading-snug">
                      {paper.title}
                    </p>
                    <p className="text-[10px] text-[var(--text-muted)] truncate mt-0.5">
                      {paper.authors?.join(", ") ?? "Unknown"}
                      {paper.year ? ` (${paper.year})` : ""}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* CTA: Explore innovations */}
      <div className="glass-card-static p-6 text-center animate-fade-up delay-400">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
          Found interesting pain points?
        </h3>
        <p className="text-xs text-[var(--text-secondary)] mb-4 max-w-md mx-auto">
          Spawn a Mode C (Divergent) run to explore cross-domain innovations targeting these pain points.
        </p>
        <button
          onClick={handleSpawnDivergent}
          disabled={spawning}
          className="btn-primary"
          style={{ background: "linear-gradient(135deg, var(--accent-amber), #d97706)" }}
        >
          {spawning ? (
            <span className="flex items-center gap-2">
              <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              Spawning...
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 2V7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M7 7L11 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M7 7L3 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              Explore Innovations
            </span>
          )}
        </button>
      </div>
    </div>
  );
}
