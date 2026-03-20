"use client";

import { useRef, useState } from "react";
import type { TimelineEntry } from "@/lib/api";

interface TimelineRailProps {
  entries: TimelineEntry[];
}

const PHASE_COLORS: Record<string, string> = {
  foundational: "var(--accent-cyan)",
  growth: "var(--accent-green)",
  modern: "var(--accent-purple)",
  recent: "var(--accent-amber)",
};

export default function TimelineRail({ entries }: TimelineRailProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  if (entries.length === 0) {
    return (
      <div className="glass-card-static p-6 text-center">
        <p className="text-sm text-[var(--text-muted)]">No timeline data available.</p>
      </div>
    );
  }

  const sorted = [...entries].sort((a, b) => a.year - b.year);
  const minYear = sorted[0].year;
  const maxYear = sorted[sorted.length - 1].year;

  return (
    <div className="glass-card-static p-5">
      <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-4">
        Historical Timeline
      </h3>
      <div ref={scrollRef} className="overflow-x-auto pb-2">
        <div className="relative min-w-[600px]" style={{ height: 140 }}>
          {/* Axis line */}
          <div
            className="absolute left-0 right-0 h-px bg-[var(--border-subtle)]"
            style={{ top: 80 }}
          />

          {/* Year labels */}
          <div
            className="absolute left-0 text-[10px] text-[var(--text-muted)]"
            style={{ top: 88, fontFamily: "var(--font-mono)" }}
          >
            {minYear}
          </div>
          <div
            className="absolute right-0 text-[10px] text-[var(--text-muted)]"
            style={{ top: 88, fontFamily: "var(--font-mono)" }}
          >
            {maxYear}
          </div>

          {/* Dots */}
          {sorted.map((entry, idx) => {
            const span = maxYear - minYear || 1;
            const pct = ((entry.year - minYear) / span) * 100;
            const color = PHASE_COLORS[entry.phase] ?? "var(--accent-cyan)";
            const isHovered = hoveredIdx === idx;

            return (
              <div
                key={`${entry.year}-${idx}`}
                className="absolute cursor-pointer transition-all duration-200"
                style={{
                  left: `${Math.max(2, Math.min(98, pct))}%`,
                  top: 72,
                  transform: "translateX(-50%)",
                  zIndex: isHovered ? 10 : 1,
                }}
                onMouseEnter={() => setHoveredIdx(idx)}
                onMouseLeave={() => setHoveredIdx(null)}
              >
                {/* Dot */}
                <div
                  className="h-4 w-4 rounded-full border-2 transition-transform duration-200"
                  style={{
                    background: color,
                    borderColor: "var(--bg-primary)",
                    boxShadow: isHovered ? `0 0 12px ${color}80` : `0 0 6px ${color}40`,
                    transform: isHovered ? "scale(1.4)" : "scale(1)",
                  }}
                />

                {/* Tooltip */}
                {isHovered && (
                  <div
                    className="absolute bottom-6 left-1/2 -translate-x-1/2 w-48 p-3 rounded-lg border border-[var(--border-subtle)] animate-scale-in"
                    style={{
                      background: "rgba(15, 23, 42, 0.95)",
                      backdropFilter: "blur(12px)",
                    }}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className="text-[10px] font-bold tabular-nums"
                        style={{ color, fontFamily: "var(--font-mono)" }}
                      >
                        {entry.year}
                      </span>
                      <span
                        className="text-[9px] px-1.5 py-0.5 rounded uppercase font-medium"
                        style={{ background: `${color}18`, color }}
                      >
                        {entry.phase}
                      </span>
                    </div>
                    <p className="text-xs font-semibold text-[var(--text-primary)] mb-0.5">
                      {entry.title}
                    </p>
                    <p className="text-[10px] text-[var(--text-secondary)] leading-relaxed">
                      {entry.significance}
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
