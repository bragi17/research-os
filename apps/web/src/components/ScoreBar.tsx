"use client";

interface ScoreBarProps {
  label: string;
  value: number; // 0-1
}

function getGradient(value: number): string {
  if (value >= 0.7) return "linear-gradient(90deg, #10b981, #06b6d4)";
  if (value >= 0.5) return "linear-gradient(90deg, #06b6d4, #8b5cf6)";
  if (value >= 0.3) return "linear-gradient(90deg, #f59e0b, #ef4444)";
  return "linear-gradient(90deg, #ef4444, #dc2626)";
}

export default function ScoreBar({ label, value }: ScoreBarProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const percent = Math.round(clamped * 100);

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] text-[var(--text-muted)] capitalize tracking-wide">
          {label}
        </span>
        <span
          className="text-[11px] tabular-nums text-[var(--text-secondary)]"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          {percent}%
        </span>
      </div>
      <div className="h-1 rounded-full bg-[rgba(148,163,184,0.08)] overflow-hidden">
        <div
          className="h-full rounded-full animate-bar-fill"
          style={{
            width: `${percent}%`,
            background: getGradient(clamped),
          }}
        />
      </div>
    </div>
  );
}
