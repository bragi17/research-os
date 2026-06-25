import { CheckCircle2, Trash2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { LiteratureSourceProfile, TestResult } from "./types";

interface LiteratureSourcesPanelProps {
  sources: LiteratureSourceProfile[];
  edits: Record<string, LiteratureSourceProfile>;
  saving: boolean;
  testing: string | null;
  testResults: Record<string, TestResult>;
  onEdit: (source: string, value: LiteratureSourceProfile) => void;
  onSave: (source: string) => void;
  onTest: (source: string) => void;
}

const TRANSIENT_OPTION_KEYS = new Set(["new_credentials", "clear_credential_ids"]);

function sourceDraft(
  source: LiteratureSourceProfile,
  edits: Record<string, LiteratureSourceProfile>,
): LiteratureSourceProfile {
  return edits[source.source] || source;
}

function optionValue(options: Record<string, unknown>, key: string): unknown {
  return options[key];
}

function clearCredentialIds(options: Record<string, unknown>): string[] {
  const value = optionValue(options, "clear_credential_ids");
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function newCredentialsText(options: Record<string, unknown>): string {
  const value = optionValue(options, "new_credentials");
  return typeof value === "string" ? value : "";
}

function editableOptions(options: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(options || {}).filter(([key]) => !TRANSIENT_OPTION_KEYS.has(key)),
  );
}

function formatOptions(options: Record<string, unknown>): string {
  return JSON.stringify(editableOptions(options), null, 2);
}

function mergeOptions(
  currentOptions: Record<string, unknown>,
  nextOptions: Record<string, unknown>,
): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...nextOptions };
  const newCredentials = optionValue(currentOptions, "new_credentials");
  const clearIds = optionValue(currentOptions, "clear_credential_ids");
  if (typeof newCredentials === "string") merged.new_credentials = newCredentials;
  if (Array.isArray(clearIds)) merged.clear_credential_ids = clearIds;
  return merged;
}

function statusClass(status: string | null | undefined): string {
  if (status === "ok") return "text-[var(--accent-green)]";
  if (status) return "text-[var(--accent-red)]";
  return "text-[var(--text-muted)]";
}

export function LiteratureSourcesPanel({
  sources,
  edits,
  saving,
  testing,
  testResults,
  onEdit,
  onSave,
  onTest,
}: LiteratureSourcesPanelProps) {
  const sourceKeys = useMemo(() => sources.map((source) => source.source).join("|"), [sources]);
  const [optionText, setOptionText] = useState<Record<string, string>>({});
  const [optionErrors, setOptionErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setOptionText((previous) => {
      const next = { ...previous };
      for (const source of sources) {
        if (next[source.source] === undefined && !edits[source.source]) {
          next[source.source] = formatOptions(source.options || {});
        }
      }
      return next;
    });
  }, [sources, sourceKeys, edits]);

  if (sources.length === 0) {
    return (
      <div className="px-5 py-5 text-[13px] text-[var(--text-muted)]">
        Literature source settings are not available.
      </div>
    );
  }

  return (
    <div className="divide-y divide-[var(--border-subtle)]">
      {sources.map((source) => {
        const draft = sourceDraft(source, edits);
        const clearIds = clearCredentialIds(draft.options || {});
        const pendingClear = new Set(clearIds);
        const nextKeys = newCredentialsText(draft.options || {});
        const testResult = testResults[source.source];
        const optionsText = optionText[source.source] ?? formatOptions(draft.options || {});
        const optionError = optionErrors[source.source];
        const hasEdit = Boolean(edits[source.source]);
        const canSave = hasEdit && !saving && !optionError;

        return (
          <div key={source.source} className="px-5 py-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(180px,240px)_1fr]">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 text-[13px] font-semibold text-[var(--text-primary)]">
                    {source.label}
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] ${
                      draft.configured
                        ? "bg-[var(--accent-green-soft)] text-[var(--accent-green)]"
                        : "bg-[var(--accent-amber-soft)] text-[var(--accent-amber)]"
                    }`}
                  >
                    {draft.configured ? "configured" : "not configured"}
                  </span>
                </div>
                <div className="space-y-1 text-[11px]">
                  {source.last_test_status ? (
                    <p className={statusClass(source.last_test_status)}>
                      Last test: {source.last_test_status}
                      {source.last_test_error ? ` (${source.last_test_error})` : ""}
                    </p>
                  ) : (
                    <p className="text-[var(--text-muted)]">No test recorded.</p>
                  )}
                  {testResult && (
                    <p
                      className={`flex items-start gap-1.5 ${
                        testResult.status === "ok"
                          ? "text-[var(--accent-green)]"
                          : "text-[var(--accent-red)]"
                      }`}
                    >
                      {testResult.status === "ok" ? (
                        <CheckCircle2 className="mt-0.5 shrink-0" size={13} strokeWidth={2} />
                      ) : (
                        <XCircle className="mt-0.5 shrink-0" size={13} strokeWidth={2} />
                      )}
                      <span className="min-w-0 break-words">{testResult.detail}</span>
                    </p>
                  )}
                </div>
                <label className="inline-flex items-center gap-2 text-[12px] text-[var(--text-secondary)]">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(event) => {
                      onEdit(source.source, { ...draft, enabled: event.target.checked });
                    }}
                  />
                  Enabled
                </label>
              </div>

              <div className="min-w-0 space-y-3">
                <div className="grid grid-cols-1 gap-2 md:grid-cols-[120px_minmax(0,1fr)]">
                  <label
                    htmlFor={`literature-options-${source.source}`}
                    className="pt-1.5 text-[12px] font-medium text-[var(--text-secondary)]"
                  >
                    Options JSON
                  </label>
                  <div className="min-w-0 space-y-1">
                    <textarea
                      id={`literature-options-${source.source}`}
                      className={`input-field min-h-[86px] resize-y py-1.5 text-[12px] leading-relaxed ${
                        optionError ? "border-[var(--accent-red)]" : ""
                      }`}
                      style={{ fontFamily: "var(--font-mono)" }}
                      value={optionsText}
                      onChange={(event) => {
                        const text = event.target.value;
                        setOptionText((previous) => ({ ...previous, [source.source]: text }));
                        try {
                          const parsed = JSON.parse(text);
                          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
                            throw new Error("Options must be a JSON object.");
                          }
                          setOptionErrors((previous) => {
                            const next = { ...previous };
                            delete next[source.source];
                            return next;
                          });
                          onEdit(source.source, {
                            ...draft,
                            options: mergeOptions(draft.options || {}, parsed as Record<string, unknown>),
                          });
                        } catch (error) {
                          setOptionErrors((previous) => ({
                            ...previous,
                            [source.source]: error instanceof Error ? error.message : "Invalid JSON object.",
                          }));
                        }
                      }}
                    />
                    {optionError && (
                      <p className="text-[11px] text-[var(--accent-red)]">{optionError}</p>
                    )}
                  </div>

                  <span className="pt-1.5 text-[12px] font-medium text-[var(--text-secondary)]">
                    Stored keys
                  </span>
                  <div className="min-w-0">
                    {source.credentials.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {source.credentials.map((credential) => {
                          const marked = credential.id ? pendingClear.has(credential.id) : false;
                          return (
                            <span
                              key={credential.id || credential.label}
                              className={`inline-flex max-w-full items-center gap-1.5 rounded-md border border-[var(--border-subtle)] px-2 py-1 text-[11px] ${
                                marked ? "text-[var(--accent-red)] line-through" : "text-[var(--text-muted)]"
                              }`}
                            >
                              <span className="min-w-0 truncate" style={{ fontFamily: "var(--font-mono)" }}>
                                {credential.preview || credential.label}
                              </span>
                              {credential.id && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    const nextClearIds = marked
                                      ? clearIds.filter((id) => id !== credential.id)
                                      : [...clearIds, credential.id];
                                    onEdit(source.source, {
                                      ...draft,
                                      options: {
                                        ...(draft.options || {}),
                                        clear_credential_ids: nextClearIds,
                                      },
                                    });
                                  }}
                                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--accent-red)] hover:bg-[var(--accent-red-soft)]"
                                  aria-label={`${marked ? "Keep" : "Remove"} ${credential.label}`}
                                  title={marked ? "Keep credential" : "Remove credential"}
                                >
                                  <Trash2 size={12} strokeWidth={2} />
                                </button>
                              )}
                            </span>
                          );
                        })}
                      </div>
                    ) : (
                      <span className="text-[12px] text-[var(--text-muted)]">No stored keys.</span>
                    )}
                  </div>

                  <label
                    htmlFor={`literature-keys-${source.source}`}
                    className="pt-1.5 text-[12px] font-medium text-[var(--text-secondary)]"
                  >
                    New keys
                  </label>
                  <textarea
                    id={`literature-keys-${source.source}`}
                    className="input-field min-h-[68px] resize-y py-1.5 text-[12px] leading-relaxed"
                    style={{ fontFamily: "var(--font-mono)" }}
                    value={nextKeys}
                    placeholder="Paste one or more keys, separated by whitespace or new lines"
                    onChange={(event) => {
                      onEdit(source.source, {
                        ...draft,
                        options: { ...(draft.options || {}), new_credentials: event.target.value },
                      });
                    }}
                  />
                </div>

                <div className="flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    className="btn-primary px-3 py-1 text-[11px]"
                    disabled={!canSave}
                    onClick={() => onSave(source.source)}
                  >
                    {saving ? "Saving..." : "Save"}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary px-3 py-1 text-[11px]"
                    disabled={testing === source.source}
                    onClick={() => onTest(source.source)}
                  >
                    {testing === source.source ? "Testing..." : "Test"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
