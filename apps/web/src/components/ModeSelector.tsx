"use client";

import type { RunMode } from "@/lib/api";

interface ModeSelectorProps {
  selected: RunMode | null;
  onSelect: (mode: RunMode) => void;
}

const MODES: {
  value: RunMode;
  label: string;
  letter: string;
  color: string;
  colorBg: string;
  colorBorder: string;
  description: string;
  audience: string;
  icon: React.ReactNode;
}[] = [
  {
    value: "atlas",
    label: "Atlas",
    letter: "A",
    color: "var(--accent-cyan)",
    colorBg: "rgba(6, 182, 212, 0.08)",
    colorBorder: "rgba(6, 182, 212, 0.3)",
    description:
      "Map an entire research field. Get a bird's-eye view of the landscape, key papers, taxonomy, and reading path.",
    audience: "New to a field? Start here.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
        <circle cx="14" cy="14" r="10" stroke="currentColor" strokeWidth="1.5" />
        <path d="M14 4V24M4 14H24" stroke="currentColor" strokeWidth="1" opacity="0.4" />
        <circle cx="14" cy="14" r="3" fill="currentColor" opacity="0.6" />
      </svg>
    ),
  },
  {
    value: "frontier",
    label: "Frontier",
    letter: "B",
    color: "var(--accent-purple)",
    colorBg: "rgba(139, 92, 246, 0.08)",
    colorBorder: "rgba(139, 92, 246, 0.3)",
    description:
      "Deep-dive into a sub-field. Compare methods on benchmarks, find pain points, and identify research gaps.",
    audience: "Know the area? Go deeper.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
        <path d="M4 24L14 4L24 24" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M8 18H20" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="14" cy="10" r="2" fill="currentColor" opacity="0.6" />
      </svg>
    ),
  },
  {
    value: "divergent",
    label: "Divergent",
    letter: "C",
    color: "var(--accent-amber)",
    colorBg: "rgba(245, 158, 11, 0.08)",
    colorBorder: "rgba(245, 158, 11, 0.3)",
    description:
      "Generate novel research ideas by borrowing methods from other domains. Cross-pollinate and innovate.",
    audience: "Ready to innovate? Push boundaries.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
        <path d="M14 4V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M14 14L22 22" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M14 14L6 22" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="14" cy="4" r="2" fill="currentColor" opacity="0.6" />
        <circle cx="22" cy="22" r="2" fill="currentColor" opacity="0.6" />
        <circle cx="6" cy="22" r="2" fill="currentColor" opacity="0.6" />
      </svg>
    ),
  },
  {
    value: "review",
    label: "Review",
    letter: "X",
    color: "var(--text-secondary)",
    colorBg: "rgba(148, 163, 184, 0.06)",
    colorBorder: "rgba(148, 163, 184, 0.2)",
    description:
      "General-purpose review mode. Combines survey and analysis without a specific innovation goal.",
    audience: "Need a flexible review? Use this.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
        <rect x="5" y="5" width="18" height="18" rx="3" stroke="currentColor" strokeWidth="1.5" />
        <path d="M10 11H18M10 14H18M10 17H15" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.6" />
      </svg>
    ),
  },
];

export default function ModeSelector({ selected, onSelect }: ModeSelectorProps) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {MODES.map((mode, idx) => {
        const isSelected = selected === mode.value;
        return (
          <button
            key={mode.value}
            type="button"
            onClick={() => onSelect(mode.value)}
            className="text-left p-5 rounded-xl border transition-all duration-300 animate-fade-up group"
            style={{
              animationDelay: `${100 + idx * 75}ms`,
              background: isSelected ? mode.colorBg : "rgba(15, 23, 42, 0.4)",
              borderColor: isSelected ? mode.colorBorder : "var(--border-subtle)",
              boxShadow: isSelected ? `0 0 20px ${mode.color}15` : "none",
            }}
          >
            <div className="flex items-start gap-4">
              <div
                className="flex items-center justify-center h-12 w-12 rounded-xl shrink-0 transition-colors"
                style={{
                  background: isSelected ? `${mode.color}18` : "rgba(148, 163, 184, 0.06)",
                  color: isSelected ? mode.color : "var(--text-muted)",
                }}
              >
                {mode.icon}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                    style={{
                      background: `${mode.color}18`,
                      color: mode.color,
                    }}
                  >
                    {mode.letter}
                  </span>
                  <h3
                    className="text-sm font-semibold transition-colors"
                    style={{
                      color: isSelected ? "var(--text-primary)" : "var(--text-secondary)",
                    }}
                  >
                    {mode.label}
                  </h3>
                </div>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-2">
                  {mode.description}
                </p>
                <p
                  className="text-[10px] font-medium"
                  style={{ color: mode.color, opacity: 0.8 }}
                >
                  {mode.audience}
                </p>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export { MODES };
