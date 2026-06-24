-- Project-level memory ledger for research artifacts and decisions.
ALTER TABLE research_run
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES research_project(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_research_run_project
    ON research_run(project_id);

CREATE TABLE IF NOT EXISTS research_memory_item (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    source_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    item_type TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    title TEXT,
    status TEXT,
    summary_text TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT research_memory_item_type_check
        CHECK (item_type IN ('paper', 'idea', 'failed_idea', 'claim', 'gap', 'experiment')),
    CONSTRAINT research_memory_item_payload_object_check
        CHECK (jsonb_typeof(payload_json) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_research_memory_item_project_type_key
    ON research_memory_item(project_id, item_type, stable_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_research_memory_item_project_id
    ON research_memory_item(project_id, id);
CREATE INDEX IF NOT EXISTS idx_research_memory_item_project_type
    ON research_memory_item(project_id, item_type);
CREATE INDEX IF NOT EXISTS idx_research_memory_item_source_run
    ON research_memory_item(source_run_id);

CREATE TABLE IF NOT EXISTS research_memory_edge (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    source_item_id UUID NOT NULL REFERENCES research_memory_item(id) ON DELETE CASCADE,
    target_item_id UUID NOT NULL REFERENCES research_memory_item(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    evidence TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT research_memory_edge_type_check
        CHECK (edge_type IN ('supports', 'contradicts', 'derived_from', 'tests', 'duplicates')),
    CONSTRAINT research_memory_edge_payload_object_check
        CHECK (jsonb_typeof(payload_json) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_research_memory_edge_unique
    ON research_memory_edge(source_item_id, target_item_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_research_memory_edge_project
    ON research_memory_edge(project_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'research_memory_edge_source_project_fk'
    ) THEN
        ALTER TABLE research_memory_edge
            ADD CONSTRAINT research_memory_edge_source_project_fk
            FOREIGN KEY (project_id, source_item_id)
            REFERENCES research_memory_item(project_id, id)
            ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'research_memory_edge_target_project_fk'
    ) THEN
        ALTER TABLE research_memory_edge
            ADD CONSTRAINT research_memory_edge_target_project_fk
            FOREIGN KEY (project_id, target_item_id)
            REFERENCES research_memory_item(project_id, id)
            ON DELETE CASCADE;
    END IF;
END $$;
