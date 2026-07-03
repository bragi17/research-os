-- Topic Work Phase Artifacts
-- Idempotent additive migration for single-topic multi-phase research workspaces.

CREATE TABLE IF NOT EXISTS research_work (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL,
    created_by UUID NOT NULL,
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    active_phase TEXT,
    root_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    project_id UUID REFERENCES research_project(id) ON DELETE SET NULL,
    budget_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_research_work_status CHECK (status IN ('active', 'archived', 'deleted')),
    CONSTRAINT valid_research_work_phase CHECK (active_phase IS NULL OR active_phase IN ('atlas', 'frontier', 'divergent'))
);

CREATE INDEX IF NOT EXISTS idx_research_work_workspace_updated
    ON research_work(workspace_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_work_project
    ON research_work(project_id);

CREATE TABLE IF NOT EXISTS phase_execution (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    work_id UUID NOT NULL REFERENCES research_work(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    execution_kind TEXT NOT NULL DEFAULT 'standard',
    status TEXT NOT NULL DEFAULT 'queued',
    backing_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_bundle_id UUID REFERENCES context_bundle(id) ON DELETE SET NULL,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_phase_execution_phase CHECK (phase IN ('atlas', 'frontier', 'divergent')),
    CONSTRAINT valid_phase_execution_kind CHECK (execution_kind IN ('standard', 'validation')),
    CONSTRAINT valid_phase_execution_status CHECK (status IN ('queued', 'running', 'paused', 'failed', 'completed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_phase_execution_work_phase_created
    ON phase_execution(work_id, phase, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_phase_execution_backing_run
    ON phase_execution(backing_run_id);

CREATE TABLE IF NOT EXISTS artifact_card (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    work_id UUID NOT NULL REFERENCES research_work(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    selection_state TEXT NOT NULL DEFAULT 'unselected',
    source_execution_id UUID REFERENCES phase_execution(id) ON DELETE SET NULL,
    source_card_ids UUID[] DEFAULT '{}',
    created_by UUID,
    updated_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_artifact_card_phase CHECK (phase IN ('atlas', 'frontier', 'divergent')),
    CONSTRAINT valid_artifact_card_status CHECK (status IN ('active', 'archived', 'deleted')),
    CONSTRAINT valid_artifact_card_selection CHECK (selection_state IN ('unselected', 'selected', 'used'))
);

CREATE INDEX IF NOT EXISTS idx_artifact_card_work_phase
    ON artifact_card(work_id, phase, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_card_type
    ON artifact_card(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifact_card_selected
    ON artifact_card(work_id, selection_state);

CREATE TABLE IF NOT EXISTS artifact_revision (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    artifact_card_id UUID NOT NULL REFERENCES artifact_card(id) ON DELETE CASCADE,
    revision_no INT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    edit_source TEXT NOT NULL DEFAULT 'user',
    edited_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_artifact_revision_source CHECK (edit_source IN ('ai', 'user', 'system')),
    UNIQUE(artifact_card_id, revision_no)
);

CREATE TABLE IF NOT EXISTS phase_input_selection (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    work_id UUID NOT NULL REFERENCES research_work(id) ON DELETE CASCADE,
    target_phase TEXT NOT NULL,
    source_card_ids UUID[] NOT NULL DEFAULT '{}',
    manual_input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_phase_input_target CHECK (target_phase IN ('atlas', 'frontier', 'divergent'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_phase_input_selection_unique
    ON phase_input_selection(work_id, target_phase);
