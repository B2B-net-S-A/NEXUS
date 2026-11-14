"""PIT-11, PIT-4R i PIT-8AR (K7a): XML e-Deklaracji i wydruk zestawienia.

Dane fikcyjne: osoby, PESEL-e z wymyślonych dat urodzenia (z poprawną cyfrą
kontrolną), NIP płatnika. Kody urzędów skarbowych są ze słownika e-Deklaracji
(to dane urzędów, nie osób). Pliki sprawdzone walidacją oficjalnych XSD
z crd.gov.pl poza repo (schematów nie trzymamy w repozytorium).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.services.hr.payroll_lists import forms_pdf
from app.services.hr.payroll_lists import pit_forms as pf
from app.services.hr.payroll_lists.pit_forms import (
    Pit4rMonth,
    Pit11Entry,
    Pit11Person,
    PitFormError,
)


def fake_pesel(born: date, serial: str) -> str:
    offset = {18: 80, 19: 0, 20: 20, 21: 40, 22: 60}[born.year // 100]
    base = f"{born.year % 100:02d}{born.month + offset:02d}{born.day:02d}{serial}"
    total = sum(int(d) * w for d, w in zip(base, (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)))
    return base + str((10 - total % 10) % 10)


def fake_nip(nine: str) -> str:
    control = sum(int(d) * w for d, w in zip(nine, (6, 5, 7, 2, 3, 4, 5, 6, 7))) % 11
    assert control != 10
    return nine + str(control)


PAYER = pf.TaxPayer(
    nip=fake_nip("123456786"),
    full_name="Firma Testowa Spółka Akcyjna",
    tax_office_code="1471",
)
YOUNG_BORN = date(2003, 6, 15)
YOUNG = Pit11Person(
    last_name="Przykładowa",
    first_name="Anna",
    birth_date=YOUNG_BORN,
    tax_office_code="1435",
    pesel=fake_pesel(YOUNG_BORN, "0002"),
    address=pf.PersonAddress(
        city="Warszawa",
        voivodeship="mazowieckie",
        county="m. st. Warszawa",
        municipality="Warszawa",
        street="Przykładowa",
        house_number="1",
        flat_number="2",
        postal_code="00950",
    ),
)
ADULT = Pit11Person(
    last_name="Testowy",
    first_name="Jan",
    birth_date=date(1985, 7, 21),
    tax_office_code="1438",
    pesel=fake_pesel(date(1985, 7, 21), "0011"),
)


def ns(form: pf.FormSpec) -> dict[str, str]:
    return {"d": form.namespace}


def parse(data: bytes) -> ET.Element:
    assert data.startswith(b"<?xml")
    return ET.fromstring(data)


def positions(root: ET.Element, form: pf.FormSpec) -> dict[str, str]:
    details = root.find("d:PozycjeSzczegolowe", ns(form))
    assert details is not None
    return {child.tag.split("}")[1]: child.text or "" for child in details}


def text(root: ET.Element, form: pf.FormSpec, path: str) -> str:
    found = root.find(path, ns(form))
    assert found is not None, path
    return found.text or ""


# ── PIT-11 ───────────────────────────────────────────────────────────────────


def test_youth_relief_goes_to_exempt_section_with_zero_advance() -> None:
    amounts = pf.pit11_amounts(
        [
            Pit11Entry(
                "uop",
                revenue=D("6000.00"),
                exempt_revenue=D("6000.00"),
                social=D("822.60"),
                health=D("465.97"),
                relief="youth",
                under26=True,
            ),
            Pit11Entry(
                "zlecenie",
                revenue=D("1000.00"),
                exempt_revenue=D("1000.00"),
                social=D("137.10"),
                health=D("77.66"),
                relief="youth",
                under26=True,
            ),
        ]
    )
    root = parse(pf.render_pit11(2026, PAYER, YOUNG, amounts))
    p = positions(root, pf.PIT11)

    assert p == {
        "P_11": "1",
        "P_97": "959.70",
        "P_109": "7000.00",
        "P_110": "6000.00",
        "P_111": "1000.00",
        "P_121": "2",
        "P_122": "543.63",
    }
    # Część E bez przychodu zwolnionego — ani wiersza, ani zaliczki.
    assert not {"P_29", "P_33", "P_36", "P_40", "P_58", "P_62", "P_65"} & set(p)


def test_header_payer_and_taxpayer_blocks() -> None:
    root = parse(pf.render_pit11(2026, PAYER, YOUNG, pf.Pit11Amounts()))
    form = pf.PIT11

    code = root.find("d:Naglowek/d:KodFormularza", ns(form))
    assert code is not None and code.text == "PIT-11"
    assert code.attrib == {
        "kodSystemowy": "PIT-11 (29)",
        "kodPodatku": "PIT",
        "rodzajZobowiazania": "Z",
        "wersjaSchemy": "4-0E",
    }
    assert text(root, form, "d:Naglowek/d:WariantFormularza") == "29"
    purpose = root.find("d:Naglowek/d:CelZlozenia", ns(form))
    assert purpose is not None and (purpose.text, purpose.get("poz")) == ("1", "P_7")
    assert text(root, form, "d:Naglowek/d:Rok") == "2026"
    assert text(root, form, "d:Naglowek/d:KodUrzedu") == "1435"  # urząd podatnika
    payer = root.find("d:Podmiot1", ns(form))
    assert payer is not None and payer.get("rola") == "Płatnik/Składający"
    assert text(root, form, "d:Podmiot1/d:OsobaNiefizyczna/d:NIP") == PAYER.nip
    assert (
        text(root, form, "d:Podmiot1/d:OsobaNiefizyczna/d:PelnaNazwa")
        == PAYER.full_name
    )
    person = "d:Podmiot2/d:OsobaFizyczna"
    assert text(root, form, f"{person}/d:PESEL") == YOUNG.pesel
    assert text(root, form, f"{person}/d:ImiePierwsze") == "Anna"
    assert text(root, form, f"{person}/d:Nazwisko") == "Przykładowa"
    assert text(root, form, f"{person}/d:DataUrodzenia") == "2003-06-15"
    address = root.find("d:Podmiot2/d:AdresZamieszkania", ns(form))
    assert address is not None and address.get("rodzajAdresu") == "RAD"
    country = address.find("d:KodKraju", ns(form))
    assert country is not None and (country.text, country.get("poz")) == ("PL", "P_19A")
    postal = address.find("d:KodPocztowy", ns(form))
    assert postal is not None and (postal.text, postal.get("poz")) == ("00-950", "P_27")
    assert text(root, form, "d:Pouczenie") == "1"


def test_rows_for_employment_specific_work_and_mandate_under26() -> None:
    entries = [
        Pit11Entry(
            "uop",
            revenue=D("84000.00"),
            kup=D("3000.00"),
            advance=D("6744"),
            social=D("11516.40"),
            social_deductible=D("11516.40"),
            health=D("6524.48"),
        ),
        Pit11Entry("dzielo", revenue=D("2000.00"), kup=D("400.00"), advance=D("192")),
        # Do 26 lat, limit ulgi przekroczony: przychód opodatkowany → wiersz 7.
        Pit11Entry(
            "zlecenie",
            revenue=D("1000.00"),
            exempt_revenue=D("400.00"),
            kup=D("103.55"),
            advance=D("50"),
            social=D("137.10"),
            social_deductible=D("82.26"),
            health=D("77.66"),
            relief="youth",
            under26=True,
        ),
        # Umowa do 200 zł z podatkiem ryczałtowym — PIT-8AR, nie PIT-11.
        Pit11Entry("zlecenie", revenue=D("150.00"), advance=D("18"), flat_tax=True),
    ]
    amounts = pf.pit11_amounts(entries, kup_code=3)
    p = positions(parse(pf.render_pit11(2026, PAYER, ADULT, amounts)), pf.PIT11)

    assert (p["P_28"], p["P_29"], p["P_30"], p["P_31"], p["P_33"]) == (
        "3",
        "84000.00",
        "3000.00",
        "81000.00",
        "6744",
    )
    assert (p["P_54"], p["P_55"], p["P_56"], p["P_57"]) == (
        "2000.00",
        "400.00",
        "1600.00",
        "192",
    )
    assert (p["P_62"], p["P_63"], p["P_64"], p["P_65"]) == (
        "600.00",
        "103.55",
        "496.45",
        "50",
    )
    assert "P_58" not in p  # wiersz 6 pusty
    assert p["P_95"] == "11516.40"
    assert p["P_96"] == "82.26"
    assert p["P_97"] == "54.84"
    assert (p["P_109"], p["P_111"]) == ("400.00", "400.00")
    assert "P_110" not in p
    assert p["P_122"] == "6602.14"


def test_other_reliefs_and_senior_rows() -> None:
    entries = [
        Pit11Entry(
            "uop",
            revenue=D("50000.00"),
            exempt_revenue=D("50000.00"),
            social=D("6855.00"),
            health=D("3883.05"),
            relief="family4",
        ),
        # Senior ponad limit ulgi: część opodatkowana → wiersz 3, składki → poz. 96.
        Pit11Entry(
            "uop",
            revenue=D("40000.00"),
            exempt_revenue=D("35528.00"),
            kup=D("250.00"),
            advance=D("300"),
            social=D("5484.00"),
            social_deductible=D("613.06"),
            health=D("3106.44"),
            relief="senior",
            senior_age=True,
        ),
        Pit11Entry(
            "zlecenie",
            revenue=D("1000.00"),
            kup=D("172.58"),
            advance=D("80"),
            social=D("137.10"),
            social_deductible=D("137.10"),
            health=D("77.66"),
            senior_age=True,
        ),
    ]
    amounts = pf.pit11_amounts(entries)
    p = positions(parse(pf.render_pit11(2026, PAYER, ADULT, amounts)), pf.PIT11)

    assert (p["P_43"], p["P_44"], p["P_45"], p["P_47"]) == (
        "4472.00",
        "250.00",
        "4222.00",
        "300",
    )
    assert (p["P_66"], p["P_67"], p["P_68"], p["P_69"]) == (
        "1000.00",
        "172.58",
        "827.42",
        "80",
    )
    assert not {"P_28", "P_29", "P_58"} & set(p)
    assert p["P_96"] == "750.16"
    assert "P_95" not in p
    assert p["P_97"] == str(D("6855.00") + D("5484.00") - D("613.06"))
    assert (p["P_114"], p["P_115"]) == ("85528.00", "85528.00")
    assert (p["P_119"], p["P_120"]) == ("1", "1")
    assert "P_118" not in p and "P_109" not in p


def test_relief_from_notes() -> None:
    assert pf.relief_from_notes(("relief_youth", "relief_family4")) == "youth"
    assert pf.relief_from_notes(("tax_reduction", "relief_senior")) == "senior"
    assert pf.relief_from_notes(("relief_limit",)) is None


def test_correction_and_nip_identified_taxpayer() -> None:
    person = replace(ADULT, pesel=None, nip=fake_nip("526000111"))
    root = parse(pf.render_pit11(2026, PAYER, person, pf.Pit11Amounts(), purpose="2"))
    form = pf.PIT11

    assert text(root, form, "d:Naglowek/d:CelZlozenia") == "2"
    assert text(root, form, "d:Podmiot2/d:OsobaFizyczna/d:NIP") == person.nip
    assert root.find("d:Podmiot2/d:OsobaFizyczna/d:PESEL", ns(form)) is None
    assert root.find("d:Podmiot2/d:AdresZamieszkania", ns(form)) is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"year": 2023}, "od 2024"),
        ({"purpose": "3"}, "cel złożenia"),
        ({"payer": replace(PAYER, nip="1234567861")}, "NIP"),
        ({"person": replace(ADULT, pesel=None)}, "PESEL albo"),
        ({"person": replace(ADULT, nip=fake_nip("526000111"))}, "PESEL albo"),
        ({"person": replace(ADULT, tax_office_code="14")}, "4 cyfry"),
        ({"person": replace(ADULT, pesel="22222222222")}, "powtórzonej"),
        ({"person": replace(ADULT, first_name="")}, "imię"),
        (
            {
                "amounts": pf.Pit11Amounts(
                    employment=pf.Pit11Row(D("100"), D("10"), D("1.50"))
                )
            },
            "pełnych złotych",
        ),
        (
            {"amounts": pf.Pit11Amounts(mandate=pf.Pit11Row(D("100"), D("120")))},
            "koszty wyższe",
        ),
        ({"amounts": pf.Pit11Amounts(relief_exempt_mandate=D("10"))}, "bez podstawy"),
        ({"amounts": pf.Pit11Amounts(health=D("-1"))}, "ujemna"),
    ],
)
def test_pit11_refuses_bad_input(kwargs: dict[str, object], message: str) -> None:
    args: dict[str, object] = {
        "year": 2026,
        "payer": PAYER,
        "person": ADULT,
        "amounts": pf.Pit11Amounts(),
    }
    args.update(kwargs)
    with pytest.raises(PitFormError) as caught:
        pf.render_pit11(**args)  # type: ignore[arg-type]
    assert message in caught.value.message


def test_bad_pesel_message_has_no_digits() -> None:
    assert ADULT.pesel is not None
    wrong = ADULT.pesel[:10] + str((int(ADULT.pesel[10]) + 1) % 10)
    with pytest.raises(PitFormError) as caught:
        pf.render_pit11(2026, PAYER, replace(ADULT, pesel=wrong), pf.Pit11Amounts())
    assert "PESEL" in caught.value.message
    assert wrong not in caught.value.message and wrong[-4:] not in caught.value.message


def test_pit11_amounts_refuses_inconsistent_entries() -> None:
    with pytest.raises(PitFormError, match="bez rodzaju ulgi"):
        pf.pit11_amounts([Pit11Entry("uop", revenue=D("10"), exempt_revenue=D("10"))])
    with pytest.raises(PitFormError, match="dzieło"):
        pf.pit11_amounts(
            [
                Pit11Entry(
                    "dzielo", revenue=D("10"), exempt_revenue=D("10"), relief="youth"
                )
            ]
        )
    with pytest.raises(PitFormError, match="większy od przychodu"):
        pf.pit11_amounts(
            [Pit11Entry("uop", revenue=D("10"), exempt_revenue=D("11"), relief="youth")]
        )
    with pytest.raises(PitFormError, match="rodzaj umowy"):
        pf.pit11_amounts([Pit11Entry("b2b", revenue=D("10"))])


# ── PIT-4R ───────────────────────────────────────────────────────────────────


def test_pit4r_totals_across_months() -> None:
    months = {
        1: Pit4rMonth(employment_advances=D("1200"), employment_taxpayers=3),
        2: Pit4rMonth(
            employment_advances=D("1300"),
            mandate_advances=D("90"),
            employment_taxpayers=3,
        ),
        7: Pit4rMonth(employment_advances=D("1100"), employment_taxpayers=2),
        12: Pit4rMonth(mandate_advances=D("45")),
    }
    root = parse(pf.render_pit4r(2026, PAYER, months))
    form = pf.PIT4R
    p = positions(root, form)

    code = root.find("d:Naglowek/d:KodFormularza", ns(form))
    assert code is not None and code.get("kodSystemowy") == "PIT-4R (13)"
    assert text(root, form, "d:Naglowek/d:KodUrzedu") == "1471"  # urząd płatnika
    payer = root.find("d:Podmiot1", ns(form))
    assert payer is not None and payer.get("rola") == "Płatnik"
    assert text(root, form, "d:Podmiot1/d:OsobaNiefizyczna/d:NIP") == PAYER.nip
    # Wiersz 1: liczba podatników I–VI = P_10–P_15, VII–XII = P_22–P_27.
    assert (p["P_10"], p["P_11"], p["P_15"], p["P_22"], p["P_27"]) == (
        "3",
        "3",
        "0",
        "2",
        "0",
    )
    # Wiersz 1: zaliczki I–VI = P_16–P_21, VII–XII = P_28–P_33.
    assert (p["P_16"], p["P_17"], p["P_28"], p["P_33"]) == ("1200", "1300", "1100", "0")
    # Wiersz 3: zlecenia i dzieła P_46–P_57.
    assert (p["P_47"], p["P_57"], p["P_46"]) == ("90", "45", "0")
    # Wiersze 5, 10 i 12 = suma wierszy 1 i 3.
    for first in (69, 121, 145):
        assert [p[f"P_{first + m}"] for m in (1, 2, 7, 12)] == [
            "1200",
            "1390",
            "1100",
            "45",
        ]
    yearly = sum(int(p[f"P_{145 + m}"]) for m in range(1, 13))
    assert yearly == 1200 + 1390 + 1100 + 45
    assert p["P_158"] == "2"
    assert "P_7" not in p
    assert text(root, form, "d:Pouczenia") == "1"


def test_pit4r_correction_without_employment_row() -> None:
    root = parse(
        pf.render_pit4r(2026, PAYER, {3: Pit4rMonth(mandate_advances=D("12"))}, "2")
    )
    form = pf.PIT4R
    p = positions(root, form)

    assert text(root, form, "d:Naglowek/d:CelZlozenia") == "2"
    assert p["P_7"] == "1"
    assert not {f"P_{n}" for n in range(10, 34)} & set(p)
    assert p["P_48"] == "12"
    assert p["P_148"] == "12"


@pytest.mark.parametrize(
    ("months", "message"),
    [
        ({13: Pit4rMonth()}, "1–12"),
        ({1: Pit4rMonth(employment_advances=D("10.40"))}, "pełnych złotych"),
        ({1: Pit4rMonth(employment_taxpayers=-1)}, "nieujemna"),
    ],
)
def test_pit4r_refuses_bad_input(months: dict[int, Pit4rMonth], message: str) -> None:
    with pytest.raises(PitFormError) as caught:
        pf.render_pit4r(2026, PAYER, months)
    assert message in caught.value.message


def test_pit4r_refuses_bad_payer_office() -> None:
    with pytest.raises(PitFormError, match="4 cyfry"):
        pf.render_pit4r(2026, replace(PAYER, tax_office_code="X471"), {})


# ── PIT-8AR ──────────────────────────────────────────────────────────────────


def test_pit8ar_month_mapping() -> None:
    root = parse(pf.render_pit8ar(2026, PAYER, {1: D("18"), 11: D("24")}))
    form = pf.PIT8AR
    p = positions(root, form)

    code = root.find("d:Naglowek/d:KodFormularza", ns(form))
    assert code is not None and code.text == "PIT-8AR"
    assert code.attrib["kodSystemowy"] == "PT-8AR (14)"  # tak w oficjalnym schemacie
    assert code.attrib["kodPodatku"] == "PPR"
    assert text(root, form, "d:Naglowek/d:WariantFormularza") == "14"
    # Wiersz 6 (art. 30 ust. 1 pkt 5a): P_70 = styczeń … P_81 = grudzień.
    assert (p["P_70"], p["P_80"], p["P_71"], p["P_81"]) == ("18", "24", "0", "0")
    assert (p["P_430"], p["P_440"], p["P_441"]) == ("18.00", "24.00", "0.00")
    assert (p["P_454"], p["P_464"]) == ("18.00", "24.00")
    assert p["P_466"] == "2"
    assert text(root, form, "d:Pouczenia") == "1"


def test_pit8ar_without_flat_tax_has_zero_totals_only() -> None:
    p = positions(parse(pf.render_pit8ar(2026, PAYER, {})), pf.PIT8AR)

    assert "P_70" not in p
    assert all(p[f"P_{453 + m}"] == "0.00" for m in range(1, 13))


def test_pit8ar_refuses_grosze() -> None:
    with pytest.raises(PitFormError, match="pełnych złotych"):
        pf.render_pit8ar(2026, PAYER, {5: D("18.20")})


# ── Wydruk ───────────────────────────────────────────────────────────────────


def _weasyprint_or_skip() -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:  # brak Pango poza obrazem Dockera
        pytest.skip(f"WeasyPrint niedostępny: {exc}")


def _young_amounts() -> pf.Pit11Amounts:
    return pf.Pit11Amounts(
        employment=pf.Pit11Row(D("7000.00"), D("250.00"), D("484")),
        social=D("959.70"),
        health=D("543.63"),
    )


def test_pit11_html_shows_positions_and_masked_pesel() -> None:
    html = forms_pdf.pit11_html(
        2026, PAYER, YOUNG, _young_amounts(), generated_on=date(2027, 1, 20)
    )

    assert (
        "PIT-11 za 2026 — zestawienie z NEXUSA (nie jest formularzem urzędowym)" in html
    )
    assert YOUNG.pesel is not None
    assert YOUNG.pesel not in html
    assert f"•••••••{YOUNG.pesel[-4:]}" in html
    assert "poz. 29" in html and "7\u00a0000,00\u00a0zł" in html
    assert "poz. 33" in html and "484\u00a0zł" in html
    assert "Przykładowa 1/2, 00-950 Warszawa" in html
    assert "Wygenerowano 20.01.2027" in html


def test_pit4r_html_has_month_table_with_totals() -> None:
    html = forms_pdf.pit4r_html(
        2026,
        PAYER,
        {1: Pit4rMonth(employment_advances=D("1200"), employment_taxpayers=3)},
    )

    assert "PIT-4R za 2026" in html
    assert html.count("<tr><td>") >= 12
    assert "Razem" in html
    assert "W. 12 — do wpłaty" in html
    assert "1\u00a0200\u00a0zł" in html


def test_display_formats_polish_amounts() -> None:
    field = pf.FormField("P_1", "x", "1234567.50", "g", "zl_gr")
    assert forms_pdf.display(field) == "1\u00a0234\u00a0567,50\u00a0zł"
    assert (
        forms_pdf.display(replace(field, value="1200", kind="zl"))
        == "1\u00a0200\u00a0zł"
    )
    assert forms_pdf.display(replace(field, value="2", kind="choice")) == "2"


def test_filename() -> None:
    assert forms_pdf.filename("PIT-11", 2026, "Anna Przykładowa") == (
        "pit-11-2026-anna-przykladowa.pdf"
    )
    assert forms_pdf.filename("PIT-4R", 2026) == "pit-4r-2026.pdf"


@pytest.mark.parametrize("form", ["PIT-11", "PIT-4R", "PIT-8AR"])
def test_pdfs_render(form: str) -> None:
    _weasyprint_or_skip()
    if form == "PIT-11":
        content = forms_pdf.pit11_pdf(2026, PAYER, YOUNG, _young_amounts())
    elif form == "PIT-4R":
        content = forms_pdf.pit4r_pdf(
            2026,
            PAYER,
            {1: Pit4rMonth(employment_advances=D("1200"), employment_taxpayers=3)},
        )
    else:
        content = forms_pdf.pit8ar_pdf(2026, PAYER, {1: D("18")})

    assert content.startswith(b"%PDF")
    assert len(content) > 2000
