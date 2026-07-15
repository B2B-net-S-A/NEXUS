"""Strip the legacy "[zatrudniony]" marker from candidate names.

Revision ID: 0165_strip_traffit_employed_marker
Revises: 0160_contract_document_type_order
Create Date: 2026-07-15

Traffit had no employment-status field, so recruiters flagged placed
consultants by stuffing "[zatrudniony]" into the candidate name/lastname. Nexus
derives employment properly (active contract / current_employment conflict /
hired pipeline stage — see app/api/candidates.py::_derive_employment), so the
marker is pure noise that also pollutes name search and CV headers.

This migration:
  1. Parks a durable, human-readable tag on candidates that carry the marker
     but have NO structured employment signal ("group B"). The Traffit sync
     never rewrites `tags`, and — now that the mapper strips the marker on
     import (same PR) — the name marker is their only remaining signal, which
     would otherwise be silently lost on their next sync. The tag keeps them
     visible and turns them into a cleanup worklist.
  2. Strips the marker from name/lastname for every affected row. Rows with a
     real employment signal stay flagged "U klienta" via that signal, so the
     badge/banner is unaffected.

Idempotent: re-running finds no marked names left, and the tag guard prevents
duplicates. Data-only cleanup, so downgrade is a no-op (the marker text cannot
be reconstructed).
"""

from alembic import op


revision = "0165_strip_traffit_employed_marker"
down_revision = "0160_contract_document_type_order"
branch_labels = None
depends_on = None


# Mirror of app/services/traffit/mappers.py::_EMPLOYMENT_MARKER_RE so the
# one-time backfill and the ongoing import strip stay in sync. Matches the
# bracketed / parenthesized / bare marker, any case, with adjacent separators.
# NOTE: a plain capturing group `(...)`, NOT `(?:...)` — alembic wraps
# op.execute() in SQLAlchemy text(), which reads the `:` in `(?:` as a bind
# parameter (`:ego`) and fails with "A value is required for bind parameter".
_MARKER = r"[[(]?\s*zatrudnion(ego|ej|ych|ymi|[yaieą])?\s*[])]?"

# Candidate currently employed at one of our clients — mirrors
# app/api/candidates.py::_at_client_predicate (active contract OR active
# current_employment conflict OR latest pipeline stage == hired).
_HAS_EMPLOYMENT_SIGNAL = """
    EXISTS (
        SELECT 1 FROM contracts c
        WHERE c.candidate_id = cand.id AND c.status::text = 'active'
    )
    OR EXISTS (
        SELECT 1 FROM candidate_conflicts cc
        WHERE cc.candidate_id = cand.id
          AND cc.type::text = 'current_employment'
          AND cc.active
    )
    OR EXISTS (
        SELECT 1 FROM candidate_stages cs
        WHERE cs.candidate_id = cand.id
          AND cs.stage::text = 'hired'
          AND NOT EXISTS (
              SELECT 1 FROM candidate_stages later
              WHERE later.candidate_id = cs.candidate_id
                AND later.job_id = cs.job_id
                AND (later.moved_at, later.id) > (cs.moved_at, cs.id)
          )
    )
"""

_PARK_TAG = '["Traffit: oznaczony jako zatrudniony (do weryfikacji)"]'


def upgrade() -> None:
    # 1. Preserve group B (marked, no structured signal) before erasing the
    #    name marker they rely on. `tags` is untouched by the Traffit UPSERT,
    #    so the parked tag survives future syncs. Guarded on array-typed tags
    #    and against duplicate parking → idempotent.
    op.execute(
        f"""
        UPDATE candidates cand
        SET tags = COALESCE(cand.tags, '[]'::jsonb) || '{_PARK_TAG}'::jsonb
        WHERE (cand.name ILIKE '%zatrudnion%' OR cand.lastname ILIKE '%zatrudnion%')
          AND jsonb_typeof(COALESCE(cand.tags, '[]'::jsonb)) = 'array'
          AND NOT (COALESCE(cand.tags, '[]'::jsonb) @> '{_PARK_TAG}'::jsonb)
          AND NOT ({_HAS_EMPLOYMENT_SIGNAL})
        """
    )

    # 2. Strip the marker everywhere. Collapse leftover whitespace, trim
    #    dangling separators, and fall back to '?' when the field was nothing
    #    but the marker (mirrors the mapper's empty-name fallback).
    op.execute(
        rf"""
        UPDATE candidates cand
        SET name = COALESCE(NULLIF(btrim(regexp_replace(
                       regexp_replace(cand.name, '{_MARKER}', ' ', 'gi'),
                       '\s+', ' ', 'g'), ' -–,;'), ''), '?'),
            lastname = COALESCE(NULLIF(btrim(regexp_replace(
                       regexp_replace(cand.lastname, '{_MARKER}', ' ', 'gi'),
                       '\s+', ' ', 'g'), ' -–,;'), ''), '?')
        WHERE cand.name ILIKE '%zatrudnion%' OR cand.lastname ILIKE '%zatrudnion%'
        """
    )


def downgrade() -> None:
    # Data-only cleanup: the original marker text cannot be reconstructed.
    pass
