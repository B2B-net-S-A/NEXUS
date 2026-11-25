"""Jarvis: waluta stawek kontraktu (audyt R3, 24.11.2026).

``list_contracts`` gubił pola walut, ``get_contract`` niósł tylko ``currency``,
a prompt kazał pisać każdą kwotę w zł — kontrakt w EUR wychodził jako „zł”.
Bez bazy: kształt wyniku narzędzia i reguła w prompcie.
"""

from __future__ import annotations

from app.services.jarvis.prompt import SYSTEM_PROMPT
from app.services.jarvis.tools import TOOLS_BY_NAME

_CURRENCIES = {
    "currency": "EUR",
    "rate_client_currency": "EUR",
    "rate_candidate_currency": "PLN",
}


def _contract() -> dict:
    return {
        "id": 7,
        "candidate_id": 11,
        "candidate_name": "Jan Testowy",
        "client_id": 3,
        "client_name": "Klient Testowy",
        "status": "active",
        "contract_type": "b2b",
        "rate_candidate": 100.0,
        "rate_client": 50.0,
        "rate_unit": "hour",
        **_CURRENCIES,
    }


def test_list_contracts_keeps_rate_currencies():
    shaped = TOOLS_BY_NAME["list_contracts"].shape(
        {"items": [_contract()], "total": 1, "page": 1, "page_size": 20}, {}
    )
    row = shaped["items"][0]
    for key, value in _CURRENCIES.items():
        assert row[key] == value


def test_get_contract_keeps_rate_currencies():
    shaped = TOOLS_BY_NAME["get_contract"].shape(_contract(), {"contract_id": 7})
    for key, value in _CURRENCIES.items():
        assert shaped[key] == value


def test_prompt_takes_currency_from_the_tool_result():
    assert "Kwoty w PLN" not in SYSTEM_PROMPT
    assert "_currency" in SYSTEM_PROMPT
    assert "brak = PLN" in SYSTEM_PROMPT
    assert "różnych walutach" in SYSTEM_PROMPT
