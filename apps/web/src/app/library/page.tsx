"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  listLibraryPapers,
  searchLibrary,
  removeFromLibrary,
  getLibraryStats,
  type LibraryPaper,
} from "@/lib/api";

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  indexed: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  pending: { bg: "var(--accent-amber-soft)", text: "var(--accent-amber)" },
  processing: { bg: "var(--accent-blue-soft)", text: "var(--accent-blue)" },
  failed: { bg: "var(--accent-red-soft)", text: "var(--accent-red)" },
};

export default function LibraryPage() {
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<{ papers: number; chunks: number }>({ papers: 0, chunks: 0 });
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeField, setActiveField] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  const fetchPapers = useCallback(async () => {
    setLoading(true);
    try {
      const params = activeField ? `field=${encodeURIComponent(activeField)}` : undefined;
      const result = await listLibraryPapers(params);
      setPapers(result.items);
      setTotal(result.total);
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [activeField]);

  const fetchStats = useCallback(async () => {
    try {
      setStats(await getLibraryStats());
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    fetchPapers();
    fetchStats();
  }, [fetchPapers, fetchStats]);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      fetchPapers();
      return;
    }
    setLoading(true);
    try {
      const result = await searchLibrary(searchQuery.trim());
      setPapers(result.items);
      setTotal(result.total);
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [searchQuery, fetchPapers]);

  useEffect(() => {
    const timeout = setTimeout(handleSearch, 300);
    return () => clearTimeout(timeout);
  }, [searchQuery, handleSearch]);

  const handleRemove = async (id: string) => {
    setRemovingId(id);
    try {
      await removeFromLibrary(id);
      setPapers((prev) => prev.filter((p) => p.id !== id));
      setTotal((prev) => prev - 1);
      setStats((prev) => ({ ...prev, papers: Math.max(0, prev.papers - 1) }));
    } catch {
      /* silent */
    } finally {
      setRemovingId(null);
    }
  };

  // Collect unique fields for filter chips
  const fields = Array.from(new Set(papers.map((p) => p.field).filter(Boolean))) as string[];

  const filteredPapers = activeField
    ? papers.filter((p) => p.field === activeField)
    : papers;

  return (
    <div className="max-w-[860px] mx-auto px-8 py-10">
      {/* Header */}
      <div className="mb-6 animate-fade-up">
        <h1
          className="text-2xl font-medium text-[var(--text-primary)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Paper Library
        </h1>
        <p className="text-sm text-[var(--text-muted)]">
          Your indexed research papers, searchable and ready for new runs.
        </p>
      </div>

      {/* Search */}
      <div className="mb-5 animate-fade-up delay-75">
        <div className="relative">
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
          >
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            className="input-field pl-10 text-[14px]"
            placeholder="Search papers by title, keyword, method..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 mb-5 animate-fade-up delay-100">
        <div className="card-static px-4 py-2.5 flex items-center gap-2">
          <span className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider">Papers</span>
          <span
            className="text-[15px] font-semibold text-[var(--accent)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {stats.papers}
          </span>
        </div>
        <div className="card-static px-4 py-2.5 flex items-center gap-2">
          <span className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider">Chunks</span>
          <span
            className="text-[15px] font-semibold text-[var(--accent-blue)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {stats.chunks}
          </span>
        </div>
        <span className="text-[12px] text-[var(--text-muted)] ml-auto">
          {total} result{total !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Field filter chips */}
      {fields.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-5 animate-fade-up delay-150">
          <button
            onClick={() => setActiveField(null)}
            className={`px-3 py-1.5 rounded-full text-[11px] font-medium transition-all border ${
              activeField === null
                ? "bg-[var(--accent)] text-white border-[var(--accent)]"
                : "bg-white text-[var(--text-secondary)] border-[var(--border-subtle)] hover:border-[var(--accent)]"
            }`}
          >
            All
          </button>
          {fields.map((field) => (
            <button
              key={field}
              onClick={() => setActiveField(activeField === field ? null : field)}
              className={`px-3 py-1.5 rounded-full text-[11px] font-medium transition-all border ${
                activeField === field
                  ? "bg-[var(--accent)] text-white border-[var(--accent)]"
                  : "bg-white text-[var(--text-secondary)] border-[var(--border-subtle)] hover:border-[var(--accent)]"
              }`}
            >
              {field}
            </button>
          ))}
        </div>
      )}

      {/* Paper list */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-5 w-5 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
        </div>
      ) : filteredPapers.length === 0 ? (
        <div className="card-static p-12 text-center animate-fade-up delay-200">
          <div className="text-3xl mb-3 opacity-40">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none" className="mx-auto">
              <rect x="8" y="10" width="32" height="28" rx="3" stroke="var(--text-muted)" strokeWidth="2" />
              <path d="M16 10V7h16v3" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" />
              <path d="M18 22h12M18 28h8" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <p className="text-[15px] font-medium text-[var(--text-secondary)] mb-1">
            No papers in your library
          </p>
          <p className="text-[13px] text-[var(--text-muted)]">
            Papers from completed research runs will appear here.
          </p>
        </div>
      ) : (
        <div className="space-y-3 animate-fade-up delay-200">
          {filteredPapers.map((paper) => {
            const statusStyle = STATUS_STYLES[paper.status] ?? STATUS_STYLES.pending;
            return (
              <div key={paper.id} className="card-static p-5">
                <div className="flex items-start justify-between gap-4 mb-2">
                  <h3
                    className="text-[15px] font-medium text-[var(--text-primary)] leading-snug flex-1 line-clamp-2"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {paper.title}
                  </h3>
                  <span
                    className="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider"
                    style={{
                      background: statusStyle.bg,
                      color: statusStyle.text,
                    }}
                  >
                    {paper.status}
                  </span>
                </div>

                <div className="flex items-center gap-2 text-[12px] text-[var(--text-muted)] mb-3">
                  {paper.venue && <span className="font-medium">{paper.venue}</span>}
                  {paper.venue && paper.year && <span>&middot;</span>}
                  {paper.year && <span>{paper.year}</span>}
                  {paper.arxiv_id && (
                    <>
                      <span>&middot;</span>
                      <span style={{ fontFamily: "var(--font-mono)" }}>{paper.arxiv_id}</span>
                    </>
                  )}
                  {paper.citation_count > 0 && (
                    <>
                      <span>&middot;</span>
                      <span>{paper.citation_count} citations</span>
                    </>
                  )}
                  {paper.field && (
                    <>
                      <span>&middot;</span>
                      <span className="text-[var(--accent)]">{paper.field}</span>
                    </>
                  )}
                </div>

                {/* Keywords pills */}
                {paper.keywords.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-3">
                    {paper.keywords.slice(0, 6).map((kw) => (
                      <span
                        key={kw}
                        className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[var(--accent-soft)] text-[var(--accent)]"
                      >
                        {kw}
                      </span>
                    ))}
                    {paper.keywords.length > 6 && (
                      <span className="text-[10px] text-[var(--text-muted)] self-center">
                        +{paper.keywords.length - 6} more
                      </span>
                    )}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2">
                  <Link
                    href={`/library/${paper.id}`}
                    className="btn-secondary text-[12px] px-3 py-1.5"
                  >
                    View
                  </Link>
                  <button
                    onClick={() => handleRemove(paper.id)}
                    disabled={removingId === paper.id}
                    className="btn-danger text-[12px] px-3 py-1.5"
                  >
                    {removingId === paper.id ? "Removing..." : "Remove"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
