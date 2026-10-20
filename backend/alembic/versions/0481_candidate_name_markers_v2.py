"""Imię i nazwisko bez dopisków — druga runda (20.10.2026).

Revision ID: 0481_candidate_name_markers_v2
Revises: 0479_equipment_return_reminder

Przeklikanie Opieki 20.10.2026 pokazało imiona, których 0436 nie znała:
„{ } Jan”, samotny „[Jan”, literówka „[acive/ Jan”, emoji („Kowalski ☁️”)
i emoji zepsute do „?‍?”. Reguła ``candidate_name_rules`` zna je od teraz
(ta sama funkcja odmawia 422 przy ręcznym wpisie i czyści ścieżki
automatyczne). Do tego trzy ręczne poprawki rozjechanych pól
(``MANUAL_FIXES_0481``) — lista „było → będzie” zatwierdzona przez Artura
20.10.2026; zapis zależy od kształtu pól, nie od samego ID.

Rdzeń jak w 0436 (``candidate_name_marker_repair``): paragon (liczby + ID)
w ``app_settings['0481_candidate_name_markers_v2']``, stare wartości pod
``repair_details_0481_candidate_name_markers_v2``. Lustro w ``entrypoint.sh``:
faza ``repair-candidate-name-markers-0481`` — ten sam runner, idempotentny
przez paragon; ona zapisuje kolejkę indeksu dla zmienionych osób.
"""

from alembic import op

from app.services.candidate_name_marker_repair import apply_name_marker_repair_0481

revision = "0481_candidate_name_markers_v2"
down_revision = "0479_equipment_return_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    apply_name_marker_repair_0481(op.get_bind())


def downgrade() -> None:
    # Porządkowanie danych: stare wartości zostają pod kluczem szczegółów
    # w `app_settings` — przywrócenie dopisku w imieniu nie jest celem.
    pass
