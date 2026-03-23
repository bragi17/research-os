"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";

interface SettingItem {
  key: string;
  value: string;
  is_set: boolean;
  is_sensitive: boolean;
}

interface Category {
  id: string;
  label: string;
  items: SettingItem[];
}

const CATEGORY_ICONS: Record<string, string> = {
  llm: "🧠",
  embedding: "📐",
  rerank: "🔄",
  academic: "🎓",
  storage: "💾",
};

const CATEGORY_DESC: Record<string, string> = {
  llm: "Configure the LLM provider for research analysis, paper review, and innovation generation.",
  embedding: "Configure the embedding model for vector search and RAG indexing.",
  rerank: "Configure the rerank model for search result relevance scoring.",
  academic: "API keys for Semantic Scholar, OpenAlex, and other academic data sources.",
  storage: "File storage paths and service URLs.",
};

export default function SettingsPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { status: string; detail: string }>>({});
  const [testing, setTesting] = useState<string | null>(null);

  const fetchSettings = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/settings/models");
      if (res.ok) {
        const data = await res.json();
        setCategories(data.categories);
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchSettings(); }, [fetchSettings]);

  const handleEdit = (key: string, value: string) => {
    setEdits((prev) => ({ ...prev, [key]: value }));
    setSaveResult(null);
  };

  const handleSave = async () => {
    if (Object.keys(edits).length === 0) return;
    setSaving(true);
    setSaveResult(null);
    try {
      const res = await fetch("/api/v1/settings/models", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(edits),
      });
      if (res.ok) {
        setSaveResult("Settings saved successfully. Restart services to apply.");
        setEdits({});
        fetchSettings();
      } else {
        const err = await res.json();
        setSaveResult(`Error: ${err.detail}`);
      }
    } catch (e) {
      setSaveResult(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async (type: "llm" | "embedding") => {
    setTesting(type);
    try {
      const res = await fetch(`/api/v1/settings/models/test-${type}`, { method: "POST" });
      const data = await res.json();
      setTestResults((prev) => ({
        ...prev,
        [type]: {
          status: data.status,
          detail: data.status === "ok"
            ? (type === "llm" ? `${data.model}: ${data.response}` : `Dimension: ${data.dimension}`)
            : data.error,
        },
      }));
    } catch (e) {
      setTestResults((prev) => ({ ...prev, [type]: { status: "error", detail: String(e) } }));
    } finally {
      setTesting(null);
    }
  };

  const hasEdits = Object.keys(edits).length > 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="h-6 w-6 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-[1060px] mx-auto px-8 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-medium text-[var(--text-primary)] mb-1" style={{ fontFamily: "var(--font-display)" }}>
            Settings
          </h1>
          <p className="text-sm text-[var(--text-muted)]">
            Configure AI models, API keys, and service endpoints.
          </p>
        </div>
        {hasEdits && (
          <button onClick={handleSave} disabled={saving} className="btn-primary text-[13px]">
            {saving ? "Saving..." : `Save ${Object.keys(edits).length} change${Object.keys(edits).length > 1 ? "s" : ""}`}
          </button>
        )}
      </div>

      {saveResult && (
        <div className={`card-static p-3 text-[13px] ${saveResult.startsWith("Error") ? "text-[var(--accent-red)]" : "text-[var(--accent-green)]"}`}>
          {saveResult}
        </div>
      )}

      {/* Categories */}
      {categories.map((cat) => (
        <div key={cat.id} className="card-static overflow-hidden">
          {/* Category header */}
          <div className="px-5 py-4 border-b border-[var(--border-subtle)]">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-base">{CATEGORY_ICONS[cat.id] || "⚙"}</span>
                <div>
                  <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">{cat.label}</h2>
                  <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{CATEGORY_DESC[cat.id] || ""}</p>
                </div>
              </div>
              {/* Test buttons for LLM and Embedding */}
              {(cat.id === "llm" || cat.id === "embedding") && (
                <button
                  onClick={() => handleTest(cat.id as "llm" | "embedding")}
                  disabled={testing === cat.id}
                  className="btn-secondary text-[11px] px-3 py-1"
                >
                  {testing === cat.id ? "Testing..." : "Test Connection"}
                </button>
              )}
            </div>
            {/* Test result */}
            {testResults[cat.id] && (
              <div className={`mt-2 text-[12px] px-3 py-1.5 rounded-lg ${
                testResults[cat.id].status === "ok"
                  ? "bg-[var(--accent-green-soft)] text-[var(--accent-green)]"
                  : "bg-[var(--accent-red-soft)] text-[var(--accent-red)]"
              }`}>
                {testResults[cat.id].status === "ok" ? "✓ " : "✗ "}
                {testResults[cat.id].detail}
              </div>
            )}
          </div>

          {/* Setting items */}
          <div className="divide-y divide-[var(--border-subtle)]">
            {cat.items.map((item) => {
              const editValue = edits[item.key];
              const isEdited = editValue !== undefined;

              return (
                <div key={item.key} className="flex items-center gap-4 px-5 py-3">
                  <div className="w-[220px] shrink-0">
                    <span className="text-[12px] text-[var(--text-secondary)] font-medium" style={{ fontFamily: "var(--font-mono)" }}>
                      {item.key}
                    </span>
                  </div>
                  <div className="flex-1">
                    <input
                      type={item.is_sensitive ? "password" : "text"}
                      className={`input-field text-[13px] py-1.5 ${isEdited ? "border-[var(--accent)]" : ""}`}
                      style={{ fontFamily: "var(--font-mono)" }}
                      value={isEdited ? editValue : item.value}
                      placeholder={item.is_set ? "(set)" : "(not set)"}
                      onChange={(e) => handleEdit(item.key, e.target.value)}
                    />
                  </div>
                  <div className="w-[60px] shrink-0 text-right">
                    {item.is_set ? (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--accent-green-soft)] text-[var(--accent-green)]">set</span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--accent-amber-soft)] text-[var(--accent-amber)]">empty</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
