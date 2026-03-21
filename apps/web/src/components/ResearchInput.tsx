"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { createRunV2, startRun, type RunMode } from "@/lib/api";

interface ResearchInputProps {
  /** If true, show a compact variant for the dashboard (no advanced options) */
  compact?: boolean;
  /** Pre-selected mode from URL param */
  initialMode?: RunMode | null;
}

const MODE_PILLS: {
  value: RunMode;
  label: string;
  color: string;
  colorBg: string;
  colorBorder: string;
}[] = [
  {
    value: "atlas",
    label: "Atlas",
    color: "var(--accent-cyan)",
    colorBg: "rgba(6, 182, 212, 0.10)",
    colorBorder: "rgba(6, 182, 212, 0.3)",
  },
  {
    value: "frontier",
    label: "Frontier",
    color: "var(--accent-purple)",
    colorBg: "rgba(139, 92, 246, 0.10)",
    colorBorder: "rgba(139, 92, 246, 0.3)",
  },
  {
    value: "divergent",
    label: "Divergent",
    color: "var(--accent-amber)",
    colorBg: "rgba(245, 158, 11, 0.10)",
    colorBorder: "rgba(245, 158, 11, 0.3)",
  },
];

const PLACEHOLDERS: Record<RunMode, string> = {
  atlas: "Describe a research field you want to explore...",
  frontier:
    "What sub-field do you want to analyze? Paste a paper ID to start...",
  divergent: "What research pain point needs innovative solutions?",
  review: "Describe your research topic...",
};

export default function ResearchInput({
  compact = false,
  initialMode = null,
}: ResearchInputProps) {
  const router = useRouter();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [mode, setMode] = useState<RunMode>(initialMode ?? "atlas");
  const [topic, setTopic] = useState("");
  const [loading, setLoading] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Advanced options
  const [seedPapers, setSeedPapers] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [maxPapers, setMaxPapers] = useState(150);
  const [maxReads, setMaxReads] = useState(40);
  const [maxCost, setMaxCost] = useState(30);
  // Frontier-specific
  const [venueFilter, setVenueFilter] = useState("");
  const [benchmark, setBenchmark] = useState("");
  // Divergent-specific
  const [painPointInput, setPainPointInput] = useState("");
  const [parentRunId, setParentRunId] = useState("");

  // Auto-grow textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const minH = 72; // ~3 rows
    const maxH = 192; // ~8 rows
    el.style.height = `${Math.max(minH, Math.min(maxH, el.scrollHeight))}px`;
  }, [topic]);

  const addKeyword = useCallback(() => {
    const trimmed = keywordInput.trim();
    if (trimmed && !keywords.includes(trimmed)) {
      setKeywords((prev) => [...prev, trimmed]);
      setKeywordInput("");
    }
  }, [keywordInput, keywords]);

  const removeKeyword = useCallback((kw: string) => {
    setKeywords((prev) => prev.filter((k) => k !== kw));
  }, []);

  const handleKeywordKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        addKeyword();
      }
    },
    [addKeyword],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;
    setLoading(true);

    try {
      const title = topic.trim().slice(0, 60);
      const kws =
        keywords.length > 0
          ? keywords
          : keywordInput
              .split(",")
              .map((k) => k.trim())
              .filter(Boolean);
      const seeds = seedPapers
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);

      const payload: Record<string, unknown> = {
        title,
        topic: topic.trim(),
        mode,
        keywords: kws,
        seed_papers: seeds,
        budget: {
          max_new_papers: maxPapers,
          max_fulltext_reads: maxReads,
          max_estimated_cost_usd: maxCost,
        },
      };

      if (mode === "divergent") {
        if (painPointInput.trim()) payload.pain_point_input = painPointInput.trim();
        if (parentRunId.trim()) payload.parent_run_id = parentRunId.trim();
      }
      if (mode === "frontier") {
        if (venueFilter.trim()) {
          payload.venue_filter = venueFilter
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean);
        }
        if (benchmark.trim()) payload.benchmark = benchmark.trim();
      }

      const run = (await createRunV2(payload)) as { id: string };
      await startRun(run.id);
      router.push(`/runs/${run.id}`);
    } catch (err) {
      alert("Failed to create research run. Check console for details.");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full">
      {/* Textarea */}
      <div className="relative">
        <textarea
          ref={textareaRef}
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder={PLACEHOLDERS[mode]}
          required
          minLength={10}
          rows={3}
          className="input-dark resize-none w-full text-[15px] leading-relaxed pr-4"
          style={{ minHeight: 72 }}
        />
      </div>

      {/* Mode pills */}
      <div className="flex items-center gap-2 mt-3">
        <span className="text-[11px] text-[var(--text-muted)] mr-1">Mode:</span>
        {MODE_PILLS.map((pill) => {
          const isActive = mode === pill.value;
          return (
            <button
              key={pill.value}
              type="button"
              onClick={() => setMode(pill.value)}
              className="px-3 py-1 rounded-full text-[12px] font-medium transition-all duration-200"
              style={{
                background: isActive ? pill.colorBg : "transparent",
                color: isActive ? pill.color : "var(--text-muted)",
                border: isActive
                  ? `1px solid ${pill.colorBorder}`
                  : "1px solid var(--border-subtle)",
              }}
            >
              {pill.label}
            </button>
          );
        })}
      </div>

      {/* Advanced options (hidden in compact mode) */}
      {!compact && (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setAdvancedOpen((prev) => !prev)}
            className="flex items-center gap-1.5 text-[12px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              className="transition-transform duration-200"
              style={{
                transform: advancedOpen ? "rotate(90deg)" : "rotate(0deg)",
              }}
            >
              <path
                d="M4 2.5L8 6L4 9.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Advanced options
          </button>

          {advancedOpen && (
            <div className="mt-3 space-y-4 animate-fade-up glass-card-static p-5 rounded-xl">
              {/* Seed papers */}
              <div>
                <label className="block text-[11px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                  Seed Papers (arXiv IDs or DOIs, one per line)
                </label>
                <textarea
                  rows={3}
                  className="input-dark resize-none text-[13px]"
                  style={{ fontFamily: "var(--font-mono)" }}
                  placeholder={"2301.07041\n10.1234/example.2024"}
                  value={seedPapers}
                  onChange={(e) => setSeedPapers(e.target.value)}
                />
              </div>

              {/* Keywords */}
              <div>
                <label className="block text-[11px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                  Keywords
                </label>
                {keywords.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {keywords.map((kw) => (
                      <span
                        key={kw}
                        className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium"
                        style={{
                          background: "rgba(6, 182, 212, 0.1)",
                          color: "var(--accent-cyan)",
                          border: "1px solid rgba(6, 182, 212, 0.2)",
                        }}
                      >
                        {kw}
                        <button
                          type="button"
                          onClick={() => removeKeyword(kw)}
                          className="hover:text-white transition-colors"
                        >
                          <svg
                            width="10"
                            height="10"
                            viewBox="0 0 10 10"
                            fill="none"
                          >
                            <path
                              d="M3 3L7 7M7 3L3 7"
                              stroke="currentColor"
                              strokeWidth="1.5"
                              strokeLinecap="round"
                            />
                          </svg>
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <input
                  type="text"
                  className="input-dark text-[13px]"
                  placeholder="Type a keyword and press Enter..."
                  value={keywordInput}
                  onChange={(e) => setKeywordInput(e.target.value)}
                  onKeyDown={handleKeywordKeyDown}
                  onBlur={addKeyword}
                />
              </div>

              {/* Budget sliders */}
              <div className="grid grid-cols-3 gap-4">
                <SliderCompact
                  label="Max Papers"
                  value={maxPapers}
                  min={10}
                  max={1000}
                  step={10}
                  onChange={setMaxPapers}
                />
                <SliderCompact
                  label="Deep Reads"
                  value={maxReads}
                  min={5}
                  max={200}
                  step={5}
                  onChange={setMaxReads}
                />
                <SliderCompact
                  label="Max Cost"
                  value={maxCost}
                  min={1}
                  max={500}
                  step={1}
                  unit="$"
                  onChange={setMaxCost}
                />
              </div>

              {/* Frontier-specific */}
              {mode === "frontier" && (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[11px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                      Venue Filter
                    </label>
                    <input
                      type="text"
                      className="input-dark text-[13px]"
                      placeholder="NeurIPS, ICML, ICLR..."
                      value={venueFilter}
                      onChange={(e) => setVenueFilter(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                      Benchmark
                    </label>
                    <input
                      type="text"
                      className="input-dark text-[13px]"
                      placeholder="ImageNet, GLUE..."
                      value={benchmark}
                      onChange={(e) => setBenchmark(e.target.value)}
                    />
                  </div>
                </div>
              )}

              {/* Divergent-specific */}
              {mode === "divergent" && (
                <div className="space-y-4">
                  <div>
                    <label className="block text-[11px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                      Pain Point Description
                    </label>
                    <textarea
                      rows={2}
                      className="input-dark resize-none text-[13px]"
                      placeholder="Describe the pain point to solve with cross-domain ideas..."
                      value={painPointInput}
                      onChange={(e) => setPainPointInput(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1.5">
                      Parent Run ID (optional)
                    </label>
                    <input
                      type="text"
                      className="input-dark text-[13px]"
                      style={{ fontFamily: "var(--font-mono)" }}
                      placeholder="Reference a Frontier run..."
                      value={parentRunId}
                      onChange={(e) => setParentRunId(e.target.value)}
                    />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Submit */}
      <div className="mt-4">
        <button
          type="submit"
          disabled={loading || topic.trim().length < 10}
          className="btn-primary px-6 py-2.5 text-sm"
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              Starting...
            </span>
          ) : (
            <span className="flex items-center gap-2">
              Start Research
              <svg
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
              >
                <path
                  d="M3 7H11M8 4L11 7L8 10"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          )}
        </button>
      </div>
    </form>
  );
}

/* -- Compact slider for budget section -- */
function SliderCompact({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  onChange: (v: number) => void;
}) {
  const display = unit === "$" ? `$${value}` : String(value);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
          {label}
        </span>
        <span
          className="text-[11px] font-semibold tabular-nums text-[var(--accent-cyan)]"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          {display}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
    </div>
  );
}
