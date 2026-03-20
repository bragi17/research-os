"use client";

interface ComparisonTableProps {
  comparison: Record<string, unknown>;
}

interface MethodRow {
  method: string;
  [key: string]: unknown;
}

export default function ComparisonTable({ comparison }: ComparisonTableProps) {
  const methods = (comparison.methods ?? comparison.rows ?? []) as MethodRow[];
  const metrics = (comparison.metrics ?? comparison.columns ?? []) as string[];

  if (methods.length === 0) {
    return (
      <div className="glass-card-static p-6 text-center">
        <p className="text-sm text-[var(--text-muted)]">No comparison data available.</p>
      </div>
    );
  }

  const displayMetrics =
    metrics.length > 0
      ? metrics
      : Object.keys(methods[0]).filter((k) => k !== "method" && k !== "name");

  return (
    <div className="glass-card-static p-4 overflow-hidden">
      <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
        Method Comparison
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[var(--border-subtle)]">
              <th className="text-left py-2 px-3 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider">
                Method
              </th>
              {displayMetrics.map((metric) => (
                <th
                  key={String(metric)}
                  className="text-right py-2 px-3 text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider"
                >
                  {String(metric).replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {methods.map((row, idx) => (
              <tr
                key={idx}
                className="border-b border-[rgba(148,163,184,0.05)] hover:bg-[rgba(148,163,184,0.04)] transition-colors"
              >
                <td className="py-2 px-3 text-[var(--text-primary)] font-medium">
                  {String(row.method ?? row.name ?? `Method ${idx + 1}`)}
                </td>
                {displayMetrics.map((metric) => {
                  const val = row[String(metric)];
                  return (
                    <td
                      key={String(metric)}
                      className="text-right py-2 px-3 tabular-nums text-[var(--text-secondary)]"
                      style={{ fontFamily: "var(--font-mono)" }}
                    >
                      {val != null ? String(val) : "-"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
