"""Protokół odbioru zbiorczy (CeZ, PFRON) → MD osoby. Bez bazy.

Dane fikcyjne: osoby „Jan Testowy”, „Anna Inna”, „Piotr Trzeci”, projekty ALFA
i BETA, numery umów i kwoty wymyślone. Układ tekstu jak w protokołach klientów
z IX–X 2026 (tekst PDF z pdfplumber): CeZ ma tabelę „Zestawienie” z wierszem
„Imię Nazwisko Suma N” i okres „w okresie od … do …”, PFRON blok na osobę
„Specjalisty: …” z „Liczba Roboczogodzin …: N” i bez miesiąca w treści.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import (
    protocol_collective,
    rules_catalog,
    service,
)

MONTH = "2026-09"

CEZ_TWO = """Protokół odbioru
Nr Umowy Wykonawczej CeZ/99/2026
Zestawienie czasu pracy i wykonanych zadań
od do
w okresie*
01.09.2026 30.09.2026
Wytworzone utwory (m.in. kody źródłowe/wynikowe, grafiki, skrypty, dokumentacja).
1) Usługi Wsparcia zostały/nie zostały wykonane w terminie umownym**
Zamawiający Wykonawca
(Data i podpis osoby uprawnionej) (Data i podpis osoby uprawnionej)
Zestawienie
Część umowy Rola Imię i nazwisko Nazwa Projektu Typ prac Suma (liczba p ełnych RBH)
I Analityk Biznesowo-Systemowy Jan Testowy ALFA Rozwój 44
Utrzymanie 132
Jan Testowy Suma 176
Anna Inna ALFA Rozwój 85,5
Utrzymanie 74,5
Anna Inna Suma 160
Suma końcowa 336
Podsumowanie projektu/ów
Część umowy Nazwa Projektu Rozwój Utrzymanie Suma końcowa
I ALFA 129,5 206,5 336
Suma końcowa 129,5 206,5 336
Zestawienie czasu pracy i wykonywanych zadań
Jan Testowy Analityk 1.wrz ALFA Rozwój Analiza 8
1.wrz Suma 8
Piotr Trzeci Suma 999
"""

CEZ_ONE_SPLIT = """Protokół odbioru
Nr Umowy
CeZ/98/2026
Wykonawczej
Zestawienie czasu pracy i wykonanych zadań
w okresie od 05.09.2026 do 30.09.2026
(Data i podpis osoby uprawnionej) (Data i podpis osoby uprawnionej)
Suma z Godziny2
Imię i
Część umowy Rola nazwisko Nazwa Projektu Typ prac Suma
Jan
III Tester Testowy BETA Budowa 160
Suma końcowa 160,0
Podsumowanie projektu/ów
III BETA 160 160
"""

# Protokół CeZ z tabelą przestawną („Suma z Godziny”), jak CeZ/177 za X 2026: w
# zestawieniu imię i nazwisko rozbite w komórce, bez wiersza „… Suma”; osoba
# z sumą jest dopiero w tabeli szczegółów pod „Podsumowaniem”. Imię w protokole
# to zdrobnienie („Janek”), w kontrakcie „Jan”.
CEZ_PIVOT = """Protokół odbioru
Nr Umowy
CeZ/97/2026
Wykonawczej
Zestawienie czasu pracy i wykonanych zadań
w okresie od 05.10.2026 do 31.10.2026
Wytworzone utwory (m.in. kody źródłowe/wynikowe, grafiki, skrypty,
1) Usługi Wsparcia zostały/ nie zostały wykonane w terminie umownym**
Zamawiający Wykonawca
(Data i podpis osoby uprawnionej) (Data i podpis osoby uprawnionej)
Suma z Godziny2
Imię i
Część umowy Rola nazwisko Nazwa Projektu Typ prac Suma
Janek
III Tester Testowy BETA Budowa 160
Suma końcowa 160,0
Podsumowanie projektu/ów
Typ prac
Część umowy Nazwa Projektu Budowa Suma końcowa
III BETA 160 160
Suma końcowa 160 160
Zestawienie czasu pracy i wykonanych zadań
Suma z
Godziny
Imię i Data Nazwa
Rola Typ prac Podsumowanie zgłoszenia
nazwisko pracy Projektu Suma
Janek
Tester 5-10 BETA Budowa Czas pracy - spotkania zespołu 4
Testowy
[BETA-1] Plan testów sprintu S1 (28.09.2026-
5-10 BETA Budowa 156
12.10.2026)
Janek Testowy Suma 160
Łącznie 160,00
"""

PFRON = """Załącznik nr 4 do Umowy nr 2026/000099/PZP
Protokół odbioru na usługi outsourcingu specjalistów IT
Na podstawie Umowy nr: 2026/000099/PZP z dnia 22.04.2026 w związku ze:
1. Zleceniem nr 1 z dnia: 26.08.2026 Zamawiający potwierdza/nie potwierdza należyte
wykonanie przez Specjalistę/Specjalistów Prac
Specjalisty: Jan Testowy Administrator ds. sieci
Zakres wykonanych przez Specjalistę i odebranych przez Zamawiającego Prac w ramach Zlecenia w
danym okresie rozliczeniowym: zgodnie z załącznikiem nr 1 do Protokołu odbioru
Prace wykonano w terminie: Tak
Liczba Roboczogodzin wykonanych i odebranych przez Zamawiającego Prac w ramach Zlecenia w
danym okresie rozliczeniowym: 196,5
Uwagi: BRAK
Specjalisty: Anna Inna Specjalista DevOps
Zakres wykonanych przez Specjalistę i odebranych przez Zamawiającego Prac w ramach Zlecenia w
danym okresie rozliczeniowym: zgodnie z załącznikiem nr 1 do Protokołu odbioru
Liczba Roboczogodzin wykonanych i odebranych przez Zamawiającego Prac w ramach Zlecenia w
danym okresie rozliczeniowym: 90,65
Uwagi: BRAK
12 W Protokole mogą zostać ujęte jedynie Prace odebrane przez Zamawiającego w danym okresie
Wykonawcę faktury VAT, zgodnie z postanowieniami Umowy –na kwotę 1 000,00 zł
"""


def _rules(month_level: str = "block") -> dict:
    return rules_catalog.effective(
        {
            "proof.month": {"level": month_level},
            "proof.name_match": {"level": "warn"},
            "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
        }
    )


def _evaluate(
    protocol, person="Jan Testowy", month=MONTH, doc_month=None, agreements=None
):
    return protocol_collective.evaluate(
        protocol,
        month=month,
        doc_month=doc_month,
        person_name=person,
        rules=_rules(),
        working_days=22,
        **({"agreements": agreements} if agreements is not None else {}),
    )


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


# ── CeZ: tabela „Zestawienie” ────────────────────────────────────────────────


def test_cez_osoby_z_wierszy_suma_i_okres_z_naglowka():
    protocol = protocol_collective.parse_text(CEZ_TWO)

    assert protocol is not None
    assert protocol.month == MONTH
    assert [(p.name, p.hours) for p in protocol.people] == [
        ("Jan Testowy", Decimal("176")),
        ("Anna Inna", Decimal("160")),
    ]


def test_cez_md_osoby_to_godziny_przez_osiem():
    protocol = protocol_collective.parse_text(CEZ_TWO)

    assert _evaluate(protocol).md_regular == Decimal("22.000")
    assert _evaluate(protocol, person="Anna Inna").md_regular == Decimal("20.000")


def test_cez_wiersz_spod_podsumowania_nie_jest_osoba():
    protocol = protocol_collective.parse_text(CEZ_TWO)

    assert _evaluate(protocol, person="Piotr Trzeci") is None


def test_cez_suma_osob_inna_niz_suma_koncowa_to_nie_wzor():
    broken = CEZ_TWO.replace("Anna Inna Suma 160", "Anna Inna Suma 150")

    assert protocol_collective.parse_text(broken) is None


def test_cez_jedna_osoba_z_rozbitym_nazwiskiem_bierze_sume_koncowa():
    protocol = protocol_collective.parse_text(CEZ_ONE_SPLIT)

    assert protocol is not None
    assert protocol.month == MONTH
    assert len(protocol.people) == 1
    assert protocol.people[0].hours == Decimal("160.0")
    assert _evaluate(protocol).md_regular == Decimal("20.000")
    assert _evaluate(protocol, person="Anna Inna") is None


# ── CeZ: tabela przestawna i osoba z numeru umowy ────────────────────────────


def test_cez_tabela_przestawna_osoba_z_wiersza_suma_pod_podsumowaniem():
    protocol = protocol_collective.parse_text(CEZ_PIVOT)

    assert protocol is not None
    assert protocol.month == "2026-10"
    assert protocol.contract == "CEZ/97/2026"
    assert [(p.name, p.hours) for p in protocol.people] == [
        ("Janek Testowy", Decimal("160"))
    ]


def test_cez_tabela_przestawna_dwie_osoby_kazda_ze_swoimi_godzinami():
    two = CEZ_PIVOT.replace(
        "III Tester Testowy BETA Budowa 160\nSuma końcowa 160,0",
        "III Tester Testowy BETA Budowa 160\nAnna\nIII Analityk Inna BETA Budowa 168\n"
        "Suma końcowa 328,0",
    ).replace(
        "Janek Testowy Suma 160\nŁącznie 160,00",
        "Janek Testowy Suma 160\nAnna Inna Suma 168\nŁącznie 328,00",
    )

    protocol = protocol_collective.parse_text(two)

    assert [(p.name, p.hours) for p in protocol.people] == [
        ("Janek Testowy", Decimal("160")),
        ("Anna Inna", Decimal("168")),
    ]
    assert _evaluate(protocol, person="Anna Inna", month="2026-10").md_regular == (
        Decimal("21.000")
    )


def test_cez_wiersz_szczegolow_z_inna_suma_nie_daje_osoby_spod_podsumowania():
    other = CEZ_PIVOT.replace("Janek Testowy Suma 160", "Janek Testowy Suma 150")

    protocol = protocol_collective.parse_text(other)

    # Jak dotąd: osobą jest tekst zestawienia, godzinami „Suma końcowa”.
    assert len(protocol.people) == 1
    assert protocol.people[0].hours == Decimal("160.0")
    assert "Część umowy" in protocol.people[0].name


def test_cez_inne_imie_bez_numeru_umowy_osoby_nic_nie_daje():
    protocol = protocol_collective.parse_text(CEZ_PIVOT)

    assert _evaluate(protocol, month="2026-10") is None
    assert _evaluate(protocol, month="2026-10", agreements=frozenset()) is None


def test_cez_inne_imie_osobe_wskazuje_numer_umowy_tylko_tej_osoby():
    protocol = protocol_collective.parse_text(CEZ_PIVOT)

    result = _evaluate(protocol, month="2026-10", agreements=frozenset({"CEZ/97/2026"}))

    assert result.md_regular == Decimal("20.000")
    assert not result.blocking and not result.warn
    titles = _titles(result)
    assert titles["Osoba z numeru umowy CEZ/97/2026"] == "ok"
    assert "Inne imię lub nazwisko niż w kontrakcie" not in titles
    detail = next(
        c["detail"]
        for g in result.groups
        for c in g["checks"]
        if c["title"] == "Osoba z numeru umowy CEZ/97/2026"
    )
    assert "Janek Testowy" in detail


def test_cez_numer_umowy_innej_osoby_nic_nie_daje():
    protocol = protocol_collective.parse_text(CEZ_PIVOT)

    assert (
        _evaluate(protocol, month="2026-10", agreements=frozenset({"CEZ/96/2026"}))
        is None
    )


def test_cez_numer_umowy_nie_wskazuje_osoby_w_protokole_dwoch_osob():
    protocol = protocol_collective.parse_text(CEZ_TWO)

    assert (
        _evaluate(
            protocol, person="Piotr Trzeci", agreements=frozenset({"CEZ/99/2026"})
        )
        is None
    )


def test_cez_za_inny_miesiac_bez_md():
    protocol = protocol_collective.parse_text(CEZ_TWO)

    result = _evaluate(protocol, month="2026-10")

    assert result.md_regular is None
    assert result.blocking


def test_cez_okres_przez_dwa_miesiace_to_nie_wzor():
    broken = CEZ_TWO.replace("01.09.2026 30.09.2026", "01.09.2026 31.10.2026")

    assert protocol_collective.parse_text(broken) is None


# ── PFRON: blok „Specjalisty:” ───────────────────────────────────────────────


def test_pfron_osoby_z_blokow_specjalisty_bez_miesiaca_w_tresci():
    protocol = protocol_collective.parse_text(PFRON)

    assert protocol is not None
    assert protocol.month is None
    assert [p.hours for p in protocol.people] == [Decimal("196.5"), Decimal("90.65")]


def test_pfron_miesiac_z_dokumentu_daje_md():
    protocol = protocol_collective.parse_text(PFRON)

    jan = _evaluate(protocol, doc_month=MONTH)
    anna = _evaluate(protocol, person="Anna Inna", doc_month=MONTH)

    assert jan.md_regular == Decimal("24.563")
    assert anna.md_regular == Decimal("11.331")
    assert _titles(jan)["Imię i nazwisko jak w kontrakcie"] == "ok"


def test_pfron_bez_miesiaca_dokumentu_bez_md():
    protocol = protocol_collective.parse_text(PFRON)

    result = _evaluate(protocol)

    assert result.md_regular is None
    assert result.blocking


def test_pfron_osoba_spoza_protokolu_nic_nie_dostaje():
    protocol = protocol_collective.parse_text(PFRON)

    assert _evaluate(protocol, person="Piotr Trzeci", doc_month=MONTH) is None


def test_inny_pdf_to_nie_protokol_zbiorczy():
    assert protocol_collective.parse_text("Faktura VAT nr 1/09/2026\nRazem 100") is None
    assert protocol_collective.parse(b"PK\x03\x04", "application/zip") is None


# ── Rozliczenie czyta protokół z pliku miesiąca ──────────────────────────────


async def test_rozliczenie_bierze_wiersz_osoby_z_protokolu(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    content = b"%PDF-1.4 protokol testowy"
    monkeypatch.setattr(
        protocol_collective,
        "pdf_text",
        lambda data: PFRON if data == content else None,
    )
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "protokol.pdf").write_bytes(content)
    doc = CpDocument(
        id=7,
        kind="report",
        mime="application/pdf",
        file_path="consultant_portal/1/protokol.pdf",
        period_year=2026,
        period_month=9,
        period_guessed=False,
    )

    result = await service._proof(
        doc, [doc], month=MONTH, person_name="Anna Inna", rules=_rules()
    )

    assert result.md_regular == Decimal("11.331")


async def test_rozliczenie_osoby_z_innym_imieniem_po_numerze_umowy(
    tmp_path, monkeypatch
):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    content = b"%PDF-1.4 protokol przestawny"
    monkeypatch.setattr(
        protocol_collective,
        "pdf_text",
        lambda data: CEZ_PIVOT if data == content else None,
    )
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "protokol.pdf").write_bytes(content)
    doc = CpDocument(
        id=8,
        kind="report",
        mime="application/pdf",
        file_path="consultant_portal/1/protokol.pdf",
        period_year=2026,
        period_month=10,
        period_guessed=False,
    )

    without = await service._proof(
        doc, [doc], month="2026-10", person_name="Jan Testowy", rules=_rules()
    )
    result = await service._proof(
        doc,
        [doc],
        month="2026-10",
        person_name="Jan Testowy",
        rules=_rules(),
        agreements=frozenset({"CEZ/97/2026"}),
    )

    assert without is None or without.md_regular is None
    assert result.md_regular == Decimal("20.000")
