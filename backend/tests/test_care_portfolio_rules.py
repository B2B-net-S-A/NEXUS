"""Opieka · „Klienci” (makieta P4, 22.10.2026) — czyste reguły wiersza klienta.

„Drzewo pełne” i „prośba czeka od” bez bazy. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

from app.services.care.portfolio import pending_since, tree_complete


def test_tree_is_complete_only_when_every_manager_reports_to_someone() -> None:
    assert tree_complete([10, 10, 11], {10: 1, 11: 1})
    # Konsultant bez menedżera.
    assert not tree_complete([10, None], {10: 1})
    # Menedżer bez „Podlega pod” (luka ``manager_unplaced``).
    assert not tree_complete([10, 11], {10: 1, 11: None})
    # Menedżer spoza osób klienta (brak w słowniku) też nie domyka drzewa.
    assert not tree_complete([12], {})
    # Bez naszych konsultantów nie ma czego domykać.
    assert not tree_complete([], {})


def test_pending_since_takes_the_oldest_request_per_client() -> None:
    requests = [
        {"client_id": 1, "due_on": date(2026, 10, 19)},
        {"client_id": 1, "due_on": date(2026, 10, 16)},
        {"client_id": 2, "due_on": date(2026, 10, 21)},
    ]
    assert pending_since(requests) == {1: date(2026, 10, 16), 2: date(2026, 10, 21)}
    assert pending_since([]) == {}
