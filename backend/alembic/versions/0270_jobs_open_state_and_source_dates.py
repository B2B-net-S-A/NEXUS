"""Rekrutacje: własna kolumna „otwartości" + prawdziwe daty ze źródła.

Trzy problemy, jedna migracja, bo dotyczą tej samej tabeli i tej samej decyzji
(hybryda z twardymi granicami: sync pisze do swoich kolumn, NEXUS do swoich).

**`opened_at`** — data OTWARCIA rekrutacji. `jobs.created_at` jest stemplowane
`NOW()` przez `_UPSERT_JOB`, czyli opisuje moment, w którym wiersz trafił do
NEXUSA, a nie moment, w którym rekrutacja ruszyła u klienta. Po migracji z maja
2026 daje to 3859 z 4229 rekrutacji „utworzonych" w jednym miesiącu i medianę
czasu realizacji równą ZERO dni. Traffit podaje prawdziwą datę w polu
`created_at` odpowiedzi `/recruitments/` — po prostu nigdy nie była mapowana.
`created_at` zostaje nietknięte (jest technicznie poprawne i sortuje listę);
prawda biznesowa idzie do osobnej kolumny, wzorem `candidate_stages.moved_at`
i `candidate_documents.uploaded_at`.

**`is_open`** — „czy MY aktywnie prowadzimy tę rekrutację". Do tej pory to
pytanie i pytanie „czy rekrutacja żyje u klienta" dzieliły jedną kolumnę
`status`, przez co odpowiedź na oba była zła: na produkcji `status='published'`
mają 14 wierszy, wszystkie z seeda demo z kwietnia 2026, a 291 realnie otwartych
rekrutacji siedzi w `draft`. Rozdzielenie pozwala naprawić `status` bez lawiny
powiadomień: mechanizmy działające (Priority Work, digest dopasowań, alerty
deadline'ów, linki zaproszeniowe) przechodzą na `is_open`, a liczniki zostają
na `status`.

Backfill `is_open = (status = 'published')` jest celowo ZACHOWAWCZY — po
wdrożeniu żadna liczba się nie zmienia. Prawdziwe otwarcie przychodzi dopiero
z pełnym biegiem importera, który operator odpala świadomie.

Revision ID: 0270_jobs_open_state_dates
Revises: 0269_configurable_section_rbac
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0270_jobs_open_state_dates"
down_revision = "0269_configurable_section_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "is_open",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_jobs_opened_at", "jobs", ["opened_at"])
    # Częściowy — zapytania pytają wyłącznie o „otwarte", a takich jest garść.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_is_open ON jobs (is_open) WHERE is_open"
    )

    # Wiersze założone W NEXUSIE mają w `created_at` prawdziwą datę — tam nikt
    # nic nie stemplował. Wiersze Traffita zostają NULL do czasu pełnego biegu
    # importera i to jest SYGNAŁ, nie brak: `job_data_trust.duration_available`
    # czyta go i każe metrykom czasu odpowiadać „nie wiemy" zamiast liczyć od
    # daty importu.
    op.execute(
        """
        UPDATE jobs
        SET opened_at = created_at
        WHERE opened_at IS NULL
          AND external_source IS DISTINCT FROM 'traffit'
        """
    )

    # Zachowawczo: dokładnie te rekrutacje, które DZIŚ przechodzą przez bramki
    # `status == published`. Dzięki temu deploy nie zmienia ani jednej liczby
    # ani nie odpala ani jednego powiadomienia.
    op.execute("UPDATE jobs SET is_open = true WHERE status = 'published'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_is_open")
    op.drop_index("ix_jobs_opened_at", table_name="jobs")
    op.drop_column("jobs", "is_open")
    op.drop_column("jobs", "opened_at")
