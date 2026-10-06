"""DDL propozycji: status „wygasła” i otwarcia skrzynki — JEDNO źródło dla
migracji 0422 i ``entrypoint.sh`` (audyt 06.10.2026).

- **R6:** zamknięcie rekrutacji wygasza jej otwarte propozycje (status
  ``expired``). Do tej daty 172 propozycje wisiały w zamkniętych rekrutacjach
  i liczyły się w skrótach. Ponowne otwarcie rekrutacji ich nie wskrzesza —
  nowe przeglądy dodają nowe osoby, stare zostają historią.
- **Telemetria skrzynki:** ``job_proposal_inbox_opens`` — jedno zdarzenie na
  (rekrutacja, osoba, dzień). Do 06.10 nie było wiadomo, czy ktokolwiek
  otwiera „Do przejrzenia” (0 pominięć w całej historii mogło znaczyć „nikt
  nie patrzy” albo „wszystko dobre”). Świadomie NIE ``match_impressions``:
  tam klucz to (przegląd, kandydat), a otwarcie skrzynki nie ma przeglądu.

Produkcyjny alembic bywa osierocony, więc siatka w ``entrypoint.sh`` jest
wdrożeniem równorzędnym z migracją — obie strony czytają listy stąd.
"""

from __future__ import annotations

STATUSES = ("proposed", "dismissed", "added", "expired")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


STATUS_CHECK_SQL = f"status IN ({_in(STATUSES)})"

# DROP+ADD w jednym bloku — timeout zamka wycofuje oba, następny start ponawia.
CONSTRAINT_DDL: list[str] = [
    f"""DO $$ BEGIN
        ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_status;
        ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_status
            CHECK ({STATUS_CHECK_SQL});
    END $$""",
]

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS job_proposal_inbox_opens (
        id BIGSERIAL PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        opened_on DATE NOT NULL,
        opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_job_proposal_inbox_opens_day
            UNIQUE (job_id, user_id, opened_on)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_job_proposal_inbox_opens_opened_on "
    "ON job_proposal_inbox_opens (opened_on)",
]
