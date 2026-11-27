"""Wynik KRZ „brak wpisów” dla umów w testach, które nie dotyczą bramki KRZ (0801).

Od 27.11.2026 niesprawdzona umowa B2B z Generatora nie idzie do podpisu
(``services/b2b_contract_generator/krz.py``). Testy podpisu, wysyłki
i automatyki zatrudnienia zakładają umowę już sprawdzoną; samą bramkę
sprawdza ``tests/test_b2b_krz.py``.
"""

KRZ_CLEAR = {
    "result": "clear",
    "entry_kind": None,
    "entry_note": None,
    "nip": None,
    "checked_at": "2026-11-27T12:00:00+00:00",
    "checked_by": None,
    "decision": None,
    "decision_reason": None,
    "decided_at": None,
    "decided_by": None,
}
