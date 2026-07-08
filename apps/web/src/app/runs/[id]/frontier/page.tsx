"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  addToLibrary,
  getRun,
  getRunContextBundle,
  getRunPapers,
  type ContextBundle,
  type Paper,
  type Run,
} from "@/lib/api";
import ResultPageNav from "@/components/ResultPageNav";
import RunArtifactCardsPanel from "@/components/work/RunArtifactCardsPanel";

interface GapItem {
  gap_type?: string;
  description?: string;
  significance?: string;
  potential_impact?: string;
  supporting_evidence?: unknown[];
}

interface BenchmarkEntry {
  method?: string;
  dataset?: string;
  score?: string;
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
  problem?: unknown;
  method?: unknown;
  experimental_setup?: unknown;
  datasets?: unknown;
  limitations?: unknown;
  main_results?: unknown;
  reusable_components?: unknown;
  paper_tags?: unknown;
  innovation_points?: unknown;
  key_contributions?: unknown;
}

interface BenchmarkData {
  key_findings?: unknown;
  method_landscape?: unknown;
  benchmark_status?: unknown;
  entry_points?: unknown;
  paper_summaries?: PaperSummary[];
  papers_read?: number;
  papers_discovered?: number;
  pain_points_count?: number;
  gaps?: GapItem[];
  comparison_matrix?: { benchmark_panel?: BenchmarkEntry[] }[];
}

interface DiscoveredPaper {
  id: string;
  title: string;
  year?: number;
  venue?: string;
  arxiv_id?: string;
  doi?: string;
  authors: string[];
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (Array.isArray(value)) return value.map(formatValue).filter(Boolean).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        const text = formatValue(item);
        return text ? `${key}: ${text}` : "";
      })
      .filter(Boolean)
      .join("; ");
  }
  return String(value);
}

function asList(value: unknown): string[] {
  if (value === null || value === undefined || value === "") return [];
  if (Array.isArray(value)) return value.map(formatValue).filter(Boolean);
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        const text = formatValue(item);
        return text ? `${key}: ${text}` : "";
      })
      .filter(Boolean);
  }
  return [String(value)];
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

function benchmarkDataFrom(bundle: ContextBundle | null): BenchmarkData {
  return (bundle?.benchmark_data ?? {}) as BenchmarkData;
}

function getWorkHref(run: Run): string | null {
  return run.work_id ? `/works/${run.work_id}` : null;
}

export default function FrontierPage() {
  const params = useParams();
  const runId = params.id as string;

  const [run, setRun] = useState<Run | null>(null);
  const [contextBundle, setContextBundle] = useState<ContextBundle | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [showPapers, setShowPapers] = useState(false);
  const [addingToLibrary, setAddingToLibrary] = useState<string | null>(null);
  const [libraryIds, setLibraryIds] = useState<Record<string, string>>({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [runData, bundleData, paperData] = await Promise.all([
          getRun(runId),
          getRunContextBundle(runId, { preferContext: true }),
          getRunPapers(runId).catch(() => [] as Paper[]),
        ]);
        setRun(runData);
        setContextBundle(bundleData.context_bundle);
        setPapers(Array.isArray(paperData) ? paperData : []);
      } catch (e) {
        console.error("Failed to fetch frontier data", e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [runId]);

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

  const benchmarkData = benchmarkDataFrom(contextBundle);
  const paperSummaries = Array.isArray(benchmarkData.paper_summaries)
    ? benchmarkData.paper_summaries
    : [];
  const gaps = Array.isArray(benchmarkData.gaps) ? benchmarkData.gaps : [];
  const rawBenchmarks = benchmarkData.comparison_matrix?.[0]?.benchmark_panel;
  const benchmarks = Array.isArray(rawBenchmarks) ? rawBenchmarks : [];
  const summaryText = contextBundle?.summary_text ?? "";
  const papersDiscovered = benchmarkData.papers_discovered ?? papers.length;
  const papersRead = benchmarkData.papers_read ?? paperSummaries.length;
  const painPointsCount = benchmarkData.pain_points_count ?? gaps.length;
  const discoveredPapers: DiscoveredPaper[] = papers.length > 0
    ? papers.map((paper) => ({
        id: paper.id,
        title: paper.title,
        year: paper.year,
        arxiv_id: paper.arxiv_id,
        doi: paper.doi,
        authors: paper.authors,
      }))
    : paperSummaries.map((summary, index) => {
        const arxivId = arxivIdFromSummary(summary);
        return {
          id: arxivId ? `summary-arxiv-${arxivId}` : `summary-${index}`,
          title: summary.title || summary.paper_title || (arxivId ? `arXiv:${arxivId}` : `Paper ${index + 1}`),
          year: summary.year,
          venue: summary.venue,
          arxiv_id: arxivId,
          doi: summary.doi,
          authors: Array.isArray(summary.authors) ? summary.authors : [],
        };
      });
  const hasAnyResults =
    Boolean(summaryText) ||
    paperSummaries.length > 0 ||
    gaps.length > 0 ||
    benchmarks.length > 0 ||
    asList(benchmarkData.key_findings).length > 0 ||
    asList(benchmarkData.method_landscape).length > 0 ||
    asList(benchmarkData.entry_points).length > 0;
  const workHref = getWorkHref(run);
  const divergentNewHref = `/new?mode=divergent&topic=${encodeURIComponent(run.topic)}`;

  return (
    <div className="max-w-[1060px] mx-auto px-8 py-8 space-y-6">
      <ResultPageNav />

      <Link href={`/runs/${runId}`} className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M9 11L5 7L9 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Back to run
      </Link>

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

        <div className="flex items-center gap-6 pt-3 border-t border-[var(--border-subtle)]">
          <Stat value={papersDiscovered} label="Discovered" />
          <Stat value={papersRead} label="Read" />
          <Stat value={paperSummaries.length} label="Reviews" />
          <Stat value={painPointsCount} label="Pain Points" />
          <Stat value={benchmarks.length} label="Benchmarks" />
        </div>
      </div>

      <RunArtifactCardsPanel run={run} phase="frontier" />

      {!hasAnyResults && (
        <div className="card-static p-8 text-center">
          <p className="text-[var(--text-muted)] text-sm">No results available yet.</p>
          <p className="text-[var(--text-muted)] text-xs mt-1">Results appear after the run completes successfully.</p>
        </div>
      )}

      {summaryText && (
        <section>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Frontier Overview
          </h2>
          <div className="card-static p-5">
            <p className="text-[13px] text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">
              {summaryText}
            </p>
          </div>
        </section>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <InsightPanel title="Key Findings" value={benchmarkData.key_findings} />
        <InsightPanel title="Method Landscape" value={benchmarkData.method_landscape} />
        <InsightPanel title="Entry Points" value={benchmarkData.entry_points} />
      </div>

      {gaps.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Research Gaps ({gaps.length})
          </h2>
          <div className="space-y-3">
            {gaps.map((gap, idx) => (
              <div key={idx} className="card-static p-4">
                <div className="flex items-center gap-2 mb-2">
                  {gap.significance && (
                    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full uppercase ${
                      gap.significance === "high"
                        ? "bg-[var(--accent-red-soft)] text-[var(--accent-red)]"
                        : "bg-[var(--accent-amber-soft)] text-[var(--accent-amber)]"
                    }`}>
                      {gap.significance}
                    </span>
                  )}
                  {gap.gap_type && (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">
                      {gap.gap_type}
                    </span>
                  )}
                </div>
                <p className="text-[13px] text-[var(--text-primary)] leading-relaxed mb-2">
                  {gap.description}
                </p>
                {gap.potential_impact && (
                  <p className="text-[12px] text-[var(--text-muted)] italic mb-2">
                    Impact: {gap.potential_impact}
                  </p>
                )}
                {Array.isArray(gap.supporting_evidence) && gap.supporting_evidence.length > 0 && (
                  <ul className="space-y-1 mt-2">
                    {gap.supporting_evidence.map((evidence, i) => (
                      <li key={i} className="text-[11px] text-[var(--text-muted)] pl-3 border-l-2 border-[var(--border-subtle)]">
                        {formatValue(evidence)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {benchmarks.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Benchmark Status ({benchmarks.length})
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
                {benchmarks.map((benchmark, idx) => (
                  <tr key={idx} className="border-b border-[var(--border-subtle)] last:border-0 align-top">
                    <td className="py-3 px-4 text-[var(--text-primary)] font-medium">{benchmark.method}</td>
                    <td className="py-3 px-4 text-[var(--text-secondary)]">{benchmark.dataset}</td>
                    <td className="py-3 px-4 text-[var(--text-muted)] text-[12px] leading-relaxed">
                      {benchmark.score || "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {paperSummaries.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Paper Reviews ({paperSummaries.length})
          </h2>
          <div className="space-y-3">
            {paperSummaries.map((paper, idx) => (
              <PaperReviewCard key={`${paper.paper_id ?? paper.title ?? idx}`} paper={paper} index={idx} />
            ))}
          </div>
        </section>
      )}

      {(discoveredPapers.length > 0 || papersDiscovered > 0) && (
        <section>
          <button
            type="button"
            onClick={() => setShowPapers(!showPapers)}
            className="flex items-center gap-2 text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3 hover:text-[var(--text-secondary)] transition-colors"
            aria-expanded={showPapers}
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 10 10"
              fill="none"
              className="transition-transform duration-200"
              style={{ transform: showPapers ? "rotate(90deg)" : "rotate(0deg)" }}
            >
              <path d="M3 1.5L7 5L3 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Discovered Papers ({discoveredPapers.length || papersDiscovered})
            <span className="text-[10px] font-normal normal-case tracking-normal">click to browse and add to library</span>
          </button>

          {showPapers && (
            <div className="space-y-2 animate-fade-up">
              {discoveredPapers.length === 0 ? (
                <p className="text-[12px] text-[var(--text-muted)] italic py-4">
                  No paper details available. Run a new research with the latest version to see papers here.
                </p>
              ) : (
                discoveredPapers.map((paper) => {
                  const libraryId = libraryIds[paper.id];
                  const isAdding = addingToLibrary === paper.id;
                  return (
                    <div key={paper.id} className="card-static p-4 flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <h4 className="text-[13px] font-medium text-[var(--text-primary)] leading-snug mb-1">
                          {paper.title}
                        </h4>
                        <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)] flex-wrap">
                          {paper.authors.length > 0 && (
                            <span className="truncate max-w-[250px]">
                              {paper.authors.slice(0, 3).join(", ")}{paper.authors.length > 3 ? " et al." : ""}
                            </span>
                          )}
                          {paper.year && <span style={{ fontFamily: "var(--font-mono)" }}>{paper.year}</span>}
                          {paper.venue && <span>{paper.venue}</span>}
                          {paper.arxiv_id && (
                            <span className="text-[var(--accent)]" style={{ fontFamily: "var(--font-mono)" }}>
                              {paper.arxiv_id}
                            </span>
                          )}
                        </div>
                      </div>
                      {libraryId ? (
                        <Link href={`/library/papers/${libraryId}`} className="btn-secondary shrink-0 text-[12px] px-3 py-1.5">
                          Open in library
                        </Link>
                      ) : (
                        <button
                          disabled={isAdding}
                          onClick={async () => {
                            setAddingToLibrary(paper.id);
                            try {
                              const libraryPaper = await addToLibrary({
                                title: paper.title,
                                arxiv_id: paper.arxiv_id,
                                doi: paper.doi,
                                authors: paper.authors,
                                year: paper.year,
                                source_run_id: runId,
                              });
                              setLibraryIds((prev) => ({ ...prev, [paper.id]: libraryPaper.id }));
                            } catch (e) {
                              console.error(e);
                            } finally {
                              setAddingToLibrary(null);
                            }
                          }}
                          className="btn-secondary shrink-0 text-[12px] px-3 py-1.5"
                        >
                          {isAdding ? "Adding" : "Add to library"}
                        </button>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}
        </section>
      )}

      <div className="pt-4 border-t border-[var(--border-subtle)]">
        {workHref ? (
          <Link href={workHref} className="btn-primary text-[13px]">
            Open topic work
          </Link>
        ) : (
          <div className="flex flex-col items-start gap-2">
            <p className="text-[13px] font-medium text-[var(--text-primary)]">
              Topic work
            </p>
            <p className="text-[12px] text-[var(--text-muted)]">
              Create a topic work page from this topic to run Divergent as a work phase.
            </p>
            <Link href={divergentNewHref} className="btn-secondary text-[13px]">
              Start a topic work
            </Link>
          </div>
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

function InsightPanel({ title, value }: { title: string; value: unknown }) {
  const items = asList(value);
  if (items.length === 0) return null;
  return (
    <section>
      <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
        {title}
      </h2>
      <div className="card-static p-4 h-full">
        <ul className="space-y-2">
          {items.map((item, index) => (
            <li key={index} className="text-[12px] text-[var(--text-secondary)] leading-relaxed">
              {item}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function PaperReviewCard({ paper, index }: { paper: PaperSummary; index: number }) {
  const title = paper.title || paper.paper_title || `Paper ${index + 1}`;
  const authors = Array.isArray(paper.authors) ? paper.authors : [];
  return (
    <article className="card-static p-5">
      <div className="mb-4">
        <h3 className="text-[15px] font-medium text-[var(--text-primary)] leading-snug mb-1">
          {title}
        </h3>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
          {authors.length > 0 && <span>{authors.slice(0, 4).join(", ")}{authors.length > 4 ? " et al." : ""}</span>}
          {paper.year && <span style={{ fontFamily: "var(--font-mono)" }}>{paper.year}</span>}
          {paper.venue && <span>{paper.venue}</span>}
          {(paper.arxiv_id || paper.doi) && (
            <span className="text-[var(--accent)]" style={{ fontFamily: "var(--font-mono)" }}>
              {paper.arxiv_id || paper.doi}
            </span>
          )}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <ReviewField label="Problem" value={paper.problem} />
        <ReviewField label="Method" value={paper.method} />
        <ReviewField label="Experimental Setup / Datasets" value={paper.experimental_setup || paper.datasets} />
        <ReviewField label="Main Results" value={paper.main_results || paper.key_contributions} />
        <ReviewField label="Limitations" value={paper.limitations} />
        <ReviewField label="Reusable Components" value={paper.reusable_components} />
        <ReviewField label="Paper Tags / Innovation Points" value={paper.paper_tags || paper.innovation_points} />
      </div>
      {(paper.summary || paper.abstract) && (
        <p className="mt-4 text-[12px] text-[var(--text-muted)] leading-relaxed">
          {paper.summary || paper.abstract}
        </p>
      )}
    </article>
  );
}

function ReviewField({ label, value }: { label: string; value: unknown }) {
  const items = asList(value);
  if (items.length === 0) return null;
  return (
    <div className="rounded-lg border border-[var(--border-subtle)] p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">
        {label}
      </p>
      {items.length === 1 ? (
        <p className="text-[12px] text-[var(--text-secondary)] leading-relaxed">{items[0]}</p>
      ) : (
        <ul className="space-y-1">
          {items.map((item, index) => (
            <li key={index} className="text-[12px] text-[var(--text-secondary)] leading-relaxed">
              {item}
            </li>
          ))}
        </ul>
      )}
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
