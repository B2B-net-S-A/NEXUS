"""Rozliczenia E4: kontrole korekt i białej listy VAT przy fakturze kontraktora.

Przypadek z testu Finansów z 13.11.2026 (zanonimizowany: sprzedawca, NIP-y,
numery KSeF i nazwy fikcyjne, liczby jak w oryginale): faktura 96 h × 75 zł
z 23% VAT od podmiotu spoza białej listy, sześć korekt i nowa faktura 112 h
„zw”. Netto po wszystkim się zgadza (8 400 zł), ale korekta ze „stanem przed”
22% zamiast 23% zostawia w KSeF 72 zł VAT, dwie korekty mają zły stan przed,
dwie zły numer faktury korygowanej. Dokumenty to prawdziwe XML-e FA(3)
czytane przez ``fa.parse_invoice`` — tak jak przy pobieraniu z KSeF.

Bez bazy i bez sieci: wiersze faktur to ``SimpleNamespace``, wykaz MF to
``httpx.MockTransport``, KSeF to słownik XML-i.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional

import httpx
import pytest

from app.services.client_settlements import contractor_details, invoice_chain
from app.services.client_settlements import contractor_invoices as ci
from app.services.hr import white_list
from app.services.hr.ksef import fa
from app.services.hr.ksef.client import KsefApiError

SELLER = "1234563218"
BUYER = "9876543210"
TODAY = date(2026, 11, 13)


def _ksef(day: str, tag: str) -> str:
    return f"{SELLER}-{day.replace('-', '')}-{tag:0>12}-AB"


def _row(qty: str, net: str, rate: str, *, before: bool = False) -> str:
    return (
        "<FaWiersz><NrWierszaFa>1</NrWierszaFa><P_7>Testowanie manualne</P_7>"
        f"<P_8A>h</P_8A><P_8B>{qty}</P_8B><P_9A>75.00</P_9A><P_11>{net}</P_11>"
        f"<P_12>{rate}</P_12>{'<StanPrzed>1</StanPrzed>' if before else ''}</FaWiersz>"
    )


def _xml(
    number: str,
    issue: str,
    *,
    net: str,
    vat: str,
    gross: str,
    rows: list[str],
    zw: bool = False,
    corrected: Optional[tuple[str, str, str]] = None,
    reason: Optional[str] = None,
) -> bytes:
    amounts = (
        f"<P_13_7>{net}</P_13_7>"
        if zw
        else f"<P_13_1>{net}</P_13_1><P_14_1>{vat}</P_14_1>"
    )
    korekta = ""
    kind = "VAT"
    if corrected is not None:
        kind = "KOR"
        ksef, nr, day = corrected
        korekta = (
            f"<PrzyczynaKorekty>{reason or 'Liczba godzin'}</PrzyczynaKorekty>"
            "<TypKorekty>1</TypKorekty><DaneFaKorygowanej>"
            f"<DataWystFaKorygowanej>{day}</DataWystFaKorygowanej>"
            f"<NrFaKorygowanej>{nr}</NrFaKorygowanej><NrKSeF>1</NrKSeF>"
            f"<NrKSeFFaKorygowanej>{ksef}</NrKSeFFaKorygowanej></DaneFaKorygowanej>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">'
        "<Naglowek><KodFormularza>FA</KodFormularza>"
        "<WariantFormularza>3</WariantFormularza></Naglowek>"
        f"<Podmiot1><DaneIdentyfikacyjne><NIP>{SELLER}</NIP>"
        "<Nazwa>Konsultant Przykładowy Usługi IT</Nazwa></DaneIdentyfikacyjne></Podmiot1>"
        f"<Podmiot2><DaneIdentyfikacyjne><NIP>{BUYER}</NIP>"
        "<Nazwa>Spółka Testowa</Nazwa></DaneIdentyfikacyjne></Podmiot2>"
        f"<Fa><KodWaluty>PLN</KodWaluty><P_1>{issue}</P_1><P_2>{number}</P_2>"
        f"<P_6>2026-10-31</P_6>{amounts}<P_15>{gross}</P_15>"
        f"<RodzajFaktury>{kind}</RodzajFaktury>{korekta}{''.join(rows)}</Fa></Faktura>"
    ).encode()


FV1 = ("FV 1/10/2026", "2026-10-29", _ksef("2026-10-29", "A1"))
K2 = ("2/K/11/2026", "2026-11-09", _ksef("2026-11-09", "B2"))
K3 = ("3/K/11/2026", "2026-11-09", _ksef("2026-11-09", "B3"))
TO_FV1 = (FV1[2], FV1[0], FV1[1])

#: (numer, data, numer KSeF, kwoty netto/VAT/brutto, XML).
CASE: list[tuple[str, str, str, str, str, str, bytes]] = []


def _add(
    number: str, issue: str, ksef: str, net: str, vat: str, gross: str, **kw: Any
) -> None:
    CASE.append(
        (
            number,
            issue,
            ksef,
            net,
            vat,
            gross,
            _xml(number, issue, net=net, vat=vat, gross=gross, **kw),
        )
    )


_add(*FV1, "7200.00", "1656.00", "8856.00", rows=[_row("96", "7200.00", "23")])
_add(
    "1/K/11/2026",
    "2026-11-09",
    _ksef("2026-11-09", "B1"),
    "0.00",
    "0.00",
    "0.00",
    rows=[],
    corrected=TO_FV1,
    reason="Liczba godzin",
)
_add(
    *K2,
    "1200.00",
    "348.00",
    "1548.00",
    rows=[_row("96", "7200.00", "22", before=True), _row("112", "8400.00", "23")],
    corrected=TO_FV1,
)
_add(
    *K3,
    "1200.00",
    "0.00",
    "1200.00",
    zw=True,
    rows=[_row("96", "7200.00", "zw", before=True), _row("112", "8400.00", "zw")],
    corrected=TO_FV1,
)
_add(
    "4/K/11/2026",
    "2026-11-10",
    _ksef("2026-11-10", "C4"),
    "-7200.00",
    "-1656.00",
    "-8856.00",
    rows=[_row("96", "7200.00", "23", before=True), _row("0", "0.00", "23")],
    corrected=TO_FV1,
)
# Korekty korekt: numer KSeF dobry, numer faktury przepisany z pierwotnej.
_add(
    "5/K/11/2026",
    "2026-11-10",
    _ksef("2026-11-10", "C5"),
    "-1200.00",
    "-276.00",
    "-1476.00",
    rows=[_row("16", "1200.00", "23", before=True), _row("0", "0.00", "23")],
    corrected=(K2[2], FV1[0], K2[1]),
)
_add(
    "6/K/11/2026",
    "2026-11-10",
    _ksef("2026-11-10", "C6"),
    "-1200.00",
    "0.00",
    "-1200.00",
    zw=True,
    rows=[_row("16", "1200.00", "zw", before=True), _row("0", "0.00", "zw")],
    corrected=(K3[2], FV1[0], FV1[1]),
)
_add(
    "FV 2/11/2026",
    "2026-11-10",
    _ksef("2026-11-10", "C7"),
    "8400.00",
    "0.00",
    "8400.00",
    zw=True,
    rows=[_row("112", "8400.00", "zw")],
)


def _doc(
    index: int,
    number: str,
    issue: str,
    ksef: str,
    net: str,
    vat: str,
    gross: str,
    xml: bytes,
    **kw: Any,
) -> SimpleNamespace:
    parsed = fa.parse_invoice(xml)
    values = dict(
        id=index + 1,
        ksef_number=ksef,
        seller_nip=SELLER,
        seller_name="Konsultant Przykładowy Usługi IT",
        buyer_nip=BUYER,
        invoice_number=number,
        invoice_type="Kor" if parsed.kind == "correction" else "Vat",
        issue_date=date.fromisoformat(issue),
        acquired_at=None,
        net_amount=Decimal(net),
        vat_amount=Decimal(vat),
        gross_amount=Decimal(gross),
        nip_state=ci.KNOWN,
        contract_id=1,
        period_month="2026-10",
        details=contractor_details.details_from(parsed),
        vat_whitelist={
            "state": "ok",
            "status": "absent",
            "on_date": issue,
            "request_id": "req",
        },
    )
    values.update(kw)
    return SimpleNamespace(**values)


def _case(**kw: Any) -> list[SimpleNamespace]:
    return [_doc(i, *entry, **kw) for i, entry in enumerate(CASE)]


def _titles(checks: list[dict[str, Any]], state: Optional[str] = None) -> list[str]:
    return [c["title"] for c in checks if state is None or c["state"] == state]


# ── Odczyt XML-a ─────────────────────────────────────────────────────────────


def test_fa_czyta_dane_faktury_korygowanej_i_powod() -> None:
    parsed = fa.parse_invoice(CASE[6][6])
    assert parsed.kind == "correction"
    assert parsed.corrected == (
        {
            "ksef_number": K3[2],
            "invoice_number": "FV 1/10/2026",
            "issue_date": "2026-10-29",
        },
    )
    assert parsed.correction_reason == "Liczba godzin"
    assert [i.get("before_correction", False) for i in parsed.items] == [True, False]
    assert fa.parse_invoice(CASE[0][6]).corrected == ()


# ── Przypadek z testu Finansów ───────────────────────────────────────────────


def test_przypadek_z_szescioma_korektami_daje_wszystkie_ostrzezenia() -> None:
    docs = _case()
    assert sum(d.net_amount for d in docs) == Decimal("8400.00")
    checks = invoice_chain.chain_checks(docs, amounts=True)
    warns = _titles(checks, "warn")
    assert "Korekty zostawiają 72,00 zł VAT" in warns
    assert sorted(t for t in warns if t.startswith("Zły stan przed")) == [
        "Zły stan przed w korekcie 2/K/11/2026",
        "Zły stan przed w korekcie 3/K/11/2026",
    ]
    assert sorted(t for t in warns if "faktury korygowanej" in t) == [
        "Zły numer faktury korygowanej w 5/K/11/2026",
        "Zły numer faktury korygowanej w 6/K/11/2026",
    ]
    assert len(warns) == 5
    assert _titles(checks, "none") == ["Korekta 1/K/11/2026 bez zmian kwot"]
    assert "Korekty zgodne po netto, VAT i brutto" not in _titles(checks)

    by_title = {c["title"]: c.get("detail", "") for c in checks}
    assert by_title["Zły stan przed w korekcie 2/K/11/2026"] == (
        "W korekcie: 96 h, 22%, 7 200,00 zł. FV 1/10/2026 ma: 96 h, 23%, 7 200,00 zł."
    )
    assert (
        "wpisano: numer FV 1/10/2026, data 29.10.2026"
        in by_title["Zły numer faktury korygowanej w 6/K/11/2026"]
    )
    assert (
        "wpisano: numer FV 1/10/2026."
        in by_title["Zły numer faktury korygowanej w 5/K/11/2026"]
    )
    assert (
        "netto 0,00 zł, VAT 72,00 zł, brutto 72,00 zł"
        in by_title["Korekty zostawiają 72,00 zł VAT"]
    )
    assert (
        "Powód w korekcie: Liczba godzin."
        == by_title["Korekta 1/K/11/2026 bez zmian kwot"]
    )


def test_bez_dostepu_do_kwot_ostrzezenia_bez_zlotowek() -> None:
    checks = invoice_chain.chain_checks(_case(), amounts=False)
    text = " ".join(f"{c['title']} {c.get('detail', '')}" for c in checks)
    assert "Korekty zostawiają VAT do skorygowania" in text
    assert "zł" not in text


def test_sprzedawca_spoza_bialej_listy_vat_nie_do_odliczenia() -> None:
    checks = invoice_chain.whitelist_checks(_case(), amounts=True, mode="live")
    assert _titles(checks) == [
        "Sprzedawca nie jest podatnikiem VAT, VAT nie do odliczenia"
    ]
    detail = checks[0]["detail"]
    assert detail.startswith(
        "Biała lista na 29.10.2026: brak w wykazie podatników VAT."
    )
    # VAT pierwotnej, 2/K, 4/K i 5/K — po korektach 72 zł, których nie odliczamy.
    assert detail.endswith(": 72,00 zł.")
    assert "FV 2/11/2026" not in detail


def test_karta_osoby_pokazuje_ostrzezenia_obok_zgodnej_kwoty() -> None:
    docs = _case()
    settlement = SimpleNamespace(amount_cost=Decimal("8400.00"), status="accepted")
    rules = {
        "ci.amount": {"level": "block", "params": {"tolerance": "0,00"}},
        "ci.buyer_nip": {"level": "warn", "params": {"nip": BUYER}},
        "ci.payment_days": {"level": "off", "params": {}},
    }
    block = ci.card(settlement, docs, rules, amounts=True)
    assert block["state"] == ci.IN_KSEF
    titles = _titles(block["checks"])
    assert titles[0] == "Kwota równa wyliczeniu z RCP"
    for title in (
        "Korekty zostawiają 72,00 zł VAT",
        "Zły stan przed w korekcie 2/K/11/2026",
        "Zły numer faktury korygowanej w 6/K/11/2026",
        "Sprzedawca nie jest podatnikiem VAT, VAT nie do odliczenia",
        "NIP nabywcy zgodny",
    ):
        assert title in titles
    assert len(titles) == len(set(titles))  # klucz wiersza w UI to tytuł
    assert [i["is_correction"] for i in block["invoices"]] == [
        False,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
    ]


# ── Poprawne łańcuchy i braki ────────────────────────────────────────────────


def _proper_chain() -> list[SimpleNamespace]:
    fv = ("FV 7/10/2026", "2026-10-30", _ksef("2026-10-30", "D1"))
    first = _xml(
        *fv[:2],
        net="7200.00",
        vat="1656.00",
        gross="8856.00",
        rows=[_row("96", "7200.00", "23")],
    )
    k1 = _xml(
        "1/K/2026",
        "2026-11-05",
        net="1200.00",
        vat="276.00",
        gross="1476.00",
        rows=[_row("96", "7200.00", "23", before=True), _row("112", "8400.00", "23")],
        corrected=(fv[2], fv[0], fv[1]),
    )
    # Druga korekta do tej samej faktury pierwotnej, stan przed = stan po pierwszej.
    k2 = _xml(
        "2/K/2026",
        "2026-11-06",
        net="-600.00",
        vat="-138.00",
        gross="-738.00",
        rows=[_row("112", "8400.00", "23", before=True), _row("104", "7800.00", "23")],
        corrected=(fv[2], fv[0], fv[1]),
    )
    return [
        _doc(0, *fv, "7200.00", "1656.00", "8856.00", first),
        _doc(
            1,
            "1/K/2026",
            "2026-11-05",
            _ksef("2026-11-05", "D2"),
            "1200.00",
            "276.00",
            "1476.00",
            k1,
        ),
        _doc(
            2,
            "2/K/2026",
            "2026-11-06",
            _ksef("2026-11-06", "D3"),
            "-600.00",
            "-138.00",
            "-738.00",
            k2,
        ),
    ]


def test_poprawny_lancuch_korekt_jest_zielony() -> None:
    checks = invoice_chain.chain_checks(_proper_chain(), amounts=True)
    assert checks == [{"state": "ok", "title": "Korekty zgodne po netto, VAT i brutto"}]


def test_vat_po_korektach_inny_niz_netto_razy_stawka() -> None:
    docs = _proper_chain()
    docs[2].vat_amount = Decimal("-100.00")
    docs[2].gross_amount = Decimal("-700.00")
    checks = invoice_chain.chain_checks(docs, amounts=True)
    assert _titles(checks, "warn") == ["Korekty zostawiają 38,00 zł VAT"]
    assert checks[0]["detail"].endswith(
        "Przy tej stawce VAT powinien wynosić 1 794,00 zł."
    )


def test_brutto_inne_niz_netto_plus_vat() -> None:
    docs = _proper_chain()
    docs[1].gross_amount = Decimal("1500.00")
    assert "Brutto korekt do FV 7/10/2026 nie zgadza się z netto i VAT" in _titles(
        invoice_chain.chain_checks(docs, amounts=True), "warn"
    )


def test_korekta_bez_tresci_z_ksef_nie_sprawdzona_zamiast_falszywego_alarmu() -> None:
    docs = _case()
    docs[2].details = None
    docs[5].details = {"state": "failed", "error": "ksef:not_found"}
    checks = invoice_chain.chain_checks(docs, amounts=True)
    assert checks[0]["state"] == "none"
    assert checks[0]["title"] == "Korekty: nie sprawdzono łańcucha"
    assert "2/K/11/2026, 5/K/11/2026" in checks[0]["detail"]
    assert not any(t.startswith("Korekty zostawiają") for t in _titles(checks))


def test_korekta_do_faktury_spoza_rozliczenia() -> None:
    docs = [d for d in _case() if d.invoice_number != "FV 1/10/2026"][:1]
    checks = invoice_chain.chain_checks(docs, amounts=True)
    assert _titles(checks, "warn") == [
        "Korekta 1/K/11/2026 wskazuje fakturę spoza rozliczenia"
    ]


def test_bez_korekt_brak_kontroli_lancucha() -> None:
    assert invoice_chain.chain_checks([_case()[-1]], amounts=True) == []


# ── Biała lista: pozostałe wyniki ────────────────────────────────────────────


def _whitelist(
    docs: list[SimpleNamespace], result: Optional[dict[str, Any]]
) -> list[SimpleNamespace]:
    for doc in docs:
        doc.vat_whitelist = result
    return docs


def test_faktura_zw_od_czynnego_podatnika() -> None:
    docs = _whitelist(
        [_case()[-1]], {"state": "ok", "status": "active", "on_date": "2026-11-10"}
    )
    checks = invoice_chain.whitelist_checks(docs, amounts=True, mode="live")
    assert _titles(checks) == ["Faktura bez VAT od czynnego podatnika VAT"]
    assert checks[0]["detail"].startswith("FV 2/11/2026: VAT 0 zł")


def test_czynny_podatnik_z_vat_jest_zielony() -> None:
    docs = _whitelist(
        [_case()[0]], {"state": "ok", "status": "active", "on_date": "2026-10-29"}
    )
    assert invoice_chain.whitelist_checks(docs, amounts=True, mode="live") == [
        {"state": "ok", "title": "Biała lista VAT: czynny podatnik VAT"}
    ]


@pytest.mark.parametrize(
    ("mode", "result", "reason"),
    [
        ("off", None, "Sprawdzanie białej listy VAT jest wyłączone."),
        ("live", None, "Czeka na sprawdzenie przy pobieraniu z KSeF."),
        (
            "live",
            {"state": "error", "code": "unavailable"},
            "Wykaz podatników VAT nie odpowiadał.",
        ),
    ],
)
def test_biala_lista_bez_odpowiedzi_to_nie_sprawdzono(
    mode: str, result: Optional[dict[str, Any]], reason: str
) -> None:
    checks = invoice_chain.whitelist_checks(
        _whitelist(_case()[:1], result), amounts=True, mode=mode
    )
    assert checks == [
        {
            "state": "none",
            "title": "Biała lista VAT: nie sprawdzono",
            "detail": f"{reason} Dotyczy: FV 1/10/2026.",
        }
    ]


# ── Pobieranie treści korekt (contractor_details) ────────────────────────────


class _Db:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


class _Source:
    def __init__(self, xml: dict[str, bytes], error: Optional[str] = None) -> None:
        self.xml = xml
        self.error = error
        self.calls: list[str] = []

    async def download_invoice(self, ksef_number: str) -> bytes:
        self.calls.append(ksef_number)
        if self.error:
            raise KsefApiError(self.error)
        return self.xml[ksef_number]


def _stored(monkeypatch: pytest.MonkeyPatch) -> list[SimpleNamespace]:
    """Wiersze jak po zapisie z metadanych: bez treści, korekty w listopadzie."""

    docs = _case(details=None, vat_whitelist=None)
    for doc in docs:
        if doc.invoice_type == "Kor":
            doc.period_month = "2026-11"

    async def recent(db: Any, today: date) -> list[SimpleNamespace]:
        return docs

    monkeypatch.setattr(contractor_details, "_recent", recent)
    return docs


@pytest.mark.asyncio
async def test_pobiera_tylko_korekty_i_korygowane_i_przenosi_korekty_do_miesiaca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs = _stored(monkeypatch)
    source = _Source({entry[2]: entry[6] for entry in CASE})
    counts = await contractor_details.fetch_details(
        _Db(), source, today=TODAY, budget=40
    )
    # Sześć korekt i faktura pierwotna; nowa faktura 2/11 bez korekty — bez pobrania.
    assert counts == {"downloads": 7, "moved": 6}
    assert CASE[-1][2] not in source.calls
    assert docs[-1].details is None
    assert all(d.period_month == "2026-10" for d in docs[:-1])
    checks = invoice_chain.chain_checks(docs, amounts=True)
    assert "Korekty zostawiają 72,00 zł VAT" in _titles(checks)


@pytest.mark.asyncio
async def test_pobieranie_w_budzecie_przebiegu(monkeypatch: pytest.MonkeyPatch) -> None:
    docs = _stored(monkeypatch)
    source = _Source({entry[2]: entry[6] for entry in CASE})
    counts = await contractor_details.fetch_details(
        _Db(), source, today=TODAY, budget=3
    )
    assert counts["downloads"] == 3
    assert sum(1 for d in docs if d.details) == 3


@pytest.mark.asyncio
async def test_ksef_niegotowy_zostawia_korekte_w_kolejce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs = _stored(monkeypatch)
    await contractor_details.fetch_details(
        _Db(), _Source({}, "not_ready"), today=TODAY, budget=40
    )
    assert docs[1].details == {"state": "pending", "attempts": 1}
    with pytest.raises(KsefApiError):
        await contractor_details.fetch_details(
            _Db(), _Source({}, "rate_limited"), today=TODAY, budget=40
        )
    await contractor_details.fetch_details(
        _Db(), _Source({}, "not_found"), today=TODAY, budget=40
    )
    assert docs[1].details == {"state": "failed", "error": "ksef:not_found"}


# ── Biała lista przy pobieraniu ──────────────────────────────────────────────


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch):
    calls: list[httpx.Request] = []
    state: dict[str, Any] = {"error": None}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if state["error"] is not None:
            raise state["error"]
        meta = {
            "requestId": f"req-{len(calls)}",
            "requestDateTime": "13-11-2026 10:00:00",
        }
        return httpx.Response(200, json={"result": {"subject": None, **meta}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        white_list,
        "_http_client",
        lambda base_url: httpx.AsyncClient(base_url=base_url, transport=transport),
    )
    monkeypatch.setattr(white_list.settings, "WHITE_LIST_MODE", "live")
    monkeypatch.setattr(white_list, "business_today", lambda: TODAY)
    white_list.reset_memory()
    yield SimpleNamespace(calls=calls, state=state)
    white_list.reset_memory()


NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_biala_lista_raz_na_nip_i_dzien(
    monkeypatch: pytest.MonkeyPatch, registry
) -> None:
    docs = _stored(monkeypatch)
    counts = await contractor_details.check_whitelist(_Db(), today=TODAY, now=NOW)
    # Trzy dni wystawienia (29.10, 09.11, 10.11) = trzy zapytania na osiem dokumentów.
    assert len(registry.calls) == 3
    assert counts == {"whitelist": 3, "whitelist_errors": 0}
    assert {d.vat_whitelist["status"] for d in docs} == {"absent"}
    assert docs[0].vat_whitelist["on_date"] == "2026-10-29"
    await contractor_details.check_whitelist(_Db(), today=TODAY, now=NOW)
    assert len(registry.calls) == 3


@pytest.mark.asyncio
async def test_awaria_wykazu_daje_nie_sprawdzono_bez_blokady(
    monkeypatch: pytest.MonkeyPatch, registry
) -> None:
    docs = _stored(monkeypatch)
    registry.state["error"] = httpx.ConnectError("brak sieci")
    counts = await contractor_details.check_whitelist(_Db(), today=TODAY, now=NOW)
    assert counts == {"whitelist": 0, "whitelist_errors": 1}
    assert len(registry.calls) == 1  # awaria przerywa przebieg, reszta czeka
    assert docs[0].vat_whitelist["state"] == "error"
    assert docs[1].vat_whitelist is None
    settlement = SimpleNamespace(amount_cost=Decimal("8400.00"), status="accepted")
    rules = {
        "ci.amount": {"level": "block", "params": {"tolerance": "0"}},
        "ci.buyer_nip": {"level": "off", "params": {}},
        "ci.payment_days": {"level": "off", "params": {}},
    }
    block = ci.card(settlement, docs, rules, amounts=True)
    assert block["state"] == ci.IN_KSEF
    whitelist = [c for c in block["checks"] if c["title"].startswith("Biała lista")]
    assert whitelist[0]["state"] == "none"
    assert whitelist[0]["detail"].startswith("Wykaz podatników VAT nie odpowiadał.")
    # Ponowienie w kolejnym przebiegu, gdy wykaz odpowiada.
    registry.state["error"] = None
    await contractor_details.check_whitelist(_Db(), today=TODAY, now=NOW)
    assert docs[0].vat_whitelist["state"] == "ok"


@pytest.mark.asyncio
async def test_biala_lista_wylaczona_nie_pyta(
    monkeypatch: pytest.MonkeyPatch, registry
) -> None:
    _stored(monkeypatch)
    monkeypatch.setattr(white_list.settings, "WHITE_LIST_MODE", "off")
    assert await contractor_details.check_whitelist(_Db(), today=TODAY, now=NOW) == {
        "whitelist": 0,
        "whitelist_errors": 0,
    }
    assert registry.calls == []


def case_for(seller: str) -> list[tuple[str, str, str, str, str, str, bytes]]:
    """Ten sam przypadek z innym NIP-em sprzedawcy i unikalnymi numerami KSeF
    (testy na bazie: numer KSeF jest unikalny w tabeli)."""

    import uuid

    renamed = {
        entry[
            2
        ]: f"{seller}-{entry[1].replace('-', '')}-{uuid.uuid4().hex[:12].upper()}-AB"
        for entry in CASE
    }
    out = []
    for number, issue, ksef, net, vat, gross, xml in CASE:
        text = xml.decode().replace(f"<NIP>{SELLER}</NIP>", f"<NIP>{seller}</NIP>")
        for old, new in renamed.items():
            text = text.replace(old, new)
        out.append((number, issue, renamed[ksef], net, vat, gross, text.encode()))
    return out
