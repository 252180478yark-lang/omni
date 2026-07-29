-- Creator-learning integrity follow-ups.
--
-- 088 is already present in the deployed migration ledger.  Keep this as a
-- separate migration so its checksum remains stable while tightening the
-- database-side admission checks introduced by that migration.

-- A template trial may only persist media when all three immutable records
-- agree: selected application, adopted script, and script_template_sources.
-- The service checks this before calling a provider; this trigger repeats it
-- at the final asset write so a direct SQL/API caller cannot bypass lineage.
CREATE OR REPLACE FUNCTION pipeline.guard_template_trial_asset()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    approved BOOLEAN;
    app_ok BOOLEAN;
    script_ok BOOLEAN;
    application_template UUID;
    application_version INTEGER;
    application_hash TEXT;
    application_snapshot JSONB;
BEGIN
    IF NEW.generation_purpose <> 'template_trial' THEN
        RETURN NEW;
    END IF;

    -- An approval is usable only for the gate's configured lifetime.  A
    -- previously approved but expired gate must never authorize a later
    -- provider render or asset insert.
    SELECT gate.decision = 'approved'
           AND gate.created_at + (gate.timeout_seconds * INTERVAL '1 second') > NOW()
      INTO approved
      FROM mcp.human_gates gate
     WHERE gate.id = NEW.generation_approval_gate_id;
    IF approved IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'template_trial_requires_unexpired_approved_human_gate'
            USING ERRCODE = '23514';
    END IF;

    SELECT application.template_id,
           application.template_version,
           application.snapshot_hash,
           application.template_snapshot,
           application.status IN ('trial_authorized', 'trial_generated')
             AND template.status = 'adopted'
             AND template.version = application.template_version
      INTO application_template,
           application_version,
           application_hash,
           application_snapshot,
           app_ok
      FROM content_studio.template_applications application
      JOIN content_studio.prompt_templates template ON template.id = application.template_id
     WHERE application.id = NEW.template_application_id;
    IF app_ok IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'template_trial_application_not_authorized'
            USING ERRCODE = '23514';
    END IF;

    -- The authorization snapshot itself is an immutable hand-off between the
    -- pre-provider service check and this asset insert.  Bind every target
    -- identifier to the row being written instead of treating any versioned
    -- JSON blob as sufficient.
    IF NEW.generation_authorization_snapshot ->> 'schema_version'
           IS DISTINCT FROM 'template_trial_authorization.v1'
       OR NEW.generation_authorization_snapshot ->> 'application_id'
           IS DISTINCT FROM NEW.template_application_id::text
       OR NEW.generation_authorization_snapshot ->> 'script_id'
           IS DISTINCT FROM NEW.script_id::text
       OR NEW.generation_authorization_snapshot ->> 'approval_gate_id'
           IS DISTINCT FROM NEW.generation_approval_gate_id::text
       OR NEW.generation_authorization_snapshot ->> 'template_id'
           IS DISTINCT FROM application_template::text
       OR NEW.generation_authorization_snapshot ->> 'template_version'
           IS DISTINCT FROM application_version::text
       OR NEW.generation_authorization_snapshot ->> 'snapshot_hash'
           IS DISTINCT FROM application_hash THEN
        RAISE EXCEPTION 'template_trial_authorization_snapshot_mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT script.status = 'adopted'
       AND script.template_application_id = NEW.template_application_id
       AND EXISTS (
           SELECT 1
             FROM pipeline.script_template_sources source_link
            WHERE source_link.script_id = script.id
              AND source_link.template_id = application_template
              AND source_link.application_id = NEW.template_application_id
              AND source_link.template_version = application_version
              AND source_link.snapshot_hash = application_hash
              AND source_link.template_snapshot = application_snapshot
       )
      INTO script_ok
      FROM pipeline.scripts script
     WHERE script.id = NEW.script_id;
    IF script_ok IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'template_trial_requires_matching_script_template_source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
