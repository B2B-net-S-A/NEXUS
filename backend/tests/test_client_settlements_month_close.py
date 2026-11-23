"""„Przebieg miesiąca” (Finanse → Przychody): powód osoby w kolejce decyzji.

Czyste funkcje bez bazy; widok na bazie jest w ``…_month_close_db.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.client_settlements import month_close


def _settlement(status: str, checks: list | None = None, fix_reason: str | None = None):
    return SimpleNamespace(status=status, checks=checks or [], fix_reason=fix_reason)


def test_pierwszy_jest_blad_przed_uwaga() -> None:
    s = _settlement(
        "warnings",
        [
            {
                "title": "RCP",
                "checks": [
                    {
                        "rule": "proof.excel_with_mail",
                        "state": "warn",
                        "title": "Excel bez maila",
                    }
                ],
            },
            {
                "title": "Sumy",
                "checks": [
                    {"rule": "fields.md_hours", "state": "fail", "title": "Sumy MD"}
                ],
            },
            {"md_over": None, "remaining_after": "1.000"},
        ],
    )
    assert month_close.first_issue(s) == ("fields.md_hours", "Sumy MD")


def test_odeslane_do_poprawy_bierze_powod_z_odeslania() -> None:
    s = _settlement("needs_fix", fix_reason="Brak podpisu klienta")
    assert month_close.first_issue(s) == ("needs_fix", "Brak podpisu klienta")


def test_bez_uwag_i_bez_rozliczenia_nie_ma_powodu() -> None:
    assert month_close.first_issue(None) is None
    ok = _settlement(
        "ok", [{"title": "RCP", "checks": [{"state": "ok", "title": "Miesiąc"}]}]
    )
    assert month_close.first_issue(ok) is None
    assert month_close._reason_for({"status": "ok"}, ok) is None
    assert month_close._reason_for({"status": "accepted"}, ok) is None


def test_brak_raportu_i_plik_bez_md_maja_wlasne_grupy() -> None:
    assert month_close._reason_for({"status": "missing"}, None) == (
        month_close.MISSING_REASON,
        "Brak raportu w poczcie rozliczeń",
    )
    assert month_close._reason_for({"status": "checking"}, None) == (
        month_close.UNREAD_REASON,
        "Plik jest, NEXUS nie odczytał MD",
    )


def test_plik_bez_md_z_opisem_trafia_pod_regule() -> None:
    s = _settlement(
        "no_md",
        [
            {
                "title": "Time Sheet",
                "checks": [
                    {
                        "rule": "proof.month",
                        "state": "fail",
                        "title": "Time Sheet za inny miesiąc",
                    }
                ],
            }
        ],
    )
    assert month_close._reason_for({"status": "no_md"}, s) == (
        "proof.month",
        "Time Sheet za inny miesiąc",
    )


def test_uwaga_bez_reguly_grupuje_sie_po_tytule() -> None:
    s = _settlement(
        "warnings",
        [
            {
                "title": "Zamówienie",
                "checks": [{"state": "warn", "title": "Ponad zamówienie o 2 MD"}],
            }
        ],
    )
    assert month_close._reason_for({"status": "warnings"}, s) == (
        "Ponad zamówienie o 2 MD",
        "Ponad zamówienie o 2 MD",
    )


def test_kwota_gotowa_tylko_z_rozliczen_bez_uwag() -> None:
    rows = [
        {"status": "ok", "amount_revenue": "1000.00"},
        {"status": "accepted", "amount_revenue": "500.50"},
        {"status": "warnings", "amount_revenue": "9999.00"},
        {"status": "ok", "amount_revenue": None},
    ]
    assert month_close._money(rows) == "1500.50"
    assert (
        month_close._money([{"status": "warnings", "amount_revenue": "1.00"}]) is None
    )
