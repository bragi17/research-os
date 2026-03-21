"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getRun, getPainPoints, getComparison, getRunPapers, spawnRun,
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

interface ComparisonData {
  gaps: GapItem[];
  comparison_matrix: { methods: unknown[]; benchmark_panel: BenchmarkEntry[] }[];
  papers_read: number;
  papers_discovered: number;
  pain_points_count: number;
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
            setCompData(raw as ComparisonData);
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
  const benchmarks = compData?.comparison_matrix?.[0]?.benchmark_panel ?? [];
  const papersDiscovered = compData?.papers_discovered ?? 0;
  const papersRead = compData?.papers_read ?? 0;

  const hasAnyResults = gaps.length > 0 || benchmarks.length > 0 || painPoints.length > 0 || papersDiscovered > 0;

  return (
    <div className="max-w-[760px] mx-auto px-8 py-8 space-y-6">
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
          <Stat value={painPoints.length} label="Pain Points" />
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

      {/* Benchmark Panel */}
      {benchmarks.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Benchmark Panel ({benchmarks.length})
          </h2>
          <div className="card-static overflow-hidden">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)]">
                  <th className="text-left py-2.5 px-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase">Method</th>
                  <th className="text-left py-2.5 px-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase">Dataset</th>
                  <th className="text-right py-2.5 px-4 text-[10px] font-semibold text-[var(--text-muted)] uppercase">Score</th>
                </tr>
              </thead>
              <tbody>
                {benchmarks.map((b, idx) => (
                  <tr key={idx} className="border-b border-[var(--border-subtle)] last:border-0">
                    <td className="py-2.5 px-4 text-[var(--text-primary)] font-medium">{b.method}</td>
                    <td className="py-2.5 px-4 text-[var(--text-secondary)]">{b.dataset}</td>
                    <td className="py-2.5 px-4 text-right text-[var(--text-muted)]" style={{ fontFamily: "var(--font-mono)" }}>
                      {b.score?.length > 40 ? b.score.slice(0, 40) + "..." : b.score}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pain Points */}
      {painPoints.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
            Pain Points ({painPoints.length})
          </h2>
          <div className="space-y-3">
            {painPoints.map((pp) => (
              <div key={pp.id} className="card-static p-4">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">
                    {pp.pain_type}
                  </span>
                  <span className="text-[11px] text-[var(--text-muted)]" style={{ fontFamily: "var(--font-mono)" }}>
                    severity: {pp.severity_score.toFixed(1)}
                  </span>
                </div>
                <p className="text-[13px] text-[var(--text-primary)] leading-relaxed">{pp.statement}</p>
              </div>
            ))}
          </div>
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
    <div className="text-center">
      <p className="text-lg font-semibold text-[var(--text-primary)]" style={{ fontFamily: "var(--font-mono)" }}>
        {value}
      </p>
      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
    </div>
  );
}
