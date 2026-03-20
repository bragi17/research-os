-- Research OS v2 Multi-Mode Migration
-- Adds support for four research modes: atlas, frontier, divergent, review
-- Idempotent: safe to re-run

-- ============================================
-- New Table: research_domain
-- Research field hierarchy for domain-aware operations
-- ============================================
CREATE TABLE IF NOT EXISTS research_domain (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    aliases TEXT[] DEFAULT '{}',
    parent_domain_id UUID REFERENCES research_domain(id) ON DELETE SET NULL,
    description_short TEXT,
    description_detailed TEXT,
    keywords TEXT[] DEFAULT '{}',
    representative_venues TEXT[] DEFAULT '{}',
    representative_datasets TEXT[] DEFAULT '{}',
    representative_methods TEXT[] DEFAULT '{}',
    canonical_paper_ids UUID[] DEFAULT '{}',
    recent_frontier_paper_ids UUID[] DEFAULT '{}',
    prerequisite_domain_ids UUID[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- New Table: figure_asset
-- Extracted figures from papers
-- ============================================
CREATE TABLE IF NOT EXISTS figure_asset (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    source_type TEXT,
    page_no INT,
    caption TEXT,
    image_path TEXT,
    figure_type TEXT,
    related_section TEXT,
    license_note TEXT,
    extraction_confidence NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_figure_asset_paper ON figure_asset(paper_id);

-- ============================================
-- New Table: context_bundle
-- Inter-mode context passing between runs
-- (Created before reading_path/pain_point/idea_card
--  so that research_run ALTER can reference it)
-- ============================================
CREATE TABLE IF NOT EXISTS context_bundle (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    source_mode TEXT,
    summary_text TEXT,
    selected_paper_ids UUID[] DEFAULT '{}',
    cluster_ids UUID[] DEFAULT '{}',
    figure_ids UUID[] DEFAULT '{}',
    pain_point_ids UUID[] DEFAULT '{}',
    idea_card_ids UUID[] DEFAULT '{}',
    benchmark_data JSONB,
    mindmap_json JSONB,
    user_annotations JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- ALTER: research_run
-- Add multi-mode columns
-- ============================================
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'atlas';
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS parent_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL;
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS source_run_ids UUID[];
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS context_bundle_id UUID REFERENCES context_bundle(id) ON DELETE SET NULL;
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS output_bundle_id UUID REFERENCES context_bundle(id) ON DELETE SET NULL;
ALTER TABLE research_run ADD COLUMN IF NOT EXISTS current_stage TEXT;

-- ============================================
-- ALTER: topic_cluster
-- Add domain-aware and analysis columns
-- ============================================
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS domain_id UUID REFERENCES research_domain(id) ON DELETE SET NULL;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS entry_keywords TEXT[];
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS methods JSONB;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS datasets JSONB;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS metrics JSONB;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS pain_point_ids UUID[];
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS future_work_mentions JSONB;
ALTER TABLE topic_cluster ADD COLUMN IF NOT EXISTS coverage_score NUMERIC(4,3);

-- ============================================
-- New Table: reading_path
-- Mode A (Atlas) learning paths
-- ============================================
CREATE TABLE IF NOT EXISTS reading_path (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES research_domain(id) ON DELETE SET NULL,
    difficulty_level TEXT,
    ordered_units JSONB,
    estimated_hours NUMERIC,
    goal TEXT,
    generated_rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- New Table: pain_point
-- Mode B (Frontier) pain points
-- ============================================
CREATE TABLE IF NOT EXISTS pain_point (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    cluster_id UUID REFERENCES topic_cluster(id) ON DELETE SET NULL,
    statement TEXT NOT NULL,
    pain_type TEXT,
    supporting_paper_ids UUID[] DEFAULT '{}',
    counter_evidence_paper_ids UUID[] DEFAULT '{}',
    severity_score NUMERIC(4,3),
    novelty_potential NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pain_point_run ON pain_point(run_id);

-- ============================================
-- New Table: idea_card
-- Mode C (Divergent) innovation cards
-- ============================================
CREATE TABLE IF NOT EXISTS idea_card (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES research_run(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    problem_statement TEXT,
    source_pain_point_ids UUID[] DEFAULT '{}',
    borrowed_methods TEXT[] DEFAULT '{}',
    source_domains TEXT[] DEFAULT '{}',
    mechanism_of_transfer TEXT,
    expected_benefit TEXT,
    risks TEXT[] DEFAULT '{}',
    required_experiments TEXT[] DEFAULT '{}',
    prior_art_check_status TEXT DEFAULT 'pending',
    novelty_score NUMERIC(4,3),
    feasibility_score NUMERIC(4,3),
    status TEXT DEFAULT 'candidate',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_idea_card_run ON idea_card(run_id);

-- ============================================
-- Trigger: auto-update updated_at on research_domain
-- ============================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_research_domain_updated'
    ) THEN
        CREATE TRIGGER update_research_domain_updated
            BEFORE UPDATE ON research_domain
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    END IF;
END;
$$;
