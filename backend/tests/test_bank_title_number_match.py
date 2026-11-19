"""Numer faktury w tytule przelewu — wynik jak dawny wzorzec, bez kompilacji na parę.

18.11.2026 import wyciągu (``POST /api/ledger/bank/import``) trwał 66,6 s:
E3 i E8 kompilowały wzorzec numeru dla każdej pary operacja × faktura, a przy
tysiącach faktur pamięć podręczna ``re`` (512 wzorców) nic nie trzymała.
``number_in_title`` kompiluje wzorzec tylko wtedy, gdy ciągi cyfr numeru stoją
w tytule — ten test pilnuje, że odpowiedź jest ta sama co dawnego wzorca
i że tysiące niepasujących faktur nie kompilują nic.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from app.services.finance_ledger import payment_rules as rules
from app.services.hr.bank import titles
from app.services.hr.bank.parsed import StatementLine
from app.services.hr.bank.titles import number_in_title


def _old(number: str, title: str) -> bool:
    """Wzorzec sprzed 19.11.2026 (E3 i E8 miały ten sam)."""

    parts = number.split()
    if not parts:
        return False
    body = r"\s*".join(re.escape(part) for part in parts)
    pattern = re.compile(
        r"(?<![0-9A-Za-z])" + body + r"(?![0-9A-Za-z])", re.IGNORECASE
    )
    return bool(pattern.search(title))


NUMBERS = [
    "FV 1/10/2026",
    "FV/1/10/2026",
    "1/10/2026",
    "fv 12/2026",
    "ABC-7",
    "abc",
    "  FV   7/03  ",
    "",
    "   ",
    "F/2026/10/0012",
    "12",
    "ZAŁ 3/2026",
]
TITLES = [
    "Zapłata za FV 1/10/2026",
    "zaplata fv1/10/2026 i FV 2/10/2026",
    "Przelew FV/1/10/2026/UE",
    "11/10/2026",
    "X1/10/2026",
    "FV 12/2026 oraz fv 12 / 2026",
    "abc-7 abcd",
    "ABC",
    "fv 7/03",
    "F/2026/10/00123",
    "Faktura 12",
    "Faktura 112",
    "zał 3/2026",
    "ZAŁ3/2026",
    "",
]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("number", NUMBERS)
def test_same_answer_as_the_old_pattern(number: str, title: str) -> None:
    assert number_in_title(number, title) is _old(number, title)


def test_thousands_of_other_invoices_compile_nothing() -> None:
    titles._number_pattern.cache_clear()
    candidates = [
        rules.CostCandidate(
            entry_id=index,
            currency="PLN",
            gross=Decimal("100.00"),
            paid=Decimal("0"),
            invoice_number=f"FV {index}/09/2026",
            ksef_number=None,
            seller_nip=None,
            seller_name=None,
            accounts=frozenset(),
        )
        for index in range(100, 3100)
    ]
    line = StatementLine(
        index=1,
        booked_on=date(2026, 11, 18),
        amount=Decimal("77.00"),
        direction="debit",
        currency="PLN",
        title="Czynsz za listopad 2026",
    )
    for _ in range(50):
        rules.decide_debit(line, candidates)
    assert titles._number_pattern.cache_info().misses == 0
