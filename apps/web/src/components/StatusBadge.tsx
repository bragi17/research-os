"use client";

interface StatusBadgeProps {
  status: string;
  size?: "sm" | "md";
}

const STATUS_CONFIG: Record<
  string,
  { bg: string; text: string; glow: string; dot?: string; icon?: string }
> = {
  running: {
    bg: "rgba(6, 182, 212, 0.12)",
    text: "var(--accent-cyan)",
    glow: "0 0 12px rgba(6, 182, 212, 0.2)",
    dot: "var(--accent-cyan)",
  },
  completed: {
    bg: "rgba(16, 185, 129, 0.12)",
    text: "var(--accent-green)",
    glow: "0 0 12px rgba(16, 185, 129, 0.2)",
    icon: "check",
  },
  failed: {
    bg: "rgba(239, 68, 68, 0.12)",
    text: "var(--accent-red)",
    glow: "0 0 12px rgba(239, 68, 68, 0.2)",
    icon: "x",
  },
  paused: {
    bg: "rgba(245, 158, 11, 0.12)",
    text: "var(--accent-amber)",
    glow: "0 0 12px rgba(245, 158, 11, 0.2)",
    icon: "pause",
  },
  queued: {
    bg: "rgba(148, 163, 184, 0.08)",
    text: "var(--text-secondary)",
    glow: "none",
    icon: "clock",
  },
  cancelled: {
    bg: "rgba(148, 163, 184, 0.08)",
    text: "var(--text-muted)",
    glow: "none",
    icon: "x",
  },
  candidate: {
    bg: "rgba(148, 163, 184, 0.08)",
    text: "var(--text-secondary)",
    glow: "none",
  },
  verified: {
    bg: "rgba(16, 185, 129, 0.12)",
    text: "var(--accent-green)",
    glow: "0 0 12px rgba(16, 185, 129, 0.2)",
    icon: "check",
  },
  rejected: {
    bg: "rgba(239, 68, 68, 0.12)",
    text: "var(--accent-red)",
    glow: "0 0 12px rgba(239, 68, 68, 0.2)",
    icon: "x",
  },
};

function StatusIcon({ type, color }: { type: string; color: string }) {
  if (type === "check") {
    return (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
        <path
          d="M2 5L4 7L8 3"
          stroke={color}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (type === "x") {
    return (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
        <path
          d="M3 3L7 7M7 3L3 7"
          stroke={color}
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  if (type === "pause") {
    return (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
        <rect x="2.5" y="2" width="1.5" height="6" rx="0.5" fill={color} />
        <rect x="6" y="2" width="1.5" height="6" rx="0.5" fill={color} />
      </svg>
    );
  }
  if (type === "clock") {
    return (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
        <circle cx="5" cy="5" r="3.5" stroke={color} strokeWidth="1" />
        <path d="M5 3V5.5L6.5 6.5" stroke={color} strokeWidth="1" strokeLinecap="round" />
      </svg>
    );
  }
  return null;
}

export default function StatusBadge({ status, size = "sm" }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? {
    bg: "rgba(148, 163, 184, 0.08)",
    text: "var(--text-secondary)",
    glow: "none",
  };

  const sizeClass = size === "sm" ? "px-2.5 py-1 text-[11px]" : "px-3 py-1.5 text-xs";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium capitalize ${sizeClass}`}
      style={{
        background: config.bg,
        color: config.text,
        boxShadow: config.glow,
        border: `1px solid ${config.text}20`,
      }}
    >
      {/* Pulse dot for running */}
      {config.dot && (
        <span
          className="h-1.5 w-1.5 rounded-full animate-status-pulse"
          style={{ background: config.dot }}
        />
      )}
      {/* Icon for other states */}
      {config.icon && <StatusIcon type={config.icon} color={config.text} />}
      {status}
    </span>
  );
}
