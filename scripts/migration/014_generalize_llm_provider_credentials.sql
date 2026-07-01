-- Generalize active LLM provider configuration while keeping DeepSeek defaults.

ALTER TABLE llm_provider_credentials
    DROP CONSTRAINT IF EXISTS llm_provider_credentials_provider_deepseek;

UPDATE llm_provider_credentials
SET is_active = FALSE,
    updated_at = NOW()
WHERE is_active
  AND provider <> 'deepseek';

UPDATE llm_provider_credentials
SET base_url = 'https://api.deepseek.com',
    model = 'deepseek-v4-pro',
    updated_at = NOW()
WHERE is_active
  AND provider = 'deepseek'
  AND (
    lower(base_url) LIKE '%qwen%'
    OR lower(base_url) LIKE '%dashscope%'
    OR lower(base_url) LIKE '%aliyun%'
    OR lower(base_url) LIKE '%yunwu%'
    OR lower(model) LIKE '%qwen%'
    OR lower(model) LIKE '%dashscope%'
    OR lower(model) LIKE '%aliyun%'
    OR lower(model) LIKE '%yunwu%'
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_provider_credentials_active_workspace
    ON llm_provider_credentials (workspace_id)
    WHERE is_active;
