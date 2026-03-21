-- Paper Library tables (migration 005)
-- PostgreSQL data on vdb disk (/data/postgresql/16/main)
-- Vector dimension: 1024 (Tongyi text-embedding-v4)

CREATE TABLE IF NOT EXISTS library_paper (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES paper(id),
    source_run_id UUID REFERENCES research_run(id),
    status TEXT NOT NULL DEFAULT 'pending',
    field TEXT,
    sub_field TEXT,
    keywords TEXT[] DEFAULT '{}',
    datasets TEXT[] DEFAULT '{}',
    benchmarks TEXT[] DEFAULT '{}',
    methods TEXT[] DEFAULT '{}',
    innovation_points TEXT[] DEFAULT '{}',
    summary_json JSONB DEFAULT '{}',
    deep_analysis_json JSONB,
    architecture_figure_path TEXT,
    arxiv_id TEXT,
    doi TEXT,
    title TEXT NOT NULL,
    authors TEXT[] DEFAULT '{}',
    year INT,
    venue TEXT,
    citation_count INT DEFAULT 0,
    latex_source_path TEXT,
    compiled_pdf_path TEXT,
    project_tags TEXT[] DEFAULT '{}',
    is_manually_uploaded BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_library_paper_keywords ON library_paper USING GIN (keywords);
CREATE INDEX IF NOT EXISTS idx_library_paper_methods ON library_paper USING GIN (methods);
CREATE INDEX IF NOT EXISTS idx_library_paper_project_tags ON library_paper USING GIN (project_tags);
CREATE INDEX IF NOT EXISTS idx_library_paper_title_fts ON library_paper USING GIN (to_tsvector('english', title));
CREATE INDEX IF NOT EXISTS idx_library_paper_field ON library_paper (field, sub_field);
CREATE INDEX IF NOT EXISTS idx_library_paper_arxiv ON library_paper (arxiv_id) WHERE arxiv_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS library_chunk (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    library_paper_id UUID NOT NULL REFERENCES library_paper(id) ON DELETE CASCADE,
    section_type TEXT NOT NULL,
    paragraph_index INT NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    token_count INT DEFAULT 0,
    tags TEXT[] DEFAULT '{}',
    claim_type TEXT,
    embedding VECTOR(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_library_chunk_paper ON library_chunk (library_paper_id);
CREATE INDEX IF NOT EXISTS idx_library_chunk_tags ON library_chunk USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_library_chunk_embedding ON library_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_library_chunk_section ON library_chunk (section_type);
