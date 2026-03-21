"use client";

/* MODE_CONFIG is still exported for backward compat with sub-pages */
const MODE_CONFIG: Record<string, { color: string; label: string; letter: string }> = {
  atlas: { color: "var(--accent)", label: "Atlas", letter: "A" },
  frontier: { color: "var(--accent)", label: "Frontier", letter: "B" },
  divergent: { color: "var(--accent-amber)", label: "Divergent", letter: "C" },
  review: { color: "var(--text-secondary)", label: "Review", letter: "X" },
};

function ModeBadge({ mode }: { mode?: string }) {
  const config = MODE_CONFIG[mode ?? ""] ?? null;
  if (!config) return null;
  return (
    <span
      className="text-[11px] font-medium px-2 py-0.5 rounded-full"
      style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
    >
      {config.label}
    </span>
  );
}

export default function WorkspaceHeader() {
  return null;
}

export { ModeBadge, MODE_CONFIG };
