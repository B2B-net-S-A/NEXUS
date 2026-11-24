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


def _row(
    status: str, contractor: str, client: str = "waiting", cost: str | None = "1000.00"
):
    return {
        "contract_id": 1,
        "person": "Osoba",
        "status": status,
        "contractor_invoice": contractor,
        "client_invoice": client,
        "md_regular": "20.000",
        "amount_cost": cost,
    }


def test_trzy_pytania_ksiegowej() -> None:
    rows = [
        _row("ok", "in_ksef"),  # faktura w KSeF, RCP nieprzyjęte
        _row("accepted", "in_ksef", "ready"),  # przyjęte, czeka na fakturę sprzedaży
        _row("accepted", "none", "issued"),  # brak faktury kontraktora → rezerwa
        _row("warnings", "can_issue", cost=None),  # rezerwa bez kosztu
        _row("missing", "none"),  # bez MD: ani rezerwa, ani nieprzyjęta
        _row(
            "accepted", "differs", "awaiting_client"
        ),  # faktura z inną kwotą jest w KSeF
    ]
    found = month_close.closing_rows(rows, 7, "Klient")
    assert len(found["ksef_not_accepted"]) == 1
    assert len(found["reserve"]) == 2
    assert len(found["sales_waiting"]) == 2
    summary = month_close._closing_summary(found, amounts=True)
    assert summary["reserve_total"] == "1000.00"
    assert summary["reserve_without_cost"] == 1
    assert summary["rows"]["reserve"][0]["client"] == "Klient"


def test_bez_uprawnienia_do_kwot_same_liczby() -> None:
    found = month_close.closing_rows([_row("accepted", "none")], 7, "Klient")
    summary = month_close._closing_summary(found, amounts=False)
    assert summary["reserve_count"] == 1
    assert summary["reserve_total"] is None
    assert summary["rows"] is None


def _person_row(status: str, **kw: object) -> dict:
    base = {
        "status": status,
        "issue_level": None,
        "contractor_invoice": "none",
        "client_invoice": "waiting",
        "accepted_auto": False,
        "order_number": "ZAM-1",
    }
    base.update(kw)
    return base


def test_kroki_miesiaca_kazda_osoba_raz_w_kazdym_kroku() -> None:
    rows = [
        _person_row("missing", order_number=None),
        _person_row("checking"),
        _person_row("no_md"),
        _person_row("warnings", issue_level="warn"),
        _person_row("warnings", issue_level="fail"),
        _person_row("needs_fix", issue_level="fail"),
        _person_row("ok", contractor_invoice="differs"),
        _person_row(
            "accepted",
            accepted_auto=True,
            contractor_invoice="in_ksef",
            client_invoice="issued",
        ),
        _person_row(
            "accepted", contractor_invoice="nip_check", client_invoice="awaiting_client"
        ),
        _person_row("accepted", client_invoice="ready"),
    ]
    s = month_close.stage_counts(rows)
    assert s["people"] == 10
    assert s["report"] == {"in": 9, "missing": 1}
    assert s["check"] == {
        "clean": 4,
        "warn": 1,
        "fail": 1,
        "returned": 1,
        "unread": 1,
        "no_md": 1,
        "missing": 1,
    }
    assert sum(s["check"].values()) == 10
    assert s["accept"] == {"done": 3, "auto": 1, "ready": 1}
    assert s["contractor_invoice"] == {
        "match": 1,
        "differs": 1,
        "nip": 1,
        "can_issue": 0,
        "none": 7,
    }
    assert s["client_invoice"] == {
        "issued": 1,
        "ready": 1,
        "waiting_client": 1,
        "waiting": 7,
        "issued_early": 0,
    }
    assert s["missing_order"] == 1
    early = month_close.stage_counts([_person_row("ok", client_invoice="issued")])
    assert early["client_invoice"]["issued_early"] == 1


def test_suma_krokow_dwoch_klientow() -> None:
    a = month_close.stage_counts([_person_row("ok"), _person_row("missing")])
    b = month_close.stage_counts([_person_row("accepted", accepted_auto=True)])
    total = month_close.add_stages(a, b)
    assert total["people"] == 3
    assert total["check"]["clean"] == 2
    assert total["accept"] == {"done": 1, "auto": 1, "ready": 1}
    assert month_close.add_stages({}, a) == a


def test_rodzaj_sprawy_rozdziela_blad_od_uwagi_i_brak_md_od_pliku() -> None:
    assert month_close.reason_level(_person_row("missing")) == "missing"
    assert month_close.reason_level(_person_row("checking")) == "unread"
    # „no_md” to brak MD na zamówieniu, a nie nieodczytany plik.
    assert month_close.reason_level(_person_row("no_md")) == "order"
    assert (
        month_close.reason_level(_person_row("needs_fix", issue_level="fail"))
        == "returned"
    )
    assert (
        month_close.reason_level(_person_row("warnings", issue_level="fail")) == "fail"
    )
    assert (
        month_close.reason_level(_person_row("warnings", issue_level="warn")) == "warn"
    )


def test_wiersz_osoby_niesie_poziom_pierwszej_sprawy() -> None:
    from app.services.client_settlements import service

    person = SimpleNamespace(contract=SimpleNamespace(id=7), name="Osoba A")

    def settlement(status: str, checks: list, fix_reason: str | None = None):
        return SimpleNamespace(
            id=1,
            status=status,
            checks=checks,
            fix_reason=fix_reason,
            md_regular=None,
            md_extra=None,
            md_charged=None,
            amount_cost=None,
            amount_revenue=None,
            meta={},
        )

    warn_then_fail = [
        {"title": "RCP", "checks": [{"state": "warn", "title": "Excel bez maila"}]},
        {"title": "Zamówienie", "checks": [{"state": "fail", "title": "Brak MD"}]},
    ]
    row = service._row(person, settlement("warnings", warn_then_fail), True, False)
    assert (row["issues"], row["issue_level"]) == ("Brak MD", "fail")
    only_warn = warn_then_fail[:1]
    row = service._row(person, settlement("warnings", only_warn), True, False)
    assert row["issue_level"] == "warn"
    row = service._row(person, settlement("needs_fix", [], "Brak podpisu"), True, False)
    assert (row["issues"], row["issue_level"]) == ("Brak podpisu", "fail")
    assert service._row(person, None, False, False)["issue_level"] is None
