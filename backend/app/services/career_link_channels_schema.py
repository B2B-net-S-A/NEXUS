"""Kanały linków w źródłach kandydatów: SQL migracji ``0641_career_link_channels``.

JEDNO źródło dla migracji i ``entrypoint.sh``. Decyzja Artura 02.11.2026: zgłoszenie
z linku leżało w kanale ``posting`` razem z ogłoszeniami z portali, więc raport
„Źródła kandydatów” nie umiał ich odróżnić. ``ENUM_DDL`` musi się wykonać poza
transakcją; ``BACKFILL_DDL`` jest idempotentny i przepina stare zdarzenia po
zgłoszeniu z tego samego momentu.
"""

ENUM_DDL = [
    "ALTER TYPE sourcechannel ADD VALUE IF NOT EXISTS 'career_link_general'",
    "ALTER TYPE sourcechannel ADD VALUE IF NOT EXISTS 'career_link_job'",
]

BACKFILL_DDL = [
    """
    UPDATE candidate_source_events e
    SET channel = (
        CASE WHEN a.details->>'link_kind' = 'recruiter'
             THEN 'career_link_general' ELSE 'career_link_job' END
    )::sourcechannel
    FROM activities a
    WHERE a.action = 'applied_via_invite'
      AND a.entity_type = 'candidate'
      AND a.entity_id = e.candidate_id
      AND e.channel = 'posting'
      AND e.captured_at BETWEEN a.created_at - INTERVAL '5 minutes'
                            AND a.created_at + INTERVAL '5 minutes'
    """,
]
