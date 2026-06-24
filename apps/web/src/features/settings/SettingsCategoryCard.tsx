import type { Category, LLMEdit, TestResult } from "./types";
import { CATEGORY_DESC, CATEGORY_ICONS } from "./metadata";

interface SettingsCategoryCardProps {
  category: Category;
  edits: Record<string, string>;
  llmEdit: LLMEdit;
  saving: boolean;
  testing: string | null;
  testResult?: TestResult;
  onEdit: (key: string, value: string) => void;
  onLlmEdit: (key: keyof LLMEdit, value: string) => void;
  onSaveLlm: () => void;
  onClearLlmKey: (category: Category) => void;
  onTest: (type: "llm" | "embedding") => void;
}

export function SettingsCategoryCard({
  category,
  edits,
  llmEdit,
  saving,
  testing,
  testResult,
  onEdit,
  onLlmEdit,
  onSaveLlm,
  onClearLlmKey,
  onTest,
}: SettingsCategoryCardProps) {
  return (
    <div className="card-static overflow-hidden">
      <div className="px-5 py-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="text-base">{CATEGORY_ICONS[category.id] || "⚙"}</span>
            <div>
              <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">{category.label}</h2>
              <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{CATEGORY_DESC[category.id] || ""}</p>
            </div>
          </div>
          {category.id === "embedding" && (
            <button
              onClick={() => onTest(category.id as "llm" | "embedding")}
              disabled={testing === category.id}
              className="btn-secondary text-[11px] px-3 py-1"
            >
              {testing === category.id ? "Testing..." : "Test Connection"}
            </button>
          )}
        </div>
        {testResult && (
          <div className={`mt-2 text-[12px] px-3 py-1.5 rounded-lg ${
            testResult.status === "ok"
              ? "bg-[var(--accent-green-soft)] text-[var(--accent-green)]"
              : "bg-[var(--accent-red-soft)] text-[var(--accent-red)]"
          }`}>
            {testResult.status === "ok" ? "✓ " : "✗ "}
            {testResult.detail}
          </div>
        )}
      </div>

      {category.id === "llm" ? (
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
              onChange={(e) => onLlmEdit("base_url", e.target.value)}
            />

            <label htmlFor="llm-model" className="text-[12px] text-[var(--text-secondary)] font-medium">
              Model
            </label>
            <input
              id="llm-model"
              type="text"
              className="input-field text-[13px] py-1.5"
              value={llmEdit.model}
              onChange={(e) => onLlmEdit("model", e.target.value)}
            />

            <label htmlFor="llm-api-key" className="text-[12px] text-[var(--text-secondary)] font-medium">
              API key
            </label>
            <input
              id="llm-api-key"
              type="password"
              className="input-field text-[13px] py-1.5"
              value={llmEdit.api_key}
              placeholder={category.profile?.is_key_set ? category.profile.api_key_preview || "(set)" : "(not set)"}
              onChange={(e) => onLlmEdit("api_key", e.target.value)}
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <span className={`px-1.5 py-0.5 rounded-full ${
                category.profile?.is_key_set
                  ? "bg-[var(--accent-green-soft)] text-[var(--accent-green)]"
                  : "bg-[var(--accent-amber-soft)] text-[var(--accent-amber)]"
              }`}>
                {category.profile?.is_key_set ? "key set" : "key empty"}
              </span>
              {category.profile?.api_key_preview && (
                <span className="text-[var(--text-muted)]" style={{ fontFamily: "var(--font-mono)" }}>
                  {category.profile.api_key_preview}
                </span>
              )}
              {category.profile?.last_test_status && (
                <span className={category.profile.last_test_status === "ok" ? "text-[var(--accent-green)]" : "text-[var(--accent-red)]"}>
                  Last test: {category.profile.last_test_status}
                  {category.profile.last_test_error ? ` (${category.profile.last_test_error})` : ""}
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button onClick={onSaveLlm} disabled={saving} className="btn-primary text-[11px] px-3 py-1">
                {saving ? "Saving..." : "Save DeepSeek"}
              </button>
              <button
                onClick={() => onTest("llm")}
                disabled={testing === "llm"}
                className="btn-secondary text-[11px] px-3 py-1"
              >
                {testing === "llm" ? "Testing..." : "Test Connection"}
              </button>
              <button
                onClick={() => onClearLlmKey(category)}
                disabled={saving || (!category.profile?.is_key_set && !llmEdit.api_key.trim())}
                className="btn-secondary text-[11px] px-3 py-1"
              >
                Clear API Key
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="divide-y divide-[var(--border-subtle)]">
          {category.items.map((item) => {
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
                    onChange={(e) => onEdit(item.key, e.target.value)}
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
  );
}
