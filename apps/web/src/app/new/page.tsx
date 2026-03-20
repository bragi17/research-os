"use client";

import { Suspense, useState, useCallback, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createRunV2, startRun, type RunMode } from "@/lib/api";
import ModeSelector from "@/components/ModeSelector";

export default function NewResearchPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="flex flex-col items-center gap-4 animate-fade-in">
            <div className="w-8 h-8 rounded-full border-2 border-[var(--accent-cyan)] border-t-transparent animate-spin" />
            <p className="text-sm text-[var(--text-muted)]">Loading...</p>
          </div>
        </div>
      }
    >
      <NewResearch />
    </Suspense>
  );
}

function NewResearch() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"mode" | "details">("mode");
  const [form, setForm] = useState({
    mode: null as RunMode | null,
    title: "",
    topic: "",
    keywords: [] as string[],
    keywordInput: "",
    seed_papers: "",
    pain_point_input: "",
    parent_run_id: "",
    venue_filter: "",
    benchmark: "",
    max_papers: 150,
    max_reads: 40,
    max_cost: 30,
  });

  useEffect(() => {
    const modeParam = searchParams.get("mode");
    if (modeParam && ["atlas", "frontier", "divergent", "review"].includes(modeParam)) {
      setForm((prev) => ({ ...prev, mode: modeParam as RunMode }));
      setStep("details");
    }
  }, [searchParams]);

  const updateForm = useCallback(
    (updates: Partial<typeof form>) => setForm((prev) => ({ ...prev, ...updates })),
    [],
  );

  const addKeyword = useCallback(() => {
    const trimmed = form.keywordInput.trim();
    if (trimmed && !form.keywords.includes(trimmed)) {
      updateForm({
        keywords: [...form.keywords, trimmed],
        keywordInput: "",
      });
    }
  }, [form.keywordInput, form.keywords, updateForm]);

  const removeKeyword = useCallback(
    (keyword: string) => {
      updateForm({
        keywords: form.keywords.filter((k) => k !== keyword),
      });
    },
    [form.keywords, updateForm],
  );

  const handleKeywordKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        addKeyword();
      }
    },
    [addKeyword],
  );

  const handleModeSelect = (mode: RunMode) => {
    updateForm({ mode });
    setStep("details");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.mode) return;
    setLoading(true);
    try {
      const keywords =
        form.keywords.length > 0
          ? form.keywords
          : form.keywordInput
              .split(",")
              .map((k) => k.trim())
              .filter(Boolean);

      const seed_papers = form.seed_papers
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((value) => ({ type: "id", value }));

      const payload: Record<string, unknown> = {
        title: form.title,
        topic: form.topic,
        mode: form.mode,
        keywords,
        seed_papers,
        budget: {
          max_new_papers: form.max_papers,
          max_fulltext_reads: form.max_reads,
          max_estimated_cost_usd: form.max_cost,
        },
      };

      // Mode-specific fields
      if (form.mode === "divergent") {
        if (form.pain_point_input.trim()) {
          payload.pain_point_input = form.pain_point_input.trim();
        }
        if (form.parent_run_id.trim()) {
          payload.parent_run_id = form.parent_run_id.trim();
        }
      }
      if (form.mode === "frontier") {
        if (form.venue_filter.trim()) {
          payload.venue_filter = form.venue_filter.split(",").map((v) => v.trim()).filter(Boolean);
        }
        if (form.benchmark.trim()) {
          payload.benchmark = form.benchmark.trim();
        }
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
    <div className="mx-auto max-w-3xl px-6 py-10">
      <div className="animate-fade-up">
        <h1 className="text-3xl font-extrabold tracking-tight mb-1">
          <span className="gradient-text">New Research</span>
        </h1>
        <p className="text-[var(--text-secondary)] text-sm mb-8">
          {step === "mode"
            ? "Choose a research mode to get started."
            : "Configure your research task."}
        </p>
      </div>

      {/* Step 1: Mode Selection */}
      {step === "mode" && (
        <div className="animate-fade-up delay-100">
          <SectionHeader number={1} title="Choose Research Mode" />
          <div className="mt-5">
            <ModeSelector selected={form.mode} onSelect={handleModeSelect} />
          </div>
        </div>
      )}

      {/* Step 2: Details form */}
      {step === "details" && form.mode && (
        <form onSubmit={handleSubmit} className="space-y-8">
          {/* Mode indicator + back button */}
          <div className="flex items-center gap-3 animate-fade-up">
            <button
              type="button"
              onClick={() => setStep("mode")}
              className="text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors flex items-center gap-1"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M8 2L4 6L8 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Change mode
            </button>
            <ModeBadgeInline mode={form.mode} />
          </div>

          {/* Research Identity */}
          <section className="glass-card-static p-6 animate-fade-up delay-100">
            <SectionHeader number={1} title="Research Identity" />
            <div className="space-y-5 mt-5">
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                  Title
                </label>
                <input
                  type="text"
                  required
                  minLength={3}
                  className="input-dark"
                  placeholder={
                    form.mode === "atlas"
                      ? "e.g., Graph Neural Networks Overview"
                      : form.mode === "frontier"
                        ? "e.g., Efficient Attention Mechanisms"
                        : form.mode === "divergent"
                          ? "e.g., Cross-domain Solutions for GNN Scalability"
                          : "e.g., Literature Review: Transformers"
                  }
                  value={form.title}
                  onChange={(e) => updateForm({ title: e.target.value })}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                  {form.mode === "atlas" ? "Research Field" : "Research Topic"}
                </label>
                <textarea
                  required
                  minLength={10}
                  rows={3}
                  className="input-dark resize-none"
                  placeholder={
                    form.mode === "atlas"
                      ? "Describe the broad research field you want to explore..."
                      : form.mode === "frontier"
                        ? "Describe the specific sub-field to analyze in depth..."
                        : form.mode === "divergent"
                          ? "Describe the problem area where you want novel innovations..."
                          : "Describe your research topic..."
                  }
                  value={form.topic}
                  onChange={(e) => updateForm({ topic: e.target.value })}
                />
              </div>

              {/* Keywords */}
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                  Keywords
                </label>
                <div className="flex flex-wrap gap-2 mb-2">
                  {form.keywords.map((kw) => (
                    <span
                      key={kw}
                      className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
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
                        className="hover:text-white transition-colors ml-0.5"
                      >
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                          <path d="M3 3L7 7M7 3L3 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                        </svg>
                      </button>
                    </span>
                  ))}
                </div>
                <input
                  type="text"
                  className="input-dark"
                  placeholder="Type a keyword and press Enter..."
                  value={form.keywordInput}
                  onChange={(e) => updateForm({ keywordInput: e.target.value })}
                  onKeyDown={handleKeywordKeyDown}
                  onBlur={addKeyword}
                />
              </div>
            </div>
          </section>

          {/* Seed Papers */}
          <section className="glass-card-static p-6 animate-fade-up delay-200">
            <SectionHeader number={2} title="Seed Papers" />
            <div className="mt-5">
              <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                DOIs or arXiv IDs (one per line)
              </label>
              <textarea
                rows={4}
                className="input-dark resize-none"
                style={{ fontFamily: "var(--font-mono)", fontSize: "13px" }}
                placeholder={"2301.07041\n10.1234/example.2024\nS2:abc123def"}
                value={form.seed_papers}
                onChange={(e) => updateForm({ seed_papers: e.target.value })}
              />
            </div>
          </section>

          {/* Mode-specific fields */}
          {form.mode === "frontier" && (
            <section className="glass-card-static p-6 animate-fade-up delay-300">
              <SectionHeader number={3} title="Frontier Settings" />
              <div className="space-y-5 mt-5">
                <div>
                  <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                    Venue Filter (comma-separated)
                  </label>
                  <input
                    type="text"
                    className="input-dark"
                    placeholder="NeurIPS, ICML, ICLR, ACL..."
                    value={form.venue_filter}
                    onChange={(e) => updateForm({ venue_filter: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                    Benchmark Focus
                  </label>
                  <input
                    type="text"
                    className="input-dark"
                    placeholder="e.g., ImageNet, GLUE, MMLU..."
                    value={form.benchmark}
                    onChange={(e) => updateForm({ benchmark: e.target.value })}
                  />
                </div>
              </div>
            </section>
          )}

          {form.mode === "divergent" && (
            <section className="glass-card-static p-6 animate-fade-up delay-300">
              <SectionHeader number={3} title="Divergent Settings" />
              <div className="space-y-5 mt-5">
                <div>
                  <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                    Pain Point Description
                  </label>
                  <textarea
                    rows={3}
                    className="input-dark resize-none"
                    placeholder="Describe the pain point or problem you want to solve with cross-domain ideas..."
                    value={form.pain_point_input}
                    onChange={(e) => updateForm({ pain_point_input: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                    Parent Run ID (optional)
                  </label>
                  <input
                    type="text"
                    className="input-dark"
                    placeholder="Reference a Mode B run to pull pain points from..."
                    style={{ fontFamily: "var(--font-mono)", fontSize: "13px" }}
                    value={form.parent_run_id}
                    onChange={(e) => updateForm({ parent_run_id: e.target.value })}
                  />
                </div>
              </div>
            </section>
          )}

          {/* Budget */}
          <section className="glass-card-static p-6 animate-fade-up delay-400">
            <SectionHeader
              number={form.mode === "frontier" || form.mode === "divergent" ? 4 : 3}
              title="Budget Limits"
            />
            <div className="space-y-6 mt-5">
              <SliderInput
                label="Max Papers"
                value={form.max_papers}
                min={10}
                max={1000}
                step={10}
                unit=""
                onChange={(v) => updateForm({ max_papers: v })}
              />
              <SliderInput
                label="Max Deep Reads"
                value={form.max_reads}
                min={5}
                max={200}
                step={5}
                unit=""
                onChange={(v) => updateForm({ max_reads: v })}
              />
              <SliderInput
                label="Max Cost"
                value={form.max_cost}
                min={1}
                max={500}
                step={1}
                unit="USD"
                onChange={(v) => updateForm({ max_cost: v })}
              />
            </div>
          </section>

          {/* Submit */}
          <div className="animate-fade-up delay-500">
            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full py-4 text-base"
            >
              {loading ? (
                <span className="flex items-center gap-3">
                  <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Initializing Research...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <circle cx="9" cy="9" r="7" stroke="currentColor" strokeWidth="1.5" />
                    <path d="M7 6L12 9L7 12V6Z" fill="currentColor" />
                  </svg>
                  Launch Research
                </span>
              )}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/* -- Section Header -- */
function SectionHeader({ number, title }: { number: number; title: string }) {
  return (
    <div className="flex items-center gap-3">
      <span
        className="flex h-6 w-6 items-center justify-center rounded-md text-[11px] font-bold"
        style={{
          background: "rgba(6, 182, 212, 0.1)",
          color: "var(--accent-cyan)",
          border: "1px solid rgba(6, 182, 212, 0.2)",
        }}
      >
        {number}
      </span>
      <h2 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h2>
    </div>
  );
}

/* -- Mode Badge Inline -- */
function ModeBadgeInline({ mode }: { mode: RunMode }) {
  const config: Record<RunMode, { color: string; label: string; letter: string }> = {
    atlas: { color: "var(--accent-cyan)", label: "Atlas", letter: "A" },
    frontier: { color: "var(--accent-purple)", label: "Frontier", letter: "B" },
    divergent: { color: "var(--accent-amber)", label: "Divergent", letter: "C" },
    review: { color: "var(--text-secondary)", label: "Review", letter: "X" },
  };
  const c = config[mode];

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider"
      style={{
        background: `${c.color}15`,
        color: c.color,
        border: `1px solid ${c.color}30`,
      }}
    >
      {c.letter}: {c.label}
    </span>
  );
}

/* -- Slider Input -- */
function SliderInput({
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
  unit: string;
  onChange: (val: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <label className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
          {label}
        </label>
        <span
          className="text-sm font-semibold tabular-nums text-[var(--accent-cyan)]"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          {unit === "USD" ? `$${value}` : value}
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
      <div className="flex justify-between mt-1">
        <span className="text-[10px] text-[var(--text-muted)]">{unit === "USD" ? `$${min}` : min}</span>
        <span className="text-[10px] text-[var(--text-muted)]">{unit === "USD" ? `$${max}` : max}</span>
      </div>
    </div>
  );
}
