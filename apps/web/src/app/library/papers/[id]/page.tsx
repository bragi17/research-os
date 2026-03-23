"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getLibraryPaper, type LibraryPaper } from "@/lib/api";

/* ── KaTeX loader ── */
function useKatex() {
  const loaded = useRef(false);
  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    // Load KaTeX CSS
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css";
    document.head.appendChild(link);
    // Load KaTeX JS
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js";
    document.head.appendChild(script);
    // Load auto-render
    script.onload = () => {
      const auto = document.createElement("script");
      auto.src = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js";
      auto.onload = () => {
        // @ts-expect-error global renderMathInElement
        if (window.renderMathInElement) {
          // @ts-expect-error global renderMathInElement
          window.renderMathInElement(document.body, {
            delimiters: [
              { left: "$$", right: "$$", display: true },
              { left: "$", right: "$", display: false },
              { left: "\\(", right: "\\)", display: false },
              { left: "\\[", right: "\\]", display: true },
            ],
          });
        }
      };
      document.head.appendChild(auto);
    };
  }, []);
}

function renderMath() {
  // @ts-expect-error global renderMathInElement
  if (typeof window !== "undefined" && window.renderMathInElement) {
    // @ts-expect-error global renderMathInElement
    window.renderMathInElement(document.body, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$", right: "$", display: false },
        { left: "\\(", right: "\\)", display: false },
        { left: "\\[", right: "\\]", display: true },
      ],
    });
  }
}

export default function LibraryPaperDetail() {
  const params = useParams();
  const paperId = params.id as string;
  const [paper, setPaper] = useState<LibraryPaper | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);

  useKatex();

  useEffect(() => {
    getLibraryPaper(paperId)
      .then(setPaper)
      .catch(() => setPaper(null))
      .finally(() => setLoading(false));
  }, [paperId]);

  // Re-render math when paper data changes
  useEffect(() => {
    if (paper) setTimeout(renderMath, 200);
  }, [paper]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const res = await fetch(`/api/v1/library/papers/${paperId}/analyze`, { method: "POST" });
      if (res.ok) {
        const updated = await getLibraryPaper(paperId);
        setPaper(updated);
        setTimeout(renderMath, 300);
      }
    } catch (e) { console.error(e); }
    finally { setAnalyzing(false); }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="h-6 w-6 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!paper) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <p className="text-[var(--accent-red)] text-sm mb-4">Paper not found</p>
          <Link href="/library" className="btn-secondary">Back to Library</Link>
        </div>
      </div>
    );
  }

  const deep = paper.deep_analysis_json as DeepAnalysisData | undefined;
  const hasDeep = deep && (deep.motivation || deep.critical_review);

  return (
    <div className="max-w-[1060px] mx-auto px-8 py-8 space-y-6">
      {/* Back */}
      <Link href="/library" className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M9 11L5 7L9 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Back to Library
      </Link>

      {/* Header card */}
      <div className="card-static p-6">
        <div className="flex items-center gap-2 mb-3">
          <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
            paper.status === "deep_analyzed"
              ? "bg-[var(--accent-green-soft)] text-[var(--accent-green)]"
              : "bg-[var(--accent-amber-soft)] text-[var(--accent-amber)]"
          }`}>
            {paper.status === "deep_analyzed" ? "Deep Analyzed" : "Light Analyzed"}
          </span>
          {paper.arxiv_id && (
            <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noopener noreferrer"
              className="text-[11px] text-[var(--accent)] hover:underline" style={{ fontFamily: "var(--font-mono)" }}>
              arXiv:{paper.arxiv_id}
            </a>
          )}
        </div>
        <h1 className="text-xl font-medium text-[var(--text-primary)] mb-2" style={{ fontFamily: "var(--font-display)" }}>
          {paper.title}
        </h1>
        {paper.authors?.length > 0 && (
          <p className="text-[13px] text-[var(--text-muted)] mb-2">{paper.authors.join(", ")}</p>
        )}
        <div className="flex items-center gap-3 text-[12px] text-[var(--text-muted)]">
          {paper.year && <span>{paper.year}</span>}
          {paper.venue && <span>{paper.venue}</span>}
          {paper.field && <span className="font-medium" style={{ color: "var(--accent)" }}>{paper.field}</span>}
        </div>
        {/* Tags */}
        {((paper.keywords?.length ?? 0) > 0 || (paper.methods?.length ?? 0) > 0) && (
          <div className="flex flex-wrap gap-1.5 mt-3 pt-3 border-t border-[var(--border-subtle)]">
            {paper.keywords?.map((kw) => (
              <span key={kw} className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">{kw}</span>
            ))}
            {paper.methods?.map((m) => (
              <span key={m} className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--accent-blue-soft)] text-[var(--accent-blue)]">{m}</span>
            ))}
          </div>
        )}
      </div>

      {/* Deep Analysis — structured rendering */}
      {hasDeep ? (
        <div className="space-y-5">
          {/* Motivation */}
          {deep.motivation && (
            <AnalysisSection title="Research Motivation" icon="💡">
              <p className="text-[13px] text-[var(--text-primary)] leading-relaxed whitespace-pre-line">
                {deep.motivation}
              </p>
            </AnalysisSection>
          )}

          {/* Mathematical Formulation — rendered with KaTeX */}
          {deep.mathematical_formulation && (
            <AnalysisSection title="Mathematical Formulation" icon="📐">
              <div className="text-[13px] text-[var(--text-primary)] leading-relaxed whitespace-pre-line">
                {deep.mathematical_formulation}
              </div>
            </AnalysisSection>
          )}

          {/* Experimental Design — structured table */}
          {deep.experimental_design && (
            <AnalysisSection title="Experimental Design" icon="🔬">
              <div className="space-y-3">
                {(deep.experimental_design?.models?.length ?? 0) > 0 && (
                  <div>
                    <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">Models</span>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {deep.experimental_design?.models?.map((m: string) => (
                        <span key={m} className="text-[12px] px-2.5 py-1 rounded-lg bg-[var(--bg-secondary)] text-[var(--text-primary)]">{m}</span>
                      ))}
                    </div>
                  </div>
                )}
                {(deep.experimental_design?.datasets?.length ?? 0) > 0 && (
                  <div>
                    <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">Datasets</span>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {deep.experimental_design?.datasets?.map((d: string) => (
                        <span key={d} className="text-[12px] px-2.5 py-1 rounded-lg bg-[var(--bg-secondary)] text-[var(--text-primary)]">{d}</span>
                      ))}
                    </div>
                  </div>
                )}
                {deep.experimental_design?.hyperparams && (
                  <div>
                    <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">Hyperparameters</span>
                    <p className="text-[12px] text-[var(--text-secondary)] mt-1 leading-relaxed" style={{ fontFamily: "var(--font-mono)" }}>
                      {deep.experimental_design?.hyperparams}
                    </p>
                  </div>
                )}
                {deep.experimental_design?.reproducibility_notes && (
                  <div>
                    <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">Reproducibility</span>
                    <p className="text-[13px] text-[var(--text-secondary)] mt-1 leading-relaxed">
                      {deep.experimental_design?.reproducibility_notes}
                    </p>
                  </div>
                )}
              </div>
            </AnalysisSection>
          )}

          {/* Results — structured display */}
          {deep.results && (
            <AnalysisSection title="Results & Conclusions" icon="📊">
              <div className="space-y-3">
                {(deep.results?.baselines?.length ?? 0) > 0 && (
                  <div>
                    <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">Baselines</span>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {deep.results?.baselines?.map((b: string) => (
                        <span key={b} className="text-[12px] px-2.5 py-1 rounded-lg bg-[var(--bg-secondary)] text-[var(--text-primary)]">{b}</span>
                      ))}
                    </div>
                  </div>
                )}
                {deep.results?.best_metrics && (
                  <div>
                    <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">Best Metrics</span>
                    <p className="text-[13px] text-[var(--text-primary)] mt-1" style={{ fontFamily: "var(--font-mono)" }}>
                      {deep.results?.best_metrics}
                    </p>
                  </div>
                )}
                {(deep.results?.key_insights?.length ?? 0) > 0 && (
                  <div>
                    <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">Key Insights</span>
                    <ul className="mt-1 space-y-1.5">
                      {deep.results?.key_insights?.map((insight: string, i: number) => (
                        <li key={i} className="text-[13px] text-[var(--text-primary)] leading-relaxed pl-3 border-l-2 border-[var(--accent)]">
                          {insight}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </AnalysisSection>
          )}

          {/* Critical Review — strengths/weaknesses/improvements */}
          {deep.critical_review && (
            <AnalysisSection title="Critical Review" icon="🔍">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {(deep.critical_review?.strengths?.length ?? 0) > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-2">
                      <span className="h-2 w-2 rounded-full bg-[var(--accent-green)]" />
                      <span className="text-[11px] font-semibold text-[var(--accent-green)] uppercase tracking-wider">Strengths</span>
                    </div>
                    <ul className="space-y-2">
                      {deep.critical_review?.strengths?.map((s: string, i: number) => (
                        <li key={i} className="text-[12px] text-[var(--text-primary)] leading-relaxed pl-3 border-l-2 border-[var(--accent-green)]/30">
                          {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(deep.critical_review?.weaknesses?.length ?? 0) > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-2">
                      <span className="h-2 w-2 rounded-full bg-[var(--accent-red)]" />
                      <span className="text-[11px] font-semibold text-[var(--accent-red)] uppercase tracking-wider">Weaknesses</span>
                    </div>
                    <ul className="space-y-2">
                      {deep.critical_review?.weaknesses?.map((w: string, i: number) => (
                        <li key={i} className="text-[12px] text-[var(--text-primary)] leading-relaxed pl-3 border-l-2 border-[var(--accent-red)]/30">
                          {w}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(deep.critical_review?.improvements?.length ?? 0) > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-2">
                      <span className="h-2 w-2 rounded-full bg-[var(--accent-amber)]" />
                      <span className="text-[11px] font-semibold text-[var(--accent-amber)] uppercase tracking-wider">Improvements</span>
                    </div>
                    <ul className="space-y-2">
                      {deep.critical_review?.improvements?.map((imp: string, i: number) => (
                        <li key={i} className="text-[12px] text-[var(--text-primary)] leading-relaxed pl-3 border-l-2 border-[var(--accent-amber)]/30">
                          {imp}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </AnalysisSection>
          )}

          {/* One More Thing */}
          {deep.one_more_thing && (
            <AnalysisSection title="One More Thing" icon="✨">
              <p className="text-[13px] text-[var(--text-primary)] leading-relaxed whitespace-pre-line">
                {deep.one_more_thing}
              </p>
            </AnalysisSection>
          )}
        </div>
      ) : (
        /* No deep analysis yet */
        <div className="card-static p-8 text-center">
          <p className="text-[14px] text-[var(--text-secondary)] mb-1">
            This paper has light-level tags only.
          </p>
          <p className="text-[12px] text-[var(--text-muted)] mb-4">
            Run deep analysis for full review with motivation, experiments, and critical assessment.
          </p>
          <button onClick={handleAnalyze} disabled={analyzing} className="btn-primary text-[13px]">
            {analyzing ? (
              <span className="flex items-center gap-2">
                <span className="h-3.5 w-3.5 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                Analyzing — this may take a minute...
              </span>
            ) : "Run Deep Analysis"}
          </button>
        </div>
      )}

      {/* Bottom actions */}
      <div className="flex items-center gap-3 pt-4 border-t border-[var(--border-subtle)]">
        {paper.arxiv_id && (
          <a href={`https://arxiv.org/pdf/${paper.arxiv_id}`} target="_blank" rel="noopener noreferrer" className="btn-secondary text-[13px]">
            View PDF on arXiv
          </a>
        )}
      </div>
    </div>
  );
}

/* ── Section wrapper ── */
function AnalysisSection({ title, icon, children }: { title: string; icon: string; children: React.ReactNode }) {
  return (
    <div className="card-static p-5 animate-fade-up">
      <h2 className="flex items-center gap-2 text-[13px] font-semibold text-[var(--text-primary)] mb-3">
        <span>{icon}</span>
        {title}
      </h2>
      {children}
    </div>
  );
}

/* ── Type for deep analysis data ── */
interface DeepAnalysisData {
  motivation?: string;
  mathematical_formulation?: string;
  experimental_design?: {
    models?: string[];
    datasets?: string[];
    hyperparams?: string;
    reproducibility_notes?: string;
  };
  results?: {
    baselines?: string[];
    best_metrics?: string;
    key_insights?: string[];
  };
  critical_review?: {
    strengths?: string[];
    weaknesses?: string[];
    improvements?: string[];
  };
  one_more_thing?: string;
}
