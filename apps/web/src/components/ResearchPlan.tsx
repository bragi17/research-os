"use client";

import { useState } from "react";

interface ResearchPlanProps {
  mode: string;
  topic: string;
  isExecuting: boolean;
}

const MODE_PLANS: Record<string, string[]> = {
  atlas: [
    "Identify domain boundaries and sub-directions",
    "Search foundational and recent representative papers",
    "Build research timeline with key milestones",
    "Construct multi-view taxonomy (method, task, modality)",
    "Deep-read representative papers from each branch",
    "Extract key figures and architecture diagrams",
    "Generate graduated reading path",
    "Synthesize one-page field atlas",
  ],
  frontier: [
    "Define sub-field scope and constraints",
    "Search with citation chain + benchmark + venue filters",
    "Prune off-topic papers, ensure method diversity",
    "Deep-read top papers with structured extraction",
    "Build method comparison matrix and benchmark panel",
    "Mine pain points, limitations, and future work",
    "Generate frontier summary with entry point suggestions",
  ],
  divergent: [
    "Normalize pain-point package into problem signature",
    "Search across domains for analogical problems",
    "Screen cross-domain methods for transfer potential",
    "Compose innovation idea cards",
    "Check prior art and novelty risk",
    "Assess feasibility (data, compute, experiments)",
    "Rank and present final idea portfolio",
  ],
  review: [
    "Load context from parent research run",
    "Apply refinement and user instructions",
    "Generate structured exports (Markdown, JSON, BibTeX)",
  ],
};

export default function ResearchPlan({ mode, topic, isExecuting }: ResearchPlanProps) {
  const [collapsed, setCollapsed] = useState(isExecuting);
  const steps = MODE_PLANS[mode] ?? MODE_PLANS.frontier;

  return (
    <div className="card-static overflow-hidden">
      <button
        onClick={() => setCollapsed((p) => !p)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left hover:bg-[var(--bg-secondary)] transition-colors"
      >
        <div className="flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <rect x="2" y="3" width="10" height="1.2" rx="0.6" fill="var(--accent)" />
            <rect x="2" y="6.4" width="7" height="1.2" rx="0.6" fill="var(--accent)" opacity="0.6" />
            <rect x="2" y="9.8" width="5" height="1.2" rx="0.6" fill="var(--accent)" opacity="0.3" />
          </svg>
          <span className="text-[13px] font-medium text-[var(--text-primary)]">Research Plan</span>
        </div>
        <svg
          width="12" height="12" viewBox="0 0 12 12" fill="none"
          className="transition-transform duration-200"
          style={{ transform: collapsed ? "rotate(0deg)" : "rotate(180deg)" }}
        >
          <path d="M3 4.5L6 7.5L9 4.5" stroke="var(--text-muted)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {!collapsed && (
        <div className="px-5 pb-4 pt-1">
          <p className="text-[12px] text-[var(--text-muted)] mb-3 italic" style={{ fontFamily: "var(--font-display)" }}>
            &ldquo;{topic}&rdquo;
          </p>
          <ol className="space-y-1.5">
            {steps.map((step, i) => (
              <li key={i} className="flex items-start gap-2.5">
                <span
                  className="text-[11px] font-medium shrink-0 mt-0.5 h-5 w-5 rounded-full flex items-center justify-center"
                  style={{ background: "var(--accent-soft)", color: "var(--accent)", fontFamily: "var(--font-mono)" }}
                >
                  {i + 1}
                </span>
                <span className="text-[13px] text-[var(--text-secondary)] leading-snug">{step}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
