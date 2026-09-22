"""0339: schemat strony kariery ma lustro w entrypoincie.

Prod alembic bywa osierocony — ``entrypoint.sh`` JEST wdrożeniem. Model
deklaruje nowe kolumny linku i dwie tabele, a ``/api/health/deep`` sonduje
tabele, więc brak lustra = 503 na prodzie przy zielonym CI.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (BACKEND / "alembic" / "versions" / "0339_career_links.py").read_text()


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_columns_tables_and_constraints_are_mirrored():
    flat = _collapse(ENTRYPOINT)
    for needle in (
        "ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'job'",
        "ADD COLUMN IF NOT EXISTS slug VARCHAR(64) NULL",
        "ADD COLUMN IF NOT EXISTS visit_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE candidate_invite_links ALTER COLUMN job_id DROP NOT NULL",
        "ALTER TABLE candidate_invite_links ALTER COLUMN expires_at DROP NOT NULL",
        "CHECK (kind IN ('job', 'recruiter'))",
        "(kind = 'recruiter' AND job_id IS NULL AND slug IS NOT NULL)",
        "CREATE TABLE IF NOT EXISTS job_public_profiles",
        "CREATE TABLE IF NOT EXISTS candidate_consents",
        "candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE CASCADE",
        "CHECK ((candidate_id IS NOT NULL) <> (application_submission_id IS NOT NULL))",
        "ON candidate_invite_links (slug) WHERE slug IS NOT NULL",
        "WHERE kind = 'recruiter' AND revoked = false",
        "ADD VALUE IF NOT EXISTS 'job_public_description'",
        "SELECT 'job_public_description', TRUE, 0, ",
    ):
        assert needle in flat, needle


def test_every_named_object_in_the_migration_exists_in_the_entrypoint():
    names = set(re.findall(r"\b((?:uq|ux|ck|ix)_[a-z_]+)\b", MIGRATION))
    assert len(names) >= 6, names
    for name in names:
        assert name in ENTRYPOINT, name


def test_model_constraints_match_the_migration():
    from app.models.candidate_consent import CandidateConsent
    from app.models.invite_link import CandidateInviteLink

    declared = {
        c.name
        for model in (CandidateInviteLink, CandidateConsent)
        for c in model.__table__.constraints
        if c.name
    } | {i.name for i in CandidateInviteLink.__table__.indexes}
    for name in (
        "ck_candidate_invite_links_kind",
        "ck_candidate_invite_links_kind_shape",
        "ux_candidate_invite_links_slug",
        "ux_candidate_invite_links_one_recruiter_link",
        "ck_candidate_consents_one_subject",
        "ck_candidate_consents_kind",
    ):
        assert name in declared, name
        assert name in MIGRATION, name


def test_new_tables_are_probed_by_deep_health():
    main = (BACKEND / "app" / "main.py").read_text()
    assert '("job_public_profiles", JobPublicProfile)' in main
    assert '("candidate_consents", CandidateConsent)' in main


def test_migration_is_the_single_alembic_head():
    """Łańcuch bez rozgałęzienia — bez zaszywania numeru poprzednika.

    Poprzednia wersja pytała o konkretny `down_revision` i czerwieniła CI przy
    każdym przenumerowaniu po kolizji z migracją z maina.
    """
    revisions: dict[str, str | None] = {}
    for path in (BACKEND / "alembic" / "versions").glob("*.py"):
        text = path.read_text()
        rev = re.search(r'^revision\s*=\s*"([^"]+)"', text, re.M)
        down = re.search(r'^down_revision\s*=\s*"([^"]+)"', text, re.M)
        if rev:
            revisions[rev.group(1)] = down.group(1) if down else None
    ours = re.search(r'^revision\s*=\s*"([^"]+)"', MIGRATION, re.M).group(1)
    parent = revisions[ours]
    assert parent in revisions, f"{ours} wskazuje na nieistniejącą migrację {parent}"
    siblings = [r for r, d in revisions.items() if d == parent and r != ours]
    assert not siblings, f"dwie migracje na {parent}: {ours} i {siblings}"
