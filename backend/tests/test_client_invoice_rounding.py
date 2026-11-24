"""Grosze „Do faktury” zaokrąglone jak w FA(3) (audyt 24.11.2026).

``client_invoice._money`` zaokrąglał bankowo (ROUND_HALF_EVEN), a silnik
rozliczeń i FA(3) połówkę w górę: 2,5 MD × 100,01 zł dawało 250,02 zł
w „Do faktury” i potwierdzeniu usług, a 250,03 zł w XML do KSeF.
Kwoty fikcyjne.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.client_invoicing import fa3_build
from app.services.client_settlements import client_invoice, engine


@pytest.mark.parametrize(
    "value, expected",
    [
        ("250.025", "250.03"),
        ("0.005", "0.01"),
        ("10.015", "10.02"),
        ("10.025", "10.03"),
        ("-0.125", "-0.13"),
        ("10.0249", "10.02"),
    ],
)
def test_grosze_polowka_w_gore_jak_fa3_i_silnik(value, expected):
    amount = Decimal(value)
    assert client_invoice._money(amount) == Decimal(expected)
    assert client_invoice._money(amount) == fa3_build.money(amount)
    assert client_invoice._money(amount) == engine._money(amount)


def test_pozycja_do_faktury_ta_sama_kwota_co_fa3():
    s = SimpleNamespace(
        md_regular=Decimal("2.5"),
        md_extra=Decimal("0"),
        md_onboarding=Decimal("0"),
        md_charged=None,
        checks=[],
        lines=[],
    )
    [base] = client_invoice.positions(
        s, name="Usługi", rate=Decimal("100.01"), overtime_suffix=None
    )
    assert base.net == Decimal("250.03")
    assert base.net == fa3_build.money(Decimal("2.5") * Decimal("100.01"))
