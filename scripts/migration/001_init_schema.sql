-- Research OS Database Schema v1.0
-- Based on 02_Architecture_and_Data_Model.md

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================
-- Core Run Management Tables
-- ============================================

-- Research Run: A complete research task execution instance
CREATE TABLE research_run (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL,
    created_by UUID NOT NULL,
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    goal_type TEXT NOT NULL DEFAULT 'survey_plus_innovations',
    autonomy_mode TEXT NOT NULL DEFAULT 'default_autonomous',
    budget_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_step TEXT,
    progress_pct NUMERIC(5,2) DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_status CHECK (status IN ('queued', 'running', 'paused', 'failed', 'completed', 'cancelled'))
);

CREATE INDEX idx_research_run_status ON research_run(status);
CREATE INDEX idx_research_run_workspace ON research_run(workspace_id);
CREATE INDEX idx_research_run_created ON research_run(created_at DESC);

-- Run Step: Individual recoverable, retryable node within a run
CREATE TABLE run_step (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    step_name TEXT NOT NULL,
    step_order INT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INT NOT NULL DEFAULT 1,
    input_json JSONB NOT NULL,
    output_json JSONB,
    error_code TEXT,
    error_message TEXT,
    idempotency_key TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_step_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped'))
);

CREATE UNIQUE INDEX idx_run_step_idempotency ON run_step(run_id, idempotency_key);
CREATE INDEX idx_run_step_run ON run_step(run_id);

-- Run Event: Event stream for observability
CREATE TABLE run_event (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_run_event_run_created ON run_event(run_id, created_at DESC);

-- Run Constraint: User-defined constraints for a run
CREATE TABLE run_constraint (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    constraint_type TEXT NOT NULL,
    constraint_value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- Paper Management Tables
-- ============================================

-- Paper: Canonical paper record
CREATE TABLE paper (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    doi TEXT,
    arxiv_id TEXT,
    openalex_id TEXT,
    s2_paper_id TEXT,
    s2_corpus_id BIGINT,
    publication_year INT,
    venue TEXT,
    abstract TEXT,
    source_trust_score NUMERIC(4,3),
    is_oa BOOLEAN DEFAULT FALSE,
    oa_url TEXT,
    is_retracted BOOLEAN DEFAULT FALSE,
    primary_language TEXT DEFAULT 'en',
    has_fulltext BOOLEAN DEFAULT FALSE,
    fulltext_status TEXT NOT NULL DEFAULT 'unknown',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_paper_doi ON paper((COALESCE(doi, ''))) WHERE doi IS NOT NULL;
CREATE INDEX idx_paper_norm_title ON paper(normalized_title);
CREATE INDEX idx_paper_year ON paper(publication_year);
CREATE INDEX idx_paper_s2_id ON paper(s2_paper_id);

-- Paper Version: Different versions of a paper (preprint, published, etc.)
CREATE TABLE paper_version (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    version_type TEXT NOT NULL,
    source_url TEXT,
    sha256 TEXT,
    object_key TEXT,
    parse_status TEXT NOT NULL DEFAULT 'pending',
    license_text TEXT,
    page_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_version_type CHECK (version_type IN ('preprint', 'published', 'revision', 'author_version'))
);

CREATE INDEX idx_paper_version_paper ON paper_version(paper_id);

-- Paper Source Record: Raw data from external sources
CREATE TABLE paper_source_record (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    raw_payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(source_name, source_record_id)
);

CREATE INDEX idx_paper_source_paper ON paper_source_record(paper_id);

-- ============================================
-- Chunk & Embedding Tables
-- ============================================

-- Chunk: Text segments for RAG retrieval
CREATE TABLE chunk (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    paper_version_id UUID REFERENCES paper_version(id) ON DELETE CASCADE,
    parent_chunk_id UUID REFERENCES chunk(id) ON DELETE CASCADE,
    chunk_type TEXT NOT NULL,
    section_path TEXT[],
    paragraph_index INT,
    page_start INT,
    page_end INT,
    char_start INT,
    char_end INT,
    text TEXT NOT NULL,
    token_count INT,
    tsv TSVECTOR,
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_chunk_type CHECK (chunk_type IN ('abstract', 'section', 'paragraph', 'table_caption', 'figure_caption', 'reference_context', 'limitation', 'future_work'))
);

-- Add embedding column (3072 dimensions for large models)
ALTER TABLE chunk ADD COLUMN IF NOT EXISTS embedding VECTOR(3072);

CREATE INDEX idx_chunk_paper ON chunk(paper_id);
CREATE INDEX idx_chunk_section ON chunk USING GIN(section_path);
CREATE INDEX idx_chunk_tsv ON chunk USING GIN(tsv);
CREATE INDEX idx_chunk_embedding ON chunk USING HNSW (embedding vector_cosine_ops);

-- Chunk Embedding: Separate table for multiple embedding models
CREATE TABLE chunk_embedding (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id UUID NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    embedding VECTOR(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(chunk_id, model_name)
);

-- ============================================
-- Claim & Evidence Tables
-- ============================================

-- Claim: Structured assertions extracted from papers
CREATE TABLE claim (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
    claim_type TEXT NOT NULL,
    subject_text TEXT,
    predicate_text TEXT,
    object_text TEXT,
    normalized_subject TEXT,
    normalized_object TEXT,
    conditions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    claim_text TEXT NOT NULL,
    polarity TEXT,
    confidence NUMERIC(4,3),
    extraction_model TEXT,
    evidence_quote TEXT,
    evidence_page_start INT,
    evidence_page_end INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_claim_type CHECK (claim_type IN ('problem_statement', 'method', 'result', 'comparison', 'limitation', 'assumption', 'future_work', 'dataset', 'metric', 'failure_mode', 'threat_to_validity')),
    CONSTRAINT valid_polarity CHECK (polarity IN ('positive', 'negative', 'neutral', NULL))
);

CREATE INDEX idx_claim_paper ON claim(paper_id);
CREATE INDEX idx_claim_type ON claim(claim_type);
CREATE INDEX idx_claim_subject ON claim(normalized_subject);

-- Claim Relation: Relationships between claims (supports, contradicts, etc.)
CREATE TABLE claim_relation (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    src_claim_id UUID NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    dst_claim_id UUID NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    confidence NUMERIC(4,3),
    rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_claim_relation CHECK (relation_type IN ('supports', 'contradicts', 'refines', 'extends', 'duplicates'))
);

CREATE INDEX idx_claim_relation_src ON claim_relation(src_claim_id);
CREATE INDEX idx_claim_relation_dst ON claim_relation(dst_claim_id);

-- ============================================
-- Paper Relation Tables (Citation Graph)
-- ============================================

-- Paper Relation: Citation and similarity relationships
CREATE TABLE paper_relation (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    src_paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    dst_paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    context_chunk_id UUID REFERENCES chunk(id) ON DELETE SET NULL,
    confidence NUMERIC(4,3),
    source_name TEXT,
    -- S2 enhanced fields
    is_influential BOOLEAN,
    intents JSONB,
    contexts JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_paper_relation CHECK (relation_type IN ('cites', 'cited_by', 'related', 'recommended', 'same_author', 'same_topic'))
);

CREATE INDEX idx_paper_relation_src ON paper_relation(src_paper_id);
CREATE INDEX idx_paper_relation_dst ON paper_relation(dst_paper_id);
CREATE INDEX idx_paper_relation_type ON paper_relation(relation_type);

-- ============================================
-- Hypothesis & Innovation Tables
-- ============================================

-- Hypothesis: Candidate innovation points
CREATE TABLE hypothesis (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    type TEXT NOT NULL,
    novelty_score NUMERIC(4,3),
    feasibility_score NUMERIC(4,3),
    evidence_score NUMERIC(4,3),
    risk_score NUMERIC(4,3),
    status TEXT NOT NULL DEFAULT 'candidate',
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_hypothesis_type CHECK (type IN ('bridge', 'assumption_relaxation', 'metric_gap', 'transfer', 'negative_result_exploitation')),
    CONSTRAINT valid_hypothesis_status CHECK (status IN ('candidate', 'verified', 'rejected', 'needs_more_evidence'))
);

CREATE INDEX idx_hypothesis_run ON hypothesis(run_id);

-- Hypothesis Evidence: Supporting/opposing evidence for hypotheses
CREATE TABLE hypothesis_evidence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    hypothesis_id UUID NOT NULL REFERENCES hypothesis(id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    paper_id UUID REFERENCES paper(id) ON DELETE SET NULL,
    claim_id UUID REFERENCES claim(id) ON DELETE SET NULL,
    chunk_id UUID REFERENCES chunk(id) ON DELETE SET NULL,
    note TEXT,
    weight NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_evidence_type CHECK (evidence_type IN ('support', 'oppose', 'prior_art', 'missing_prerequisite'))
);

CREATE INDEX idx_hypothesis_evidence_hyp ON hypothesis_evidence(hypothesis_id);

-- ============================================
-- Topic Cluster Tables
-- ============================================

-- Topic Cluster: Research topic clusters
CREATE TABLE topic_cluster (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    description TEXT,
    representative_paper_ids UUID[] DEFAULT '{}',
    cluster_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Paper Cluster Membership: Paper-to-cluster membership
CREATE TABLE paper_cluster_membership (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    cluster_id UUID NOT NULL REFERENCES topic_cluster(id) ON DELETE CASCADE,
    membership_score NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(paper_id, cluster_id)
);

-- ============================================
-- S2 Provider Cache Tables
-- ============================================

-- S2 Paper Cache: Cached data from Semantic Scholar
CREATE TABLE s2_paper_cache (
    s2_paper_id TEXT PRIMARY KEY,
    s2_corpus_id BIGINT,
    doi TEXT,
    title TEXT,
    abstract TEXT,
    year INT,
    publication_date DATE,
    venue TEXT,
    publication_venue JSONB,
    authors JSONB,
    citation_count INT,
    influential_citation_count INT,
    reference_count INT,
    is_open_access BOOLEAN,
    open_access_pdf JSONB,
    fields_of_study JSONB,
    s2_fields_of_study JSONB,
    tldr JSONB,
    specter_v2 VECTOR(768),
    external_ids JSONB,
    raw_payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

-- S2 Citation Edges: Citation relationships with context
CREATE TABLE s2_citation_edges (
    edge_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    src_internal_paper_uid UUID REFERENCES paper(id) ON DELETE CASCADE,
    dst_internal_paper_uid UUID REFERENCES paper(id) ON DELETE CASCADE,
    src_s2_paper_id TEXT,
    dst_s2_paper_id TEXT,
    src_s2_corpus_id BIGINT,
    dst_s2_corpus_id BIGINT,
    edge_kind TEXT NOT NULL,
    is_influential BOOLEAN,
    intents JSONB,
    contexts JSONB,
    provider TEXT NOT NULL DEFAULT 'semantic_scholar',
    source_endpoint TEXT NOT NULL,
    raw_payload JSONB,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_edge_kind CHECK (edge_kind IN ('reference', 'citation'))
);

CREATE INDEX idx_s2_citation_edges_src ON s2_citation_edges(src_internal_paper_uid);
CREATE INDEX idx_s2_citation_edges_dst ON s2_citation_edges(dst_internal_paper_uid);

-- S2 Query Cache: Cache for API responses
CREATE TABLE s2_query_cache (
    cache_key TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    query_params JSONB NOT NULL,
    request_body JSONB,
    response_payload JSONB NOT NULL,
    status_code INT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_seconds INT NOT NULL DEFAULT 86400
);

-- S2 Dataset Sync State: Track dataset synchronization
CREATE TABLE s2_dataset_sync_state (
    dataset_name TEXT PRIMARY KEY,
    current_release_id TEXT,
    last_sync_started_at TIMESTAMPTZ,
    last_sync_finished_at TIMESTAMPTZ,
    last_sync_status TEXT,
    last_error TEXT,
    meta JSONB
);

-- ============================================
-- Provider Paper Identity
-- ============================================

CREATE TABLE provider_paper_identity (
    internal_paper_uid UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_paper_id TEXT,
    provider_corpus_id BIGINT,
    doi TEXT,
    arxiv_id TEXT,
    url TEXT,
    title_hash TEXT,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (internal_paper_uid, provider)
);

-- ============================================
-- Run Output Table
-- ============================================

CREATE TABLE run_output (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    output_type TEXT NOT NULL,
    format TEXT NOT NULL,
    content TEXT NOT NULL,
    object_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_run_output_run ON run_output(run_id);

-- ============================================
-- Functions & Triggers
-- ============================================

-- Update timestamp trigger function
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply update triggers
CREATE TRIGGER update_research_run_updated
    BEFORE UPDATE ON research_run
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_paper_updated
    BEFORE UPDATE ON paper
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Full-text search trigger for chunks
CREATE OR REPLACE FUNCTION update_chunk_tsv()
RETURNS TRIGGER AS $$
BEGIN
    NEW.tsv = to_tsvector('english', COALESCE(NEW.text, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_chunk_tsv_trigger
    BEFORE INSERT OR UPDATE ON chunk
    FOR EACH ROW EXECUTE FUNCTION update_chunk_tsv();
