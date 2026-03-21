"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createRunV2, startRun, type RunMode } from "@/lib/api";

const MODES: { value: RunMode; label: string; desc: string }[] = [
  { value: "atlas", label: "Atlas", desc: "Explore a new field" },
  { value: "frontier", label: "Frontier", desc: "Analyze a sub-field" },
  { value: "divergent", label: "Divergent", desc: "Find innovations" },
];

export default function Dashboard() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [mode, setMode] = useState<RunMode>("frontier");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim() || topic.trim().length < 10) return;
    setLoading(true);
    try {
      const run = (await createRunV2({
        title: topic.trim().slice(0, 60),
        topic: topic.trim(),
        mode,
        keywords: [],
        seed_papers: [],
        budget: {},
      })) as { id: string };
      await startRun(run.id);
      router.push(`/runs/${run.id}`);
    } catch (err) {
      console.error(err);
      alert("Failed to start research.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-full px-8">
      <div className="w-full max-w-[580px]">
        {/* Hero */}
        <div className="text-center mb-8">
          <h1
            className="text-3xl font-medium text-[var(--text-primary)] mb-2"
            style={{ fontFamily: "var(--font-display)" }}
          >
            What would you like to research?
          </h1>
          <p className="text-[15px] text-[var(--text-muted)]">
            Describe a topic, paste a paper ID, or ask a research question.
          </p>
        </div>

        {/* Input card */}
        <form onSubmit={handleSubmit}>
          <div className="card-static p-1 mb-3">
            <textarea
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. 3D anomaly detection for industrial inspection..."
              required
              minLength={10}
              rows={3}
              className="w-full bg-transparent border-none outline-none resize-none px-4 pt-4 pb-2 text-[15px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)]"
              style={{ fontFamily: "var(--font-body)" }}
            />
            <div className="flex items-center justify-between px-3 pb-3 pt-1">
              <div className="flex items-center gap-1.5">
                {MODES.map((m) => (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => setMode(m.value)}
                    className={`px-3 py-1.5 rounded-full text-[12px] font-medium transition-all duration-150 ${
                      mode === m.value
                        ? "bg-[var(--accent)] text-white"
                        : "text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              <button
                type="submit"
                disabled={loading || topic.trim().length < 10}
                className="btn-primary text-[13px] px-4 py-1.5"
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                    Starting
                  </span>
                ) : (
                  "Research →"
                )}
              </button>
            </div>
          </div>
          <p className="text-[12px] text-[var(--text-muted)] text-center">
            {MODES.find((m) => m.value === mode)?.desc} &middot;{" "}
            <span
              className="text-[var(--accent)] cursor-pointer hover:underline"
              onClick={() => router.push(`/new?mode=${mode}`)}
            >
              Advanced options
            </span>
          </p>
        </form>
      </div>
    </div>
  );
}
