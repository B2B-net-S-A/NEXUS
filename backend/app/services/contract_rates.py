"""Jedno miejsce, w którym rozstrzyga się, ile kontrakt kosztuje i ile przynosi.

Kontrakt niesie stawki w DWÓCH postaciach i to jest źródło całej klasy błędów,
którą ten moduł zamyka:

* kolumny ``rate_candidate`` / ``rate_client`` / ``framework_rate`` — cache
  odświeżany wyłącznie w momencie ZAPISU kontraktu;
* harmonogramy ``candidate_rate_schedule`` / ``client_rate_schedule`` /
  ``framework_rate_schedule`` — datowana prawda o tym, ile obowiązywało kiedy.

Kolumna kłamie zawsze wtedy, gdy stawka zmienia się w czasie: aneks
``rate_change`` z datą przyszłą wpisuje do niej wartość w chwili UTWORZENIA
aneksu i nic jej potem nie przelicza, więc do dnia, w którym ktoś przypadkiem
zapisze kontrakt, kolumna pokazuje stawkę sprzed zmiany. Przy stawce
progresywnej cała historia jest płaska na najnowszej wartości.

Dlatego resolver jest tutaj, a nie — jak dotąd — w routerze ``api/contracts.py``:
konsumentami są analityka, raporty, ``/my-clients``, zamówienia i profil klienta,
a moduł ``api.*`` importujący inny moduł ``api.*`` po to, żeby policzyć marżę,
to zależność, która przy pierwszym cyklu importów wymusza kopiowanie funkcji.
Kopia zaś rozjeżdża się cicho — i dokładnie to opisuje temat 1 audytu
z 21.08.2026 (``docs/tech-debt-audit-2026-08-21.md``).

``api.contracts._effective_rate_fields`` zostaje jako alias, żeby ta zmiana nie
dotykała istniejących wywołań.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import selectinload

from app.models.contract import Contract, ContractStatus

__all__ = [
    "RATE_SCHEDULE_LOADS",
    "REVENUE_BEARING_STATUSES",
    "effective_rate_fields",
]


# Każdy czytelnik stawek MUSI mieć te trzy relacje wczytane z góry.
# ``effective_*_rate`` sięga po nie atrybutem, a w sesji async lazy-load nie jest
# wolniejszym odczytem, tylko ``MissingGreenlet`` — czyli HTTP 500 bez nagłówków
# CORS, który front pokazuje jako „Network Error". Trzymanie tej krotki obok
# resolvera sprawia, że nowy konsument dostaje komplet w jednym imporcie zamiast
# przepisywać trzy ``selectinload`` z pamięci i pominąć jeden.
RATE_SCHEDULE_LOADS = (
    selectinload(Contract.candidate_rate_schedule),
    selectinload(Contract.client_rate_schedule),
    selectinload(Contract.framework_rate_schedule),
)


# Statusy, które reprezentują WYKONYWANĄ umowę i tym samym wchodzą do przychodu.
#
# Lista jest POZYTYWNA świadomie. Warunek pisany jako negacja
# (``status != draft``) wpuszcza wszystko, co dopisano do enuma później — dziś
# ``ready_for_signature`` (umowa jeszcze niepodpisana, więc bez przychodu)
# i ``void`` (anulowana, terminalna). Negacja nie ma sposobu, żeby zaprotestować
# przy dodaniu nowej wartości; lista pozytywna wymusza decyzję.
#
# ``ended`` ZOSTAJE w zbiorze: o tym, czy kontrakt żył w danym okresie,
# rozstrzygają ``start_date``/``end_date`` w zapytaniu point-in-time, a nie
# dzisiejszy status. Wycięcie ``ended`` skasowałoby z historii każdy zakończony
# projekt i zaniżyło każdy miniony miesiąc.
REVENUE_BEARING_STATUSES = (
    ContractStatus.active,
    ContractStatus.ending,
    ContractStatus.ended,
)


def effective_rate_fields(contract: Contract, on: date) -> dict:
    """Stawki kandydata i klienta (plus marża) obowiązujące dnia ``on``.

    Wszystko liczone z harmonogramów, nigdy z cache'owanych kolumn — krok
    zaplanowany na przyszłość nie zmienia dzisiejszej stawki, a krok sprzed
    miesiąca wycenia tamten miesiąc tamtą kwotą. Stawka ramowa jest wyliczana
    tak samo, żeby planowana zmiana pokazała się w swojej dacie bez edycji,
    ale NIE wchodzi do marży.

    Wymaga wczytanych ``RATE_SCHEDULE_LOADS``.
    """
    eff_candidate = contract.effective_candidate_rate(on)
    eff_client = contract.effective_client_rate(on)
    eff_framework = contract.effective_framework_rate(on)

    candidate_dec = Contract._as_decimal(eff_candidate)
    client_dec = Contract._as_decimal(eff_client)
    candidate_currency = contract.resolved_rate_candidate_currency
    client_currency = contract.resolved_rate_client_currency
    margin: Optional[Decimal] = (
        client_dec - candidate_dec
        if client_dec is not None
        and candidate_dec is not None
        and client_currency == candidate_currency
        else None
    )

    monthly_candidate = contract.monthly_rate(eff_candidate)
    monthly_client = contract.monthly_rate(eff_client)
    monthly_margin: Optional[Decimal] = (
        monthly_client - monthly_candidate
        if monthly_client is not None
        and monthly_candidate is not None
        and client_currency == candidate_currency
        else None
    )

    return {
        "rate_candidate": eff_candidate,
        "rate_client": eff_client,
        "rate_candidate_currency": candidate_currency,
        "rate_client_currency": client_currency,
        # Legacy response alias: old consumers understand it as the client
        # (revenue/order) currency.
        "currency": client_currency,
        "framework_rate": eff_framework,
        "margin": margin,
        "monthly_rate_candidate": monthly_candidate,
        "monthly_rate_client": monthly_client,
        "monthly_margin": monthly_margin,
    }
