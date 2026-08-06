"""Centrum e-Zdrowia — jedyny klient z polem „część umowy" (ticket #3, Faza C).

Bramka po ``client_id`` (decyzja Fazy B) — NIE po nazwie: Traffit nadpisuje
``Client.name`` przy każdym syncu, a duplikat 37721 „E-Zdrowie" został scalony
w kanoniczny rekord 115 (docs/klienci-faza-b-decyzje.md). Gdyby kiedyś doszły
kolejne wiersze e-Zdrowia, dopisz je do zbioru — needle'y nazwowe zostają
wyłącznie w klauzulach umów (clause_override_content.py).

Wartości części: cz.3 CELOWO nie istnieje (potwierdzone w tickecie).
Kod w DB to slug (``cz1``…), etykieta PL żyje w warstwie prezentacji
(frontend/src/lib/ezdrowie.ts) — ten sam wzorzec co B2B_CLOSURE_REASON_LABEL.
"""

from __future__ import annotations

EZDROWIE_CLIENT_ID = 115

PROJECT_PARTS: tuple[str, ...] = ("cz1", "cz2", "cz4", "cz5", "cz6")


def is_ezdrowie_client(client_id: int | None) -> bool:
    return client_id == EZDROWIE_CLIENT_ID


def validate_project_part(
    client_id: int | None, project_part: str | None, *, require: bool
) -> str | None:
    """Zwraca znormalizowaną wartość albo rzuca ValueError z komunikatem PL.

    - klient inny niż e-Zdrowie: część MUSI być pusta (nie przechowujemy po
      cichu wartości, których UI nigdy nie pokaże),
    - e-Zdrowie + ``require=True`` (nowe zamówienie/przedłużenie): wymagana,
    - wartość spoza słownika: odrzucona niezależnie od klienta.
    """
    normalized = (project_part or "").strip() or None
    if normalized is not None and normalized not in PROJECT_PARTS:
        raise ValueError(
            "Nieprawidłowa część umowy — dozwolone: " + ", ".join(PROJECT_PARTS)
        )
    if not is_ezdrowie_client(client_id):
        if normalized is not None:
            raise ValueError("Pole „część umowy” dotyczy wyłącznie Centrum e-Zdrowia")
        return None
    if require and normalized is None:
        raise ValueError("Wybierz część umowy")
    return normalized
