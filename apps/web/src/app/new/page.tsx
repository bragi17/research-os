"use client";

import { Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  createWork,
  getModelSettings,
  listLibraryPools,
  searchLibraryTitles,
  startPhaseExecution,
  type LibraryPaper,
  type LibraryPool,
  type ResearchPhase,
} from "@/lib/api";

const MODES: { value: ResearchPhase; label: string; desc: string; icon: string }[] = [
  { value: "atlas", label: "Atlas", desc: "Explore & map a research field", icon: "🗺" },
  { value: "frontier", label: "Frontier", desc: "Analyze a sub-field in depth", icon: "🔬" },
  { value: "divergent", label: "Divergent", desc: "Find cross-domain innovations", icon: "💡" },
];

const PLACEHOLDERS: Record<ResearchPhase, string> = {
  atlas: "e.g. Multi-agent reinforcement learning and cooperative AI systems",
  frontier: "e.g. 3D anomaly detection for industrial point cloud inspection",
  divergent: "e.g. Finding novel approaches to zero-shot 3D anomaly detection",
};

const DEFAULT_EXPERIMENT_ROOT = "/data/research-os/experiments";
const WORK_PHASE_HINTS_STORAGE_KEY = "ros_work_phases";

function createDraftRunId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const value = Math.floor(Math.random() * 16);
    const next = char === "x" ? value : (value & 0x3) | 0x8;
    return next.toString(16);
  });
}

function slugifyRunTitle(title: string): string {
  const slug = Array.from(title.trim().toLowerCase())
    .map((char) => (/[\p{L}\p{N}]/u.test(char) ? char : "-"))
    .join("")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80)
    .replace(/-$/g, "");
  return slug || "research-run";
}

function joinWorkspacePath(root: string, name: string): string {
  return `${root.replace(/\/+$/g, "")}/${name}`;
}

function isUuid(value: string | null): value is string {
  return Boolean(value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value));
}

function rememberWorkPhase(workId: string, phase: ResearchPhase) {
  try {
    const stored = JSON.parse(localStorage.getItem(WORK_PHASE_HINTS_STORAGE_KEY) || "{}");
    const next = stored && typeof stored === "object" && !Array.isArray(stored) ? stored : {};
    localStorage.setItem(WORK_PHASE_HINTS_STORAGE_KEY, JSON.stringify({ ...next, [workId]: phase }));
  } catch { /* silent */ }
}

export default function NewResearchPage() {
  return (
    <Suspense fallback={<div className="flex h-screen items-center justify-center bg-[var(--bg-primary)]"><div className="h-5 w-5 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" /></div>}>
      <NewResearchContent />
    </Suspense>
  );
}

function timeAgo(dateStr: string): string {
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    return `${Math.floor(hrs / 24)}d`;
  } catch { return ""; }
}

function NewResearchContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const modeParam = searchParams.get("mode");
  const topicParam = searchParams.get("topic");
  const initialMode: ResearchPhase = modeParam && ["atlas", "frontier", "divergent"].includes(modeParam) ? (modeParam as ResearchPhase) : "frontier";

  const [mode, setMode] = useState<ResearchPhase>(initialMode);
  const [topic, setTopic] = useState(topicParam ?? "");
  const [topicError, setTopicError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [draftRunId, setDraftRunId] = useState("");
  const [experimentRoot, setExperimentRoot] = useState(DEFAULT_EXPERIMENT_ROOT);
  const [experimentWorkspace, setExperimentWorkspace] = useState("");
  const [workspaceEdited, setWorkspaceEdited] = useState(false);

  // Research parameters - always visible
  const [seedPapers, setSeedPapers] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);

  // Budget - collapsed
  const [budgetOpen, setBudgetOpen] = useState(false);
  const [maxPapers, setMaxPapers] = useState(150);
  const [maxReads, setMaxReads] = useState(40);
  const [maxCost, setMaxCost] = useState(30);

  // Library seed paper picker
  const [libraryQuery, setLibraryQuery] = useState("");
  const [libraryResults, setLibraryResults] = useState<LibraryPaper[]>([]);
  const [librarySearching, setLibrarySearching] = useState(false);
  const [selectedLibraryPapers, setSelectedLibraryPapers] = useState<LibraryPaper[]>([]);
  const libraryDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [libraryPools, setLibraryPools] = useState<LibraryPool[]>([]);
  const [selectedPoolIds, setSelectedPoolIds] = useState<string[]>([]);

  // Mode-specific
  const [venueFilter, setVenueFilter] = useState("");
  const [benchmark, setBenchmark] = useState("");
  const [painPointInput, setPainPointInput] = useState("");

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(72, Math.min(160, el.scrollHeight))}px`;
  }, [topic]);

  useEffect(() => {
    setDraftRunId(createDraftRunId());
  }, []);

  useEffect(() => {
    listLibraryPools()
      .then((result) => setLibraryPools(result.items))
      .catch(() => setLibraryPools([]));
  }, []);

  useEffect(() => {
    let active = true;
    getModelSettings()
      .then((result) => {
        const storage = result.categories.find((category) => category.id === "storage");
        const root = storage?.items.find((item) => item.key === "RESEARCH_OS_WORKSPACE_ROOT");
        if (active && root?.value) {
          setExperimentRoot(root.value);
        }
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  const runTitle = useMemo(() => topic.trim().slice(0, 60) || "New Research", [topic]);
  const defaultExperimentWorkspace = useMemo(
    () => joinWorkspacePath(
      experimentRoot,
      `${slugifyRunTitle(runTitle)}-${draftRunId || "draft"}`,
    ),
    [draftRunId, experimentRoot, runTitle],
  );
  const displayedExperimentWorkspace = workspaceEdited
    ? experimentWorkspace
    : defaultExperimentWorkspace;

  const addKeyword = useCallback(() => {
    const trimmed = keywordInput.trim();
    if (trimmed && !keywords.includes(trimmed)) {
      setKeywords((prev) => [...prev, trimmed]);
      setKeywordInput("");
    }
  }, [keywordInput, keywords]);

  // Library typeahead search with debounce
  useEffect(() => {
    if (!libraryQuery.trim()) {
      setLibraryResults([]);
      return;
    }
    if (libraryDebounceRef.current) clearTimeout(libraryDebounceRef.current);
    libraryDebounceRef.current = setTimeout(async () => {
      setLibrarySearching(true);
      try {
        const result = await searchLibraryTitles(
          libraryQuery.trim(),
          10,
          selectedPoolIds,
        );
        setLibraryResults(result.items);
      } catch {
        setLibraryResults([]);
      } finally {
        setLibrarySearching(false);
      }
    }, 250);
    return () => {
      if (libraryDebounceRef.current) clearTimeout(libraryDebounceRef.current);
    };
  }, [libraryQuery, selectedPoolIds]);

  const addLibraryPaper = useCallback((paper: LibraryPaper) => {
    if (selectedLibraryPapers.some((p) => p.id === paper.id)) return;
    setSelectedLibraryPapers((prev) => [...prev, paper]);
    setLibraryQuery("");
    setLibraryResults([]);
  }, [selectedLibraryPapers]);

  const removeLibraryPaper = useCallback((paperId: string) => {
    setSelectedLibraryPapers((prev) => prev.filter((p) => p.id !== paperId));
  }, []);

  const togglePool = useCallback((poolId: string) => {
    setSelectedPoolIds((prev) =>
      prev.includes(poolId)
        ? prev.filter((id) => id !== poolId)
        : [...prev, poolId],
    );
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const currentTopic = (textareaRef.current?.value ?? topic).trim();
    if (currentTopic.length < 10) {
      setTopicError("Enter at least 10 characters to start research.");
      textareaRef.current?.focus();
      return;
    }
    setTopicError(null);
    setLoading(true);
    try {
      const manualSeeds = seedPapers.split("\n").map((s) => s.trim()).filter(Boolean);
      const librarySeeds = selectedLibraryPapers
        .map((p) => p.arxiv_id || p.doi || "")
        .filter(Boolean);
      const seeds = [...librarySeeds, ...manualSeeds];
      const kws = keywords.length > 0 ? keywords : keywordInput.split(",").map((k) => k.trim()).filter(Boolean);
      const experimentWorkspacePolicy = {
        path: displayedExperimentWorkspace.trim() || defaultExperimentWorkspace,
      };
      const budget = {
        max_new_papers: maxPapers,
        max_fulltext_reads: maxReads,
        max_cost_usd: maxCost,
      };
      const policy: Record<string, unknown> = {
        keywords: kws,
        seed_papers: seeds,
        library_pool_ids: selectedPoolIds,
        experiment_workspace: experimentWorkspacePolicy,
      };
      const manualInput: Record<string, unknown> = {
        topic: currentTopic,
        keywords: kws,
        seed_papers: seeds,
        library_pool_ids: selectedPoolIds,
        mode,
      };
      manualInput.experiment_workspace = experimentWorkspacePolicy;
      if (workspaceEdited && displayedExperimentWorkspace.trim()) {
        policy.workspace_edited = true;
        manualInput.workspace_edited = true;
      }
      if (mode === "frontier") {
        const venues = venueFilter.split(",").map((v) => v.trim()).filter(Boolean);
        manualInput.scope = currentTopic;
        if (venues.length > 0) manualInput.venue_filter = venues;
        if (benchmark.trim()) manualInput.benchmark = benchmark.trim();
      }
      if (mode === "divergent") {
        manualInput.pain_point_input = painPointInput.trim() || currentTopic;
      }
      const work = await createWork({
        title: currentTopic.slice(0, 60),
        topic: currentTopic,
        project_id: isUuid(searchParams.get("project")) ? searchParams.get("project") : null,
        budget,
        policy,
      });
      rememberWorkPhase(work.id, mode);
      try {
        await startPhaseExecution(work.id, mode, {
          manual_input: manualInput,
          source_card_ids: [],
        });
        router.push(`/works/${work.id}?phase=${mode}`);
      } catch (phaseErr) {
        console.error(phaseErr);
        router.push(`/works/${work.id}?phase=${mode}&phase_start=failed`);
      }
    } catch (err) {
      console.error(err);
      alert("Failed to create research work. Check console.");
    } finally { setLoading(false); }
  };

  return (
        <div className="max-w-[1060px] mx-auto px-8 py-10">
          {/* Header */}
          <div className="mb-8 animate-fade-up">
            <h1 className="text-2xl font-medium text-[var(--text-primary)] mb-1" style={{ fontFamily: "var(--font-display)" }}>
              New Research
            </h1>
            <p className="text-sm text-[var(--text-muted)]">
              Configure your research and start an autonomous analysis session.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5 animate-fade-up delay-100">
            {/* Mode selector */}
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                Research Mode
              </label>
              <div className="grid grid-cols-3 gap-2">
                {MODES.map((m) => (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => setMode(m.value)}
                    className={`p-3 rounded-xl text-left transition-all border ${
                      mode === m.value
                        ? "bg-white border-[var(--accent)] shadow-sm"
                        : "bg-transparent border-[var(--border-subtle)] hover:border-[var(--accent)] hover:bg-white/50"
                    }`}
                  >
                    <div className="text-base mb-1">{m.icon}</div>
                    <div className={`text-[13px] font-semibold ${mode === m.value ? "text-[var(--accent)]" : "text-[var(--text-primary)]"}`}>
                      {m.label}
                    </div>
                    <div className="text-[11px] text-[var(--text-muted)] mt-0.5 leading-snug">{m.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Topic */}
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                Research Topic
              </label>
              <textarea
                ref={textareaRef}
                value={topic}
                onChange={(e) => {
                  setTopic(e.target.value);
                  if (topicError) setTopicError(null);
                }}
                placeholder={PLACEHOLDERS[mode]}
                required
                minLength={10}
                rows={3}
                className="input-field resize-none text-[15px] leading-relaxed"
              />
              {topicError && (
                <p className="mt-1.5 text-[12px] text-[var(--accent-red)]">{topicError}</p>
              )}
            </div>

            {/* Knowledge pools */}
            {libraryPools.length > 0 && (
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
                  Knowledge Pools
                </label>
                <div className="flex flex-wrap gap-2 mt-2">
                  {libraryPools.map((pool) => {
                    const selected = selectedPoolIds.includes(pool.id);
                    return (
                      <button
                        key={pool.id}
                        type="button"
                        onClick={() => togglePool(pool.id)}
                        className={`px-3 py-2 rounded-lg text-left transition-all border min-w-[150px] ${
                          selected
                            ? "bg-[var(--accent-soft)] border-[var(--accent)] text-[var(--text-primary)]"
                            : "bg-white border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--accent)]"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[12px] font-semibold truncate">{pool.name}</span>
                          <span className="text-[11px] tabular-nums text-[var(--text-muted)]">{pool.paper_count}</span>
                        </div>
                        <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mt-0.5">
                          {pool.kind}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Seed Papers - always visible */}
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
                Seed Papers
              </label>
              <p className="text-[11px] text-[var(--text-muted)] mb-2">
                Search your library or paste arXiv IDs to anchor the search (optional)
              </p>

              {/* Library typeahead */}
              <div className="relative mb-3">
                <div className="relative">
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 14 14"
                    fill="none"
                    className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none"
                  >
                    <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.2" />
                    <path d="M9.5 9.5l3 3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                  </svg>
                  <input
                    type="text"
                    className="input-field text-[13px]"
                    style={{ paddingLeft: "2.75rem" }}
                    placeholder="Search library..."
                    value={libraryQuery}
                    onChange={(e) => setLibraryQuery(e.target.value)}
                  />
                  {librarySearching && (
                    <div className="absolute right-3 top-1/2 -translate-y-1/2">
                      <div className="h-3.5 w-3.5 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
                    </div>
                  )}
                </div>

                {/* Results dropdown */}
                {libraryResults.length > 0 && (
                  <div className="absolute z-20 w-full mt-1 bg-white border border-[var(--border-subtle)] rounded-xl shadow-lg overflow-hidden">
                    {libraryResults.map((paper) => {
                      const alreadySelected = selectedLibraryPapers.some((p) => p.id === paper.id);
                      return (
                        <button
                          key={paper.id}
                          type="button"
                          disabled={alreadySelected}
                          onClick={() => addLibraryPaper(paper)}
                          className={`flex items-center gap-2 w-full px-3.5 py-2.5 text-left transition-colors border-b border-[var(--border-subtle)] last:border-b-0 ${
                            alreadySelected
                              ? "opacity-40 cursor-not-allowed"
                              : "hover:bg-[var(--bg-secondary)]"
                          }`}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="text-[13px] text-[var(--text-primary)] truncate">{paper.title}</div>
                            <div className="text-[11px] text-[var(--text-muted)]">
                              {[paper.venue, paper.year, paper.arxiv_id].filter(Boolean).join(" \u00b7 ")}
                            </div>
                          </div>
                          {!alreadySelected && (
                            <span className="shrink-0 text-[var(--accent)] text-sm font-bold">+</span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Selected library papers */}
              {selectedLibraryPapers.length > 0 && (
                <div className="mb-3">
                  <div className="text-[11px] text-[var(--text-muted)] mb-1.5">Selected from library:</div>
                  <div className="space-y-1">
                    {selectedLibraryPapers.map((paper) => (
                      <div
                        key={paper.id}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--accent-soft)] border border-[var(--accent)]/15"
                      >
                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="shrink-0 text-[var(--accent)]">
                          <path d="M2 3h10v8H2zM4 3V2h6v1M5 6h4M5 8h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                        </svg>
                        <span className="text-[12px] text-[var(--text-primary)] truncate flex-1">
                          {paper.title}
                          {paper.year && <span className="text-[var(--text-muted)]"> ({paper.year})</span>}
                        </span>
                        <button
                          type="button"
                          onClick={() => removeLibraryPaper(paper.id)}
                          className="shrink-0 text-[var(--text-muted)] hover:text-[var(--accent-red)] transition-colors text-sm"
                        >
                          &times;
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Manual arXiv IDs */}
              <div className="text-[11px] text-[var(--text-muted)] mb-1.5">Manual arXiv IDs (one per line):</div>
              <textarea
                rows={2}
                className="input-field resize-none text-[13px]"
                style={{ fontFamily: "var(--font-mono)" }}
                placeholder={"2505.24431\n2301.07041"}
                value={seedPapers}
                onChange={(e) => setSeedPapers(e.target.value)}
              />
            </div>

            {/* Keywords - always visible */}
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
                Keywords
              </label>
              <p className="text-[11px] text-[var(--text-muted)] mb-2">
                Help narrow the search scope (optional, press Enter to add)
              </p>
              {keywords.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {keywords.map((kw) => (
                    <span key={kw} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-[var(--accent-soft)] text-[var(--accent)] border border-[var(--accent)]/20">
                      {kw}
                      <button type="button" onClick={() => setKeywords((p) => p.filter((k) => k !== kw))} className="hover:opacity-70 text-xs ml-0.5">&times;</button>
                    </span>
                  ))}
                </div>
              )}
              <input
                type="text"
                className="input-field text-[13px]"
                placeholder="e.g. point cloud, anomaly detection, zero-shot..."
                value={keywordInput}
                onChange={(e) => setKeywordInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addKeyword(); } }}
                onBlur={addKeyword}
              />
            </div>

            {/* Mode-specific fields */}
            {mode === "frontier" && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
                    Venue Filter
                  </label>
                  <input type="text" className="input-field text-[13px]" placeholder="CVPR, ICCV, NeurIPS..." value={venueFilter} onChange={(e) => setVenueFilter(e.target.value)} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
                    Benchmark
                  </label>
                  <input type="text" className="input-field text-[13px]" placeholder="MVTec 3D-AD..." value={benchmark} onChange={(e) => setBenchmark(e.target.value)} />
                </div>
              </div>
            )}

            {mode === "divergent" && (
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
                  Pain Point Description
                </label>
                <textarea
                  rows={2}
                  className="input-field resize-none text-[13px]"
                  placeholder="Describe the pain point you want to solve with cross-domain ideas..."
                  value={painPointInput}
                  onChange={(e) => setPainPointInput(e.target.value)}
                />
              </div>
            )}

            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
                Experiment Directory
              </label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  type="text"
                  className="input-field text-[13px] flex-1"
                  style={{ fontFamily: "var(--font-mono)" }}
                  value={displayedExperimentWorkspace}
                  onChange={(e) => {
                    setWorkspaceEdited(true);
                    setExperimentWorkspace(e.target.value);
                  }}
                />
                {workspaceEdited && (
                  <button
                    type="button"
                    className="btn-secondary text-[11px] px-3 py-1.5 sm:w-auto"
                    onClick={() => {
                      setWorkspaceEdited(false);
                      setExperimentWorkspace("");
                    }}
                  >
                    Default
                  </button>
                )}
              </div>
            </div>

            {/* Budget - collapsible */}
            <div className="border-t border-[var(--border-subtle)] pt-4">
              <button
                type="button"
                onClick={() => setBudgetOpen((p) => !p)}
                className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
              >
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
                  className="transition-transform duration-200"
                  style={{ transform: budgetOpen ? "rotate(90deg)" : "rotate(0deg)" }}>
                  <path d="M3 1.5L7 5L3 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Budget &amp; limits
              </button>

              {budgetOpen && (
                <div className="mt-3 grid grid-cols-2 gap-4 animate-fade-up">
                  <SliderField label="Max Papers" value={maxPapers} min={10} max={1000} step={10} onChange={setMaxPapers} />
                  <SliderField label="Deep Reads" value={maxReads} min={5} max={200} step={5} onChange={setMaxReads} />
                </div>
              )}
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full py-3 text-sm"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                  Starting research...
                </span>
              ) : (
                "Start Research"
              )}
            </button>
          </form>
        </div>
  );
}

function SliderField({ label, value, min, max, step, unit, onChange }: { label: string; value: number; min: number; max: number; step: number; unit?: string; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{label}</span>
        <span className="text-[11px] font-semibold text-[var(--accent)]" style={{ fontFamily: "var(--font-mono)" }}>
          {unit === "$" ? `$${value}` : value}
        </span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full" />
    </div>
  );
}
