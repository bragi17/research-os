"use client";

import { useState, useCallback } from "react";
import type { Run } from "@/lib/api";

interface RightDrawerProps {
  run?: Run | null;
  onAction?: (action: string) => void;
}

type TabKey = "chat" | "evidence" | "controls";

const TABS: { key: TabKey; label: string }[] = [
  { key: "chat", label: "Chat" },
  { key: "evidence", label: "Evidence" },
  { key: "controls", label: "Controls" },
];

export default function RightDrawer({ run, onAction }: RightDrawerProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>("chat");
  const [chatInput, setChatInput] = useState("");

  const handleAction = useCallback(
    (action: string) => {
      if (onAction) onAction(action);
    },
    [onAction],
  );

  if (collapsed) {
    return (
      <aside className="w-10 shrink-0 border-l border-[var(--border-subtle)] bg-[rgba(8,8,16,0.6)] backdrop-blur-md flex flex-col items-center pt-3">
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded-lg hover:bg-[rgba(148,163,184,0.08)] transition-colors text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          title="Expand drawer"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M9 3L5 7L9 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </aside>
    );
  }

  const isTerminal = run && ["completed", "failed", "cancelled"].includes(run.status);

  return (
    <aside className="w-[360px] shrink-0 border-l border-[var(--border-subtle)] bg-[rgba(8,8,16,0.6)] backdrop-blur-md flex flex-col overflow-hidden">
      {/* Header with tabs */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-all duration-200"
              style={{
                background: activeTab === tab.key ? "rgba(6, 182, 212, 0.1)" : "transparent",
                color: activeTab === tab.key ? "var(--accent-cyan)" : "var(--text-muted)",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setCollapsed(true)}
          className="p-1 rounded hover:bg-[rgba(148,163,184,0.08)] transition-colors text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          title="Collapse drawer"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M4 2L8 6L4 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-3">
        {activeTab === "chat" && (
          <div className="flex flex-col h-full">
            <div className="flex-1 flex flex-col items-center justify-center py-12">
              <div className="w-12 h-12 rounded-full border border-[var(--border-subtle)] flex items-center justify-center mb-3">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-[var(--text-muted)]">
                  <path d="M4 4H16V13C16 13.5523 15.5523 14 15 14H8L5 17V14H5C4.44772 14 4 13.5523 4 13V4Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                  <path d="M8 8H12M8 11H10" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
                </svg>
              </div>
              <p className="text-xs text-[var(--text-muted)] text-center">
                Chat with your research assistant.
              </p>
              <p className="text-[10px] text-[var(--text-muted)] text-center mt-1 opacity-60">
                Coming soon
              </p>
            </div>
            <div className="mt-auto pt-3 border-t border-[var(--border-subtle)]">
              <div className="relative">
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="Ask about your research..."
                  className="w-full h-9 pl-3 pr-8 rounded-lg text-xs bg-[rgba(15,23,42,0.6)] border border-[var(--border-subtle)] text-[var(--text-secondary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-cyan)] transition-all"
                />
                <button className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--accent-cyan)] transition-colors">
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M12 7L2 2V5.5L8 7L2 8.5V12L12 7Z" fill="currentColor" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === "evidence" && (
          <div className="flex flex-col items-center justify-center py-12">
            <div className="w-12 h-12 rounded-full border border-[var(--border-subtle)] flex items-center justify-center mb-3">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-[var(--text-muted)]">
                <rect x="4" y="3" width="12" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
                <path d="M8 7H12M8 10H12M8 13H10" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
              </svg>
            </div>
            <p className="text-xs text-[var(--text-muted)] text-center">
              Source citations appear here when viewing results.
            </p>
          </div>
        )}

        {activeTab === "controls" && run && (
          <div className="space-y-4">
            {/* Run controls */}
            <div>
              <h4 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
                Run Controls
              </h4>
              <div className="space-y-2">
                {run.status === "running" && (
                  <button
                    onClick={() => handleAction("pause")}
                    className="btn-secondary w-full text-xs"
                  >
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                      <rect x="2.5" y="2" width="2.5" height="8" rx="0.5" fill="currentColor" />
                      <rect x="7" y="2" width="2.5" height="8" rx="0.5" fill="currentColor" />
                    </svg>
                    Pause Run
                  </button>
                )}
                {run.status === "paused" && (
                  <button
                    onClick={() => handleAction("resume")}
                    className="btn-primary w-full text-xs"
                  >
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                      <path d="M3 1.5L10 6L3 10.5V1.5Z" fill="currentColor" />
                    </svg>
                    Resume Run
                  </button>
                )}
                {!isTerminal && (
                  <button
                    onClick={() => handleAction("cancel")}
                    className="btn-danger w-full text-xs"
                  >
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                      <rect x="2.5" y="2.5" width="7" height="7" rx="1" fill="currentColor" />
                    </svg>
                    Cancel Run
                  </button>
                )}
              </div>
            </div>

            {/* Scope actions */}
            <div>
              <h4 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
                Scope Actions
              </h4>
              <div className="space-y-2">
                <button
                  onClick={() => handleAction("broaden_scope")}
                  className="btn-secondary w-full text-xs"
                  disabled={!!isTerminal}
                >
                  Broaden Scope
                </button>
                <button
                  onClick={() => handleAction("narrow_scope")}
                  className="btn-secondary w-full text-xs"
                  disabled={!!isTerminal}
                >
                  Narrow Scope
                </button>
                <button
                  onClick={() => handleAction("add_seed_paper")}
                  className="btn-secondary w-full text-xs"
                  disabled={!!isTerminal}
                >
                  Add Seed Paper
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === "controls" && !run && (
          <div className="flex flex-col items-center justify-center py-12">
            <p className="text-xs text-[var(--text-muted)]">
              Select a run to see controls.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
