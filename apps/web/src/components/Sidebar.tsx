"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { listRuns, getLibraryStats, type Run } from "@/lib/api";

const MODE_LABELS: Record<string, string> = {
  atlas: "Atlas", frontier: "Frontier", divergent: "Divergent", review: "Review",
};
const STATUS_COLORS: Record<string, string> = {
  running: "var(--accent-green)", completed: "var(--accent-green)",
  failed: "var(--accent-red)", paused: "var(--accent-amber)",
  queued: "var(--text-muted)", cancelled: "var(--text-muted)",
};

function timeAgo(dateStr: string): string {
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    return `${Math.floor(hrs / 24)}d`;
  } catch { return ""; }
}

/* ━━━ Types ━━━ */
interface Project {
  id: string;
  name: string;
  runIds: string[];
}

/* ━━━ Custom Confirm Modal ━━━ */
function ConfirmModal({ title, message, onConfirm, onCancel }: {
  title: string; message: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center" onClick={onCancel}>
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" />
      <div className="relative bg-white rounded-2xl shadow-xl border border-[var(--border-subtle)] p-6 max-w-sm w-full mx-4 animate-fade-up" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)] mb-2">{title}</h3>
        <p className="text-[13px] text-[var(--text-muted)] mb-5 leading-relaxed">{message}</p>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="btn-secondary text-[13px] px-4 py-2">Cancel</button>
          <button onClick={onConfirm} className="btn-danger text-[13px] px-4 py-2">Delete</button>
        </div>
      </div>
    </div>
  );
}

/* ━━━ Context Menu (smart direction) ━━━ */
function ContextMenu({ x, y, items, onClose }: {
  x: number; y: number;
  items: { label: string; icon: string; action: () => void; danger?: boolean }[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: y, left: x });

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  // Smart positioning: flip up if near bottom
  useEffect(() => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const viewH = window.innerHeight;
    const viewW = window.innerWidth;
    let top = y;
    let left = x;
    if (y + rect.height > viewH - 8) top = y - rect.height;
    if (x + rect.width > viewW - 8) left = x - rect.width;
    if (top < 8) top = 8;
    if (left < 8) left = 8;
    setPos({ top, left });
  }, [x, y]);

  return (
    <div
      ref={ref}
      className="fixed z-[100] py-1.5 min-w-[170px] rounded-xl border border-[var(--border-subtle)] bg-white shadow-xl animate-fade-in"
      style={{ top: pos.top, left: pos.left }}
    >
      {items.map((item, i) => (
        <button
          key={i}
          onClick={() => { item.action(); onClose(); }}
          className={`flex items-center gap-2.5 w-full px-3.5 py-2 text-[13px] text-left transition-colors ${
            item.danger
              ? "text-[var(--accent-red)] hover:bg-[var(--accent-red-soft)]"
              : "text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]"
          }`}
        >
          <span className="text-[13px] w-4 text-center">{item.icon}</span>
          {item.label}
        </button>
      ))}
    </div>
  );
}

/* ━━━ Sidebar ━━━ */
export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; items: { label: string; icon: string; action: () => void; danger?: boolean }[] } | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmModal, setConfirmModal] = useState<{ title: string; message: string; onConfirm: () => void } | null>(null);
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set();
    try { return new Set(JSON.parse(localStorage.getItem("ros_pinned") || "[]")); }
    catch { return new Set(); }
  });
  const [projects, setProjects] = useState<Project[]>(() => {
    if (typeof window === "undefined") return [];
    try { return JSON.parse(localStorage.getItem("ros_projects") || "[]"); }
    catch { return []; }
  });
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(() => new Set());
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragOverTarget, setDragOverTarget] = useState<string | null>(null);
  const [libraryCount, setLibraryCount] = useState(0);

  useEffect(() => {
    getLibraryStats()
      .then((s) => setLibraryCount(s.papers))
      .catch(() => { /* silent */ });
  }, []);

  const fetchRuns = useCallback(async () => {
    try { setRuns((await listRuns()).items ?? []); }
    catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchRuns(); const i = setInterval(fetchRuns, 3000); return () => clearInterval(i); }, [fetchRuns]);
  useEffect(() => { fetchRuns(); const t = setTimeout(fetchRuns, 500); return () => clearTimeout(t); }, [pathname, fetchRuns]);
  useEffect(() => { if (typeof window !== "undefined") localStorage.setItem("ros_pinned", JSON.stringify([...pinnedIds])); }, [pinnedIds]);
  useEffect(() => { if (typeof window !== "undefined") localStorage.setItem("ros_projects", JSON.stringify(projects)); }, [projects]);

  const activeRunId = pathname.match(/\/runs\/([^/]+)/)?.[1] ?? null;
  const isNewPage = pathname === "/new";

  // Compute which runs are in projects
  const runsInProjects = new Set(projects.flatMap((p) => p.runIds));
  const pinned = runs.filter((r) => pinnedIds.has(r.id) && !runsInProjects.has(r.id));
  const ungrouped = runs.filter((r) => !pinnedIds.has(r.id) && !runsInProjects.has(r.id));
  const groups = groupByDate(ungrouped);

  /* ── Project CRUD ── */
  const createProject = () => {
    const id = `proj_${Date.now()}`;
    setProjects((prev) => [{ id, name: "New Project", runIds: [] }, ...prev]);
    setRenamingId(id);
    setRenameValue("New Project");
    setExpandedProjects((prev) => new Set([...prev, id]));
  };

  const renameProject = (projId: string, name: string) => {
    setProjects((prev) => prev.map((p) => p.id === projId ? { ...p, name } : p));
    setRenamingId(null);
  };

  const deleteProject = (projId: string) => {
    setProjects((prev) => prev.filter((p) => p.id !== projId));
  };

  const addRunToProject = (projId: string, runId: string) => {
    setProjects((prev) => prev.map((p) =>
      p.id === projId ? { ...p, runIds: [...new Set([...p.runIds, runId])] } : p
    ));
  };

  const removeRunFromProject = (projId: string, runId: string) => {
    setProjects((prev) => prev.map((p) =>
      p.id === projId ? { ...p, runIds: p.runIds.filter((id) => id !== runId) } : p
    ));
  };

  /* ── Run actions ── */
  const handleRename = (id: string, currentName: string) => {
    setRenamingId(id);
    setRenameValue(currentName);
  };

  const handleRenameSubmit = async (id: string) => {
    if (!renameValue.trim()) { setRenamingId(null); return; }
    // Is it a project?
    if (id.startsWith("proj_")) {
      renameProject(id, renameValue.trim());
    } else {
      try {
        await fetch(`/api/v1/runs/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: renameValue.trim() }),
        });
        fetchRuns();
      } catch { /* silent */ }
      setRenamingId(null);
    }
  };

  const handleDeleteRun = (run: Run) => {
    setConfirmModal({
      title: "Delete Research",
      message: `Are you sure you want to delete "${run.title}"? This action cannot be undone.`,
      onConfirm: async () => {
        setConfirmModal(null);
        try {
          await fetch(`/api/v1/runs/${run.id}`, { method: "DELETE" });
          fetchRuns();
          if (activeRunId === run.id) router.push("/");
        } catch { /* silent */ }
      },
    });
  };

  const handleDeleteProject = (proj: Project) => {
    setConfirmModal({
      title: "Delete Project",
      message: `Delete project "${proj.name}"? The research runs inside will be unlinked but not deleted.`,
      onConfirm: () => { deleteProject(proj.id); setConfirmModal(null); },
    });
  };

  const handlePin = (run: Run) => {
    setPinnedIds((prev) => { const n = new Set(prev); n.has(run.id) ? n.delete(run.id) : n.add(run.id); return n; });
  };

  /* ── Drag & Drop ── */
  const handleDragStart = (e: React.DragEvent, id: string) => {
    setDragId(id);
    e.dataTransfer.effectAllowed = "move";
    (e.currentTarget as HTMLElement).style.opacity = "0.4";
  };
  const handleDragEnd = (e: React.DragEvent) => {
    (e.currentTarget as HTMLElement).style.opacity = "1";
    // If dropping on a project folder
    if (dragId && dragOverTarget?.startsWith("proj_") && !dragId.startsWith("proj_")) {
      addRunToProject(dragOverTarget, dragId);
    }
    setDragId(null);
    setDragOverTarget(null);
  };

  /* ── Context menus ── */
  const showRunMenu = (e: React.MouseEvent, run: Run, inProjectId?: string) => {
    e.preventDefault();
    const items: { label: string; icon: string; action: () => void; danger?: boolean }[] = [
      { label: "Rename", icon: "✏️", action: () => handleRename(run.id, run.title) },
      { label: pinnedIds.has(run.id) ? "Unpin" : "Pin to top", icon: "📌", action: () => handlePin(run) },
    ];
    if (inProjectId) {
      items.push({ label: "Remove from project", icon: "↩", action: () => removeRunFromProject(inProjectId, run.id) });
    }
    // Add "Move to project" submenu items
    for (const proj of projects) {
      if (!proj.runIds.includes(run.id)) {
        items.push({ label: `Move to ${proj.name}`, icon: "📁", action: () => addRunToProject(proj.id, run.id) });
      }
    }
    items.push({ label: "Delete", icon: "🗑", action: () => handleDeleteRun(run), danger: true });
    setContextMenu({ x: e.clientX, y: e.clientY, items });
  };

  const showProjectMenu = (e: React.MouseEvent, proj: Project) => {
    e.preventDefault();
    setContextMenu({
      x: e.clientX, y: e.clientY,
      items: [
        { label: "New Research here", icon: "➕", action: () => router.push(`/new?project=${proj.id}`) },
        { label: "Rename", icon: "✏️", action: () => handleRename(proj.id, proj.name) },
        { label: "Delete project", icon: "🗑", action: () => handleDeleteProject(proj), danger: true },
      ],
    });
  };

  /* ── Render helpers ── */
  const renderRunItem = (run: Run, opts?: { pinned?: boolean; inProjectId?: string }) => {
    const isActive = run.id === activeRunId;
    const isDragOver = run.id === dragOverTarget;

    if (renamingId === run.id) {
      return (
        <div key={run.id} className="px-3 py-1.5 mb-0.5">
          <input autoFocus className="input-field text-[13px] py-1.5 px-2" value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleRenameSubmit(run.id); if (e.key === "Escape") setRenamingId(null); }}
            onBlur={() => handleRenameSubmit(run.id)}
          />
        </div>
      );
    }

    return (
      <div key={run.id} draggable
        onDragStart={(e) => handleDragStart(e, run.id)}
        onDragEnd={handleDragEnd}
        onContextMenu={(e) => showRunMenu(e, run, opts?.inProjectId)}
        className={`rounded-xl cursor-pointer transition-all duration-150 mb-0.5 ${isDragOver ? "ring-2 ring-[var(--accent)] ring-offset-1" : ""}`}
      >
        <Link href={`/runs/${run.id}`}>
          <div className={`px-3 py-2 rounded-xl transition-all duration-150 ${isActive ? "bg-white border border-[var(--border-active)] shadow-sm" : "hover:bg-white/60"}`}>
            <div className="flex items-center gap-2 mb-0.5">
              {opts?.pinned && <span className="text-[9px]">📌</span>}
              <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${run.status === "running" ? "animate-pulse-dot" : ""}`}
                style={{ background: STATUS_COLORS[run.status] ?? "var(--text-muted)" }} />
              <span className={`text-[13px] font-medium truncate flex-1 ${isActive ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]"}`}>
                {run.title}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] pl-4">
              {run.mode && <span className="font-medium" style={{ color: "var(--accent)" }}>{MODE_LABELS[run.mode] ?? run.mode}</span>}
              <span>&middot;</span>
              <span className="capitalize">{run.status}</span>
              <span className="ml-auto">{timeAgo(run.updated_at || run.created_at)}</span>
            </div>
          </div>
        </Link>
      </div>
    );
  };

  return (
    <aside className="w-[260px] shrink-0 bg-[var(--bg-sidebar)] border-r border-[var(--border-subtle)] flex flex-col h-screen select-none">
      {/* Header */}
      <div className="p-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center justify-between mb-3">
          <Link href="/" className="text-base font-semibold text-[var(--text-primary)] hover:opacity-80 transition-opacity" style={{ fontFamily: "var(--font-display)" }}>
            Research OS
          </Link>
        </div>
        <Link href="/new"
          className={`flex items-center justify-center gap-2 w-full py-2.5 rounded-xl text-[13px] font-medium transition-all ${
            isNewPage ? "bg-[var(--accent)] text-white shadow-sm" : "border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
          }`}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 3V11M3 7H11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          New Research
        </Link>
        <Link
          href="/library"
          className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg text-[13px] font-medium transition-all mt-2 ${
            pathname === "/library"
              ? "bg-[var(--accent-soft)] text-[var(--accent)]"
              : "text-[var(--text-secondary)] hover:bg-white/40"
          }`}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M2 3h10v8H2zM4 3V2h6v1M5 6h4M5 8h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
          Library
          {libraryCount > 0 && <span className="text-[10px] text-[var(--text-muted)] ml-auto">{libraryCount}</span>}
        </Link>
      </div>

      {/* Scrollable list */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="h-4 w-4 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
          </div>
        ) : (
          <>
            {/* Projects section */}
            <div className="mb-2">
              <button onClick={createProject}
                className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-[12px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/40 transition-colors">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M2 4.5h3l1.5-1.5h3.5a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-4.5z" stroke="currentColor" strokeWidth="1.2" fill="none" />
                  <path d="M7 6.5v3M5.5 8h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                </svg>
                New Project
              </button>
            </div>

            {/* Project folders */}
            {projects.map((proj) => {
              const isExpanded = expandedProjects.has(proj.id);
              const projectRuns = runs.filter((r) => proj.runIds.includes(r.id));
              const isDragOver = dragOverTarget === proj.id;

              return (
                <div key={proj.id} className="mb-1"
                  onDragOver={(e) => { e.preventDefault(); setDragOverTarget(proj.id); }}
                  onDragLeave={() => setDragOverTarget(null)}
                  onDrop={(e) => { e.preventDefault(); if (dragId) addRunToProject(proj.id, dragId); setDragId(null); setDragOverTarget(null); }}
                >
                  {renamingId === proj.id ? (
                    <div className="px-3 py-1.5">
                      <input autoFocus className="input-field text-[13px] py-1.5 px-2" value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") handleRenameSubmit(proj.id); if (e.key === "Escape") setRenamingId(null); }}
                        onBlur={() => handleRenameSubmit(proj.id)}
                      />
                    </div>
                  ) : (
                    <button
                      onClick={() => setExpandedProjects((p) => { const n = new Set(p); n.has(proj.id) ? n.delete(proj.id) : n.add(proj.id); return n; })}
                      onContextMenu={(e) => showProjectMenu(e, proj)}
                      className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg text-left transition-all ${
                        isDragOver ? "bg-[var(--accent-soft)] border border-dashed border-[var(--accent)]" : "hover:bg-white/40"
                      }`}
                    >
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="shrink-0">
                        <path d="M2 4.5h3l1.5-1.5h3.5a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-4.5z"
                          stroke="var(--accent)" strokeWidth="1.2" fill={isExpanded ? "var(--accent-soft)" : "none"} />
                      </svg>
                      <span className="text-[13px] font-medium text-[var(--text-primary)] truncate flex-1">{proj.name}</span>
                      <span className="text-[10px] text-[var(--text-muted)]">{projectRuns.length}</span>
                      <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
                        className="shrink-0 transition-transform duration-200"
                        style={{ transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)" }}>
                        <path d="M3 1.5L7 5L3 8.5" stroke="var(--text-muted)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </button>
                  )}
                  {isExpanded && (
                    <div className="ml-3 mt-0.5 border-l border-[var(--border-subtle)] pl-1">
                      {projectRuns.length === 0 ? (
                        <p className="text-[11px] text-[var(--text-muted)] px-3 py-2 italic">
                          Drag runs here
                        </p>
                      ) : (
                        projectRuns.map((run) => renderRunItem(run, { inProjectId: proj.id }))
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Pinned */}
            {pinned.length > 0 && (
              <div className="mb-2">
                <div className="px-3 py-1.5 text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider">Pinned</div>
                {pinned.map((run) => renderRunItem(run, { pinned: true }))}
              </div>
            )}

            {/* Date groups */}
            {groups.map((group) => (
              <div key={group.label} className="mb-2">
                <div className="px-3 py-1.5 text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider">{group.label}</div>
                {group.runs.map((run) => renderRunItem(run))}
              </div>
            ))}

            {runs.length === 0 && projects.length === 0 && (
              <div className="text-center py-12 px-4">
                <p className="text-[13px] text-[var(--text-secondary)] font-medium">No research yet</p>
                <p className="text-[12px] text-[var(--text-muted)] mt-1">Click &ldquo;New Research&rdquo; to start</p>
              </div>
            )}
          </>
        )}
      </div>

      {/* Context menu */}
      {contextMenu && (
        <ContextMenu x={contextMenu.x} y={contextMenu.y} items={contextMenu.items} onClose={() => setContextMenu(null)} />
      )}

      {/* Confirm modal */}
      {confirmModal && (
        <ConfirmModal title={confirmModal.title} message={confirmModal.message}
          onConfirm={confirmModal.onConfirm} onCancel={() => setConfirmModal(null)} />
      )}
    </aside>
  );
}

function groupByDate(runs: Run[]): { label: string; runs: Run[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);
  const groups: { label: string; runs: Run[] }[] = [
    { label: "Today", runs: [] }, { label: "Yesterday", runs: [] },
    { label: "Previous 7 days", runs: [] }, { label: "Older", runs: [] },
  ];
  for (const run of runs) {
    const d = new Date(run.created_at);
    if (d >= today) groups[0].runs.push(run);
    else if (d >= yesterday) groups[1].runs.push(run);
    else if (d >= weekAgo) groups[2].runs.push(run);
    else groups[3].runs.push(run);
  }
  return groups.filter((g) => g.runs.length > 0);
}
