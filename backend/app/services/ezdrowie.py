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

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

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


EXECUTIVE_CONTRACT_REQUIRED_MESSAGE = "Wybierz umowę wykonawczą"
EXECUTIVE_CONTRACT_ONLY_EZDROWIE_MESSAGE = (
    "Pole „umowa wykonawcza” dotyczy wyłącznie Centrum e-Zdrowia"
)


async def resolve_ezdrowie_assignment(
    db: "AsyncSession",
    *,
    client_id: Optional[int],
    executive_contract_id: Optional[int],
    project_part: Optional[str],
    require: bool,
) -> tuple[Optional[int], Optional[str]]:
    """Przypisanie zamówienia u Centrum e-Zdrowia (ticket 09.2026).

    Zwraca ``(executive_contract_id, project_part)`` albo rzuca ``ValueError``
    z komunikatem PL (wołający zamienia na 422).

    Od ticketu „Struktura umów wykonawczych" konsultant jest przypisywany do
    KONKRETNEJ umowy wykonawczej, nie do części ramowej:

    - klient inny niż CeZ: oba pola MUSZĄ być puste (jak dotąd
      ``validate_project_part``);
    - CeZ + ``require=True`` (nowe zamówienie / przedłużenie / nowa karta MD):
      wymagana umowa wykonawcza — sama część już nie wystarcza, bo pod jedną
      częścią bywa kilka umów wykonawczych;
    - podana umowa: musi należeć do klienta i być ``active``; część jest
      POCHODNĄ z jej umowy ramowej (jawnie podana inna część → błąd);
    - CeZ + ``require=False`` + nic nie podane: ``(None, None)`` — PATCH innych
      pól nie rusza przypisania.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.client_executive_contract import (
        EXECUTIVE_CONTRACT_STATUS_ACTIVE,
        ClientExecutiveContract,
    )

    normalized_part = validate_project_part(client_id, project_part, require=False)
    if not is_ezdrowie_client(client_id):
        if executive_contract_id is not None:
            raise ValueError(EXECUTIVE_CONTRACT_ONLY_EZDROWIE_MESSAGE)
        return None, None
    if executive_contract_id is None:
        if require or normalized_part is not None:
            # Sama część już nie wystarcza (pod jedną częścią bywa kilka umów
            # wykonawczych) — także przy PATCH-u: część bez umowy odtwarzałaby
            # stan sprzed struktury dwupoziomowej.
            raise ValueError(EXECUTIVE_CONTRACT_REQUIRED_MESSAGE)
        return None, None
    executive = await db.scalar(
        select(ClientExecutiveContract)
        .options(selectinload(ClientExecutiveContract.framework_contract))
        .where(
            ClientExecutiveContract.id == executive_contract_id,
            ClientExecutiveContract.client_id == client_id,
        )
        # FOR SHARE: zakończenie umowy wykonawczej blokuje jej wiersz FOR UPDATE
        # i liczy przypisania — bez tej blokady przypisanie równoległe z
        # zakończeniem przechodziło na umowę, która właśnie się kończy.
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if executive is None:
        raise ValueError(
            "Wskazana umowa wykonawcza nie istnieje albo należy do innego klienta"
        )
    if executive.status != EXECUTIVE_CONTRACT_STATUS_ACTIVE:
        raise ValueError(
            f"Umowa wykonawcza {executive.number} jest zakończona — wybierz aktywną"
        )
    derived_part = (
        executive.framework_contract.project_part
        if executive.framework_contract is not None
        else None
    )
    if normalized_part is not None and derived_part != normalized_part:
        raise ValueError(
            "Część umowy nie zgadza się z umową wykonawczą — część wynika "
            "z umowy ramowej, pod którą wisi umowa wykonawcza"
        )
    return executive.id, derived_part
