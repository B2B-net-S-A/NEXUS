"""Imię i nazwisko kandydata bez dopisków z Traffita (D6, 13.10.2026).

Revision ID: 0436_candidate_name_markers
Revises: 0435_candidate_document_removed

„[ACTIVE] Jan”, „Nowak (zaakceptowany)”, „(czarna lista) Piotr” — dopiski,
których nie zdjęły 0165 i 0232. Najpierw pole (czarna lista → ``status``,
„active” → ``availability_status``), potem tekst; zdjęte dopiski idą do
``cv_extracted_data.traffit_name_marker``, bez notatek. Jedna reguła
z ``app/services/candidate_name_rules.py`` (tą samą czyści import Traffita),
SQL i runner w ``app/services/candidate_name_marker_repair.py``.

Paragon (liczby + ID) w ``app_settings['0436_candidate_name_markers']``,
stare wartości pod ``repair_details_0436_candidate_name_markers``. Lustro
w ``entrypoint.sh`` (prod alembic bywa osierocony): faza
``repair-candidate-name-markers`` — ten sam runner, idempotentny przez
paragon; ona też zapisuje kolejkę indeksu dla zmienionych osób.
"""

from alembic import op

from app.services.candidate_name_marker_repair import apply_name_marker_repair

revision = "0436_candidate_name_markers"
down_revision = "0435_candidate_document_removed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    apply_name_marker_repair(op.get_bind())


def downgrade() -> None:
    # Porządkowanie danych: stare wartości zostają pod kluczem szczegółów
    # w `app_settings` — przywrócenie dopisku w imieniu nie jest celem.
    pass
