import type { LLMEdit, LLMProfile } from "./types";

export const DEFAULT_LLM_EDIT: LLMEdit = {
  provider: "deepseek",
  api_key: "",
  base_url: "https://api.deepseek.com",
  model: "deepseek-v4-pro",
  label: "DeepSeek",
};

export const llmEditFromProfile = (profile?: LLMProfile): LLMEdit => ({
  provider: profile?.provider || DEFAULT_LLM_EDIT.provider,
  api_key: "",
  base_url: profile?.base_url || DEFAULT_LLM_EDIT.base_url,
  model: profile?.model || DEFAULT_LLM_EDIT.model,
  label: profile?.label || DEFAULT_LLM_EDIT.label,
});

export const isDirtyLlmEdit = (current: LLMEdit, saved: LLMEdit) => (
  current.api_key.trim().length > 0
  || current.provider !== saved.provider
  || current.base_url !== saved.base_url
  || current.model !== saved.model
  || current.label !== saved.label
);
