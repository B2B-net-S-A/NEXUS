"""KEDU (K7a): DRA + RCA (+ RSA) miesiąca i zgłoszenia ZUA, ZZA, ZWUA.

Dane fikcyjne: osoby, PESEL-e (zbudowane z wymyślonych dat urodzenia z poprawną
cyfrą kontrolną), NIP i REGON płatnika. Kwoty wpisane ręcznie — test sprawdza
plik, nie silnik. Struktura sprawdzona walidacją XSD KEDU 5.7 z BIP ZUS poza
repo (schematu nie trzymamy w repozytorium).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.services.hr.payroll_lists import kedu
from app.services.hr.payroll_lists.kedu import (
    KeduAddress,
    KeduBreak,
    KeduError,
    KeduInsured,
    KeduMonth,
    KeduPayer,
    KeduPerson,
    KeduRegistration,
    KeduTermination,
)

NS = {"k": kedu.NAMESPACE}
CREATED = date(2026, 12, 4)


def fake_pesel(born: date, serial: str) -> str:
    offset = {18: 80, 19: 0, 20: 20, 21: 40, 22: 60}[born.year // 100]
    base = f"{born.year % 100:02d}{born.month + offset:02d}{born.day:02d}{serial}"
    total = sum(int(d) * w for d, w in zip(base, (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)))
    return base + str((10 - total % 10) % 10)


def fake_nip(nine: str) -> str:
    control = sum(int(d) * w for d, w in zip(nine, (6, 5, 7, 2, 3, 4, 5, 6, 7))) % 11
    assert control != 10
    return nine + str(control)


def fake_regon(eight: str) -> str:
    control = sum(int(d) * w for d, w in zip(eight, (8, 9, 2, 3, 4, 5, 6, 7))) % 11
    return eight + str(control % 10)


PAYER = KeduPayer(
    nip=fake_nip("123456786"),
    regon=fake_regon("12345678"),
    short_name="Firma Testowa S.A.",
)
ANNA = KeduPerson("Przykładowa", "Anna", "P", fake_pesel(date(1990, 3, 3), "0002"))
JAN = KeduPerson("Testowy", "Jan", "P", fake_pesel(date(1985, 7, 21), "0011"))
PIOTR = KeduPerson("Zmyślony", "Piotr", "P", fake_pesel(date(1999, 1, 15), "0031"))


def employee(person: KeduPerson, gross: str, **kw: object) -> KeduInsured:
    """Pracownik: składki z kwotami wpisanymi ręcznie (stawki 2026)."""

    base: dict[str, object] = dict(
        person=person,
        title_code="011000",
        pension_basis=D(gross),
        sickness_basis=D(gross),
        accident_basis=D(gross),
        work_time=(1, 1),
    )
    base.update(kw)
    return KeduInsured(**base)  # type: ignore[arg-type]


INSURED = (
    employee(
        ANNA,
        "7800.00",
        pension_employee=D("761.28"),
        disability_employee=D("117.00"),
        sickness_employee=D("191.10"),
        pension_employer=D("761.28"),
        disability_employer=D("507.00"),
        accident_employer=D("130.26"),
        health_basis=D("6730.62"),
        health=D("605.76"),
        ppk_employer=D("117.00"),
    ),
    employee(
        JAN,
        "12000.00",
        pension_employee=D("1171.20"),
        disability_employee=D("180.00"),
        sickness_employee=D("294.00"),
        pension_employer=D("1171.20"),
        disability_employer=D("780.00"),
        accident_employer=D("200.40"),
        health_basis=D("10354.80"),
        health=D("931.93"),
        annual_limit_code="2",
    ),
    KeduInsured(
        person=PIOTR,
        title_code="0411 0 0",
        pension_basis=D("3000.00"),
        accident_basis=D("3000.00"),
        pension_employee=D("292.80"),
        disability_employee=D("45.00"),
        pension_employer=D("292.80"),
        disability_employer=D("195.00"),
        accident_employer=D("50.10"),
        health_basis=D("2662.20"),
        health=D("239.60"),
    ),
)


def month(**kw: object) -> KeduMonth:
    base: dict[str, object] = dict(
        year=2026,
        month=11,
        payer=PAYER,
        insured=INSURED,
        labour_fund=D("485.10"),
        fgsp=D("22.80"),
        accident_rate=D("1.67"),
        created_on=CREATED,
    )
    base.update(kw)
    return KeduMonth(**base)  # type: ignore[arg-type]


def parse(data: bytes) -> ET.Element:
    assert data.startswith(b"<?xml")
    return ET.fromstring(data)


def text(node: ET.Element, path: str) -> str:
    found = node.find(path, NS)
    assert found is not None, path
    return found.text or ""


def leaves(node: ET.Element, block: str) -> dict[str, str]:
    """Pola bloku bez podelementów (kod tytułu i wymiar czasu pomijane)."""

    found = node.find(block, NS)
    assert found is not None, block
    return {
        child.tag.split("}")[1]: child.text or "" for child in found if len(child) == 0
    }


def amounts(node: ET.Element, block: str) -> dict[str, D]:
    return {key: D(value) for key, value in leaves(node, block).items()}


def total(attr: str) -> D:
    return sum((getattr(item, attr) for item in INSURED), D("0"))


# ── Deklaracja miesiąca ──────────────────────────────────────────────────────


def test_month_is_kedu_with_dra_and_rca_only() -> None:
    root = parse(kedu.render_month(month()))

    assert root.tag == f"{{{kedu.NAMESPACE}}}KEDU"
    assert root.get("wersja_schematu") == "1"
    assert text(root, "k:naglowek.KEDU/k:program/k:producent") == "NEXUS"
    assert text(root, "k:naglowek.KEDU/k:data_utworzenia_KEDU") == "2026-12-04"
    docs = [child.tag.split("}")[1] for child in root if "ZUS" in child.tag]
    assert docs == ["ZUSDRA", "ZUSRCA"]
    assert [d.get("id_dokumentu") for d in root if "ZUS" in d.tag] == ["1", "2"]


def test_period_identifier_and_payer_blocks() -> None:
    root = parse(kedu.render_month(month(declaration_id=2)))
    dra = root.find("k:ZUSDRA", NS)
    rca = root.find("k:ZUSRCA", NS)
    assert dra is not None and rca is not None

    assert text(dra, "k:I/k:p1") == "3"  # do 15. dnia — osoba prawna
    assert text(dra, "k:I/k:p2/k:p1") == "02"
    assert text(dra, "k:I/k:p2/k:p2") == "2026-11"
    assert text(rca, "k:I/k:p1/k:p1") == "02"
    assert text(rca, "k:I/k:p1/k:p2") == "2026-11"
    for doc in (dra, rca):
        assert text(doc, "k:II/k:p1") == PAYER.nip
        assert text(doc, "k:II/k:p2") == PAYER.regon
        assert text(doc, "k:II/k:p6") == "FIRMA TESTOWA S.A."
    assert text(dra, "k:XIII/k:p1") == "2026-12-04"
    assert text(rca, "k:IV/k:p1") == "2026-12-04"


def test_dra_totals_are_sums_of_rca_plus_funds() -> None:
    root = parse(kedu.render_month(month()))
    dra = root.find("k:ZUSDRA", NS)
    assert dra is not None
    iv = amounts(dra, "k:IV")

    pension = total("pension_employee") + total("pension_employer")
    disability = total("disability_employee") + total("disability_employer")
    social = (
        pension + disability + total("sickness_employee") + total("accident_employer")
    )
    assert iv["p1"] == pension
    assert iv["p2"] == disability
    assert iv["p3"] == pension + disability
    assert iv["p4"] == total("pension_employee")
    assert iv["p6"] == total("pension_employee") + total("disability_employee")
    assert iv["p9"] == total("pension_employer") + total("disability_employer")
    assert iv["p19"] == iv["p22"] == iv["p24"] == total("sickness_employee")
    assert iv["p20"] == iv["p26"] == iv["p27"] == total("accident_employer")
    assert iv["p37"] == social == D("7140.42")
    # „Nie wypełniać”: PFRON i chorobowa z Funduszu Kościelnego.
    assert not {"p13", "p14", "p15", "p31", "p32", "p33", "p34"} & set(iv)

    vi = amounts(dra, "k:VI")
    assert vi["p2"] == vi["p5"] == vi["p7"] == total("health") == D("1777.29")
    assert "p6" not in vi
    vii = amounts(dra, "k:VII")
    assert (vii["p1"], vii["p2"], vii["p3"]) == (D("485.10"), D("22.80"), D("507.90"))
    ix = amounts(dra, "k:IX")
    assert ix == {"p1": D("0.00"), "p2": social + total("health") + D("507.90")}
    assert text(dra, "k:III/k:p1") == "3"
    assert text(dra, "k:III/k:p3") == "1.67"


def test_rca_blocks_title_codes_work_time_and_amounts() -> None:
    root = parse(kedu.render_month(month()))
    blocks = root.findall("k:ZUSRCA/k:III", NS)

    assert [b.get("id_bloku") for b in blocks] == ["1", "2", "3"]
    anna, jan, piotr = blocks
    assert text(anna, "k:A/k:p1") == "PRZYKŁADOWA"
    assert text(anna, "k:A/k:p2") == "ANNA"
    assert text(anna, "k:A/k:p3") == "P"
    assert text(anna, "k:A/k:p4") == ANNA.id_number
    assert [text(anna, f"k:B/k:p1/k:p{n}") for n in (1, 2, 3)] == ["0110", "0", "0"]
    assert [text(piotr, f"k:B/k:p1/k:p{n}") for n in (1, 2, 3)] == ["0411", "0", "0"]
    assert text(anna, "k:B/k:p3/k:p1") == "001"
    assert text(anna, "k:B/k:p3/k:p2") == "001"
    assert piotr.find("k:B/k:p3", NS) is None  # zlecenie bez wymiaru czasu pracy
    assert text(jan, "k:B/k:p2") == "2"  # przekroczenie 30-krotności wg płatnika
    assert anna.find("k:B/k:p2", NS) is None

    b = leaves(anna, "k:B")
    assert b["p4"] == b["p5"] == b["p6"] == "7800.00"
    assert (b["p7"], b["p8"], b["p9"]) == ("761.28", "117.00", "191.10")
    assert (b["p11"], b["p12"], b["p14"]) == ("761.28", "507.00", "130.26")
    assert b["p28"] == "117.00"  # PPK płatnika — poza łączną kwotą składek
    assert b["p29"] == "2467.92"
    assert not {"p19", "p20", "p21", "p22", "p25"} & set(b)
    c = amounts(anna, "k:C")
    assert (c["p1"], c["p4"]) == (D("6730.62"), D("605.76"))
    assert anna.find("k:D", NS) is None


def test_breaks_add_rsa_and_count_people_once() -> None:
    sick = KeduBreak(
        JAN,
        "011000",
        "331",
        date(2026, 11, 3),
        date(2026, 11, 7),
        days=5,
        amount=D("1234.56"),
    )
    leave = KeduBreak(
        KeduPerson("Nowa", "Ewa", "P", fake_pesel(date(1992, 9, 9), "0040")),
        "011000",
        "111",
        date(2026, 11, 1),
        date(2026, 11, 30),
    )
    root = parse(kedu.render_month(month(breaks=(sick, leave))))
    rsa = root.find("k:ZUSRSA", NS)

    assert rsa is not None and rsa.get("id_dokumentu") == "3"
    first, second = rsa.findall("k:III", NS)
    assert text(first, "k:B/k:p2") == "331"
    assert (text(first, "k:B/k:p3"), text(first, "k:B/k:p4")) == (
        "2026-11-03",
        "2026-11-07",
    )
    assert (text(first, "k:B/k:p5"), text(first, "k:B/k:p6")) == ("5", "1234.56")
    assert second.find("k:B/k:p5", NS) is None and second.find("k:B/k:p6", NS) is None
    assert text(rsa, "k:I/k:p1/k:p2") == "2026-11"
    assert text(rsa, "k:XI/k:p1") == "2026-12-04"
    assert text(root, "k:ZUSDRA/k:III/k:p1") == "4"  # 3 z RCA + 1 tylko z RSA


def test_benefits_are_deducted_from_amount_due() -> None:
    root = parse(kedu.render_month(month(sickness_benefits=D("800.00"))))
    dra = root.find("k:ZUSDRA", NS)
    assert dra is not None

    v = amounts(dra, "k:V")
    assert (v["p1"], v["p5"]) == (D("800.00"), D("800.00"))
    assert amounts(dra, "k:IX")["p2"] == D("7140.42") + D("1777.29") + D("507.90") - D(
        "800"
    )


def test_document_identity_types_without_pesel() -> None:
    passport = replace(INSURED[2], person=KeduPerson("Obcy", "Tom", "2", "ab 12345"))
    root = parse(kedu.render_month(month(insured=(passport,))))
    block = root.find("k:ZUSRCA/k:III", NS)
    assert block is not None

    assert text(block, "k:A/k:p3") == "2"
    assert text(block, "k:A/k:p4") == "AB12345"


# ── Odmowy ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"payer": replace(PAYER, nip="1234567861")}, "NIP płatnika"),
        ({"payer": replace(PAYER, regon="123456789")}, "REGON płatnika"),
        ({"payer": replace(PAYER, short_name="X" * 32)}, "Nazwa skrócona"),
        ({"insured": ()}, "co najmniej jednej osoby"),
        ({"insured": (replace(INSURED[0], title_code="0110"),)}, "kod tytułu"),
        ({"insured": (replace(INSURED[0], health=D("-1.00")),)}, "ujemna"),
        ({"insured": (replace(INSURED[0], health=D("1.005")),)}, "dwa miejsca"),
        ({"insured": (replace(INSURED[0], work_time=(2, 1)),)}, "wymiar czasu"),
        ({"accident_rate": D("0")}, "stopa"),
        ({"accident_rate": D("1.675")}, "stopa"),
        ({"declaration_id": 100}, "Numer deklaracji"),
        ({"month": 13}, "Okres"),
        ({"fgsp": D("-0.10")}, "FGŚP"),
    ],
)
def test_month_refuses_bad_input(change: dict[str, object], message: str) -> None:
    with pytest.raises(KeduError) as caught:
        kedu.render_month(month(**change))
    assert message in caught.value.message


def test_bad_pesel_message_has_no_digits_of_the_number() -> None:
    wrong = JAN.id_number[:10] + str((int(JAN.id_number[10]) + 1) % 10)
    broken = replace(INSURED[1], person=replace(JAN, id_number=wrong))

    with pytest.raises(KeduError) as caught:
        kedu.render_month(month(insured=(INSURED[0], broken)))

    assert "RCA, pozycja 2" in caught.value.message
    assert "PESEL" in caught.value.message
    assert wrong not in caught.value.message
    assert wrong[-4:] not in caught.value.message


def test_regon_checksum() -> None:
    assert kedu.regon_checksum_valid(fake_regon("12345678"))
    assert not kedu.regon_checksum_valid("123456789")
    assert not kedu.regon_checksum_valid("12345678")
    assert (
        kedu.regon_checksum_valid("12345678500000") is False
    )  # zera bez cyfry kontrolnej
    # KRS-owy zapis 9-cyfrowego REGON-u z pięcioma zerami jest skracany.
    padded = replace(PAYER, regon=fake_regon("12345678") + "00000")
    root = parse(kedu.render_month(month(payer=padded)))
    assert text(root, "k:ZUSDRA/k:II/k:p2") == PAYER.regon


# ── Zgłoszenia ───────────────────────────────────────────────────────────────

ADDRESS = KeduAddress(
    postal_code="00-950",
    city="Warszawa",
    municipality="Śródmieście",
    street="Przykładowa",
    house_number="1",
    flat_number="2",
)


def registrations() -> list[KeduRegistration]:
    return [
        KeduRegistration(
            kind="ZUA",
            person=ANNA,
            birth_date=date(1990, 3, 3),
            title_code="011000",
            date_from=date(2026, 11, 1),
            nfz_code="07r",
            sex="F",
            citizenship="polskie",
            occupation_code="251401",
            address=ADDRESS,
        ),
        KeduRegistration(
            kind="ZUA",
            person=PIOTR,
            birth_date=date(1999, 1, 15),
            title_code="041100",
            date_from=date(2026, 11, 1),
            nfz_code="07R",
            sickness=False,
            voluntary_sickness=True,
        ),
        KeduRegistration(
            kind="ZZA",
            person=KeduPerson("Inna", "Ewa", "2", "AB123456"),
            birth_date=date(1980, 5, 5),
            title_code="041100",
            date_from=date(2026, 11, 1),
            nfz_code="12R",
            occupation_code="251401",
            address=KeduAddress(postal_code="40001", city="Katowice"),
        ),
        KeduRegistration(
            kind="ZWUA",
            person=JAN,
            birth_date=date(1985, 7, 21),
            title_code="011000",
            date_from=date(2026, 12, 1),
            reason_code="100",
            termination=KeduTermination(date(2026, 11, 30), "22r", "402", initiator=2),
        ),
    ]


def test_registrations_build_one_document_per_person() -> None:
    root = parse(kedu.render_registrations(PAYER, registrations(), CREATED))
    docs = [child for child in root if "ZUS" in child.tag]

    assert [d.tag.split("}")[1] for d in docs] == [
        "ZUSZUA",
        "ZUSZUA",
        "ZUSZZA",
        "ZUSZWUA",
    ]
    assert [d.get("id_dokumentu") for d in docs] == ["1", "2", "3", "4"]
    zua, zua_mandate, zza, zwua = docs
    for doc in docs:
        assert text(doc, "k:I/k:p1") == "true"
        assert text(doc, "k:II/k:p1") == PAYER.nip

    assert text(zua, "k:III/k:p1") == ANNA.id_number
    assert (text(zua, "k:III/k:p5"), text(zua, "k:III/k:p6")) == ("PRZYKŁADOWA", "ANNA")
    assert text(zua, "k:III/k:p7") == "1990-03-03"
    assert (text(zua, "k:IV/k:p3"), text(zua, "k:IV/k:p4")) == ("POLSKIE", "K")
    assert text(zua, "k:V/k:p1/k:p1") == "0110"
    assert [text(zua, f"k:VI/k:p{n}") for n in range(1, 6)] == [
        "2026-11-01",
        "true",
        "true",
        "true",
        "true",
    ]
    assert (text(zua, "k:VII/k:p1"), text(zua, "k:VII/k:p2")) == ("2026-11-01", "07R")
    assert text(zua, "k:X/k:p1") == "251401"
    assert [text(zua, f"k:XI/k:p{n}") for n in range(1, 7)] == [
        "00950",
        "WARSZAWA",
        "ŚRÓDMIEŚCIE",
        "PRZYKŁADOWA",
        "1",
        "2",
    ]
    assert text(zua, "k:XIV/k:p1") == "2026-12-04"

    assert text(zua_mandate, "k:VI/k:p4") == "false"
    assert text(zua_mandate, "k:VIII/k:p5") == "true"
    assert text(zua_mandate, "k:VIII/k:p6") == "2026-11-01"
    assert zua_mandate.find("k:IV", NS) is None

    assert zza.find("k:III/k:p1", NS) is None
    assert (text(zza, "k:III/k:p3"), text(zza, "k:III/k:p4")) == ("2", "AB123456")
    assert text(zza, "k:V/k:p1/k:p1") == "0411"
    assert text(zza, "k:V/k:p2") == "251401"
    assert (text(zza, "k:VI/k:p1"), text(zza, "k:VI/k:p2")) == ("2026-11-01", "12R")
    assert (text(zza, "k:VIII/k:p1"), text(zza, "k:VIII/k:p2")) == ("40001", "KATOWICE")
    assert text(zza, "k:XI/k:p1") == "2026-12-04"

    assert text(zwua, "k:IV/k:p2") == "2026-12-01"
    assert text(zwua, "k:IV/k:p3") == "100"
    assert [text(zwua, f"k:V/k:p{n}") for n in (1, 2, 3, 5)] == [
        "2026-11-30",
        "22R",
        "402",
        "2",
    ]
    assert zwua.find("k:V/k:p4", NS) is None
    assert text(zwua, "k:VI/k:p1") == "2026-12-04"


@pytest.mark.parametrize(
    ("index", "change", "message"),
    [
        (0, {"kind": "ZIUA"}, "rodzaj zgłoszenia"),
        (0, {"nfz_code": None}, "NFZ"),
        (0, {"nfz_code": "17R"}, "NFZ"),
        (0, {"sex": "X"}, "płeć"),
        (0, {"occupation_code": "2514"}, "kod zawodu"),
        (0, {"address": replace(ADDRESS, postal_code="0095")}, "kod pocztowy"),
        (1, {"sickness": True}, "obowiązkowe albo dobrowolne"),
        (3, {"reason_code": None}, "kod przyczyny"),
        (3, {"termination": KeduTermination(date(2026, 11, 30), "XX", "402")}, "trybu"),
        (3, {"termination": KeduTermination(date(2026, 11, 30), "22R", "550")}, "550"),
        (
            3,
            {
                "termination": KeduTermination(
                    date(2026, 11, 30), "22R", "402", initiator=3
                )
            },
            "strona",
        ),
    ],
)
def test_registrations_refuse_bad_input(
    index: int, change: dict[str, object], message: str
) -> None:
    items = registrations()
    items[index] = replace(items[index], **change)  # type: ignore[arg-type]

    with pytest.raises(KeduError) as caught:
        kedu.render_registrations(PAYER, items, CREATED)
    assert message in caught.value.message


def test_registrations_refuse_empty_list_and_bad_payer() -> None:
    with pytest.raises(KeduError, match="co najmniej jeden dokument"):
        kedu.render_registrations(PAYER, [], CREATED)
    with pytest.raises(KeduError, match="REGON"):
        kedu.render_registrations(
            replace(PAYER, regon="12345"), registrations(), CREATED
        )


def test_termination_with_custom_legal_basis_text() -> None:
    items = registrations()
    items[3] = replace(
        items[3],
        termination=KeduTermination(
            date(2026, 11, 30),
            "37R",
            "550",
            legal_basis_text="art. 1 ustawy przykładowej",
        ),
    )
    root = parse(kedu.render_registrations(PAYER, items, CREATED))

    assert text(root, "k:ZUSZWUA/k:V/k:p4") == "art. 1 ustawy przykładowej"
    assert root.find("k:ZUSZWUA/k:V/k:p5", NS) is None
