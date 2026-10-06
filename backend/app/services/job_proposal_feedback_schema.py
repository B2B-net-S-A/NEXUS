"""DDL propozycji: źródło „Z portalu” i powód „Pomiń” — JEDNO źródło dla
migracji 0405 i ``entrypoint.sh``.

Decyzje Artura 30.09.2026 (audyt ``docs/audits/2026-09-30/wyszukiwanie-kandydatow.md``):

- dopasowanie z integracji (skrypt JJIT/RocketJobs) trafia do „Do przejrzenia”
  jako propozycja ``job_board``, nigdy jako karta na tablicy;
- „Pomiń” wymaga powodu — bez niego nie wiemy, czy propozycje są złe, czy
  niewidziane (do 30.09 żadna z 57 nocnych propozycji nie miała decyzji).

Produkcyjny alembic bywa osierocony, więc siatka w ``entrypoint.sh`` jest
wdrożeniem równorzędnym z migracją — obie strony czytają listy stąd.
"""

from __future__ import annotations

SOURCES = (
    "full_base",
    "new_cv",
    "similar_projects",
    "recommendation",
    "marketplace",
    "reassign",
    "trainee",
    "job_board",
)
DISMISS_REASONS = (
    "missing_critical",
    "too_expensive",
    "location_office",
    "too_junior",
    "outdated_cv",
    "other",
)
DISMISS_NOTE_MAX = 500
# 0422 (07.10.2026): ``expired`` — propozycja nocnego przeglądu, której nowszy,
# kompletny przegląd tej rekrutacji już nie zaproponował. Wiersz zostaje
# (``request_allocation`` czyta istnienie ``full_base`` jako dowód przeglądu).
STATUSES = ("proposed", "dismissed", "added", "expired")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


SOURCE_CHECK_SQL = f"source IN ({_in(SOURCES)})"
STATUS_CHECK_SQL = f"status IN ({_in(STATUSES)})"
DISMISS_REASON_CHECK_SQL = (
    f"dismiss_reason IS NULL OR dismiss_reason IN ({_in(DISMISS_REASONS)})"
)

COLUMN_DDL: list[str] = [
    "ALTER TABLE job_proposals ADD COLUMN IF NOT EXISTS dismiss_reason VARCHAR(32) NULL",
    f"ALTER TABLE job_proposals ADD COLUMN IF NOT EXISTS dismiss_note "
    f"VARCHAR({DISMISS_NOTE_MAX}) NULL",
]

# DROP+ADD w jednym bloku — timeout zamka wycofuje oba, następny start ponawia.
CONSTRAINT_DDL: list[str] = [
    f"""DO $$ BEGIN
        ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_source;
        ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_source
            CHECK ({SOURCE_CHECK_SQL});
    END $$""",
    f"""DO $$ BEGIN
        ALTER TABLE job_proposals
            DROP CONSTRAINT IF EXISTS ck_job_proposals_dismiss_reason;
        ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_dismiss_reason
            CHECK ({DISMISS_REASON_CHECK_SQL});
    END $$""",
]

# 0422: status ``expired``. Osobna lista, bo 0405 czyta ``CONSTRAINT_DDL``.
STATUS_CONSTRAINT_DDL: list[str] = [
    f"""DO $$ BEGIN
        ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_status;
        ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_status
            CHECK ({STATUS_CHECK_SQL});
    END $$""",
]
