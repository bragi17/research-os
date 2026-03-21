"use client";

interface StatusBadgeProps {
  status: string;
  size?: "sm" | "md";
}

const STATUS_CONFIG: Record<string, { bg: string; text: string; dot?: boolean }> = {
  running: { bg: "var(--accent-green-soft)", text: "var(--accent-green)", dot: true },
  completed: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  failed: { bg: "var(--accent-red-soft)", text: "var(--accent-red)" },
  paused: { bg: "var(--accent-amber-soft)", text: "var(--accent-amber)" },
  queued: { bg: "rgba(0,0,0,0.04)", text: "var(--text-muted)" },
  cancelled: { bg: "rgba(0,0,0,0.04)", text: "var(--text-muted)" },
  candidate: { bg: "rgba(0,0,0,0.04)", text: "var(--text-secondary)" },
  verified: { bg: "var(--accent-green-soft)", text: "var(--accent-green)" },
  rejected: { bg: "var(--accent-red-soft)", text: "var(--accent-red)" },
};

export default function StatusBadge({ status, size = "sm" }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? { bg: "rgba(0,0,0,0.04)", text: "var(--text-muted)" };
  const sizeClass = size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium capitalize ${sizeClass}`}
      style={{ background: config.bg, color: config.text }}
    >
      {config.dot && (
        <span className="h-1.5 w-1.5 rounded-full animate-pulse-dot" style={{ background: config.text }} />
      )}
      {status}
    </span>
  );
}
