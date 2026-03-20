"use client";

import type { RunEvent } from "@/lib/api";

interface EventTimelineProps {
  events: RunEvent[];
}

const SEVERITY_COLORS: Record<string, { dot: string; line: string; text: string; bg: string }> = {
  info: {
    dot: "var(--accent-cyan)",
    line: "rgba(6, 182, 212, 0.2)",
    text: "var(--accent-cyan)",
    bg: "rgba(6, 182, 212, 0.06)",
  },
  success: {
    dot: "var(--accent-green)",
    line: "rgba(16, 185, 129, 0.2)",
    text: "var(--accent-green)",
    bg: "rgba(16, 185, 129, 0.06)",
  },
  warning: {
    dot: "var(--accent-amber)",
    line: "rgba(245, 158, 11, 0.2)",
    text: "var(--accent-amber)",
    bg: "rgba(245, 158, 11, 0.06)",
  },
  error: {
    dot: "var(--accent-red)",
    line: "rgba(239, 68, 68, 0.2)",
    text: "var(--accent-red)",
    bg: "rgba(239, 68, 68, 0.06)",
  },
};

function formatTime(timestamp: string): string {
  try {
    const d = new Date(timestamp);
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return timestamp;
  }
}

export default function EventTimeline({ events }: EventTimelineProps) {
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="w-12 h-12 rounded-full border border-[var(--border-subtle)] flex items-center justify-center mb-4">
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="none"
            className="text-[var(--text-muted)]"
          >
            <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" />
            <path
              d="M10 6V10.5L13 12"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </div>
        <p className="text-sm text-[var(--text-secondary)]">No events yet</p>
        <p className="text-xs text-[var(--text-muted)] mt-1">
          Start the run to see activity here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-0.5 overflow-y-auto max-h-[70vh] pr-1 relative">
      {events.map((event, idx) => {
        const colors = SEVERITY_COLORS[event.severity] ?? SEVERITY_COLORS.info;
        const message =
          typeof event.payload?.message === "string"
            ? event.payload.message
            : JSON.stringify(event.payload);
        const isLast = idx === events.length - 1;

        return (
          <div
            key={idx}
            className="flex gap-4 group animate-fade-up"
            style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}
          >
            {/* Timestamp */}
            <span
              className="shrink-0 w-[72px] pt-3 text-[11px] tabular-nums text-[var(--text-muted)] text-right"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {formatTime(event.timestamp)}
            </span>

            {/* Dot + line */}
            <div className="relative flex flex-col items-center shrink-0">
              <div
                className="relative z-10 mt-3 h-2.5 w-2.5 rounded-full shrink-0"
                style={{
                  background: colors.dot,
                  boxShadow: `0 0 8px ${colors.dot}60`,
                }}
              />
              {!isLast && (
                <div
                  className="w-px flex-1 min-h-[20px]"
                  style={{ background: colors.line }}
                />
              )}
            </div>

            {/* Content */}
            <div
              className="flex-1 min-w-0 pb-3 pt-1.5 rounded-lg px-3 py-2 transition-all duration-200 hover:backdrop-blur-sm"
              style={{ background: "transparent" }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.background = colors.bg;
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.background = "transparent";
              }}
            >
              <div className="flex items-center gap-2 mb-0.5">
                <span
                  className="text-[11px] font-semibold uppercase tracking-wider"
                  style={{ color: colors.text }}
                >
                  {event.event_type.replace(/_/g, " ")}
                </span>
              </div>
              <p className="text-[13px] text-[var(--text-primary)] leading-relaxed">
                {message}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
