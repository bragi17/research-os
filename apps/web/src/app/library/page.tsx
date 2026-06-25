"use client";

import { useState, useEffect, useCallback } from "react";
import {
  copyLibraryPaperToPool,
  createLibraryPool,
  deleteLibraryPool,
  getLibraryPoolDuplicates,
  listLibraryPapers,
  listLibraryPools,
  moveLibraryPaperToPool,
  searchLibrary,
  removeFromLibrary,
  analyzeLibraryPaper,
  uploadLibraryFile,
  getLibraryStats,
  uploadToLibrary,
  type LibraryDuplicateCandidate,
  type LibraryPaper,
  type LibraryPool,
} from "@/lib/api";
import { LibraryPaperCard } from "@/features/library/LibraryPaperCard";
import { LibraryUploadPanel } from "@/features/library/LibraryUploadPanel";

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
  const [pools, setPools] = useState<LibraryPool[]>([]);
  const [activePoolId, setActivePoolId] = useState<string | null>(null);
  const [newPoolName, setNewPoolName] = useState("");
  const [creatingPool, setCreatingPool] = useState(false);
  const [deletePoolPapers, setDeletePoolPapers] = useState(false);
  const [duplicateGroups, setDuplicateGroups] = useState<LibraryDuplicateCandidate[]>([]);

  const fetchPools = useCallback(async () => {
    try {
      const result = await listLibraryPools();
      setPools(result.items);
      setActivePoolId((current) => {
        if (current && result.items.some((pool) => pool.id === current)) return current;
        return result.items.find((pool) => pool.kind === "default")?.id ?? result.items[0]?.id ?? null;
      });
    } catch {
      /* silent */
    }
  }, []);

  const fetchPapers = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const params = new URLSearchParams();
      if (activeField) params.set("field", activeField);
      if (activePoolId) params.set("pool_ids", activePoolId);
      const query = params.toString();
      const result = await listLibraryPapers(query || undefined);
      setPapers(result.items);
      setTotal(result.total);
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [activeField, activePoolId]);

  const fetchStats = useCallback(async () => {
    try {
      setStats(await getLibraryStats());
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    fetchPools();
  }, [fetchPools]);

  useEffect(() => {
    fetchPapers(true);  // show spinner only on first load
    fetchStats();
  }, [fetchPapers, fetchStats]);

  useEffect(() => {
    if (!activePoolId) {
      setDuplicateGroups([]);
      return;
    }
    let cancelled = false;
    getLibraryPoolDuplicates(activePoolId)
      .then((result) => {
        if (!cancelled) setDuplicateGroups(result.items);
      })
      .catch(() => {
        if (!cancelled) setDuplicateGroups([]);
      });
    return () => { cancelled = true; };
  }, [activePoolId, papers]);

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
        const result = await searchLibrary(
          searchQuery.trim(),
          20,
          activePoolId ? [activePoolId] : [],
        );
        setPapers(result.items);
        setTotal(result.total);
      } catch { /* silent */ }
      finally { setLoading(false); }
    }, 300);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, activePoolId]);

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
      await uploadToLibrary({ arxiv_id: id, pool_ids: activePoolId ? [activePoolId] : [] });
      setUploadId("");
      setShowUpload(false);
      fetchPapers();
      fetchPools();
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
      await uploadLibraryFile(selectedFile, activePoolId);
      setSelectedFile(null);
      setShowUpload(false);
      fetchPapers();
      fetchPools();
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

  const handleCreatePool = async () => {
    const name = newPoolName.trim();
    if (!name) return;
    setCreatingPool(true);
    try {
      const created = await createLibraryPool({ name });
      setNewPoolName("");
      await fetchPools();
      setActivePoolId(created.id);
    } catch {
      /* silent */
    } finally {
      setCreatingPool(false);
    }
  };

  const handleDeletePool = async () => {
    const pool = pools.find((item) => item.id === activePoolId);
    if (!pool || pool.is_system) return;
    const confirmed = window.confirm(
      deletePoolPapers
        ? `Delete "${pool.name}" and permanently delete ${pool.paper_count} paper(s) from the library?`
        : `Delete "${pool.name}" and move papers with no other pool to Unassigned?`,
    );
    if (!confirmed) return;
    try {
      await deleteLibraryPool(pool.id, deletePoolPapers);
      setDeletePoolPapers(false);
      await fetchPools();
      await fetchPapers();
      await fetchStats();
    } catch {
      /* silent */
    }
  };

  const handleCopyToPool = async (paperId: string, targetPoolId: string) => {
    await copyLibraryPaperToPool(paperId, targetPoolId);
    fetchPools();
  };

  const handleMoveToPool = async (paperId: string, targetPoolId: string) => {
    if (!activePoolId) return;
    await moveLibraryPaperToPool(paperId, activePoolId, targetPoolId);
    fetchPapers();
    fetchPools();
  };

  // Collect unique fields for filter chips
  const fields = Array.from(new Set(papers.map((p) => p.field).filter(Boolean))) as string[];
  const activePool = pools.find((pool) => pool.id === activePoolId) ?? null;
  const duplicateReasonByPaper = new Map<string, string>();
  duplicateGroups.forEach((group) => {
    group.paper_ids.forEach((paperId) => {
      duplicateReasonByPaper.set(paperId, group.reason);
    });
  });

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
        <LibraryUploadPanel
          uploadTab={uploadTab}
          uploadId={uploadId}
          uploading={uploading}
          uploadError={uploadError}
          selectedFile={selectedFile}
          targetPoolName={activePool?.name ?? "Default Library"}
          onTabChange={setUploadTab}
          onUploadIdChange={setUploadId}
          onFileChange={setSelectedFile}
          onUpload={handleUpload}
          onFileUpload={handleFileUpload}
        />
      )}

      {/* Pools */}
      <div className="card-static p-4 mb-5 animate-fade-up delay-75">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mr-1">
            Knowledge Pools
          </span>
          {pools.map((pool) => (
            <button
              key={pool.id}
              type="button"
              onClick={() => setActivePoolId(pool.id)}
              className={`px-3 py-1.5 rounded-full text-[11px] font-medium transition-all border ${
                activePoolId === pool.id
                  ? "bg-[var(--accent)] text-white border-[var(--accent)]"
                  : "bg-white text-[var(--text-secondary)] border-[var(--border-subtle)] hover:border-[var(--accent)]"
              }`}
            >
              {pool.name}
              <span className="ml-1 opacity-70">{pool.paper_count}</span>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            className="input-field text-[12px] py-1.5 max-w-[220px]"
            placeholder="New pool name"
            value={newPoolName}
            onChange={(event) => setNewPoolName(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") handleCreatePool(); }}
          />
          <button
            type="button"
            onClick={handleCreatePool}
            disabled={creatingPool || !newPoolName.trim()}
            className="btn-secondary text-[12px] px-3 py-1.5"
          >
            {creatingPool ? "Creating..." : "Create Pool"}
          </button>

          {activePool && !activePool.is_system && (
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
                <input
                  type="checkbox"
                  checked={deletePoolPapers}
                  onChange={(event) => setDeletePoolPapers(event.target.checked)}
                />
                Delete papers too
              </label>
              <button
                type="button"
                onClick={handleDeletePool}
                className="btn-danger text-[12px] px-3 py-1.5"
              >
                Delete Pool
              </button>
            </div>
          )}
        </div>
      </div>

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
          {filteredPapers.map((paper) => (
            <LibraryPaperCard
              key={paper.id}
              paper={paper}
              pools={pools}
              activePoolId={activePoolId}
              duplicateReason={duplicateReasonByPaper.get(paper.id)}
              removingId={removingId}
              reanalyzingId={reanalyzingId}
              onRemove={handleRemove}
              onReanalyze={handleReanalyze}
              onCopyToPool={handleCopyToPool}
              onMoveToPool={handleMoveToPool}
            />
          ))}
        </div>
      )}
    </div>
  );
}
