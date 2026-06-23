-- LLM provider credential storage

CREATE TABLE IF NOT EXISTS llm_provider_credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    provider TEXT NOT NULL DEFAULT 'deepseek',
    label TEXT NOT NULL DEFAULT 'DeepSeek',
    base_url TEXT NOT NULL DEFAULT 'https://api.deepseek.com',
    model TEXT NOT NULL DEFAULT 'deepseek-v4-pro',
    api_key_encrypted TEXT,
    api_key_preview TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_test_status TEXT,
    last_test_error TEXT,
    last_test_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT llm_provider_credentials_provider_deepseek CHECK (provider = 'deepseek'),
    CONSTRAINT llm_provider_credentials_base_url_nonblank CHECK (btrim(base_url) <> ''),
    CONSTRAINT llm_provider_credentials_model_nonblank CHECK (btrim(model) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_provider_credentials_active_provider
    ON llm_provider_credentials (workspace_id, provider)
    WHERE is_active;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'update_llm_provider_credentials_updated'
    ) THEN
        CREATE TRIGGER update_llm_provider_credentials_updated
            BEFORE UPDATE ON llm_provider_credentials
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    END IF;
END;
$$;
