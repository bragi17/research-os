"use client";

import { useState, useCallback } from "react";
import type { TaxonomyNode } from "@/lib/api";

interface TaxonomyTreeProps {
  root: TaxonomyNode;
}

function TreeNode({ node, depth }: { node: TaxonomyNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = node.children && node.children.length > 0;

  const toggle = useCallback(() => setOpen((prev) => !prev), []);

  const indent = depth * 16;

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        className="flex items-center gap-2 w-full text-left py-1.5 px-2 rounded-lg hover:bg-[rgba(148,163,184,0.06)] transition-colors group"
        style={{ paddingLeft: `${8 + indent}px` }}
      >
        {/* Expand/collapse indicator */}
        {hasChildren ? (
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            className="shrink-0 transition-transform duration-200"
            style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}
          >
            <path
              d="M4 2.5L8 6L4 9.5"
              stroke="var(--text-muted)"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : (
          <span className="w-3 h-3 shrink-0 flex items-center justify-center">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: depth < 2 ? "var(--accent-cyan)" : "var(--accent-purple)", opacity: 0.6 }}
            />
          </span>
        )}

        <span
          className="text-xs transition-colors"
          style={{
            color: hasChildren ? "var(--text-primary)" : "var(--text-secondary)",
            fontWeight: hasChildren ? 600 : 400,
          }}
        >
          {node.label}
        </span>

        {node.representative_papers && node.representative_papers.length > 0 && (
          <span className="text-[9px] text-[var(--text-muted)] ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
            {node.representative_papers.length} paper{node.representative_papers.length > 1 ? "s" : ""}
          </span>
        )}
      </button>

      {/* Children */}
      {hasChildren && open && (
        <div className="animate-fade-in">
          {node.children!.map((child, idx) => (
            <TreeNode key={`${child.label}-${idx}`} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function TaxonomyTree({ root }: TaxonomyTreeProps) {
  if (!root || !root.label) {
    return (
      <div className="glass-card-static p-6 text-center">
        <p className="text-sm text-[var(--text-muted)]">No taxonomy data available.</p>
      </div>
    );
  }

  return (
    <div className="glass-card-static p-4">
      <h3 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
        Taxonomy
      </h3>
      <div className="max-h-[400px] overflow-y-auto">
        <TreeNode node={root} depth={0} />
      </div>
    </div>
  );
}
