"""DDL próśb o warunki kandydata — JEDNO źródło dla migracji 0729 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``candidate_terms_requests``: jeden wiersz na mail po aplikacji (albo prośbę
rekrutera). Token powstaje dopiero przy wysyłce, a baza trzyma tylko jego
skrót. ``answers`` to ostatnia odpowiedź kandydata (formularz pokazuje ją przy
ponownym wejściu zamiast wartości z profilu, które mógł wpisać rekruter).
Reguła: ``docs/claude/kandydaci-wyszukiwanie/warunki-od-kandydata-formularz-po-aplikacji.md``.
"""

from __future__ import annotations

STATUSES: tuple[str, ...] = ("queued", "sent", "skipped", "failed")
ACTIONS: tuple[str, ...] = ("link", "thanks")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS candidate_terms_requests (
           id SERIAL PRIMARY KEY,
           candidate_id INTEGER NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
           job_id INTEGER NULL REFERENCES jobs (id) ON DELETE SET NULL,
           source VARCHAR(40) NOT NULL,
           ad_title VARCHAR(200) NULL,
           status VARCHAR(16) NOT NULL DEFAULT 'queued'
               CONSTRAINT ck_candidate_terms_requests_status CHECK (status IN ({_in(STATUSES)})),
           action VARCHAR(16) NULL
               CONSTRAINT ck_candidate_terms_requests_action CHECK (action IS NULL OR action IN ({_in(ACTIONS)})),
           skip_reason VARCHAR(40) NULL,
           missing JSONB NOT NULL DEFAULT '[]'::jsonb,
           token_sha256 VARCHAR(64) NULL,
           recruiter_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           applied_at TIMESTAMPTZ NOT NULL,
           queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           sent_at TIMESTAMPTZ NULL,
           expires_at TIMESTAMPTZ NULL,
           answered_at TIMESTAMPTZ NULL,
           answer_count INTEGER NOT NULL DEFAULT 0,
           answers JSONB NULL,
           opted_out_at TIMESTAMPTZ NULL
       )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_terms_requests_token
           ON candidate_terms_requests (token_sha256) WHERE token_sha256 IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_terms_requests_candidate
           ON candidate_terms_requests (candidate_id, sent_at DESC)""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_terms_requests_queue
           ON candidate_terms_requests (queued_at) WHERE status = 'queued'""",
]

DOWNGRADE_DDL: list[str] = ["DROP TABLE IF EXISTS candidate_terms_requests"]
