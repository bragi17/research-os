"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  listLibraryPapers,
  searchLibrary,
  removeFromLibrary,
  analyzeLibraryPaper,
  getLibraryStats,
  uploadToLibrary,
  type LibraryPaper,
} from "@/lib/api";

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  analyzed: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  deep_analyzed: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  light_analyzed: { bg: "var(--accent-blue-soft)", text: "var(--accent-blue)" },
  indexed: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  partial: { bg: "var(--accent-amber-soft)", text: "var(--accent-amber)" },
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
  const [showUpload, setShowUpload] = useState(false);
  const [uploadTab, setUploadTab] = useState<"arxiv" | "file">("arxiv");
  const [uploadId, setUploadId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [reanalyzingId, setReanalyzingId] = useState<string | null>(null);

  const fetchPapers = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
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
    fetchPapers(true);  // show spinner only on first load
    fetchStats();
  }, [fetchPapers, fetchStats]);

  // Debounced search — only triggers when query changes, not on every render
  useEffect(() => {
    if (!searchQuery.trim()) {
      // Empty query: refetch all papers
      fetchPapers();
      return;
    }
    const timeout = setTimeout(async () => {
      setLoading(true);
      try {
        const result = await searchLibrary(searchQuery.trim());
        setPapers(result.items);
        setTotal(result.total);
      } catch { /* silent */ }
      finally { setLoading(false); }
    }, 300);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery]);

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

  const handleUpload = async () => {
    const id = uploadId.trim();
    if (!id) return;
    setUploading(true);
    setUploadError("");
    try {
      await uploadToLibrary({ arxiv_id: id });
      setUploadId("");
      setShowUpload(false);
      fetchPapers();
      fetchStats();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleFileUpload = async () => {
    if (!selectedFile) return;
    setUploading(true);
    setUploadError("");
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const res = await fetch("/api/v1/library/upload-file", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }
      setSelectedFile(null);
      setShowUpload(false);
      fetchPapers();
      fetchStats();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleReanalyze = async (paperId: string) => {
    setReanalyzingId(paperId);
    try {
      await analyzeLibraryPaper(paperId);
      fetchPapers();
      fetchStats();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Re-analyze failed");
    }
    finally { setReanalyzingId(null); }
  };

  // Collect unique fields for filter chips
  const fields = Array.from(new Set(papers.map((p) => p.field).filter(Boolean))) as string[];

  const filteredPapers = activeField
    ? papers.filter((p) => p.field === activeField)
    : papers;

  return (
    <div className="max-w-[1060px] mx-auto px-8 py-10">
      {/* Header */}
      <div className="flex items-start justify-between mb-6 animate-fade-up">
        <div>
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
        <button
          onClick={() => setShowUpload(!showUpload)}
          className="btn-primary text-[13px] shrink-0"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          Upload Paper
        </button>
      </div>

      {/* Upload panel */}
      {showUpload && (
        <div className="card-static p-5 mb-5 animate-fade-up">
          {/* Tab: arXiv ID / File Upload */}
          <div className="flex gap-4 mb-4">
            <button
              onClick={() => setUploadTab("arxiv")}
              className={`text-[13px] font-medium pb-1 transition-colors ${uploadTab === "arxiv" ? "text-[var(--accent)] border-b-2 border-[var(--accent)]" : "text-[var(--text-muted)]"}`}
            >
              arXiv ID
            </button>
            <button
              onClick={() => setUploadTab("file")}
              className={`text-[13px] font-medium pb-1 transition-colors ${uploadTab === "file" ? "text-[var(--accent)] border-b-2 border-[var(--accent)]" : "text-[var(--text-muted)]"}`}
            >
              Upload File
            </button>
          </div>

          {uploadTab === "arxiv" ? (
            <>
              <div className="flex gap-3">
                <input
                  type="text"
                  className="input-field text-[13px] flex-1"
                  style={{ fontFamily: "var(--font-mono)" }}
                  placeholder="e.g. 2505.24431"
                  value={uploadId}
                  onChange={(e) => setUploadId(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleUpload(); }}
                />
                <button onClick={handleUpload} disabled={uploading || !uploadId.trim()} className="btn-primary text-[13px] px-5">
                  {uploading ? <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />Adding</span> : "Add"}
                </button>
              </div>
              <p className="text-[11px] text-[var(--text-muted)] mt-2">
                The paper will be downloaded from arXiv, parsed, tagged, and indexed.
              </p>
            </>
          ) : (
            <>
              <div className="flex gap-3 items-center">
                <label className="flex-1 cursor-pointer">
                  <div className="input-field text-[13px] text-center py-6 border-dashed hover:border-[var(--accent)] transition-colors">
                    {selectedFile ? (
                      <span className="text-[var(--text-primary)]">{selectedFile.name}</span>
                    ) : (
                      <span className="text-[var(--text-muted)]">
                        Click to select .tar.gz, .gz, or .zip file
                      </span>
                    )}
                  </div>
                  <input type="file" className="hidden" accept=".tar.gz,.tgz,.gz,.zip,.tex"
                    onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)} />
                </label>
                <button
                  onClick={handleFileUpload}
                  disabled={uploading || !selectedFile}
                  className="btn-primary text-[13px] px-5"
                >
                  {uploading ? <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />Uploading</span> : "Upload"}
                </button>
              </div>
              <p className="text-[11px] text-[var(--text-muted)] mt-2">
                Upload a LaTeX source archive (same format as arXiv downloads). The paper will be parsed and indexed.
              </p>
            </>
          )}

          {uploading && (
            <div className="flex items-center gap-2 mt-3 text-[11px] text-[var(--text-muted)]">
              <div className="h-3 w-3 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin shrink-0" />
              <span className="animate-pulse">Downloading → Parsing → Analyzing → Tagging → Embedding → Storing...</span>
            </div>
          )}
          {uploadError && (
            <p className="text-[12px] text-[var(--accent-red)] mt-2">{uploadError}</p>
          )}
        </div>
      )}

      {/* Search */}
      <div className="mb-5 animate-fade-up delay-75">
        <div className="relative">
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none"
          >
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            className="input-field text-[14px]"
            style={{ paddingLeft: "2.75rem" }}
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
        <div className="card-static p-12 text-center">
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
        <div className="space-y-3">
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

                {/* Re-analyzing progress */}
                {reanalyzingId === paper.id && (
                  <div className="flex items-center gap-2 mb-3 text-[11px] text-[var(--text-muted)]">
                    <div className="h-3 w-3 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin shrink-0" />
                    <span className="animate-pulse">Analyzing: content → sections → LLM analysis → tagging → embedding → storing...</span>
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2">
                  <Link
                    href={`/library/papers/${paper.id}`}
                    className="btn-secondary text-[12px] px-3 py-1.5"
                  >
                    View
                  </Link>
                  {(paper.status === "partial" || paper.status === "pending" || paper.status === "light_analyzed") && (
                    <button
                      onClick={() => handleReanalyze(paper.id)}
                      disabled={reanalyzingId === paper.id}
                      className="btn-secondary text-[12px] px-3 py-1.5"
                    >
                      {reanalyzingId === paper.id ? "Analyzing..." : "Re-analyze"}
                    </button>
                  )}
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
