DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    SELECT conname
      INTO constraint_name
      FROM pg_constraint
     WHERE conrelid = 'mission_change_logs'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%reason_type%'
     LIMIT 1;

    IF constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE mission_change_logs DROP CONSTRAINT %I',
            constraint_name
        );
    END IF;

    ALTER TABLE mission_change_logs
    ADD CONSTRAINT mission_change_logs_reason_type_check
    CHECK (
        reason_type IN (
            'too_easy',
            'too_hard',
            'dislike',
            'cant_do',
            'just_change',
            'onboarding_auto_replace',
            'personalized_change',
            'generated_change'
        )
    );
END $$;

DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    SELECT conname
      INTO constraint_name
      FROM pg_constraint
     WHERE conrelid = 'mission_ui_actions'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%action_type%'
     LIMIT 1;

    IF constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE mission_ui_actions DROP CONSTRAINT %I',
            constraint_name
        );
    END IF;

    ALTER TABLE mission_ui_actions
    ADD CONSTRAINT mission_ui_actions_action_type_check
    CHECK (
        action_type IN (
            'mission_change_reason',
            'mission_dislike_confirm',
            'mission_change_method',
            'awaiting_replacement_mission'
        )
    );
END $$;
