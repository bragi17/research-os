"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getRun, getPainPoints, getComparison, getRunPapers, spawnRun, addToLibrary,
  type Run, type PainPoint, type Paper,
} from "@/lib/api";

interface GapItem {
  gap_type: string;
  description: string;
  significance: string;
  potential_impact: string;
  supporting_evidence: string[];
}

interface BenchmarkEntry {
  method: string;
  dataset: string;
  score: string;
}

interface PaperSummary {
  title?: string;
  paper_title?: string;
  paper_id?: string;
  arxiv_id?: string;
  doi?: string;
  authors?: string[];
  year?: number;
  venue?: string;
  abstract?: string;
  summary?: string;
  key_contributions?: string[];
  limitations?: string[];
  paper_tags?: Record<string, unknown>;
}

interface ComparisonData {
  gaps: GapItem[];
  comparison_matrix: { methods: unknown[]; benchmark_panel: BenchmarkEntry[] }[];
  papers_read: number;
  papers_discovered: number;
  pain_points_count: number;
  paper_summaries?: PaperSummary[];
}

function arxivIdFromSummary(summary: PaperSummary): string | undefined {
  const raw = summary.arxiv_id || summary.paper_id;
  if (!raw) return undefined;
  const text = String(raw).trim();
  const lower = text.toLowerCase();
  if (lower.startsWith("arxiv:")) return text.slice("arxiv:".length).trim() || undefined;
  if (lower.startsWith("arxiv/")) return text.slice("arxiv/".length).trim() || undefined;
  return text.includes(".") ? text : undefined;
}

export default function FrontierPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;

  const [run, setRun] = useState<Run | null>(null);
  const [painPoints, setPainPoints] = useState<PainPoint[]>([]);
  const [compData, setCompData] = useState<ComparisonData | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [spawning, setSpawning] = useState(false);
  const [showPapers, setShowPapers] = useState(false);
  const [addingToLibrary, setAddingToLibrary] = useState<string | null>(null);
  const [addedToLibrary, setAddedToLibrary] = useState<Set<string>>(new Set());

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
        if (results[1].status === "fulfilled") {
          const raw = results[1].value.comparison;
          if (raw && typeof raw === "object" && Object.keys(raw).length > 0) {
            setCompData(raw as unknown as ComparisonData);
          }
        }
        if (results[2].status === "fulfilled") {
          const pd = results[2].value;
          setPapers(Array.isArray(pd) ? pd : []);
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
        target_mode: "divergent",
        selection: { intent: "explore innovations" },
      })) as { id: string };
      router.push(`/runs/${newRun.id}`);
    } catch (e) { console.error(e); }
    finally { setSpawning(false); }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="h-6 w-6 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
      </div>
    );
  }
  if (!run) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <p className="text-[var(--accent-red)] text-sm">Run not found</p>
      </div>
    );
  }

  const gaps = compData?.gaps ?? [];
  const rawBenchmarks = compData?.comparison_matrix?.[0]?.benchmark_panel;
  const benchmarks = Array.isArray(rawBenchmarks) ? rawBenchmarks : [];
  const papersDiscovered = compData?.papers_discovered ?? 0;
  const papersRead = compData?.papers_read ?? 0;
  const effectivePainPoints = painPoints.length > 0 ? painPoints : [];

  // Discovered papers: prefer paper table, fallback to paper_summaries from context_bundle
  const paperSummaries: PaperSummary[] = compData?.paper_summaries ?? [];
  const discoveredPapers = papers.length > 0
    ? papers.map((p) => ({
        title: p.title,
        year: p.year,
        venue: "",
        arxiv_id: p.arxiv_id,
        doi: p.doi,
        authors: p.authors,
        id: p.id,
      }))
    : paperSummaries.map((ps, i) => {
        const arxiv_id = arxivIdFromSummary(ps);
        return {
          title: ps.title || ps.paper_title || (arxiv_id ? `arXiv:${arxiv_id}` : `Paper ${i + 1}`),
          year: ps.year,
          venue: ps.venue || "",
          arxiv_id,
          doi: ps.doi,
          authors: Array.isArray(ps.authors) ? ps.authors : [] as string[],
          id: arxiv_id ? `summary-arxiv-${arxiv_id}` : `summary-${i}`,
        };
      });

  const hasAnyResults = gaps.length > 0 || benchmarks.length > 0 || effectivePainPoints.length > 0 || papersDiscovered > 0;

  return (
    <div className="max-w-[1060px] mx-auto px-8 py-8 space-y-6">
      {/* Back */}
      <Link href={`/runs/${runId}`} className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M9 11L5 7L9 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Back to run
      </Link>

      {/* Header */}
      <div className="card-static p-6">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">
            Frontier
          </span>
          <span className={`text-[11px] px-2 py-0.5 rounded-full capitalize font-medium ${
            run.status === "completed" ? "bg-[var(--accent-green-soft)] text-[var(--accent-green)]" : "text-[var(--text-muted)]"
          }`}>
            {run.status}
          </span>
        </div>
        <h1 className="text-xl font-medium text-[var(--text-primary)] mb-1" style={{ fontFamily: "var(--font-display)" }}>
          {run.title}
        </h1>
        <p className="text-[13px] text-[var(--text-muted)] mb-4">{run.topic}</p>

        {/* Stats */}
        <div className="flex items-center gap-6 pt-3 border-t border-[var(--border-subtle)]">
          <Stat value={papersDiscovered} label="Discovered" />
          <Stat value={papersRead} label="Read" />
          <Stat value={gaps.length} label="Gaps" />
          <Stat value={effectivePainPoints.length} label="Pain Points" />
          <Stat value={benchmarks.length} label="Benchmarks" />
        </div>
      </div>

      {!hasAnyResults && (
        <div className="card-static p-8 text-center">
          <p className="text-[var(--text-muted)] text-sm">No results available yet.</p>
          <p className="text-[var(--text-muted)] text-xs mt-1">Results appear after the run completes successfully.</p>
        </div>
      )}

      {/* Research Gaps */}
      {gaps.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Research Gaps ({gaps.length})
          </h2>
          <div className="space-y-3">
            {gaps.map((gap, idx) => (
              <div key={idx} className="card-static p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full uppercase ${
                    gap.significance === "high"
                      ? "bg-[var(--accent-red-soft)] text-[var(--accent-red)]"
                      : "bg-[var(--accent-amber-soft)] text-[var(--accent-amber)]"
                  }`}>
                    {gap.significance}
                  </span>
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">
                    {gap.gap_type}
                  </span>
                </div>
                <p className="text-[13px] text-[var(--text-primary)] leading-relaxed mb-2">
                  {gap.description}
                </p>
                {gap.potential_impact && (
                  <p className="text-[12px] text-[var(--text-muted)] italic mb-2">
                    Impact: {gap.potential_impact}
                  </p>
                )}
                {gap.supporting_evidence?.length > 0 && (
                  <ul className="space-y-1 mt-2">
                    {gap.supporting_evidence.map((ev, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-muted)] pl-3 border-l-2 border-[var(--border-subtle)]">
                        {ev}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Benchmark Panel — full score display */}
      {benchmarks.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Benchmark Panel ({benchmarks.length})
          </h2>
          <div className="card-static overflow-hidden">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)]">
                  <th className="text-left py-2.5 px-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase w-[30%]">Method</th>
                  <th className="text-left py-2.5 px-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase w-[20%]">Dataset</th>
                  <th className="text-left py-2.5 px-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase">Score / Notes</th>
                </tr>
              </thead>
              <tbody>
                {benchmarks.map((b, idx) => (
                  <tr key={idx} className="border-b border-[var(--border-subtle)] last:border-0 align-top">
                    <td className="py-3 px-4 text-[var(--text-primary)] font-medium">{b.method}</td>
                    <td className="py-3 px-4 text-[var(--text-secondary)]">{b.dataset}</td>
                    <td className="py-3 px-4 text-[var(--text-muted)] text-[12px] leading-relaxed">
                      {b.score || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pain Points (from pain_point table) */}
      {effectivePainPoints.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Pain Points ({effectivePainPoints.length})
          </h2>
          <div className="space-y-3">
            {effectivePainPoints.map((pp) => (
              <div key={pp.id} className="card-static p-4">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">
                    {pp.pain_type}
                  </span>
                  <span className="text-[11px] text-[var(--text-muted)]" style={{ fontFamily: "var(--font-mono)" }}>
                    severity: {Number(pp.severity_score || 0).toFixed(1)}
                  </span>
                </div>
                <p className="text-[13px] text-[var(--text-primary)] leading-relaxed">{pp.statement}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Discovered Papers — uses paper_summaries from context_bundle */}
      {(discoveredPapers.length > 0 || papersDiscovered > 0) && (
        <div>
          <button
            onClick={() => setShowPapers(!showPapers)}
            className="flex items-center gap-2 text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3 hover:text-[var(--text-secondary)] transition-colors"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
              className="transition-transform duration-200"
              style={{ transform: showPapers ? "rotate(90deg)" : "rotate(0deg)" }}>
              <path d="M3 1.5L7 5L3 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Discovered Papers ({discoveredPapers.length || papersDiscovered})
            <span className="text-[10px] font-normal normal-case tracking-normal">— click to browse and add to library</span>
          </button>

          {showPapers && (
            <div className="space-y-2 animate-fade-up">
              {discoveredPapers.length === 0 ? (
                <p className="text-[12px] text-[var(--text-muted)] italic py-4">
                  No paper details available. Run a new research with the latest version to see papers here.
                </p>
              ) : (
                discoveredPapers.map((paper) => {
                  const isAdded = addedToLibrary.has(paper.id);
                  const isAdding = addingToLibrary === paper.id;
                  return (
                    <div key={paper.id} className="card-static p-4 flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <h4 className="text-[13px] font-medium text-[var(--text-primary)] leading-snug mb-1">
                          {paper.title}
                        </h4>
                        <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)] flex-wrap">
                          {paper.authors?.length > 0 && (
                            <span className="truncate max-w-[250px]">
                              {paper.authors.slice(0, 3).join(", ")}{paper.authors.length > 3 ? " et al." : ""}
                            </span>
                          )}
                          {paper.year && <span style={{ fontFamily: "var(--font-mono)" }}>{paper.year}</span>}
                          {paper.arxiv_id && (
                            <span className="text-[var(--accent)]" style={{ fontFamily: "var(--font-mono)" }}>
                              {paper.arxiv_id}
                            </span>
                          )}
                        </div>
                      </div>
                      <button
                        disabled={isAdded || isAdding}
                        onClick={async () => {
                          setAddingToLibrary(paper.id);
                          try {
                            await addToLibrary({
                              title: paper.title,
                              arxiv_id: paper.arxiv_id,
                              doi: "doi" in paper ? (paper as Record<string, unknown>).doi as string : undefined,
                              authors: paper.authors,
                              year: paper.year,
                              source_run_id: runId,
                            });
                            setAddedToLibrary((prev) => new Set([...prev, paper.id]));
                          } catch (e) { console.error(e); }
                          finally { setAddingToLibrary(null); }
                        }}
                        className={`shrink-0 text-[12px] px-3 py-1.5 rounded-lg transition-all ${
                          isAdded
                            ? "bg-[var(--accent-green-soft)] text-[var(--accent-green)]"
                            : "btn-secondary"
                        }`}
                      >
                        {isAdding ? (
                          <span className="flex items-center gap-1.5">
                            <span className="h-3 w-3 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
                            Adding
                          </span>
                        ) : isAdded ? "✓ In Library" : "+ Add to Library"}
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      )}

      {/* Spawn Divergent */}
      <div className="pt-4 border-t border-[var(--border-subtle)]">
        <button onClick={handleSpawnDivergent} disabled={spawning} className="btn-primary text-[13px]">
          {spawning ? "Creating..." : "Explore innovations for these gaps →"}
        </button>
      </div>
    </div>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="text-center min-w-[70px]">
      <p className="text-lg font-semibold text-[var(--text-primary)] tabular-nums" style={{ fontFamily: "var(--font-mono)" }}>
        {value}
      </p>
      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
    </div>
  );
}
