-- Paper verification records for search candidates and prior-art hits.
CREATE TABLE IF NOT EXISTS paper_verification (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    candidate_key TEXT NOT NULL,
    candidate_id TEXT,
    source TEXT,
    input_title TEXT,
    canonical_title TEXT,
    canonical_doi TEXT,
    canonical_arxiv_id TEXT,
    canonical_s2_id TEXT,
    canonical_openalex_id TEXT,
    verification_status TEXT NOT NULL DEFAULT 'verify_pending',
    verification_method TEXT NOT NULL DEFAULT 'none',
    verification_reason TEXT,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT paper_verification_status_check
        CHECK (verification_status IN ('verified', 'unverified', 'verify_pending', 'error')),
    CONSTRAINT paper_verification_raw_object_check
        CHECK (jsonb_typeof(raw_json) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_verification_run_key
    ON paper_verification(COALESCE(source_run_id, '00000000-0000-0000-0000-000000000000'::uuid), candidate_key);
CREATE INDEX IF NOT EXISTS idx_paper_verification_status ON paper_verification(verification_status);
CREATE INDEX IF NOT EXISTS idx_paper_verification_arxiv ON paper_verification(canonical_arxiv_id);
CREATE INDEX IF NOT EXISTS idx_paper_verification_doi ON paper_verification(canonical_doi);
