-- Users table
CREATE TABLE IF NOT EXISTS app_user (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'research_user',
    is_active BOOLEAN NOT NULL DEFAULT true,
    workspace_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_role CHECK (role IN ('admin', 'research_manager', 'research_user', 'viewer'))
);

CREATE INDEX idx_app_user_email ON app_user(email);
CREATE INDEX idx_app_user_workspace ON app_user(workspace_id);

-- Workspace table
CREATE TABLE IF NOT EXISTS workspace (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    owner_id UUID REFERENCES app_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add foreign key from user to workspace
ALTER TABLE app_user ADD CONSTRAINT fk_user_workspace
    FOREIGN KEY (workspace_id) REFERENCES workspace(id);
