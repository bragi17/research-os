-- Jury and deduplication fields for generated idea cards.
ALTER TABLE idea_card
    ADD COLUMN IF NOT EXISTS dedup_key TEXT,
    ADD COLUMN IF NOT EXISTS novelty_verdict TEXT NOT NULL DEFAULT 'unclear',
    ADD COLUMN IF NOT EXISTS quality_verdict TEXT NOT NULL DEFAULT 'hold',
    ADD COLUMN IF NOT EXISTS closest_prior_work JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS strongest_objection TEXT,
    ADD COLUMN IF NOT EXISTS required_validation TEXT[] NOT NULL DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS jury_model TEXT,
    ADD COLUMN IF NOT EXISTS jury_trace_id TEXT,
    ADD COLUMN IF NOT EXISTS jury_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS prior_art_details JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE idea_card
    ALTER COLUMN novelty_verdict SET DEFAULT 'unclear',
    ALTER COLUMN quality_verdict SET DEFAULT 'hold',
    ALTER COLUMN closest_prior_work SET DEFAULT '[]'::jsonb,
    ALTER COLUMN required_validation SET DEFAULT '{}'::text[],
    ALTER COLUMN jury_status SET DEFAULT 'pending',
    ALTER COLUMN prior_art_details SET DEFAULT '[]'::jsonb;

UPDATE idea_card
SET novelty_verdict = 'unclear'
WHERE novelty_verdict IS NULL;

UPDATE idea_card
SET quality_verdict = 'hold'
WHERE quality_verdict IS NULL;

UPDATE idea_card
SET closest_prior_work = '[]'::jsonb
WHERE closest_prior_work IS NULL;

UPDATE idea_card
SET required_validation = '{}'::text[]
WHERE required_validation IS NULL;

UPDATE idea_card
SET jury_status = 'pending'
WHERE jury_status IS NULL;

UPDATE idea_card
SET prior_art_details = '[]'::jsonb
WHERE prior_art_details IS NULL;

ALTER TABLE idea_card
    ALTER COLUMN novelty_verdict SET NOT NULL,
    ALTER COLUMN quality_verdict SET NOT NULL,
    ALTER COLUMN closest_prior_work SET NOT NULL,
    ALTER COLUMN required_validation SET NOT NULL,
    ALTER COLUMN jury_status SET NOT NULL,
    ALTER COLUMN prior_art_details SET NOT NULL;

UPDATE idea_card
SET dedup_key = concat_ws(
    '-',
    NULLIF(
        trim(
            BOTH '-' FROM regexp_replace(
                lower(COALESCE(NULLIF(title, ''), id::text)),
                '[^a-z0-9]+',
                '-',
                'g'
            )
        ),
        ''
    ),
    id::text
)
WHERE dedup_key IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'idea_card'::regclass
            AND conname = 'idea_card_novelty_verdict_check'
    ) THEN
        ALTER TABLE idea_card
            ADD CONSTRAINT idea_card_novelty_verdict_check
            CHECK (novelty_verdict IN ('novel', 'incremental', 'duplicate', 'unclear'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'idea_card'::regclass
            AND conname = 'idea_card_quality_verdict_check'
    ) THEN
        ALTER TABLE idea_card
            ADD CONSTRAINT idea_card_quality_verdict_check
            CHECK (quality_verdict IN ('pursue', 'hold', 'reject'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'idea_card'::regclass
            AND conname = 'idea_card_jury_status_check'
    ) THEN
        ALTER TABLE idea_card
            ADD CONSTRAINT idea_card_jury_status_check
            CHECK (jury_status IN ('pending', 'reviewed', 'error'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'idea_card'::regclass
            AND conname = 'idea_card_closest_prior_work_array_check'
    ) THEN
        ALTER TABLE idea_card
            ADD CONSTRAINT idea_card_closest_prior_work_array_check
            CHECK (jsonb_typeof(closest_prior_work) = 'array');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'idea_card'::regclass
            AND conname = 'idea_card_prior_art_details_array_check'
    ) THEN
        ALTER TABLE idea_card
            ADD CONSTRAINT idea_card_prior_art_details_array_check
            CHECK (jsonb_typeof(prior_art_details) = 'array');
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_idea_card_run_dedup_key
    ON idea_card(run_id, dedup_key)
    WHERE dedup_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_idea_card_quality_verdict
    ON idea_card(quality_verdict);
CREATE INDEX IF NOT EXISTS idx_idea_card_novelty_verdict
    ON idea_card(novelty_verdict);
