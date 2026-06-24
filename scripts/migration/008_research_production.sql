-- Automated research production durable schema
-- Adds project, experiment, coding-agent, execution, claim, writing, and terminal tables.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS research_project (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL CHECK (btrim(title) <> ''),
    description TEXT,
    primary_topic TEXT NOT NULL CHECK (btrim(primary_topic) <> ''),
    status TEXT NOT NULL DEFAULT 'active',
    owner_user_id UUID,
    default_library_pool_ids UUID[] NOT NULL DEFAULT '{}',
    default_workspace_path TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT research_project_status_check
        CHECK (status IN ('active', 'paused', 'archived', 'completed')),
    CONSTRAINT research_project_metadata_object_check
        CHECK (jsonb_typeof(metadata_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_research_project_status ON research_project(status);
CREATE INDEX IF NOT EXISTS idx_research_project_owner ON research_project(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_research_project_created ON research_project(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_project_topic_fts
    ON research_project USING GIN (to_tsvector('english', primary_topic));

CREATE TABLE IF NOT EXISTS project_query_pack (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    source_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    topic TEXT,
    query_pack_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT project_query_pack_object_check
        CHECK (jsonb_typeof(query_pack_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_project_query_pack_project ON project_query_pack(project_id);
CREATE INDEX IF NOT EXISTS idx_project_query_pack_run ON project_query_pack(source_run_id);

CREATE TABLE IF NOT EXISTS novelty_report (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES research_project(id) ON DELETE CASCADE,
    idea_id UUID,
    search_queries_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    competing_work_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    claim_overlap_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    novelty_verdict TEXT NOT NULL DEFAULT 'unclear',
    confidence NUMERIC(4,3),
    reviewer_model TEXT,
    human_decision TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT novelty_report_verdict_check
        CHECK (novelty_verdict IN ('novel', 'incremental', 'duplicate', 'unclear')),
    CONSTRAINT novelty_report_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT novelty_report_search_queries_array_check
        CHECK (jsonb_typeof(search_queries_json) = 'array'),
    CONSTRAINT novelty_report_competing_work_array_check
        CHECK (jsonb_typeof(competing_work_json) = 'array'),
    CONSTRAINT novelty_report_claim_overlap_object_check
        CHECK (jsonb_typeof(claim_overlap_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_novelty_report_project ON novelty_report(project_id);
CREATE INDEX IF NOT EXISTS idx_novelty_report_idea ON novelty_report(idea_id);
CREATE INDEX IF NOT EXISTS idx_novelty_report_verdict ON novelty_report(novelty_verdict);

CREATE TABLE IF NOT EXISTS experiment_plan (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    idea_id UUID,
    source_run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    title TEXT NOT NULL CHECK (btrim(title) <> ''),
    hypothesis TEXT NOT NULL CHECK (btrim(hypothesis) <> ''),
    method_plan_markdown TEXT NOT NULL DEFAULT '',
    implementation_plan_markdown TEXT NOT NULL DEFAULT '',
    datasets_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    baselines_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ablation_plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_outputs_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    acceptance_criteria_json JSONB NOT NULL DEFAULT '{
        "sanity_checks": [],
        "minimum_artifacts": [],
        "metric_thresholds": [],
        "negative_controls": [],
        "reproducibility_requirements": [],
        "claim_support_requirements": []
    }'::jsonb,
    risk_register_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT experiment_plan_status_check
        CHECK (status IN (
            'draft',
            'reviewed',
            'accepted',
            'implementing',
            'code_ready',
            'sanity_running',
            'sanity_passed',
            'full_running',
            'analyzing',
            'claim_checked',
            'completed',
            'rejected',
            'code_failed',
            'sanity_failed',
            'experiment_research',
            'manifest_revision',
            'job_failed',
            'stopped',
            'insufficient_evidence',
            'writing_with_limited_claims'
        )),
    CONSTRAINT experiment_plan_datasets_object_check
        CHECK (jsonb_typeof(datasets_json) = 'object'),
    CONSTRAINT experiment_plan_baselines_object_check
        CHECK (jsonb_typeof(baselines_json) = 'object'),
    CONSTRAINT experiment_plan_metrics_object_check
        CHECK (jsonb_typeof(metrics_json) = 'object'),
    CONSTRAINT experiment_plan_ablation_object_check
        CHECK (jsonb_typeof(ablation_plan_json) = 'object'),
    CONSTRAINT experiment_plan_resources_object_check
        CHECK (jsonb_typeof(resource_plan_json) = 'object'),
    CONSTRAINT experiment_plan_outputs_object_check
        CHECK (jsonb_typeof(expected_outputs_json) = 'object'),
    CONSTRAINT experiment_plan_acceptance_object_check
        CHECK (jsonb_typeof(acceptance_criteria_json) = 'object'),
    CONSTRAINT experiment_plan_acceptance_required_keys_check
        CHECK (
            acceptance_criteria_json ? 'sanity_checks'
            AND acceptance_criteria_json ? 'minimum_artifacts'
            AND acceptance_criteria_json ? 'metric_thresholds'
            AND acceptance_criteria_json ? 'negative_controls'
            AND acceptance_criteria_json ? 'reproducibility_requirements'
            AND acceptance_criteria_json ? 'claim_support_requirements'
        ),
    CONSTRAINT experiment_plan_risk_object_check
        CHECK (jsonb_typeof(risk_register_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_experiment_plan_project ON experiment_plan(project_id);
CREATE INDEX IF NOT EXISTS idx_experiment_plan_run ON experiment_plan(source_run_id);
CREATE INDEX IF NOT EXISTS idx_experiment_plan_status ON experiment_plan(status);
CREATE INDEX IF NOT EXISTS idx_experiment_plan_created ON experiment_plan(created_at DESC);

CREATE TABLE IF NOT EXISTS coding_task (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    experiment_plan_id UUID REFERENCES experiment_plan(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'codex',
    provider_session_id TEXT,
    workspace_path TEXT,
    thread_name TEXT,
    system_prompt TEXT,
    user_prompt TEXT NOT NULL CHECK (btrim(user_prompt) <> ''),
    model TEXT,
    timeout_sec INT,
    semantic_inactivity_timeout_sec INT,
    env_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    mcp_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    thinking_level TEXT,
    prompt_hash TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    failure_reason TEXT,
    failure_detail TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms BIGINT,
    token_usage_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    extra_args JSONB NOT NULL DEFAULT '[]'::jsonb,
    custom_args JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT coding_task_provider_check
        CHECK (provider IN ('codex', 'claude', 'copilot', 'cursor', 'opencode')),
    CONSTRAINT coding_task_status_check
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'timeout', 'cancelled', 'blocked')),
    CONSTRAINT coding_task_timeout_check
        CHECK (timeout_sec IS NULL OR timeout_sec >= 1),
    CONSTRAINT coding_task_semantic_inactivity_timeout_check
        CHECK (semantic_inactivity_timeout_sec IS NULL OR semantic_inactivity_timeout_sec >= 1),
    CONSTRAINT coding_task_duration_check
        CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT coding_task_env_object_check
        CHECK (jsonb_typeof(env_json) = 'object'),
    CONSTRAINT coding_task_mcp_config_object_check
        CHECK (jsonb_typeof(mcp_config_json) = 'object'),
    CONSTRAINT coding_task_token_usage_object_check
        CHECK (jsonb_typeof(token_usage_json) = 'object'),
    CONSTRAINT coding_task_extra_args_array_check
        CHECK (jsonb_typeof(extra_args) = 'array'),
    CONSTRAINT coding_task_custom_args_array_check
        CHECK (jsonb_typeof(custom_args) = 'array'),
    CONSTRAINT coding_task_metadata_object_check
        CHECK (jsonb_typeof(metadata_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_coding_task_project ON coding_task(project_id);
CREATE INDEX IF NOT EXISTS idx_coding_task_run ON coding_task(run_id);
CREATE INDEX IF NOT EXISTS idx_coding_task_plan ON coding_task(experiment_plan_id);
CREATE INDEX IF NOT EXISTS idx_coding_task_status ON coding_task(status);
CREATE INDEX IF NOT EXISTS idx_coding_task_created ON coding_task(created_at DESC);

CREATE TABLE IF NOT EXISTS coding_event (
    id BIGSERIAL PRIMARY KEY,
    coding_task_id UUID NOT NULL REFERENCES coding_task(id) ON DELETE CASCADE,
    run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    content TEXT,
    tool TEXT,
    call_id TEXT,
    input_json JSONB,
    output_text TEXT,
    status_text TEXT,
    level TEXT,
    provider_raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT coding_event_type_check
        CHECK (event_type IN ('text', 'thinking', 'tool_use', 'tool_result', 'status', 'error', 'log')),
    CONSTRAINT coding_event_level_check
        CHECK (level IS NULL OR level IN ('debug', 'info', 'warning', 'error', 'critical')),
    CONSTRAINT coding_event_input_object_check
        CHECK (input_json IS NULL OR jsonb_typeof(input_json) = 'object'),
    CONSTRAINT coding_event_raw_object_check
        CHECK (jsonb_typeof(provider_raw_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_coding_event_task_created ON coding_event(coding_task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_coding_event_run_created ON coding_event(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_coding_event_type ON coding_event(event_type);

CREATE TABLE IF NOT EXISTS code_artifact (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coding_task_id UUID REFERENCES coding_task(id) ON DELETE SET NULL,
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    experiment_plan_id UUID REFERENCES experiment_plan(id) ON DELETE SET NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL CHECK (btrim(path) <> ''),
    content_hash TEXT,
    summary TEXT,
    validation_status TEXT NOT NULL DEFAULT 'pending',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT code_artifact_type_check
        CHECK (artifact_type IN ('diff', 'file_snapshot', 'manifest', 'test_output', 'review_report')),
    CONSTRAINT code_artifact_validation_status_check
        CHECK (validation_status IN ('pending', 'passed', 'failed')),
    CONSTRAINT code_artifact_metadata_object_check
        CHECK (jsonb_typeof(metadata_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_code_artifact_task ON code_artifact(coding_task_id);
CREATE INDEX IF NOT EXISTS idx_code_artifact_project ON code_artifact(project_id);
CREATE INDEX IF NOT EXISTS idx_code_artifact_plan ON code_artifact(experiment_plan_id);
CREATE INDEX IF NOT EXISTS idx_code_artifact_type ON code_artifact(artifact_type);

CREATE TABLE IF NOT EXISTS experiment_manifest (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_plan_id UUID NOT NULL REFERENCES experiment_plan(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    manifest_version TEXT NOT NULL DEFAULT '1',
    generated_by_coding_task_id UUID REFERENCES coding_task(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT experiment_manifest_status_check
        CHECK (status IN ('draft', 'accepted', 'running', 'completed', 'failed')),
    CONSTRAINT experiment_manifest_json_object_check
        CHECK (jsonb_typeof(manifest_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_experiment_manifest_plan ON experiment_manifest(experiment_plan_id);
CREATE INDEX IF NOT EXISTS idx_experiment_manifest_project ON experiment_manifest(project_id);
CREATE INDEX IF NOT EXISTS idx_experiment_manifest_status ON experiment_manifest(status);

CREATE TABLE IF NOT EXISTS remote_host (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    owner_user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    host TEXT NOT NULL CHECK (btrim(host) <> ''),
    port INT NOT NULL DEFAULT 22,
    username TEXT,
    auth_type TEXT NOT NULL DEFAULT 'agent',
    key_ref TEXT,
    default_workdir TEXT,
    default_env_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    capabilities_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'unknown',
    last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT remote_host_port_check
        CHECK (port > 0 AND port <= 65535),
    CONSTRAINT remote_host_auth_type_check
        CHECK (auth_type IN ('key', 'agent', 'password_ref')),
    CONSTRAINT remote_host_status_check
        CHECK (status IN ('unknown', 'reachable', 'unreachable', 'disabled')),
    CONSTRAINT remote_host_default_env_object_check
        CHECK (jsonb_typeof(default_env_json) = 'object'),
    CONSTRAINT remote_host_capabilities_object_check
        CHECK (jsonb_typeof(capabilities_json) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_remote_host_owner_name ON remote_host(owner_user_id, lower(name));
CREATE INDEX IF NOT EXISTS idx_remote_host_owner_status ON remote_host(owner_user_id, status);

CREATE TABLE IF NOT EXISTS experiment_job (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manifest_id UUID NOT NULL REFERENCES experiment_manifest(id) ON DELETE CASCADE,
    experiment_plan_id UUID NOT NULL REFERENCES experiment_plan(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    phase_name TEXT NOT NULL CHECK (btrim(phase_name) <> ''),
    job_name TEXT NOT NULL CHECK (btrim(job_name) <> ''),
    executor_type TEXT NOT NULL DEFAULT 'local',
    remote_host_id UUID REFERENCES remote_host(id) ON DELETE SET NULL,
    cmd TEXT NOT NULL CHECK (btrim(cmd) <> ''),
    cwd TEXT NOT NULL DEFAULT '.',
    pid INT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INT NOT NULL DEFAULT 1,
    max_attempts INT NOT NULL DEFAULT 1,
    expected_outputs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    stdout_log_path TEXT,
    stderr_log_path TEXT,
    artifact_dir TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT experiment_job_executor_type_check
        CHECK (executor_type IN ('local', 'ssh')),
    CONSTRAINT experiment_job_status_check
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'failed_oom', 'timeout', 'stuck', 'cancelled')),
    CONSTRAINT experiment_job_attempt_check
        CHECK (attempt >= 1 AND max_attempts >= 1 AND attempt <= max_attempts),
    CONSTRAINT experiment_job_expected_outputs_array_check
        CHECK (jsonb_typeof(expected_outputs_json) = 'array'),
    CONSTRAINT experiment_job_metrics_object_check
        CHECK (jsonb_typeof(metrics_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_experiment_job_manifest ON experiment_job(manifest_id);
CREATE INDEX IF NOT EXISTS idx_experiment_job_plan ON experiment_job(experiment_plan_id);
CREATE INDEX IF NOT EXISTS idx_experiment_job_project ON experiment_job(project_id);
CREATE INDEX IF NOT EXISTS idx_experiment_job_status ON experiment_job(status);
CREATE INDEX IF NOT EXISTS idx_experiment_job_remote_host ON experiment_job(remote_host_id);
CREATE INDEX IF NOT EXISTS idx_experiment_job_heartbeat ON experiment_job(last_heartbeat_at);

CREATE TABLE IF NOT EXISTS result_observation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_job_id UUID NOT NULL REFERENCES experiment_job(id) ON DELETE CASCADE,
    experiment_plan_id UUID NOT NULL REFERENCES experiment_plan(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    observation_type TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_artifact_path TEXT,
    confidence NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT result_observation_type_check
        CHECK (observation_type IN ('metric', 'table', 'figure', 'log_signal', 'anomaly', 'failure')),
    CONSTRAINT result_observation_payload_object_check
        CHECK (jsonb_typeof(payload_json) = 'object'),
    CONSTRAINT result_observation_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE INDEX IF NOT EXISTS idx_result_observation_job ON result_observation(experiment_job_id);
CREATE INDEX IF NOT EXISTS idx_result_observation_plan ON result_observation(experiment_plan_id);
CREATE INDEX IF NOT EXISTS idx_result_observation_project ON result_observation(project_id);
CREATE INDEX IF NOT EXISTS idx_result_observation_type ON result_observation(observation_type);

CREATE TABLE IF NOT EXISTS claim_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    experiment_plan_id UUID REFERENCES experiment_plan(id) ON DELETE SET NULL,
    claim_text TEXT NOT NULL CHECK (btrim(claim_text) <> ''),
    claim_type TEXT NOT NULL DEFAULT 'main',
    status TEXT NOT NULL DEFAULT 'proposed',
    support_level NUMERIC(4,3),
    evidence_summary TEXT,
    reviewer_model TEXT,
    human_decision TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT claim_ledger_type_check
        CHECK (claim_type IN ('main', 'ablation', 'limitation', 'negative', 'comparison')),
    CONSTRAINT claim_ledger_status_check
        CHECK (status IN ('proposed', 'supported', 'partially_supported', 'unsupported', 'contradicted', 'needs_more_evidence')),
    CONSTRAINT claim_ledger_support_level_check
        CHECK (support_level IS NULL OR (support_level >= 0 AND support_level <= 1))
);

CREATE INDEX IF NOT EXISTS idx_claim_ledger_project ON claim_ledger(project_id);
CREATE INDEX IF NOT EXISTS idx_claim_ledger_plan ON claim_ledger(experiment_plan_id);
CREATE INDEX IF NOT EXISTS idx_claim_ledger_status ON claim_ledger(status);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claim_ledger(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id UUID,
    quote_or_metric TEXT,
    artifact_path TEXT,
    support_relation TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT claim_evidence_source_type_check
        CHECK (source_type IN ('experiment_job', 'artifact', 'paper', 'chunk', 'manual_note')),
    CONSTRAINT claim_evidence_support_relation_check
        CHECK (support_relation IN ('supports', 'weakly_supports', 'contradicts', 'contextualizes'))
);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim ON claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_source ON claim_evidence(source_type, source_id);

CREATE TABLE IF NOT EXISTS manuscript_package (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_project(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK (btrim(title) <> ''),
    venue_target TEXT,
    paper_dir TEXT,
    status TEXT NOT NULL DEFAULT 'outline',
    claim_ledger_snapshot_id UUID,
    bib_snapshot_id UUID,
    artifact_snapshot_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT manuscript_package_status_check
        CHECK (status IN ('outline', 'drafting', 'reviewing', 'revising', 'ready_to_submit', 'submitted', 'rejected', 'accepted', 'resubmitting'))
);

CREATE INDEX IF NOT EXISTS idx_manuscript_package_project ON manuscript_package(project_id);
CREATE INDEX IF NOT EXISTS idx_manuscript_package_status ON manuscript_package(status);

CREATE TABLE IF NOT EXISTS submission_package (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manuscript_package_id UUID NOT NULL REFERENCES manuscript_package(id) ON DELETE CASCADE,
    venue TEXT NOT NULL CHECK (btrim(venue) <> ''),
    deadline TIMESTAMPTZ,
    submission_dir TEXT,
    checklist_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    anonymity_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    compile_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    claim_audit_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    citation_audit_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_provenance_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'preparing',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT submission_package_status_check
        CHECK (status IN ('preparing', 'gated', 'ready', 'submitted', 'failed')),
    CONSTRAINT submission_package_checklist_object_check
        CHECK (jsonb_typeof(checklist_json) = 'object'),
    CONSTRAINT submission_package_anonymity_object_check
        CHECK (jsonb_typeof(anonymity_report_json) = 'object'),
    CONSTRAINT submission_package_compile_object_check
        CHECK (jsonb_typeof(compile_report_json) = 'object'),
    CONSTRAINT submission_package_claim_audit_object_check
        CHECK (jsonb_typeof(claim_audit_report_json) = 'object'),
    CONSTRAINT submission_package_citation_audit_object_check
        CHECK (jsonb_typeof(citation_audit_report_json) = 'object'),
    CONSTRAINT submission_package_artifact_provenance_object_check
        CHECK (jsonb_typeof(artifact_provenance_report_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_submission_package_manuscript ON submission_package(manuscript_package_id);
CREATE INDEX IF NOT EXISTS idx_submission_package_status ON submission_package(status);
CREATE INDEX IF NOT EXISTS idx_submission_package_deadline ON submission_package(deadline);

CREATE TABLE IF NOT EXISTS terminal_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES research_project(id) ON DELETE CASCADE,
    run_id UUID REFERENCES research_run(id) ON DELETE SET NULL,
    experiment_job_id UUID REFERENCES experiment_job(id) ON DELETE SET NULL,
    session_type TEXT NOT NULL DEFAULT 'local',
    remote_host_id UUID REFERENCES remote_host(id) ON DELETE SET NULL,
    cwd TEXT,
    shell TEXT,
    status TEXT NOT NULL DEFAULT 'opening',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,

    CONSTRAINT terminal_session_type_check
        CHECK (session_type IN ('local', 'ssh')),
    CONSTRAINT terminal_session_status_check
        CHECK (status IN ('opening', 'open', 'closed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_terminal_session_project ON terminal_session(project_id);
CREATE INDEX IF NOT EXISTS idx_terminal_session_run ON terminal_session(run_id);
CREATE INDEX IF NOT EXISTS idx_terminal_session_job ON terminal_session(experiment_job_id);
CREATE INDEX IF NOT EXISTS idx_terminal_session_status ON terminal_session(status);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    trigger_table TEXT;
    trigger_name TEXT;
BEGIN
    FOREACH trigger_table IN ARRAY ARRAY[
        'research_project',
        'project_query_pack',
        'experiment_plan',
        'coding_task',
        'experiment_manifest',
        'remote_host',
        'experiment_job',
        'claim_ledger',
        'manuscript_package',
        'submission_package'
    ]
    LOOP
        trigger_name := 'update_' || trigger_table || '_updated';
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = trigger_name
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION update_updated_at()',
                trigger_name,
                trigger_table
            );
        END IF;
    END LOOP;
END;
$$;
