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

export interface Category {
  id: string;
  label: string;
  items: SettingItem[];
  profile?: LLMProfile;
}

export interface LLMEdit {
  api_key: string;
  base_url: string;
  model: string;
  label: string;
}

export interface TestResult {
  status: string;
  detail: string;
}
