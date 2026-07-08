"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getRun,
  getRunPapers,
  getPainPoints,
  getIdeaCards,
  addToLibrary,
  type Run,
  type Paper,
  type PainPoint,
  type IdeaCard,
} from "@/lib/api";
import IdeaCardDisplay from "@/components/IdeaCardDisplay";
import ResultPageNav from "@/components/ResultPageNav";
import RunArtifactCardsPanel from "@/components/work/RunArtifactCardsPanel";

function getWorkHref(run: Run): string | null {
  return run.work_id ? `/works/${run.work_id}` : null;
}

export default function DivergentPage() {
  const params = useParams();
  const runId = params.id as string;

  const [run, setRun] = useState<Run | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [painPoints, setPainPoints] = useState<PainPoint[]>([]);
  const [ideaCards, setIdeaCards] = useState<IdeaCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [addingPaperId, setAddingPaperId] = useState<string | null>(null);
  const [libraryPaperIds, setLibraryPaperIds] = useState<Record<string, string>>({});
  const [libraryError, setLibraryError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const runData = await getRun(runId);
        setRun(runData);

        const results = await Promise.allSettled([
          getRunPapers(runId),
          getPainPoints(runId),
          getIdeaCards(runId),
        ]);

        if (results[0].status === "fulfilled") setPapers(results[0].value ?? []);
        if (results[1].status === "fulfilled") setPainPoints(results[1].value.items ?? []);
        if (results[2].status === "fulfilled") setIdeaCards(results[2].value.items ?? []);
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

  const handleAddPaperToLibrary = async (paper: Paper) => {
    setAddingPaperId(paper.id);
    setLibraryError(null);
    try {
      const libraryPaper = await addToLibrary({
        title: paper.title,
        authors: paper.authors ?? [],
        year: paper.year,
        doi: paper.doi,
        arxiv_id: paper.arxiv_id,
        source_run_id: runId,
        project_tags: ["research-run", "divergent"],
      });
      if (libraryPaper.id) {
        setLibraryPaperIds((current) => ({
          ...current,
          [paper.id]: libraryPaper.id,
        }));
      }
    } catch (e) {
      console.error("Failed to add paper to library", e);
      setLibraryError("Failed to add paper to library.");
    } finally {
      setAddingPaperId(null);
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

  const workHref = getWorkHref(run);
  const frontierNewHref = `/new?mode=frontier&topic=${encodeURIComponent(run.topic)}`;

  return (
    <div className="max-w-[1060px] mx-auto px-8 py-8 space-y-6">
      <ResultPageNav />

      {/* Back button */}
      <Link
        href={`/runs/${runId}`}
        className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M9 11L5 7L9 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Back to run
      </Link>

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
            <p className="text-lg font-bold tabular-nums text-[var(--accent-cyan)]" style={{ fontFamily: "var(--font-mono)" }}>
              {papers.length}
            </p>
            <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">Papers</p>
          </div>
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
        <div className="mt-5 flex flex-wrap items-center gap-3">
          {workHref ? (
            <Link href={workHref} className="btn-primary text-[13px] px-4">
              Open topic work
            </Link>
          ) : (
            <Link href={frontierNewHref} className="btn-secondary text-[13px] px-4">
              Start a topic work
            </Link>
          )}
        </div>
      </div>

      <RunArtifactCardsPanel run={run} phase="divergent" />

      {/* Papers explored */}
      {papers.length > 0 && (
        <div className="animate-fade-up delay-75">
          <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
            Papers Explored ({papers.length})
          </h3>
          <div className="glass-card-static p-4">
            <div className="space-y-3">
              {papers.map((paper) => (
                <div key={paper.id} className="flex flex-col gap-2 border-b border-[var(--border-subtle)] pb-3 last:border-b-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-[var(--text-primary)] leading-snug">
                      {paper.title}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-[var(--text-muted)]">
                      {paper.authors?.length > 0 && (
                        <span className="truncate max-w-[360px]">
                          {paper.authors.slice(0, 4).join(", ")}
                          {paper.authors.length > 4 ? " et al." : ""}
                        </span>
                      )}
                      {paper.year && (
                        <span style={{ fontFamily: "var(--font-mono)" }}>
                          {paper.year}
                        </span>
                      )}
                      {paper.doi && (
                        <span className="truncate max-w-[220px]" style={{ fontFamily: "var(--font-mono)" }}>
                          {paper.doi}
                        </span>
                      )}
                      {paper.arxiv_id && (
                        <span style={{ fontFamily: "var(--font-mono)" }}>
                          arXiv:{paper.arxiv_id}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {libraryPaperIds[paper.id] ? (
                      <Link
                        href={`/library/papers/${libraryPaperIds[paper.id]}`}
                        className="btn-secondary px-3 py-1.5 text-[12px]"
                      >
                        Open in library
                      </Link>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleAddPaperToLibrary(paper)}
                        disabled={addingPaperId === paper.id}
                        className="btn-secondary px-3 py-1.5 text-[12px]"
                      >
                        {addingPaperId === paper.id ? "Adding..." : "Add to library"}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {libraryError && (
              <p className="mt-3 text-[11px] text-[var(--accent-red)]">
                {libraryError}
              </p>
            )}
          </div>
        </div>
      )}

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
          Topic work
        </h3>
        <p className="text-xs text-[var(--text-secondary)] mb-4 max-w-md mx-auto">
          {workHref
            ? "Open the topic work page to manage selected idea cards and phase work."
            : "Create a topic work page from this topic to review the most promising ideas with Frontier."}
        </p>
        {workHref ? (
          <Link href={workHref} className="btn-primary text-[13px] px-4">
            Open topic work
          </Link>
        ) : (
          <Link href={frontierNewHref} className="btn-secondary text-[13px] px-4">
            Start a topic work
          </Link>
        )}
      </div>

      <BottomBackToRun runId={runId} />
    </div>
  );
}

function BottomBackToRun({ runId }: { runId: string }) {
  return (
    <div className="border-t border-[var(--border-subtle)] pt-4">
      <Link
        href={`/runs/${runId}`}
        className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path
            d="M9 11L5 7L9 3"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        Back to run
      </Link>
    </div>
  );
}
