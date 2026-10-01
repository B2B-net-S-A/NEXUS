"""PKO BP: tabela Wykonawców z położenia słów (ticket 12, 01.10.2026).

Zgłoszenie: imię i nazwisko sklejało się z profilem („… DevSecOpS"), bo
środkowa linia wielolinijkowego profilu ląduje w linii wiersza, a słownik słów
profilu nie zna każdego profilu. Osoba trafiała do weryfikacji. Kolumny czytamy
teraz z nagłówków tabeli, a wiersze — z dat w kolumnie „Początek Zaangażowania".

Dane w testach są fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services import cv_text_extractor as cte
from app.services import order_document_text as odt
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction
from app.services.order_policies import pko_bp, pko_bp_layout
from app.services.order_policies.registry import (
    PolicyContext,
    apply_policies,
    apply_rate_kind,
    policy_by_key,
    prepare_document_text,
)

# ── Budowa słów tabeli (bez PDF-a) ──────────────────────────────────────────

#: Lewe krawędzie kolumn i ich szerokość (układ jak w zamówieniu PKO BP).
_COLUMNS = {
    "name": (40, 95),
    "profile": (135, 80),
    "start": (215, 75),
    "end": (290, 75),
    "md": (365, 40),
    "rate": (405, 58),
    "location": (463, 58),
    "ssgw": (521, 50),
}
_HEADER = {
    "name": ["Imię i nazwisko", "Wykonawców"],
    "profile": ["Profil"],
    "start": ["Początek", "Zaangażowania"],
    "end": ["Planowany", "Koniec", "Zaangażowania"],
    "md": ["Liczba", "MD"],
    "rate": ["Stawka", "PLN/MD", "netto"],
    "location": ["Lokalizacja"],
    "ssgw": ["Numer", "SSGW"],
}
_H = 8.0  # wysokość linii
_PITCH = 9.5  # odstęp linii w komórce
_CHAR = 4.4  # szerokość znaku


def _line_words(page: int, col: str, text: str, top: float) -> list[list]:
    """Linia komórki wyśrodkowana w poziomie, słowo po słowie."""
    left, width = _COLUMNS[col]
    total = len(text) * _CHAR
    x = left + max((width - total) / 2, 2)
    out: list[list] = []
    for word in text.split(" "):
        w = len(word) * _CHAR
        out.append([page, round(x, 2), round(x + w, 2), top, top + _H, word])
        x += w + _CHAR
    return out


def _cell(page, col, lines, center, align="middle", row_top=0.0, row_bottom=0.0):
    n = len(lines)
    if align == "top":
        first = row_top
    elif align == "bottom":
        first = row_bottom - _H - (n - 1) * _PITCH
    else:
        first = center - _H / 2 - (n - 1) * _PITCH / 2
    out: list[list] = []
    for i, text in enumerate(lines):
        out.extend(_line_words(page, col, text, round(first + i * _PITCH, 2)))
    return out


def _table_words(
    rows: list[dict[str, list[str]]],
    *,
    page: int = 0,
    top: float = 130.0,
    padding: float = 3.0,
    align: str = "middle",
    header: bool = True,
    header_rate: list[str] | None = None,
) -> tuple[list[list], float]:
    """Słowa tabeli: nagłówek (wyśrodkowany) + wiersze. Zwraca (słowa, dół)."""
    words: list[list] = []
    y = top
    if header:
        spec = dict(_HEADER)
        if header_rate:
            spec["rate"] = header_rate
        tallest = max(len(v) for v in spec.values())
        height = tallest * _PITCH + 2 * padding
        center = y + height / 2
        for col, lines in spec.items():
            words.extend(_cell(page, col, lines, center))
        y += height
    for row in rows:
        tallest = max(len(v) for v in row.values())
        height = (tallest - 1) * _PITCH + _H + 2 * padding
        center = y + height / 2
        for col, lines in row.items():
            words.extend(
                _cell(
                    page,
                    col,
                    lines,
                    center,
                    align=align,
                    row_top=y + padding,
                    row_bottom=y + height - padding,
                )
            )
        y += height
    return words, y


def _row(name, profile, start="2031-10-01", end="2031-12-31", md="63", rate="880,00"):
    return {
        "name": name if isinstance(name, list) else [name],
        "profile": profile if isinstance(profile, list) else [profile],
        "start": [start],
        "end": [end],
        "md": [md],
        "rate": [rate],
        "location": ["Warszawa"],
        "ssgw": ["104214-1"],
    }


TICKET_ROW = _row(
    "Konrad Przykładowy", ["Inżynier", "DevSecOpS", "Senior"], rate="1 240,00*"
)


def _read(words) -> list[pko_bp_layout.LayoutRow]:
    table = pko_bp_layout.read_table(pko_bp_layout.words_from_payload(words))
    assert table is not None
    return table.rows


# ── Odczyt kolumn ───────────────────────────────────────────────────────────


class TestColumnsFromHeaders:
    def test_name_comes_only_from_the_name_column(self):
        words, _ = _table_words([TICKET_ROW])
        [row] = _read(words)
        assert row.cells["name"] == "Konrad Przykładowy"
        assert row.cells["profile"] == "Inżynier DevSecOpS Senior"
        assert (row.cells["start"], row.cells["end"]) == ("2031-10-01", "2031-12-31")
        assert (row.cells["md"], row.cells["rate"]) == ("63", "1 240,00*")
        assert row.reasons == []

    def test_every_row_is_a_person_with_its_own_profile(self):
        rows = [
            TICKET_ROW,
            _row("Anna Testowa-Nowak", "Tester Middle", md="58"),
            _row(
                ["Jan Maria", "Przykładowy-Wzorcowy"],
                ["Architekt", "Rozwiązań", "Chmurowych", "Expert"],
                start="2031-11-01",
                end="2032-01-31",
                md="40",
                rate="1 500,00",
            ),
        ]
        words, _ = _table_words(rows)
        got = [(r.cells["name"], r.cells["profile"], r.cells["md"]) for r in _read(words)]
        assert got == [
            ("Konrad Przykładowy", "Inżynier DevSecOpS Senior", "63"),
            ("Anna Testowa-Nowak", "Tester Middle", "58"),
            (
                "Jan Maria Przykładowy-Wzorcowy",
                "Architekt Rozwiązań Chmurowych Expert",
                "40",
            ),
        ]

    @pytest.mark.parametrize("align", ["middle", "top", "bottom"])
    @pytest.mark.parametrize("padding", [0.0, 3.0])
    def test_rows_without_cell_padding_and_any_vertical_alignment(self, align, padding):
        rows = [
            _row(["Jan", "Przykładowy-Wzorcowy"], ["Inżynier", "DevSecOpS", "Senior"]),
            _row("Ewa Testowa", "SRE", md="20"),
            _row("Piotr Wzorcowy", ["Kierownik", "Projektu IT", "Senior"], md="30"),
        ]
        words, _ = _table_words(rows, padding=padding, align=align)
        got = [(r.cells["name"], r.cells["md"], r.reasons) for r in _read(words)]
        assert got == [
            ("Jan Przykładowy-Wzorcowy", "63", []),
            ("Ewa Testowa", "20", []),
            ("Piotr Wzorcowy", "30", []),
        ]

    def test_text_below_the_table_is_not_part_of_a_row(self):
        words, bottom = _table_words([TICKET_ROW])
        words += _line_words(0, "name", "* stawka negocjowana", bottom + 2)
        words += _line_words(0, "name", "Łączna wartość zamówienia", bottom + 14)
        [row] = _read(words)
        assert row.cells["name"] == "Konrad Przykładowy"

    def test_table_continues_on_the_next_page_without_header(self):
        first, _ = _table_words([TICKET_ROW])
        second, _ = _table_words(
            [_row("Ewa Testowa", "Tester Middle", md="20")], page=1, top=40, header=False
        )
        rows = _read(first + second)
        assert [r.cells["name"] for r in rows] == ["Konrad Przykładowy", "Ewa Testowa"]

    def test_document_without_the_table_gives_nothing(self):
        words = _line_words(0, "name", "Zamówienie nr 1830/2031", 100)
        assert pko_bp_layout.read_table(pko_bp_layout.words_from_payload(words)) is None

    def test_row_without_a_name_is_uncertain(self):
        row = _row("Konrad", "Tester Middle")
        words, _ = _table_words([row])
        [got] = _read(words)
        assert pko_bp_layout.REASON_NAME in got.reasons

    def test_gross_rate_header_is_kept_for_the_rate_rule(self):
        words, _ = _table_words([TICKET_ROW], header_rate=["Stawka", "PLN/MD", "brutto"])
        table = pko_bp_layout.read_table(pko_bp_layout.words_from_payload(words))
        assert table is not None and "brutto" in table.rate_label


# ── Tekst dokumentu i reguła ────────────────────────────────────────────────

TEXT = """PKO Bank Polski SA
Zamówienie nr 1830/2031
Zgodnie z postanowieniem Umowy ramowej numer DIT-2031-0005 …
1. Wykonawcy, Profile, Terminy, Stawki:
Planowany Stawka
Imię i nazwisko Początek Liczba Numer
Profil Koniec PLN/MD Lokalizacja
Wykonawców Zaangażowania MD SSGW
Zaangażowania netto
Inżynier
Konrad Przykładowy DevSecOpS 2031-10-01 2031-12-31 63 1 240,00* Warszawa 104214-1
Senior
* stawka negocjowana
Łączna wartość zamówienia wynosi: 78 120,00 PLN netto.
"""


def _words():
    return _table_words([TICKET_ROW])[0]


class TestDocumentText:
    def test_text_only_rule_reproduces_the_ticket(self):
        # Bez położenia słów profil skleja się z nazwiskiem — tak było w zgłoszeniu.
        [row] = pko_bp.extract_rows(TEXT.replace("DevSecOpS", "Cyberbezpieczeństwa"))
        assert row.consultant_name == "Konrad Przykładowy Cyberbezpieczeństwa"
        assert row.uncertain is True

    def test_raw_table_is_replaced_by_rows_read_from_columns(self):
        text = pko_bp.apply_layout_table(TEXT, _words())
        assert pko_bp_layout.TABLE_TITLE in text
        assert "Konrad Przykładowy DevSecOpS" not in text
        assert "Imię i nazwisko Wykonawców: Konrad Przykładowy |" in text
        assert text.startswith("PKO Bank Polski SA\nZamówienie nr 1830/2031")
        assert "* stawka negocjowana\nŁączna wartość" in text
        # Idempotentne — tekst przygotowany drugi raz się nie zmienia.
        assert pko_bp.apply_layout_table(text, _words()) == text

    def test_without_words_the_text_stays(self):
        assert pko_bp.apply_layout_table(TEXT, None) == TEXT

    def test_layout_with_fewer_rows_than_the_text_rule_is_not_used(self):
        second = TEXT.replace(
            "Senior\n",
            "Senior\nEwa Testowa Tester Middle 2031-10-01 2031-12-31 20 900,00 "
            "Warszawa 104214-2\n",
        )
        assert pko_bp.apply_layout_table(second, _words()) == second

    def test_policy_reads_person_period_md_and_rate(self):
        policies = [policy_by_key("pko_bp")]
        text = prepare_document_text(TEXT, policies, words=_words())
        result, _ = apply_policies(
            OrderExtraction(source="claude"), PolicyContext(document_text=text), policies
        )
        result = apply_rate_kind(result, text, policies)
        assert result.title == "1830/2031"
        assert [
            (r.consultant_name, r.start_date, r.end_date, r.md_total, r.rate_client)
            for r in result.consultant_rows
        ] == [
            (
                "Konrad Przykładowy",
                "2031-10-01",
                "2031-12-31",
                Decimal("63"),
                Decimal("1240.00"),
            )
        ]
        assert (result.md_total, result.rate_client, result.rate_unit) == (
            Decimal("63"),
            Decimal("1240.00"),
            "day",
        )
        assert result.uncertain is False and result.uncertain_reasons == []

    def test_gross_rate_column_from_layout_goes_to_review(self):
        policies = [policy_by_key("pko_bp")]
        words, _ = _table_words([TICKET_ROW], header_rate=["Stawka", "PLN/MD", "brutto"])
        text = prepare_document_text(
            TEXT.replace("netto\n", "brutto\n", 1), policies, words=words
        )
        result, _ = apply_policies(
            OrderExtraction(source="claude"), PolicyContext(document_text=text), policies
        )
        result = apply_rate_kind(result, text, policies)
        assert pko_bp.REASON_GROSS_HEADER in result.uncertain_reasons

    def test_unreadable_numbers_leave_the_fields_empty(self):
        text = pko_bp.apply_layout_table(TEXT, _words()).replace(
            "Liczba MD: 63", "Liczba MD: 6 3x"
        )
        [row] = pko_bp.extract_rows(text)
        assert row.md_total is None and row.uncertain is True
        assert pko_bp_layout.REASON_NUMBERS in (row.uncertain_reason or "")

    def test_model_name_with_profile_word_is_reconciled(self):
        # Model (albo odczyt zapisany przed poprawką — „Przelicz plan") z dopiskiem
        # spoza słownika profili; kolumna „Profil" z układu go rozpoznaje.
        policies = [policy_by_key("pko_bp")]
        text = prepare_document_text(TEXT, policies, words=_words())
        stored = OrderExtraction(source="claude")
        stored.consultant_rows = [
            ConsultantOrderRow(
                consultant_name="Konrad Przykładowy DevSecOpS",
                uncertain=True,
                uncertain_reason=(
                    "Nie rozpoznano granicy imienia i nazwiska oraz profilu w wierszu "
                    "„Konrad Przykładowy DevSecOpS” — sprawdź osobę"
                ),
            )
        ]
        result, _ = apply_policies(
            stored, PolicyContext(document_text=text, reapplied=True), policies
        )
        [row] = result.consultant_rows
        assert row.consultant_name == "Konrad Przykładowy"
        assert row.uncertain is False and row.uncertain_reason is None

    def test_other_policies_ignore_words(self):
        policies = [policy_by_key("kir")]
        assert prepare_document_text(TEXT, policies, words=_words()) == TEXT


def test_text_rule_knows_devsecops_profile():
    name, reason = pko_bp.split_name_and_profile("Konrad Przykładowy DevSecOpS")
    assert (name, reason) == ("Konrad Przykładowy", None)


# ── Położenie słów z prawdziwego PDF-a ──────────────────────────────────────


def _pdf_with_table() -> bytes:
    """PDF z tabelą bez linii: komórki wyśrodkowane, profil w trzech liniach."""
    from tests.test_pdf_extraction_sandbox import _pdf

    page_h = 842
    commands: list[bytes] = []

    def put(x: float, top: float, text: str) -> None:
        y = page_h - top - 7
        commands.append(b"BT /F1 8 Tf %.2f %.2f Td (%s) Tj ET\n" % (x, y, text.encode()))

    put(40, 60, "Zamowienie nr 1830/2031")
    header = {
        40: ["Imie i nazwisko", "Wykonawcow"],
        135: ["Profil"],
        215: ["Poczatek", "Zaangazowania"],
        290: ["Planowany", "Koniec", "Zaangazowania"],
        365: ["Liczba", "MD"],
        405: ["Stawka", "PLN/MD", "netto"],
        463: ["Lokalizacja"],
        521: ["Numer", "SSGW"],
    }
    for x, lines in header.items():
        first = 120 - (len(lines) - 1) * 9.5 / 2
        for i, text in enumerate(lines):
            put(x, first + i * 9.5, text)
    rows = [
        (
            ["Konrad Przykladowy"],
            ["Inzynier", "Cyberochrony", "Senior"],
            "63",
            "1 240,00*",
        ),
        (["Ewa", "Testowa-Nowak"], ["Tester Middle"], "20", "900,00"),
    ]
    center = 160.0
    for name, profile, md, rate in rows:
        cells = {
            40: name,
            135: profile,
            215: ["2031-10-01"],
            290: ["2031-12-31"],
            365: [md],
            405: [rate],
            463: ["Warszawa"],
            521: ["104214-1"],
        }
        for x, lines in cells.items():
            first = center - (len(lines) - 1) * 9.5 / 2
            for i, text in enumerate(lines):
                put(x, first + i * 9.5, text)
        center += 40
    put(40, center, "Laczna wartosc zamowienia wynosi: 96 120,00 PLN netto.")
    return _pdf(b"".join(commands))


def test_words_from_the_pdf_worker_rebuild_the_table(tmp_path):
    path = tmp_path / "zamowienie.pdf"
    path.write_bytes(_pdf_with_table())
    text = cte.extract_text(str(path), "zamowienie.pdf")
    # Zwykły tekst skleja środkową linię profilu z nazwiskiem.
    assert "Konrad Przykladowy Cyberochrony 2031-10-01" in text
    words = odt.extract_order_words(str(path), "zamowienie.pdf", text)
    assert words
    table = pko_bp_layout.read_table(pko_bp_layout.words_from_payload(words))
    assert table is not None
    assert [(r.cells["name"], r.cells["profile"], r.reasons) for r in table.rows] == [
        ("Konrad Przykladowy", "Inzynier Cyberochrony Senior", []),
        ("Ewa Testowa-Nowak", "Tester Middle", []),
    ]
    rows = pko_bp.extract_rows(pko_bp.apply_layout_table(text, words))
    assert [(r.consultant_name, r.md_total, r.rate_client) for r in rows] == [
        ("Konrad Przykladowy", Decimal("63"), Decimal("1240.00")),
        ("Ewa Testowa-Nowak", Decimal("20"), Decimal("900.00")),
    ]


def test_words_are_read_only_for_documents_with_the_table(tmp_path, monkeypatch):
    def _must_not_run(path):  # pragma: no cover — wywołanie = błąd testu
        raise AssertionError("bez tabeli nie ma czego czytać z położenia")

    monkeypatch.setattr(odt, "extract_pdf_words_sandboxed", _must_not_run)
    assert odt.extract_order_words("x.pdf", "x.pdf", "Zamówienie nr 7") is None
    assert odt.extract_order_words("x.docx", "x.docx", "Numer SSGW") is None
