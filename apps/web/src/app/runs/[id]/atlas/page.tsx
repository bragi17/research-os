"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getRun,
  getTimeline,
  getTaxonomy,
  getReadingPath,
  getRunPapers,
  spawnRun,
  type Run,
  type TimelineEntry,
  type TaxonomyNode,
  type Paper,
} from "@/lib/api";
import TimelineRail from "@/components/TimelineRail";
import TaxonomyTree from "@/components/TaxonomyTree";

export default function AtlasPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;

  const [run, setRun] = useState<Run | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [taxonomy, setTaxonomy] = useState<TaxonomyNode | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [readingPath, setReadingPath] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [spawning, setSpawning] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const runData = await getRun(runId);
        setRun(runData);

        const results = await Promise.allSettled([
          getTimeline(runId),
          getTaxonomy(runId),
          getRunPapers(runId),
          getReadingPath(runId),
        ]);

        if (results[0].status === "fulfilled") setTimeline(results[0].value.timeline ?? []);
        if (results[1].status === "fulfilled") setTaxonomy(results[1].value.taxonomy ?? null);
        if (results[2].status === "fulfilled") {
          const papersData = results[2].value;
          setPapers(Array.isArray(papersData) ? papersData : []);
        }
        if (results[3].status === "fulfilled") setReadingPath(results[3].value);
      } catch (e) {
        console.error("Failed to fetch atlas data", e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [runId]);

  const handleSpawnFrontier = async () => {
    if (!run) return;
    setSpawning(true);
    try {
      const newRun = (await spawnRun(runId, {
        mode: "frontier",
        title: `Frontier: ${run.topic}`,
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
          <div className="w-8 h-8 rounded-full border-2 border-[var(--accent-cyan)] border-t-transparent animate-spin" />
          <p className="text-sm text-[var(--text-muted)]">Loading atlas data...</p>
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

  const readingItems = (readingPath as { items?: { title: string; week?: number; difficulty?: string; reason?: string }[] })?.items ?? [];

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6 space-y-6">
      {/* Hero card */}
      <div className="glass-card-static p-6 animate-fade-up">
        <div className="flex items-center gap-2 mb-3">
          <span
            className="text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider"
            style={{
              background: "rgba(6, 182, 212, 0.1)",
              color: "var(--accent-cyan)",
              border: "1px solid rgba(6, 182, 212, 0.2)",
            }}
          >
            A: Atlas
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
        <div className="flex items-center gap-4 mt-4 text-[11px] text-[var(--text-muted)]" style={{ fontFamily: "var(--font-mono)" }}>
          <span>{papers.length} papers</span>
          <span>{timeline.length} timeline entries</span>
        </div>
      </div>

      {/* Timeline */}
      {timeline.length > 0 && (
        <div className="animate-fade-up delay-100">
          <TimelineRail entries={timeline} />
        </div>
      )}

      {/* Two columns: Taxonomy + Reading Path */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Taxonomy */}
        {taxonomy && (
          <div className="animate-fade-up delay-200">
            <TaxonomyTree root={taxonomy} />
          </div>
        )}

        {/* Reading Path */}
        {readingItems.length > 0 && (
          <div className="glass-card-static p-4 animate-fade-up delay-300">
            <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
              Reading Path
            </h3>
            <div className="space-y-2 max-h-[400px] overflow-y-auto">
              {readingItems.map((item, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-3 p-2 rounded-lg hover:bg-[rgba(148,163,184,0.04)] transition-colors"
                >
                  <span
                    className="flex items-center justify-center h-6 w-6 rounded-md text-[10px] font-bold shrink-0"
                    style={{
                      background: "rgba(6, 182, 212, 0.1)",
                      color: "var(--accent-cyan)",
                    }}
                  >
                    {idx + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-[var(--text-primary)]">
                      {item.title}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      {item.week != null && (
                        <span className="text-[9px] text-[var(--text-muted)]">
                          Week {item.week}
                        </span>
                      )}
                      {item.difficulty && (
                        <span
                          className="text-[9px] px-1.5 py-0.5 rounded"
                          style={{
                            background:
                              item.difficulty === "beginner"
                                ? "rgba(16, 185, 129, 0.1)"
                                : item.difficulty === "intermediate"
                                  ? "rgba(245, 158, 11, 0.1)"
                                  : "rgba(239, 68, 68, 0.1)",
                            color:
                              item.difficulty === "beginner"
                                ? "var(--accent-green)"
                                : item.difficulty === "intermediate"
                                  ? "var(--accent-amber)"
                                  : "var(--accent-red)",
                          }}
                        >
                          {item.difficulty}
                        </span>
                      )}
                    </div>
                    {item.reason && (
                      <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                        {item.reason}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Representative papers */}
      {papers.length > 0 && (
        <div className="animate-fade-up delay-400">
          <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
            Representative Papers
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {papers.slice(0, 12).map((paper, idx) => (
              <div
                key={paper.id}
                className="glass-card p-4 animate-fade-up"
                style={{ animationDelay: `${idx * 50}ms` }}
              >
                <h4 className="text-xs font-semibold text-[var(--text-primary)] mb-1 leading-snug line-clamp-2">
                  {paper.title}
                </h4>
                <p className="text-[10px] text-[var(--text-muted)] mb-1 truncate">
                  {paper.authors?.join(", ") ?? "Unknown authors"}
                </p>
                <div className="flex items-center gap-2">
                  {paper.year && (
                    <span
                      className="text-[9px] text-[var(--accent-cyan)] tabular-nums"
                      style={{ fontFamily: "var(--font-mono)" }}
                    >
                      {paper.year}
                    </span>
                  )}
                  {paper.arxiv_id && (
                    <span className="text-[9px] text-[var(--text-muted)]">
                      arXiv:{paper.arxiv_id}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* CTA: Deep dive */}
      <div className="glass-card-static p-6 text-center animate-fade-up delay-500">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
          Ready to go deeper?
        </h3>
        <p className="text-xs text-[var(--text-secondary)] mb-4 max-w-md mx-auto">
          Spawn a Mode B (Frontier) run to analyze a specific direction from this landscape in depth.
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
                <path d="M2 12L7 2L12 12" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                <path d="M4 9H10" stroke="currentColor" strokeWidth="1.5" />
              </svg>
              Deep dive into this direction
            </span>
          )}
        </button>
      </div>
    </div>
  );
}
