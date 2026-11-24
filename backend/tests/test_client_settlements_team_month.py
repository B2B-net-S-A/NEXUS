"""Biuro w „Przebiegu miesiąca”: stany osoby z ewidencji, faktury z KSeF i zapłaty.

Czyste funkcje bez bazy. Decyzje Artura z 24.11.2026: faktury biura tylko po
NIP-ie (bez NIP-u = ``no_nip``, nie zgadujemy po nazwie), bez kwot w odpowiedzi.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.services.client_settlements import team_month


def _sheet(status: str, approved_at=None, returned_at=None):
    return SimpleNamespace(
        status=status, approved_at=approved_at, returned_at=returned_at
    )


def _invoice(
    invoice_id: int,
    issue: date,
    *,
    period: tuple[int, int] | None = None,
    sale: date | None = None,
    kind: str = "original",
    settlement_id: int | None = None,
):
    return SimpleNamespace(
        id=invoice_id,
        issue_date=issue,
        sale_date=sale,
        period_year=period[0] if period else None,
        period_month=period[1] if period else None,
        invoice_kind=kind,
        settlement_id=settlement_id,
        net_amount="12345.00",
    )


def test_ewidencja_brak_szkic_zwrocona_zlozona_zatwierdzona() -> None:
    assert team_month.timesheet_state(None) == "missing"
    assert team_month.timesheet_state(_sheet("draft")) == "draft"
    returned = _sheet("draft", returned_at=datetime(2026, 11, 3, tzinfo=timezone.utc))
    assert team_month.timesheet_state(returned) == "returned"
    assert team_month.timesheet_state(_sheet("submitted")) == "submitted"
    assert team_month.timesheet_state(_sheet("approved")) == "approved"


def test_bez_nip_to_nie_brak_faktury() -> None:
    assert team_month.invoice_state(False, None, None) == "no_nip"
    assert team_month.invoice_state(True, None, None) == "missing"
    invoice = _invoice(1, date(2026, 11, 3), period=(2026, 10))
    assert team_month.invoice_state(True, invoice, None) == "in_ksef"
    mismatch = SimpleNamespace(status="mismatch", paid_at=None)
    assert team_month.invoice_state(True, invoice, mismatch) == "differs"


def test_faktura_za_miesiac_bez_korekt_najwczesniejsza() -> None:
    september = _invoice(1, date(2026, 10, 2), period=(2026, 9))
    correction = _invoice(2, date(2026, 11, 1), period=(2026, 10), kind="correction")
    late = _invoice(3, date(2026, 11, 9), period=(2026, 10))
    early = _invoice(4, date(2026, 11, 3), sale=date(2026, 10, 31))
    picked = team_month.pick_invoice([september, correction, late, early], 2026, 10)
    assert picked is early
    assert team_month.pick_invoice([september, correction], 2026, 10) is None


def test_zaplata_z_plac_albo_z_przelewu_w_kosztach() -> None:
    paid = SimpleNamespace(
        status="paid", paid_at=datetime(2026, 11, 14, 11, 0, tzinfo=timezone.utc)
    )
    assert team_month.paid_on(paid, None) == date(2026, 11, 14)
    approved = SimpleNamespace(status="approved", paid_at=None)
    assert team_month.paid_on(approved, date(2026, 11, 16)) == date(2026, 11, 16)
    assert team_month.paid_on(None, None) is None


def test_wiersz_osoby_bez_kwot() -> None:
    invoice = _invoice(5, date(2026, 11, 3), period=(2026, 10))
    sheet = _sheet(
        "approved", approved_at=datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    )
    row = team_month.person_row(
        7, "Osoba A", True, sheet, invoice, None, date(2026, 11, 16)
    )
    assert row == {
        "user_id": 7,
        "person": "Osoba A",
        "timesheet": "approved",
        "timesheet_on": "2026-11-05",
        "invoice": "in_ksef",
        "invoice_on": "2026-11-03",
        "paid": True,
        "paid_on": "2026-11-16",
    }
    assert not any("amount" in key for key in row)
    empty = team_month.person_row(8, "Osoba B", False, None, None, None, None)
    assert (empty["timesheet"], empty["invoice"], empty["paid"]) == (
        "missing",
        "no_nip",
        False,
    )
