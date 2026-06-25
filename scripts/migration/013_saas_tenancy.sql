-- SaaS tenancy foundation.
-- Idempotent: safe to re-run.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS tenant (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    owner_id UUID REFERENCES app_user(id) ON DELETE SET NULL,
    plan TEXT NOT NULL DEFAULT 'starter',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE workspace ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE workspace ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
DECLARE
    workspace_row RECORD;
    generated_tenant_id UUID;
BEGIN
    FOR workspace_row IN
        SELECT id, name, owner_id
        FROM workspace
        WHERE tenant_id IS NULL
    LOOP
        generated_tenant_id := uuid_generate_v4();
        INSERT INTO tenant (id, name, owner_id)
        VALUES (
            generated_tenant_id,
            COALESCE(NULLIF(workspace_row.name, ''), 'Research OS Tenant'),
            workspace_row.owner_id
        )
        ON CONFLICT (id) DO NOTHING;

        UPDATE workspace
        SET tenant_id = generated_tenant_id,
            updated_at = NOW()
        WHERE id = workspace_row.id
          AND tenant_id IS NULL;
    END LOOP;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_workspace_tenant'
    ) THEN
        ALTER TABLE workspace
            ADD CONSTRAINT fk_workspace_tenant
            FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_workspace_tenant ON workspace(tenant_id);

CREATE TABLE IF NOT EXISTS workspace_member (
    workspace_id UUID NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id),
    CONSTRAINT valid_workspace_member_role
        CHECK (role IN ('owner', 'admin', 'member', 'viewer'))
);

INSERT INTO workspace_member (workspace_id, user_id, role)
SELECT w.id, w.owner_id, 'owner'
FROM workspace w
WHERE w.owner_id IS NOT NULL
ON CONFLICT (workspace_id, user_id) DO UPDATE
SET role = CASE
    WHEN workspace_member.role = 'owner' THEN workspace_member.role
    ELSE EXCLUDED.role
END;

INSERT INTO workspace_member (workspace_id, user_id, role)
SELECT u.workspace_id, u.id, 'member'
FROM app_user u
WHERE u.workspace_id IS NOT NULL
ON CONFLICT (workspace_id, user_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_workspace_member_user ON workspace_member(user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_member_role ON workspace_member(workspace_id, role);

ALTER TABLE research_project ADD COLUMN IF NOT EXISTS workspace_id UUID;
UPDATE research_project p
SET workspace_id = u.workspace_id
FROM app_user u
WHERE p.workspace_id IS NULL
  AND p.owner_user_id = u.id
  AND u.workspace_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_research_project_workspace'
    ) THEN
        ALTER TABLE research_project
            ADD CONSTRAINT fk_research_project_workspace
            FOREIGN KEY (workspace_id) REFERENCES workspace(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_research_project_workspace ON research_project(workspace_id);

ALTER TABLE remote_host ADD COLUMN IF NOT EXISTS workspace_id UUID;
UPDATE remote_host rh
SET workspace_id = u.workspace_id
FROM app_user u
WHERE rh.workspace_id IS NULL
  AND rh.owner_user_id = u.id
  AND u.workspace_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_remote_host_workspace'
    ) THEN
        ALTER TABLE remote_host
            ADD CONSTRAINT fk_remote_host_workspace
            FOREIGN KEY (workspace_id) REFERENCES workspace(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_remote_host_workspace_status ON remote_host(workspace_id, status);

ALTER TABLE terminal_session ADD COLUMN IF NOT EXISTS workspace_id UUID;
UPDATE terminal_session ts
SET workspace_id = rp.workspace_id
FROM research_project rp
WHERE ts.workspace_id IS NULL
  AND ts.project_id = rp.id
  AND rp.workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_terminal_session_workspace ON terminal_session(workspace_id);

ALTER TABLE code_artifact ADD COLUMN IF NOT EXISTS workspace_id UUID;
UPDATE code_artifact ca
SET workspace_id = rp.workspace_id
FROM research_project rp
WHERE ca.workspace_id IS NULL
  AND ca.project_id = rp.id
  AND rp.workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_code_artifact_workspace ON code_artifact(workspace_id);
