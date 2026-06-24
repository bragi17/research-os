-- Paper Library pools (migration 007)
-- First-class knowledge-base pools with many-to-many paper membership.

CREATE TABLE IF NOT EXISTS library_pool (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    kind TEXT NOT NULL DEFAULT 'custom',
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_library_pool_kind CHECK (kind IN ('default', 'unassigned', 'custom'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_library_pool_name_lower
    ON library_pool (LOWER(name));

CREATE UNIQUE INDEX IF NOT EXISTS idx_library_pool_system_kind
    ON library_pool (kind)
    WHERE kind IN ('default', 'unassigned');

CREATE TABLE IF NOT EXISTS library_pool_paper (
    pool_id UUID NOT NULL REFERENCES library_pool(id) ON DELETE CASCADE,
    library_paper_id UUID NOT NULL REFERENCES library_paper(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (pool_id, library_paper_id)
);

CREATE INDEX IF NOT EXISTS idx_library_pool_paper_pool
    ON library_pool_paper (pool_id);

CREATE INDEX IF NOT EXISTS idx_library_pool_paper_paper
    ON library_pool_paper (library_paper_id);

INSERT INTO library_pool (name, description, kind, is_system)
SELECT 'Default Library', 'Default pool for library papers', 'default', TRUE
WHERE NOT EXISTS (SELECT 1 FROM library_pool WHERE kind = 'default');

INSERT INTO library_pool (name, description, kind, is_system)
SELECT 'Unassigned', 'Papers without another pool membership', 'unassigned', TRUE
WHERE NOT EXISTS (SELECT 1 FROM library_pool WHERE kind = 'unassigned');

INSERT INTO library_pool_paper (pool_id, library_paper_id)
SELECT default_pool.id, lp.id
FROM library_paper lp
CROSS JOIN (
    SELECT id FROM library_pool WHERE kind = 'default' LIMIT 1
) default_pool
WHERE NOT EXISTS (
    SELECT 1
    FROM library_pool_paper lpp
    WHERE lpp.library_paper_id = lp.id
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_library_pool_updated'
    ) THEN
        CREATE TRIGGER update_library_pool_updated
            BEFORE UPDATE ON library_pool
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    END IF;
END;
$$;
