import Link from "next/link";

import type { LibraryPaper } from "@/lib/api";
import { STATUS_STYLES } from "./status";

interface LibraryPaperCardProps {
  paper: LibraryPaper;
  removingId: string | null;
  reanalyzingId: string | null;
  onRemove: (id: string) => void;
  onReanalyze: (id: string) => void;
}

export function LibraryPaperCard({
  paper,
  removingId,
  reanalyzingId,
  onRemove,
  onReanalyze,
}: LibraryPaperCardProps) {
  const statusStyle = STATUS_STYLES[paper.status] ?? STATUS_STYLES.pending;

  return (
    <div className="card-static p-5">
      <div className="flex items-start justify-between gap-4 mb-2">
        <h3
          className="text-[15px] font-medium text-[var(--text-primary)] leading-snug flex-1 line-clamp-2"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {paper.title}
        </h3>
        <span
          className="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider"
          style={{
            background: statusStyle.bg,
            color: statusStyle.text,
          }}
        >
          {paper.status}
        </span>
      </div>

      <div className="flex items-center gap-2 text-[12px] text-[var(--text-muted)] mb-3">
        {paper.venue && <span className="font-medium">{paper.venue}</span>}
        {paper.venue && paper.year && <span>&middot;</span>}
        {paper.year && <span>{paper.year}</span>}
        {paper.arxiv_id && (
          <>
            <span>&middot;</span>
            <span style={{ fontFamily: "var(--font-mono)" }}>{paper.arxiv_id}</span>
          </>
        )}
        {paper.citation_count > 0 && (
          <>
            <span>&middot;</span>
            <span>{paper.citation_count} citations</span>
          </>
        )}
        {paper.field && (
          <>
            <span>&middot;</span>
            <span className="text-[var(--accent)]">{paper.field}</span>
          </>
        )}
      </div>

      {paper.keywords.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {paper.keywords.slice(0, 6).map((kw) => (
            <span
              key={kw}
              className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[var(--accent-soft)] text-[var(--accent)]"
            >
              {kw}
            </span>
          ))}
          {paper.keywords.length > 6 && (
            <span className="text-[10px] text-[var(--text-muted)] self-center">
              +{paper.keywords.length - 6} more
            </span>
          )}
        </div>
      )}

      {reanalyzingId === paper.id && (
        <div className="flex items-center gap-2 mb-3 text-[11px] text-[var(--text-muted)]">
          <div className="h-3 w-3 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin shrink-0" />
          <span className="animate-pulse">Analyzing: content → sections → LLM analysis → tagging → embedding → storing...</span>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Link
          href={`/library/papers/${paper.id}`}
          className="btn-secondary text-[12px] px-3 py-1.5"
        >
          View
        </Link>
        {(paper.status === "partial" || paper.status === "pending" || paper.status === "light_analyzed") && (
          <button
            onClick={() => onReanalyze(paper.id)}
            disabled={reanalyzingId === paper.id}
            className="btn-secondary text-[12px] px-3 py-1.5"
          >
            {reanalyzingId === paper.id ? "Analyzing..." : "Re-analyze"}
          </button>
        )}
        <button
          onClick={() => onRemove(paper.id)}
          disabled={removingId === paper.id}
          className="btn-danger text-[12px] px-3 py-1.5"
        >
          {removingId === paper.id ? "Removing..." : "Remove"}
        </button>
      </div>
    </div>
  );
}
