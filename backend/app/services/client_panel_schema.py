"""DDL panelu klienta (0630) — jedno źródło dla migracji i ``entrypoint.sh``.

Panel to strona całej rekrutacji pod linkiem z CV, bez logowania
(``docs/claude/klienci/panel-klienta-pod-linkiem.md``). Domyślnie wyłączony.

- ``client_panels``: jeden wiersz na rekrutację; w bazie tylko skrót tokenu.
- ``client_panel_candidates``: identyfikator osoby widoczny w linku zamiast
  ``candidate_id``, ukrycie i dowody odrzucone przez Delivery Leada.
- ``client_panel_requests``: pytania, prośby o rozmowę, „nie pasuje”, zmiany
  wymagań. Kaskada po kandydacie, bo treść mówi o tej osobie.
- ``client_panel_views``: dziennik wejść, bez surowego IP; retencja 180 dni
  w ``tasks/queue_retention.py``.
"""

REQUEST_KINDS = ("question", "interview", "not_fit", "requirements_change")
REQUEST_STATUSES = ("open", "answered", "closed")
VIEW_ACTIONS = ("open", "candidate", "requirement", "tab", "file")

TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS client_panels (
        id SERIAL PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        enabled BOOLEAN NOT NULL DEFAULT FALSE,
        show_rate BOOLEAN NOT NULL DEFAULT TRUE,
        show_other_candidates BOOLEAN NOT NULL DEFAULT TRUE,
        allow_actions BOOLEAN NOT NULL DEFAULT TRUE,
        expires_at TIMESTAMPTZ NULL,
        token_nonce VARCHAR(32) NULL,
        token_sha256 VARCHAR(64) NULL,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_client_panels_job UNIQUE (job_id)
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_panels_token "
    "ON client_panels (token_sha256) WHERE token_sha256 IS NOT NULL",
    """CREATE TABLE IF NOT EXISTS client_panel_candidates (
        id SERIAL PRIMARY KEY,
        panel_id INTEGER NOT NULL REFERENCES client_panels(id) ON DELETE CASCADE,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        public_id VARCHAR(16) NOT NULL,
        hidden BOOLEAN NOT NULL DEFAULT FALSE,
        rejected_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        shared_document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_client_panel_candidates_pair UNIQUE (panel_id, candidate_id),
        CONSTRAINT uq_client_panel_candidates_public UNIQUE (public_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_panel_candidates_candidate "
    "ON client_panel_candidates (candidate_id)",
    """CREATE TABLE IF NOT EXISTS client_panel_requests (
        id SERIAL PRIMARY KEY,
        panel_id INTEGER NOT NULL REFERENCES client_panels(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE CASCADE,
        kind VARCHAR(24) NOT NULL,
        author_name VARCHAR(120) NOT NULL,
        author_email VARCHAR(255) NOT NULL,
        body VARCHAR(2000) NULL,
        reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
        slot_request_id INTEGER NULL
            REFERENCES client_interview_slot_requests(id) ON DELETE SET NULL,
        status VARCHAR(12) NOT NULL DEFAULT 'open',
        answer VARCHAR(4000) NULL,
        answered_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        answered_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_client_panel_requests_kind CHECK (
            kind IN ('question', 'interview', 'not_fit', 'requirements_change')
        ),
        CONSTRAINT ck_client_panel_requests_status CHECK (
            status IN ('open', 'answered', 'closed')
        )
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_panel_requests_panel_created "
    "ON client_panel_requests (panel_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_client_panel_requests_job_status "
    "ON client_panel_requests (job_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_client_panel_requests_candidate "
    "ON client_panel_requests (candidate_id)",
    """CREATE TABLE IF NOT EXISTS client_panel_views (
        id BIGSERIAL PRIMARY KEY,
        panel_id INTEGER NOT NULL REFERENCES client_panels(id) ON DELETE CASCADE,
        candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE CASCADE,
        action VARCHAR(12) NOT NULL,
        detail VARCHAR(120) NULL,
        ip_hash VARCHAR(64) NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_client_panel_views_action CHECK (
            action IN ('open', 'candidate', 'requirement', 'tab', 'file')
        )
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_panel_views_panel_created "
    "ON client_panel_views (panel_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_client_panel_views_created "
    "ON client_panel_views (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_client_panel_views_candidate "
    "ON client_panel_views (candidate_id)",
)

DOWNGRADE_DDL = (
    "DROP TABLE IF EXISTS client_panel_views",
    "DROP TABLE IF EXISTS client_panel_requests",
    "DROP TABLE IF EXISTS client_panel_candidates",
    "DROP TABLE IF EXISTS client_panels",
)
