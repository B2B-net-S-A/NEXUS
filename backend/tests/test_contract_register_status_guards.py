"""Bramki statusu na schematach rejestru umów.

Sprzeczność, która wcześniej przechodziła przez walidację i dopiero w bazie
zamieniała się w liczby: kontrakt „kończący się" bez daty końca, czyli taki,
który nigdy nie ustanie — a mimo to bez końca liczy się jako przychód.

Statusu operacyjnego na ``ContractCreate`` te testy świadomie NIE pilnują
odmową na poziomie schematu: wybór z rejestru jest honorowany, a bramki
(komplet pól, dowód podpisu, sync zamówień) egzekwuje handler przez
``contract_lifecycle`` — patrz ``test_create_contract_active_requires_complete_draft``
w ``test_contract_lifecycle_invariant.py``. Tutaj pilnujemy stanów, które
nigdy nie należą do rejestru, i sprzeczności nie do naprawienia później.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.contract import ContractStatus
from app.schemas.contract import ContractCreate, ContractUpdate

_BASE = {"candidate_id": 1, "client_id": 1, "start_date": date(2026, 7, 1)}


def test_create_defaults_to_draft_without_status() -> None:
    assert ContractCreate(**_BASE).status == ContractStatus.draft


def test_create_still_rejects_lifecycle_only_statuses() -> None:
    """``void``/``ready_for_signature`` prowadzą osobne, audytowane procesy.

    Rejestr ich nie oferuje, ale kontrakt HTTP nie jest listą rozwijaną —
    odmowa na wejściu jest tańsza niż wykrywanie ich w handlerze.
    """
    for lifecycle_only in ("void", "ready_for_signature"):
        with pytest.raises(ValidationError):
            ContractCreate(**_BASE, status=lifecycle_only)


def test_update_rejects_ending_with_explicit_null_end_date() -> None:
    """``ending`` + bezterminowo = wiersz liczony jako aktywny bez końca.

    Serwerowe samoleczenie jest dla PATCH-a ZE statusem wyłączone z rozmysłem
    (żeby nie nadpisywać jawnego wyboru), więc tej sprzeczności nikt później
    nie naprawi.
    """
    with pytest.raises(ValidationError) as err:
        ContractUpdate(status="ending", end_date=None)
    assert "daty zakończenia" in str(err.value)


def test_update_allows_ending_when_end_date_is_not_part_of_the_patch() -> None:
    """PATCH jest częściowy: brak klucza znaczy „zostaw datę z bazy"."""
    payload = ContractUpdate(status="ending")
    assert payload.status == ContractStatus.ending
    assert "end_date" not in payload.model_fields_set


def test_update_allows_ended_with_null_end_date() -> None:
    """``ended`` ma udokumentowane wykonanie — handler stempluje dzisiejszą datę
    i domyka zamówienia klienta. Odmowa zmuszałaby operatora do wpisania daty,
    którą serwer i tak zna."""
    assert ContractUpdate(status="ended", end_date=None).status == ContractStatus.ended


def test_update_allows_ending_with_a_date() -> None:
    payload = ContractUpdate(status="ending", end_date=date(2026, 9, 30))
    assert payload.end_date == date(2026, 9, 30)
