"""Jeden formularz screeningu — SQL migracji 0424 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0424_screening_form_versions.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony). Decyzje Artura
D1–D10 z 07.10.2026 (makieta https://claude.ai/artifact/TNGomEmwM6ehsbdPDSaaBi).

* ``screening_form_versions`` — historia formularza pary (kandydat,
  rekrutacja): migawka arkusza, pól karty rekomendacji i stawki kandydata po
  każdej realnej zmianie, z listą zmian „przed → po”. Przywrócenie i cofnięcie
  zapisują NOWĄ wersję — nic nie znika z historii. ``fix_requested`` i ``meta``
  czekają na prośbę Delivery Leada o poprawki (PR 2), bez drugiej migracji.
  Tabela trzyma wartości (także narodowość) — czytają ją wyłącznie ludzie
  (strażnik w ``test_recommendation_card_ai_privacy.py``).
* CHECK źródła zmiany stawki przyjmuje ``screening``
  (``candidate_rate_change_schema.source_constraint_ddl``).
* Udostępnianie karty Championa klientowi zniknęło (D2): wszystkie tokeny
  dostają ``revoked`` — publiczny odczyt i tak odpowiada już 410.
"""

from __future__ import annotations

from app.services.candidate_rate_change_schema import source_constraint_ddl

ACTIONS = ("baseline", "external", "save", "restore", "undo", "fix_requested")
SOURCES = ("form", "note_import")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS screening_form_versions ("
    "id SERIAL PRIMARY KEY, "
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "version_no INTEGER NOT NULL, "
    "process_id INTEGER NULL REFERENCES recruitment_processes(id) ON DELETE SET NULL, "
    "stage_id INTEGER NULL REFERENCES candidate_stages(id) ON DELETE SET NULL, "
    "note_id INTEGER NULL REFERENCES notes(id) ON DELETE SET NULL, "
    "created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "attempt_no INTEGER NULL, "
    "action VARCHAR(20) NOT NULL, "
    "source VARCHAR(20) NOT NULL DEFAULT 'form', "
    "restored_from_version INTEGER NULL, "
    "snapshot JSONB NOT NULL, "
    "changes JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "meta JSONB NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT uq_screening_form_versions_pair_no "
    "UNIQUE (candidate_id, job_id, version_no), "
    "CONSTRAINT ck_screening_form_versions_version_no CHECK (version_no > 0), "
    f"CONSTRAINT ck_screening_form_versions_action CHECK (action IN ({_in(ACTIONS)})), "
    f"CONSTRAINT ck_screening_form_versions_source CHECK (source IN ({_in(SOURCES)})))",
    "CREATE INDEX IF NOT EXISTS ix_screening_form_versions_job "
    "ON screening_form_versions (job_id)",
)

CONSTRAINT_DDL = (source_constraint_ddl(),)

# D2: linki do karty Championa dla klienta przestają działać. Idempotentne —
# kolejny start nic nie znajdzie, a nowych tokenów nikt już nie wystawi.
DATA_DDL = (
    "UPDATE champion_card_share_tokens SET revoked = true WHERE revoked = false",
)

ALL_DDL = TABLE_DDL + CONSTRAINT_DDL + DATA_DDL
