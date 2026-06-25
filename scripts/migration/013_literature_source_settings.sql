-- Literature source settings and multi-key credential storage.

CREATE TABLE IF NOT EXISTS literature_source_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    source TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    options_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_test_status TEXT,
    last_test_error TEXT,
    last_test_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT literature_source_settings_source_check CHECK (
        source IN (
            'local_library',
            'zotero',
            'obsidian',
            'web_search',
            'semantic_scholar',
            'openalex',
            'deepxiv'
        )
    ),
    CONSTRAINT literature_source_settings_options_object_check
        CHECK (jsonb_typeof(options_json) = 'object'),
    CONSTRAINT literature_source_settings_test_status_check CHECK (
        last_test_status IS NULL OR last_test_status IN ('ok', 'error')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_literature_source_settings_workspace_source
    ON literature_source_settings (workspace_id, source);

CREATE TABLE IF NOT EXISTS literature_source_credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    source TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'primary',
    secret_encrypted TEXT NOT NULL,
    secret_preview TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_status TEXT,
    last_error TEXT,
    last_used_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT literature_source_credentials_source_check CHECK (
        source IN ('web_search', 'semantic_scholar', 'openalex')
    ),
    CONSTRAINT literature_source_credentials_status_check CHECK (
        last_status IS NULL OR last_status IN ('ok', 'rate_limited', 'credential_error', 'error')
    )
);

CREATE INDEX IF NOT EXISTS idx_literature_source_credentials_workspace_source
    ON literature_source_credentials (workspace_id, source)
    WHERE is_active;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'update_literature_source_settings_updated'
    ) THEN
        CREATE TRIGGER update_literature_source_settings_updated
            BEFORE UPDATE ON literature_source_settings
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'update_literature_source_credentials_updated'
    ) THEN
        CREATE TRIGGER update_literature_source_credentials_updated
            BEFORE UPDATE ON literature_source_credentials
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    END IF;
END;
$$;
