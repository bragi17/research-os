-- Submission gate reports that require independent audit artifacts.
ALTER TABLE submission_package
    ADD COLUMN IF NOT EXISTS paper_claim_audit_report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS adversarial_audit_report_json JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'submission_package_paper_claim_audit_object_check'
    ) THEN
        ALTER TABLE submission_package
            ADD CONSTRAINT submission_package_paper_claim_audit_object_check
            CHECK (jsonb_typeof(paper_claim_audit_report_json) = 'object');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'submission_package_adversarial_audit_object_check'
    ) THEN
        ALTER TABLE submission_package
            ADD CONSTRAINT submission_package_adversarial_audit_object_check
            CHECK (jsonb_typeof(adversarial_audit_report_json) = 'object');
    END IF;
END $$;
