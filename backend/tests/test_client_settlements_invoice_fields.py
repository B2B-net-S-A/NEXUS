"""Pola faktury kontraktora z XML-a KSeF: data sprzedaży, miesiąc w nazwie, płatność.

Najczęstsze powody maili rozliczeń z prośbą o korektę (IX–X 2026). Faktury
fikcyjne składane w teście jako XML FA(3) i czytane przez ``fa.parse_invoice``,
jak przy pobieraniu z KSeF. Bez bazy i bez sieci.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.services.client_settlements import contractor_details, invoice_fields
from app.services.client_settlements import contractor_invoices as ci
from app.services.client_settlements import rules_catalog as catalog
from app.services.hr.ksef import fa

SELLER = "1234563218"
BUYER = "9876543210"
TODAY = date(2026, 11, 13)
TRANSFER = (
    "<Platnosc><TerminPlatnosci><Termin>2026-11-20</Termin></TerminPlatnosci>"
    "<FormaPlatnosci>6</FormaPlatnosci>"
    "<RachunekBankowy><NrRB>11222233334444555566667777</NrRB></RachunekBankowy>"
    "</Platnosc>"
)


def _xml(
    *,
    sale: Optional[str] = "<P_6>2026-10-31</P_6>",
    item: str = "Usługi programistyczne październik 2026",
    payment: str = TRANSFER,
    issue: str = "2026-11-03",
) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">'
        "<Naglowek><KodFormularza>FA</KodFormularza>"
        "<WariantFormularza>3</WariantFormularza></Naglowek>"
        f"<Podmiot1><DaneIdentyfikacyjne><NIP>{SELLER}</NIP>"
        "<Nazwa>Konsultant Przykładowy</Nazwa></DaneIdentyfikacyjne></Podmiot1>"
        f"<Podmiot2><DaneIdentyfikacyjne><NIP>{BUYER}</NIP>"
        "<Nazwa>Spółka Testowa</Nazwa></DaneIdentyfikacyjne></Podmiot2>"
        f"<Fa><KodWaluty>PLN</KodWaluty><P_1>{issue}</P_1><P_2>FV 7/2026</P_2>"
        f"{sale or ''}<P_13_1>8400.00</P_13_1><P_14_1>1932.00</P_14_1>"
        "<P_15>10332.00</P_15><RodzajFaktury>VAT</RodzajFaktury>"
        f"<FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>{item}</P_7><P_8A>h</P_8A>"
        "<P_8B>112</P_8B><P_9A>75.00</P_9A><P_11>8400.00</P_11><P_12>23</P_12>"
        f"</FaWiersz>{payment}</Fa></Faktura>"
    ).encode()


def _doc(xml: Optional[bytes] = None, **kw: Any) -> SimpleNamespace:
    values: dict[str, Any] = dict(
        id=1,
        ksef_number=f"{SELLER}-20261103-0000000000A1-AB",
        seller_nip=SELLER,
        seller_name="Konsultant Przykładowy",
        buyer_nip=BUYER,
        invoice_number="FV 7/2026",
        invoice_type="Vat",
        issue_date=date(2026, 11, 3),
        acquired_at=None,
        net_amount=Decimal("8400.00"),
        vat_amount=Decimal("1932.00"),
        gross_amount=Decimal("10332.00"),
        nip_state=ci.KNOWN,
        contract_id=1,
        period_month="2026-10",
        details=contractor_details.details_from(fa.parse_invoice(xml or _xml())),
        vat_whitelist=None,
    )
    values.update(kw)
    return SimpleNamespace(**values)


def _rules(level: str = "warn") -> dict[str, Any]:
    return {key: {"level": level, "params": {}} for key in invoice_fields.RULE_KEYS}


def _bad(checks: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(c["state"], c.get("detail", "")) for c in checks if c["state"] != "ok"]


# ── Odczyt XML-a ─────────────────────────────────────────────────────────────


def test_xml_daje_forme_platnosci_i_znacznik_zaplaty() -> None:
    parsed = fa.parse_invoice(_xml())
    assert (parsed.payment_form, parsed.paid) == ("6", False)
    paid = fa.parse_invoice(
        _xml(
            payment="<Platnosc><Zaplacono>1</Zaplacono>"
            "<DataZaplaty>2026-11-03</DataZaplaty>"
            "<FormaPlatnosci>1</FormaPlatnosci></Platnosc>"
        )
    )
    assert (paid.payment_form, paid.paid) == ("1", True)
    other = fa.parse_invoice(
        _xml(
            payment="<Platnosc><PlatnoscInna>1</PlatnoscInna>"
            "<OpisPlatnosci>kompensata</OpisPlatnosci></Platnosc>"
        )
    )
    assert other.payment_form == "other"
    none = fa.parse_invoice(_xml(payment=""))
    assert (none.payment_form, none.paid, none.accounts) == (None, False, ())


# ── Kontrole na karcie osoby ─────────────────────────────────────────────────


def test_zgodna_faktura_przechodzi_wszystkie_trzy_kontrole() -> None:
    checks = invoice_fields.field_checks([_doc()], _rules())
    assert [c["state"] for c in checks] == ["ok", "ok", "ok"]


def test_reguly_wylaczone_nie_dodaja_kontroli() -> None:
    assert invoice_fields.field_checks([_doc(_xml(payment=""))], _rules("off")) == []
    # Klient bez nowych kluczy w regułach (stare zestawy) = wyłączone.
    assert invoice_fields.field_checks([_doc()], {}) == []


def test_data_sprzedazy_inna_niz_koniec_miesiaca_blokuje() -> None:
    doc = _doc(_xml(sale="<P_6>2026-10-15</P_6>"))
    checks = invoice_fields.field_checks(
        [doc], {"ci.sale_date": {"level": "block", "params": {}}}
    )
    assert checks == [
        {
            "state": "fail",
            "title": "Data sprzedaży inna niż ostatni dzień miesiąca",
            "detail": "FV 7/2026: 15.10.2026 zamiast 31.10.2026.",
        }
    ]


def test_bez_p6_data_sprzedazy_to_data_wystawienia() -> None:
    late = _doc(_xml(sale=None, issue="2026-11-03"))
    assert _bad(invoice_fields.field_checks([late], _rules())) == [
        ("warn", "FV 7/2026: 03.11.2026 zamiast 31.10.2026.")
    ]
    on_time = _doc(_xml(sale=None, issue="2026-10-31"))
    assert _bad(invoice_fields.field_checks([on_time], _rules())) == []


def test_okres_faktury_konczacy_sie_ostatniego_dnia_przechodzi() -> None:
    doc = _doc(
        _xml(
            sale="<OkresFa><P_6_Od>2026-10-01</P_6_Od><P_6_Do>2026-10-31</P_6_Do></OkresFa>"
        )
    )
    assert _bad(invoice_fields.field_checks([doc], _rules())) == []


@pytest.mark.parametrize(
    "item, other",
    [
        ("Usługi IT za wrzesień 2026", "wrzesień 2026"),
        ("Usługi IT za miesiąc wrzesien", "wrzesień"),
        ("Usługi programistyczne 09.2026", "wrzesień 2026"),
        ("Usługi programistyczne 2026-09", "wrzesień 2026"),
        ("Usługi programistyczne październik 2025", "październik 2025"),
    ],
)
def test_nazwa_pozycji_z_innym_miesiacem(item: str, other: str) -> None:
    checks = invoice_fields.field_checks(
        [_doc(_xml(item=item))], {"ci.item_month": {"level": "warn", "params": {}}}
    )
    assert checks == [
        {
            "state": "warn",
            "title": "Nazwa pozycji z innym miesiącem niż rozliczany",
            "detail": f"FV 7/2026: {other} zamiast październik 2026.",
        }
    ]


@pytest.mark.parametrize(
    "item",
    [
        "Usługi programistyczne",
        "Usługi za październik",
        "Usługi 01.10.2026 - 31.10.2026",
        "Usługi wg zamówienia 3/2026, październik 2026",
        "Majątek i marketing w październiku",
    ],
)
def test_nazwa_pozycji_bez_innego_miesiaca(item: str) -> None:
    checks = invoice_fields.field_checks(
        [_doc(_xml(item=item))], {"ci.item_month": {"level": "warn", "params": {}}}
    )
    assert [c["state"] for c in checks] == ["ok"]


@pytest.mark.parametrize(
    "payment, problem",
    [
        (
            "<Platnosc><Zaplacono>1</Zaplacono><DataZaplaty>2026-11-03</DataZaplaty>"
            "</Platnosc>",
            "faktura oznaczona jako zapłacona",
        ),
        (
            "<Platnosc><FormaPlatnosci>1</FormaPlatnosci></Platnosc>",
            "gotówka zamiast przelewu",
        ),
        ("", "bez formy płatności i numeru rachunku"),
    ],
)
def test_platnosc_do_poprawy(payment: str, problem: str) -> None:
    checks = invoice_fields.field_checks(
        [_doc(_xml(payment=payment))],
        {"ci.payment_form": {"level": "block", "params": {}}},
    )
    assert checks == [
        {
            "state": "fail",
            "title": "Płatność do poprawy na fakturze",
            "detail": f"FV 7/2026: {problem}.",
        }
    ]


def test_rachunek_bez_formy_platnosci_przechodzi() -> None:
    payment = (
        "<Platnosc><RachunekBankowy><NrRB>11222233334444555566667777</NrRB>"
        "</RachunekBankowy></Platnosc>"
    )
    checks = invoice_fields.field_checks([_doc(_xml(payment=payment))], _rules())
    assert [c["state"] for c in checks] == ["ok", "ok", "ok"]


def test_bez_tresci_z_ksef_uwaga_nie_sprawdzono_a_nie_blad() -> None:
    waiting = _doc(details=None)
    failed = _doc(details={"state": "failed", "error": "ksef:not_found"})
    # Treść sprzed odczytu płatności też jeszcze nie wystarcza.
    old = _doc(details={"state": "ok", "type": "VAT", "items": []})
    checks = invoice_fields.field_checks([waiting], _rules("block"))
    assert checks == [
        {
            "state": "none",
            "title": "Pola faktury: nie sprawdzono",
            "detail": "Treść z KSeF jeszcze nie pobrana: FV 7/2026.",
        }
    ]
    assert invoice_fields.field_checks([failed], _rules())[0]["detail"].startswith(
        "Nie udało się odczytać z KSeF"
    )
    assert [c["state"] for c in invoice_fields.field_checks([old], _rules())] == [
        "none"
    ]


def test_korekty_nie_sa_sprawdzane() -> None:
    correction = _doc(_xml(sale="<P_6>2026-10-15</P_6>"), invoice_type="Kor")
    assert invoice_fields.field_checks([correction], _rules()) == []


def test_karta_osoby_pokazuje_kontrole_pol() -> None:
    settlement = SimpleNamespace(amount_cost=Decimal("8400.00"), status="accepted")
    rules = {
        "ci.amount": {"level": "block", "params": {"tolerance": "0,00"}},
        "ci.buyer_nip": {"level": "off", "params": {}},
        "ci.payment_days": {"level": "off", "params": {}},
        "ci.sale_date": {"level": "block", "params": {}},
        "ci.item_month": {"level": "off", "params": {}},
        "ci.payment_form": {"level": "warn", "params": {}},
    }
    doc = _doc(_xml(sale="<P_6>2026-10-20</P_6>", payment=""))
    block = ci.card(settlement, [doc], rules, amounts=False)
    titles = {c["title"]: c["state"] for c in block["checks"]}
    assert titles["Data sprzedaży inna niż ostatni dzień miesiąca"] == "fail"
    assert titles["Płatność do poprawy na fakturze"] == "warn"


# ── Katalog i pobieranie ─────────────────────────────────────────────────────


def test_reguly_pol_w_katalogu_domyslnie_wylaczone() -> None:
    section = next(s for s in catalog.SECTIONS if s.key == "contractor_invoice")
    keys = [r.key for r in section.rules]
    for key in invoice_fields.RULE_KEYS:
        assert key in keys
        assert catalog.RULES[key].level == "off"
        assert catalog.effective({})[key]["level"] == "off"


class _Db:
    async def flush(self) -> None:
        return None


class _Source:
    def __init__(self, xml: dict[str, bytes]) -> None:
        self.xml = xml
        self.calls: list[str] = []

    async def download_invoice(self, ksef_number: str) -> bytes:
        self.calls.append(ksef_number)
        return self.xml[ksef_number]


@pytest.mark.asyncio
async def test_xml_raz_dla_przypietej_faktury_tylko_z_bound_i_kontraktem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def row(index: int, **kw: Any) -> SimpleNamespace:
        values: dict[str, Any] = {"details": None, **kw}
        return _doc(
            id=index,
            ksef_number=f"{SELLER}-20261103-0000000000{index:0>2}-AB",
            **values,
        )

    pinned = row(1)
    old = row(2, details={"state": "ok", "type": "VAT", "items": []})
    suggested = row(3, nip_state=ci.SUGGESTED)
    no_contract = row(4, contract_id=None)
    done = row(5, details=contractor_details.details_from(fa.parse_invoice(_xml())))
    docs = [pinned, old, suggested, no_contract, done]

    async def recent(db: Any, today: date) -> list[SimpleNamespace]:
        return docs

    monkeypatch.setattr(contractor_details, "_recent", recent)
    source = _Source({d.ksef_number: _xml() for d in docs})
    counts = await contractor_details.fetch_details(
        _Db(), source, today=TODAY, budget=40
    )
    assert source.calls == [pinned.ksef_number, old.ksef_number]
    assert counts["downloads"] == 2
    assert pinned.details["paid"] is False and old.details["payment_form"] == "6"
    # Drugi przebieg nic już nie pobiera.
    again = await contractor_details.fetch_details(
        _Db(), source, today=TODAY, budget=40
    )
    assert again["downloads"] == 0
