export interface SettingItem {
  key: string;
  value: string;
  display_value?: string;
  is_set: boolean;
  is_sensitive: boolean;
}

export interface LLMProfile {
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

export interface LiteratureCredentialPreview {
  id: string | null;
  label: string;
  preview: string;
  is_active: boolean;
  last_status: string | null;
  last_error: string | null;
  last_used_at: string | null;
  cooldown_until: string | null;
}

export interface LiteratureSourceProfile {
  source: string;
  label: string;
  enabled: boolean;
  configured: boolean;
  options: Record<string, unknown>;
  credentials: LiteratureCredentialPreview[];
  last_test_status: string | null;
  last_test_error: string | null;
  last_test_at: string | null;
}

export interface Category {
  id: string;
  label: string;
  items: SettingItem[];
  profile?: LLMProfile;
  sources?: LiteratureSourceProfile[];
}

export interface LLMEdit {
  provider: string;
  api_key: string;
  base_url: string;
  model: string;
  label: string;
}

export interface TestResult {
  status: string;
  detail: string;
}
