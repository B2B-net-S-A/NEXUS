\set ON_ERROR_STOP on

-- P0 operator artifact: quarantine the retired synthetic bootstrap administrator.
-- Run only from an authenticated, private PostgreSQL session after the patched
-- backend image is live. This file contains no credentials and is safe to keep
-- in source control. It preserves the user id and historical foreign keys.

BEGIN;

DO $quarantine$
DECLARE
    original_email CONSTANT text := 'claude-admin@b2bnet.pl';
    quarantine_pattern CONSTANT text := '^quarantined\+claude-admin-[0-9]+@invalid\.local$';
    original_count integer;
    quarantine_count integer;
    target_user users%ROWTYPE;
    quarantine_email text;
    changed_count integer;
BEGIN
    SELECT count(*)
      INTO original_count
      FROM users
     WHERE lower(email) = original_email;

    SELECT count(*)
      INTO quarantine_count
      FROM users
     WHERE email ~ quarantine_pattern;

    IF original_count + quarantine_count <> 1 THEN
        RAISE EXCEPTION
            'Expected exactly one bootstrap/quarantine account, found original=% quarantine=%',
            original_count,
            quarantine_count;
    END IF;

    SELECT *
      INTO STRICT target_user
      FROM users
     WHERE lower(email) = original_email
        OR email ~ quarantine_pattern
     FOR UPDATE;

    quarantine_email := format(
        'quarantined+claude-admin-%s@invalid.local',
        target_user.id
    );

    UPDATE users
       SET email = quarantine_email,
           password_hash = NULL,
           is_active = false,
           role = 'user'::userrole,
           roles = '["user"]'::jsonb,
           email_verified = false,
           force_password_change = true,
           force_password_change_at = now(),
           oauth_provider = NULL,
           external_id = NULL,
           azure_oid = NULL,
           microsoft_upn = NULL,
           aad_group_ids = '[]'::jsonb,
           updated_at = now()
     WHERE id = target_user.id;

    GET DIAGNOSTICS changed_count = ROW_COUNT;
    IF changed_count <> 1 THEN
        RAISE EXCEPTION 'Quarantine update changed % rows instead of 1', changed_count;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM users
         WHERE id = target_user.id
           AND (
               email <> quarantine_email
               OR is_active
               OR password_hash IS NOT NULL
               OR role <> 'user'::userrole
               OR roles <> '["user"]'::jsonb
               OR oauth_provider IS NOT NULL
               OR azure_oid IS NOT NULL
           )
    ) THEN
        RAISE EXCEPTION 'Post-quarantine invariant failed for user id %', target_user.id;
    END IF;

    INSERT INTO activities (
        entity_type,
        entity_id,
        action,
        details,
        user_id,
        external_source,
        external_id,
        created_at,
        updated_at
    )
    VALUES (
        'user',
        target_user.id,
        'security_bootstrap_account_quarantined',
        jsonb_build_object(
            'incident', 'P0-2026-07-13-bootstrap-admin',
            'original_email', original_email,
            'quarantine_email', quarantine_email,
            'preserved_user_id', target_user.id
        ),
        NULL,
        'security_incident',
        'P0-2026-07-13-bootstrap-admin-quarantine',
        now(),
        now()
    )
    ON CONFLICT (external_source, external_id)
        WHERE external_id IS NOT NULL
        DO NOTHING;

    RAISE NOTICE 'Bootstrap account id % is quarantined as %',
        target_user.id,
        quarantine_email;
END
$quarantine$;

COMMIT;
