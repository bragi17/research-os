ALTER TABLE run_event ADD COLUMN IF NOT EXISTS trace_id TEXT;
CREATE INDEX IF NOT EXISTS idx_run_event_trace ON run_event(trace_id) WHERE trace_id IS NOT NULL;
