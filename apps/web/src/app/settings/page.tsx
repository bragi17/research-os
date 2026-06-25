"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { SettingsCategoryCard } from "@/features/settings/SettingsCategoryCard";
import { DEFAULT_LLM_EDIT, isDirtyLlmEdit, llmEditFromProfile } from "@/features/settings/llmProfile";
import type { Category, LiteratureSourceProfile, LLMEdit, TestResult } from "@/features/settings/types";
import { apiFetch } from "@/lib/api";

export default function SettingsPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [llmEdit, setLlmEdit] = useState<LLMEdit>(DEFAULT_LLM_EDIT);
  const [savedLlmEdit, setSavedLlmEdit] = useState<LLMEdit>(DEFAULT_LLM_EDIT);
  const [literatureEdits, setLiteratureEdits] = useState<Record<string, LiteratureSourceProfile>>({});
  const [savingLiteratureSource, setSavingLiteratureSource] = useState<string | null>(null);
  const savedLlmEditRef = useRef<LLMEdit>(DEFAULT_LLM_EDIT);
  const llmDirtyRef = useRef(false);

  const fetchSettings = useCallback(async (options?: { forceLlmReset?: boolean }) => {
    try {
      setLoadError(null);
      const data = await apiFetch<{ categories?: Category[] }>("/api/v1/settings/models");
      const loadedCategories = Array.isArray(data.categories) ? data.categories as Category[] : [];
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
      if (loadedCategories.length === 0) {
        setLoadError("Settings loaded, but no categories were returned.");
      }
    } catch (error) {
      setLoadError(`Settings failed to load: ${String(error)}`);
      setCategories([]);
    }
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
      await apiFetch("/api/v1/settings/models", {
        method: "PUT",
        body: JSON.stringify(edits),
      });
      setSaveResult("Settings saved successfully. Restart services to apply.");
      setEdits({});
      fetchSettings();
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
      await apiFetch("/api/v1/settings/llm", {
        method: "PUT",
        body: JSON.stringify({
          label: llmEdit.label,
          base_url: llmEdit.base_url,
          model: llmEdit.model,
          api_key: llmEdit.api_key.trim() ? llmEdit.api_key : null,
        }),
      });
      setSaveResult("DeepSeek settings saved successfully.");
      fetchSettings({ forceLlmReset: true });
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
      await apiFetch("/api/v1/settings/llm/api-key", { method: "DELETE" });
      setSaveResult("DeepSeek API key cleared.");
      fetchSettings({ forceLlmReset: true });
    } catch (e) {
      setSaveResult(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleLiteratureEdit = (source: string, value: LiteratureSourceProfile) => {
    setLiteratureEdits((prev) => ({ ...prev, [source]: value }));
    setTestResults((prev) => {
      if (!prev[source]) return prev;
      const next = { ...prev };
      delete next[source];
      return next;
    });
    setSaveResult(null);
  };

  const handleSaveLiterature = async (source: string) => {
    const draft = literatureEdits[source];
    if (!draft) return;

    setSavingLiteratureSource(source);
    setSaveResult(null);
    try {
      const newCredentials = String(draft.options["new_credentials"] || "")
        .split(/\s+/)
        .map((item) => item.trim())
        .filter(Boolean);
      const clearCredentialIds = Array.isArray(draft.options["clear_credential_ids"])
        ? draft.options["clear_credential_ids"].filter((item): item is string => typeof item === "string")
        : [];
      const cleanOptions = { ...draft.options };
      delete cleanOptions.new_credentials;
      delete cleanOptions.clear_credential_ids;

      await apiFetch(`/api/v1/settings/literature/${source}`, {
        method: "PUT",
        body: JSON.stringify({
          enabled: draft.enabled,
          options: cleanOptions,
          new_credentials: newCredentials,
          clear_credential_ids: clearCredentialIds,
        }),
      });

      setLiteratureEdits((prev) => {
        const next = { ...prev };
        delete next[source];
        return next;
      });
      setSaveResult("Literature source settings saved.");
      fetchSettings();
    } catch (error) {
      setSaveResult(`Error: ${String(error)}`);
    } finally {
      setSavingLiteratureSource(null);
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
      const data = await apiFetch<{
        status: string;
        model?: string;
        response?: string;
        dimension?: number;
        error?: string;
      }>(testUrl, { method: "POST" });
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

  const handleTestLiterature = async (source: string) => {
    if (literatureEdits[source]) {
      setTestResults((prev) => ({
        ...prev,
        [source]: { status: "error", detail: "Save this source before testing." },
      }));
      return;
    }

    setTesting(source);
    try {
      const data = await apiFetch<{ status: string; error?: string }>(
        `/api/v1/settings/literature/${source}/test`,
        { method: "POST" },
      );
      setTestResults((prev) => ({
        ...prev,
        [source]: {
          status: data.status,
          detail: data.status === "ok" ? "Connection test passed." : data.error || "Unknown error",
        },
      }));
      fetchSettings();
    } catch (error) {
      setTestResults((prev) => ({
        ...prev,
        [source]: { status: "error", detail: String(error) },
      }));
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

      {loadError && (
        <div className="card-static border-[var(--accent-red)]/30 bg-[var(--accent-red-soft)] p-3 text-[13px] text-[var(--accent-red)]">
          {loadError}
        </div>
      )}

      {/* Categories */}
      {categories.length > 0 ? categories.map((cat) => (
        <SettingsCategoryCard
          key={cat.id}
          category={cat}
          edits={edits}
          llmEdit={llmEdit}
          literatureEdits={literatureEdits}
          saving={saving}
          savingLiteratureSource={savingLiteratureSource}
          testing={testing}
          testResult={testResults[cat.id]}
          literatureTestResults={testResults}
          onEdit={handleEdit}
          onLlmEdit={handleLlmEdit}
          onLiteratureEdit={handleLiteratureEdit}
          onSaveLlm={handleSaveLlm}
          onSaveLiterature={handleSaveLiterature}
          onClearLlmKey={handleClearLlmKey}
          onTest={handleTest}
          onTestLiterature={handleTestLiterature}
        />
      )) : (
        <div className="card-static p-6 text-center text-[13px] text-[var(--text-muted)]">
          No settings categories are available.
        </div>
      )}
    </div>
  );
}
