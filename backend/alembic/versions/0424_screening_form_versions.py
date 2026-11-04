"""Jeden formularz screeningu: historia wersji, stawka z formularza, koniec kart dla klienta.

Revision ID: 0424_screening_form_versions
Revises: 0423_notes_facts_to_fields

* ``screening_form_versions`` — historia formularza pary (kandydat,
  rekrutacja): migawka i zmiany „przed → po” po każdej realnej zmianie.
* CHECK ``ck_candidate_rate_changes_source`` przyjmuje ``screening``.
* Wszystkie tokeny karty Championa dla klienta odwołane (D2, 07.10.2026).

SQL ma jedno źródło (``app/services/screening_form_schema.py``) — ten sam
moduł importuje ``entrypoint.sh``.
"""

from alembic import op

from app.services import screening_form_schema as schema
from app.services.candidate_rate_change_schema import SOURCES, source_constraint_ddl

revision = "0424_screening_form_versions"
down_revision = "0423_notes_facts_to_fields"
branch_labels = None
depends_on = None

_SOURCES_BEFORE = tuple(source for source in SOURCES if source != "screening")


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Historia formularza żyje tylko w tej tabeli, a węższy CHECK nie przyjąłby
    # zmian stawki zapisanych z formularza.
    bind = op.get_bind()
    versions = bind.exec_driver_sql(
        "SELECT count(*) FROM screening_form_versions"
    ).scalar()
    if versions:
        raise RuntimeError(
            f"screening_form_versions ma {versions} wierszy — downgrade skasowałby "
            "historię formularza screeningu bez śladu."
        )
    from_form = bind.exec_driver_sql(
        "SELECT count(*) FROM candidate_rate_changes WHERE source = 'screening'"
    ).scalar()
    if from_form:
        raise RuntimeError(
            f"candidate_rate_changes ma {from_form} zmian stawki z formularza — "
            "węższy CHECK nie przyjąłby tych wierszy."
        )
    op.execute("DROP TABLE IF EXISTS screening_form_versions")
    op.execute(source_constraint_ddl(_SOURCES_BEFORE))
    # Odwołanych tokenów karty Championa nie przywracamy — link był dla klienta.
