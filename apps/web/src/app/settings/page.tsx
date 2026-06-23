"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";

interface SettingItem {
  key: string;
  value: string;
  display_value?: string;
  is_set: boolean;
  is_sensitive: boolean;
}

interface LLMProfile {
  provider: string;
  label: string;
  base_url: string;
  model: string;
  api_key_preview: string;
  is_key_set: boolean;
  last_test_status: string | null;
  last_test_error: string | null;
  last_test_at: string | null;
}

interface Category {
  id: string;
  label: string;
  items: SettingItem[];
  profile?: LLMProfile;
}

interface LLMEdit {
  api_key: string;
  base_url: string;
  model: string;
  label: string;
}

const DEFAULT_LLM_EDIT: LLMEdit = {
  api_key: "",
  base_url: "https://api.deepseek.com",
  model: "deepseek-v4-pro",
  label: "DeepSeek",
};

const llmEditFromProfile = (profile?: LLMProfile): LLMEdit => ({
  api_key: "",
  base_url: profile?.base_url || DEFAULT_LLM_EDIT.base_url,
  model: profile?.model || DEFAULT_LLM_EDIT.model,
  label: profile?.label || DEFAULT_LLM_EDIT.label,
});

const isDirtyLlmEdit = (current: LLMEdit, saved: LLMEdit) => (
  current.api_key.trim().length > 0
  || current.base_url !== saved.base_url
  || current.model !== saved.model
  || current.label !== saved.label
);

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
  const [llmEdit, setLlmEdit] = useState<LLMEdit>(DEFAULT_LLM_EDIT);
  const [savedLlmEdit, setSavedLlmEdit] = useState<LLMEdit>(DEFAULT_LLM_EDIT);
  const savedLlmEditRef = useRef<LLMEdit>(DEFAULT_LLM_EDIT);
  const llmDirtyRef = useRef(false);

  const fetchSettings = useCallback(async (options?: { forceLlmReset?: boolean }) => {
    try {
      const res = await fetch("/api/v1/settings/models");
      if (res.ok) {
        const data = await res.json();
        const loadedCategories = data.categories as Category[];
        setCategories(loadedCategories);
        const llmProfile = loadedCategories.find((cat) => cat.id === "llm")?.profile;
        const nextSavedLlmEdit = llmEditFromProfile(llmProfile);
        setSavedLlmEdit(nextSavedLlmEdit);
        savedLlmEditRef.current = nextSavedLlmEdit;
        setLlmEdit((prev) => {
          if (options?.forceLlmReset || !llmDirtyRef.current) {
            llmDirtyRef.current = false;
            return nextSavedLlmEdit;
          }
          llmDirtyRef.current = isDirtyLlmEdit(prev, nextSavedLlmEdit);
          return prev;
        });
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
        try {
          const err = await res.json();
          setSaveResult(`Error: ${err.detail || res.statusText}`);
        } catch {
          setSaveResult(`Error: ${res.status} ${res.statusText}`);
        }
      }
    } catch (e) {
      setSaveResult(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleLlmEdit = (key: keyof LLMEdit, value: string) => {
    setLlmEdit((prev) => {
      const next = { ...prev, [key]: value };
      llmDirtyRef.current = isDirtyLlmEdit(next, savedLlmEditRef.current);
      return next;
    });
    setSaveResult(null);
  };

  const handleSaveLlm = async () => {
    setSaving(true);
    setSaveResult(null);
    try {
      const res = await fetch("/api/v1/settings/llm", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: llmEdit.label,
          base_url: llmEdit.base_url,
          model: llmEdit.model,
          api_key: llmEdit.api_key.trim() ? llmEdit.api_key : null,
        }),
      });
      if (res.ok) {
        setSaveResult("DeepSeek settings saved successfully.");
        fetchSettings({ forceLlmReset: true });
      } else {
        try {
          const err = await res.json();
          setSaveResult(`Error: ${err.detail || res.statusText}`);
        } catch {
          setSaveResult(`Error: ${res.status} ${res.statusText}`);
        }
      }
    } catch (e) {
      setSaveResult(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleClearLlmKey = async (cat: Category) => {
    if (llmEdit.api_key.trim()) {
      setLlmEdit((prev) => {
        const next = { ...prev, api_key: "" };
        llmDirtyRef.current = isDirtyLlmEdit(next, savedLlmEditRef.current);
        return next;
      });
      setSaveResult("Unsaved DeepSeek API key cleared.");
      return;
    }
    if (!cat.profile?.is_key_set) return;

    setSaving(true);
    setSaveResult(null);
    try {
      const res = await fetch("/api/v1/settings/llm/api-key", { method: "DELETE" });
      if (res.ok) {
        setSaveResult("DeepSeek API key cleared.");
        fetchSettings({ forceLlmReset: true });
      } else {
        try {
          const err = await res.json();
          setSaveResult(`Error: ${err.detail || res.statusText}`);
        } catch {
          setSaveResult(`Error: ${res.status} ${res.statusText}`);
        }
      }
    } catch (e) {
      setSaveResult(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const isLlmDirty = isDirtyLlmEdit(llmEdit, savedLlmEdit);

  const handleTest = async (type: "llm" | "embedding") => {
    if (type === "llm" && isLlmDirty) {
      setTestResults((prev) => ({
        ...prev,
        llm: { status: "error", detail: "Save DeepSeek settings before testing." },
      }));
      return;
    }

    setTesting(type);
    try {
      const testUrl = type === "llm"
        ? "/api/v1/settings/llm/test"
        : "/api/v1/settings/models/test-embedding";
      const res = await fetch(testUrl, { method: "POST" });
      if (!res.ok) {
        setTestResults((prev) => ({ ...prev, [type]: { status: "error", detail: `HTTP ${res.status}` } }));
        return;
      }
      const data = await res.json();
      setTestResults((prev) => ({
        ...prev,
        [type]: {
          status: data.status,
          detail: data.status === "ok"
            ? (type === "llm" ? `${data.model}: ${data.response}` : `Dimension: ${data.dimension}`)
            : data.error || "Unknown error",
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
              {/* Test button for Embedding */}
              {cat.id === "embedding" && (
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
          {cat.id === "llm" ? (
            <div className="px-5 py-4 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-[160px_1fr] gap-3 items-center">
                <span className="text-[12px] text-[var(--text-secondary)] font-medium">Provider</span>
                <div className="text-[13px] text-[var(--text-primary)]">DeepSeek</div>

                <label htmlFor="llm-base-url" className="text-[12px] text-[var(--text-secondary)] font-medium">
                  Base URL
                </label>
                <input
                  id="llm-base-url"
                  type="text"
                  className="input-field text-[13px] py-1.5"
                  value={llmEdit.base_url}
                  onChange={(e) => handleLlmEdit("base_url", e.target.value)}
                />

                <label htmlFor="llm-model" className="text-[12px] text-[var(--text-secondary)] font-medium">
                  Model
                </label>
                <input
                  id="llm-model"
                  type="text"
                  className="input-field text-[13px] py-1.5"
                  value={llmEdit.model}
                  onChange={(e) => handleLlmEdit("model", e.target.value)}
                />

                <label htmlFor="llm-api-key" className="text-[12px] text-[var(--text-secondary)] font-medium">
                  API key
                </label>
                <input
                  id="llm-api-key"
                  type="password"
                  className="input-field text-[13px] py-1.5"
                  value={llmEdit.api_key}
                  placeholder={cat.profile?.is_key_set ? cat.profile.api_key_preview || "(set)" : "(not set)"}
                  onChange={(e) => handleLlmEdit("api_key", e.target.value)}
                />
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                <div className="flex flex-wrap items-center gap-2 text-[11px]">
                  <span className={`px-1.5 py-0.5 rounded-full ${
                    cat.profile?.is_key_set
                      ? "bg-[var(--accent-green-soft)] text-[var(--accent-green)]"
                      : "bg-[var(--accent-amber-soft)] text-[var(--accent-amber)]"
                  }`}>
                    {cat.profile?.is_key_set ? "key set" : "key empty"}
                  </span>
                  {cat.profile?.api_key_preview && (
                    <span className="text-[var(--text-muted)]" style={{ fontFamily: "var(--font-mono)" }}>
                      {cat.profile.api_key_preview}
                    </span>
                  )}
                  {cat.profile?.last_test_status && (
                    <span className={cat.profile.last_test_status === "ok" ? "text-[var(--accent-green)]" : "text-[var(--accent-red)]"}>
                      Last test: {cat.profile.last_test_status}
                      {cat.profile.last_test_error ? ` (${cat.profile.last_test_error})` : ""}
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button onClick={handleSaveLlm} disabled={saving} className="btn-primary text-[11px] px-3 py-1">
                    {saving ? "Saving..." : "Save DeepSeek"}
                  </button>
                  <button
                    onClick={() => handleTest("llm")}
                    disabled={testing === "llm"}
                    className="btn-secondary text-[11px] px-3 py-1"
                  >
                    {testing === "llm" ? "Testing..." : "Test Connection"}
                  </button>
                  <button
                    onClick={() => handleClearLlmKey(cat)}
                    disabled={saving || (!cat.profile?.is_key_set && !llmEdit.api_key.trim())}
                    className="btn-secondary text-[11px] px-3 py-1"
                  >
                    Clear API Key
                  </button>
                </div>
              </div>
            </div>
          ) : (
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
          )}
        </div>
      ))}
    </div>
  );
}
