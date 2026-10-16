"""Szablony protokołów sprzętu (docxtpl) — budowane kodem ze wzoru recepcji.

Wzór wydania to protokół zdawczo-odbiorczy recepcji (16.10.2026) słowo
w słowo: ten sam układ akapitów, ta sama tabela (Lp., Nazwa sprzętu,
Nr seryjny, Ilość, Cena, Wartość), te same klauzule i podpisy. Dane osoby,
numery i kwoty są polami Jinja; jedyny dopisek to numer protokołu pod
tytułem (makieta „Sprzęt → Wydaj sprzęt”), bez którego nie da się go
odszukać ani podpisać linkiem.

Wzoru zwrotu recepcja nie miała — protokół zwrotu ma ten sam nagłówek
i strony zamienione miejscami, a w tabeli stan przy zwrocie zamiast ceny.

Szablony w ``app/templates/equipment`` są WYNIKIEM tego modułu (jak
``scripts/build_academy_templates.py`` dla Akademii)::

    python -m app.services.equipment.protocol_template

Zmiana treści = zmiana tutaj, ponowne uruchomienie i nowa
``TEMPLATE_VERSION`` (protokół zapisuje wersję wzoru, z której powstał).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Emu, Pt, Twips

from app.core.docx_cells import row_cells

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "equipment"
ISSUE_TEMPLATE = "protokol_wydania.docx"
RETURN_TEMPLATE = "protokol_zwrotu.docx"
TEMPLATE_VERSION = "2026-10-16"

COMPANY_LINE = (
    "Spółka B2B.net SA, z siedzibą w Warszawie 02-486, Al. Jerozolimskie 180, "
    "z upoważnienia "
)
LIABILITY_TAIL = (
    ", iż przyjmuje na siebie odpowiedzialność materialną za mienie Spółki "
    "B2B.net SA powierzone na podstawie niniejszego protokołu z obowiązkiem "
    "jego zwrotu w stanie niepogorszonym. "
)
CONDITION_TAIL = (
    "się ze stanem technicznym powierzonego mienia i nie wnosi zastrzeżeń. "
)
CLAUSE_1 = (
    "Sprzęt będzie oddany w dokładnie takim samym stanie, w jakim został przekazany."
)
CLAUSE_A = (
    " Wszelkie uszkodzenia lub zmiany w stanie sprzętu, które nie wynikają "
    "z normalnego użytkowania, zostaną udokumentowane i mogą skutkować "
    "dodatkowymi opłatami."
)
CLAUSE_B = (
    " Osoba odpowiedzialna za sprzęt będzie ponosić wszelkie opłaty związane "
    "z przywróceniem sprzętu do pierwotnego stanu, jeśli zostanie on oddany "
    "w stanie odmiennym od tego, w jakim został przekazany."
)
CLAUSE_SIGNING = (
    "Podpisując niniejszy protokół, osoba odbierająca sprzęt potwierdza, że "
    "zapoznała się z jego aktualnym stanem i akceptuje odpowiedzialność za "
    "utrzymanie go w tym samym stanie podczas użytkowania."
)
CLAUSE_C = (
    " Strony ustalają, że niniejszy protokół może być zawarty i podpisany "
    "w formie elektronicznej z wykorzystaniem podpisu zaufanego, o którym mowa "
    "w art. 3 pkt 14 ustawy z dnia 17 lutego 2005 r. o informatyzacji "
    "działalności podmiotów realizujących zadania publiczne. Strony uznają, "
    "że podpis zaufany użyty przez każdą ze stron jest równoważny z podpisem "
    "własnoręcznym dla celów prawnych i dowodowych."
)
CLAUSE_2 = (
    "Osoba kończąca świadczenie usług zobowiązana jest do zwrotu powierzonego "
    "sprzętu osobiście w siedzibie biura, znajdującej się przy Alejach "
    "Jerozolimskich 180 w Warszawie. W przypadku braku możliwości osobistego "
    "zwrotu, dopuszcza się przesłanie sprzętu na własny koszt za pośrednictwem "
    "firmy kurierskiej, na adres siedziby: B2B.NET S.A. Aleje Jerozolimskie "
    "180, 02-486 Warszawa"
)
CLAUSE_3 = (
    "3. Zabrania się dokonywania jakichkolwiek zmian lub ingerencji "
    "w przekazany sprzęt; naruszenie zakazu skutkuje odpowiedzialnością "
    "materialną oraz obowiązkiem pokrycia kosztów przywrócenia sprzętu do "
    "stanu pierwotnego."
)
COPIES = "Powyższy protokół został sporządzony w 2 jednobrzmiących egzemplarzach. "
RETURN_RECEIPT = (
    "Strona przyjmująca potwierdza odbiór sprzętu wymienionego w tabeli "
    "w stanie opisanym w kolumnie „Stan przy zwrocie”."
)

_BODY = "Cambria"
_DATA = "Calibri"
_LINE = Emu(190500)  # 15 pt — interlinia akapitów wzoru

_ISSUE_COLUMNS = ("Lp.", "Nazwa sprzętu", "Nr seryjny", "Ilość", "Cena", "Wartość")
_RETURN_COLUMNS = (
    "Lp.",
    "Nazwa sprzętu",
    "Nr seryjny",
    "Ilość",
    "Stan przy zwrocie",
    "Uwagi",
)
_COLUMN_WIDTHS = (418, 2960, 2643, 992, 1843, 1275)  # twipy, jak we wzorze


@dataclass(frozen=True)
class Run:
    text: str
    bold: bool = False
    size: float | None = 9.0
    font: str = _BODY


def _new_document() -> docx.document.Document:
    document = docx.Document()
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.0
    section = document.sections[0]
    section.page_width = Emu(7560310)
    section.page_height = Emu(10692130)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Emu(457200))
    props = document.core_properties
    props.author = "NEXUS"
    props.last_modified_by = "NEXUS"
    props.title = "Protokół zdawczo-odbiorczy"
    props.comments = ""
    return document


def _paragraph(
    document: docx.document.Document,
    *runs: Run,
    center: bool = False,
    spaced: bool = True,
) -> None:
    paragraph = document.add_paragraph()
    if center:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if spaced:
        paragraph.paragraph_format.line_spacing = _LINE
    for spec in runs:
        run = paragraph.add_run(spec.text)
        run.bold = spec.bold
        run.font.name = spec.font
        if spec.size is not None:
            run.font.size = Pt(spec.size)


def _empty(document: docx.document.Document, *, center: bool = False) -> None:
    _paragraph(document, center=center)


def _cell(cell, *runs: Run, center: bool = False) -> None:
    paragraph = cell.paragraphs[0]
    if center:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for spec in runs:
        run = paragraph.add_run(spec.text)
        run.bold = spec.bold
        run.font.name = spec.font
        if spec.size is not None:
            run.font.size = Pt(spec.size)


def _table(
    document: docx.document.Document,
    columns: tuple[str, ...],
    data: tuple[str, ...],
    total: tuple[Run | None, Run | None] | None,
) -> None:
    rows = 4 + (1 if total else 0)
    table = document.add_table(rows=rows, cols=len(columns))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # Komórki przez docx_cells (strażnik `test_docx_table_cells.py`); tabela
    # jest świeża, bez scaleń, więc to te same komórki co w `row.cells`.
    cells = [row_cells(row) for row in table.rows]
    for row in cells:
        for index, cell in enumerate(row):
            cell.width = Twips(_COLUMN_WIDTHS[index])
    for index, title in enumerate(columns):
        _cell(cells[0][index], Run(title, bold=True), center=True)
    # docxtpl zamienia CAŁY wiersz z „{%tr …%}” na znacznik pętli.
    _cell(cells[1][0], Run("{%tr for line in lines %}"))
    for index, field in enumerate(data):
        size, font = (9.0, _BODY) if index in (0, 3) else (11.0, _DATA)
        _cell(
            cells[2][index],
            Run("{{ line.%s }}" % field, size=size, font=font),
            center=index >= 2,
        )
    _cell(cells[3][0], Run("{%tr endfor %}"))
    if total:
        label, value = total
        if label:
            _cell(
                cells[4][4],
                label,
                Run("{{ total }} zł", size=11.0, font=_DATA),
            )
        if value:
            _cell(cells[4][5], value)


def _signatures(document: docx.document.Document) -> None:
    _empty(document)
    _empty(document, center=True)
    _paragraph(
        document,
        Run("                  ", bold=True, size=11.0),
        Run("Strona przekazująca", bold=True, size=11.0),
        Run("\t\t\t\t\t\t    ", size=None),
        Run("Strona przyjmująca", bold=True, size=11.0),
    )
    _paragraph(
        document,
        Run("(podpis)" + " " * 48 + "\t" + " " * 52 + "(podpis)", size=11.0),
        center=True,
    )


def _header(document: docx.document.Document) -> None:
    _paragraph(document, Run("PROTOKÓŁ", bold=True, size=None), center=True)
    _paragraph(document, Run("ZDAWCZO-ODBIORCZY", bold=True, size=None), center=True)
    _paragraph(document, Run("nr {{ number }}", size=None), center=True)
    _empty(document, center=True)
    _paragraph(
        document,
        Run("Sporządzony w dniu {{ protocol_date }} r. roku w Warszawie,", size=None),
    )
    _empty(document)


def build_issue_template() -> docx.document.Document:
    """Wzór recepcji: protokół wydania sprzętu."""
    document = _new_document()
    _header(document)
    _paragraph(document, Run("Strona przekazująca: ", bold=True, size=None))
    _paragraph(
        document,
        Run(COMPANY_LINE, size=None),
        Run("{{ issuer_name }}", bold=True, size=None, font=_DATA),
    )
    _empty(document)
    _paragraph(
        document,
        Run("Strona przyjmująca ", bold=True, size=None),
        Run("{{ holder_name }}", size=11.0, font=_DATA),
        spaced=False,
    )
    _paragraph(document, Run("PRZEDMIOT PRZEKAZANIA", bold=True, size=None))
    _empty(document)
    _table(
        document,
        _ISSUE_COLUMNS,
        ("position", "name", "identifier", "quantity", "price", "value"),
        (Run("Razem ", bold=True), Run("{{ total }} zł", size=11.0, font=_DATA)),
    )
    _empty(document)
    _paragraph(
        document,
        Run("Wartość przedmiotu przekazania słownie", size=None),
        Run(":", size=None),
        Run(" ", size=None),
        Run("{{ total_words }}.", size=None),
    )
    _empty(document)
    _paragraph(
        document,
        Run("Pan"),
        Run("/Pani"),
        Run(" ", bold=True, size=None, font=_DATA),
        Run("{{ holder_name }}", bold=True, size=None, font=_DATA),
        Run(" "),
        Run("oświadcza"),
        Run(LIABILITY_TAIL),
        spaced=False,
    )
    _empty(document)
    _paragraph(
        document,
        Run("Pan"),
        Run("/Pani"),
        Run(" "),
        Run("{{ holder_name }}", bold=True, size=None, font=_DATA),
        Run(" "),
        Run("zapoznał"),
        Run("/-a"),
        Run(" "),
        Run(CONDITION_TAIL),
        spaced=False,
    )
    _empty(document, center=False)
    _paragraph(document, Run("1.", bold=True), Run(CLAUSE_1), spaced=False)
    _paragraph(document, spaced=False)
    _paragraph(document, Run("a.", bold=True), Run(CLAUSE_A), spaced=False)
    _paragraph(document, Run("b.", bold=True), Run(CLAUSE_B), spaced=False)
    _paragraph(document, Run(CLAUSE_SIGNING))
    _paragraph(document, Run("c.", bold=True), Run(CLAUSE_C))
    _empty(document)
    _paragraph(document, Run("2.", bold=True), Run(CLAUSE_2))
    _empty(document)
    _paragraph(document, Run(CLAUSE_3))
    _empty(document)
    _paragraph(document, Run(COPIES))
    _signatures(document)
    return document


def build_return_template() -> docx.document.Document:
    """Zwrot: nagłówek wzoru, strony zamienione, stan przy zwrocie w tabeli."""
    document = _new_document()
    _header(document)
    _paragraph(document, Run("Strona przekazująca: ", bold=True, size=None))
    _paragraph(document, Run("{{ holder_name }}", bold=True, size=None, font=_DATA))
    _empty(document)
    _paragraph(document, Run("Strona przyjmująca ", bold=True, size=None))
    _paragraph(
        document,
        Run(COMPANY_LINE, size=None),
        Run("{{ issuer_name }}", bold=True, size=None, font=_DATA),
    )
    _empty(document)
    _paragraph(document, Run("PRZEDMIOT ZWROTU", bold=True, size=None))
    _empty(document)
    _table(
        document,
        _RETURN_COLUMNS,
        ("position", "name", "identifier", "quantity", "condition", "notes"),
        None,
    )
    _empty(document)
    _paragraph(document, Run(RETURN_RECEIPT))
    _empty(document)
    _paragraph(document, Run(COPIES))
    _signatures(document)
    return document


def write_templates(target: Path = TEMPLATE_DIR) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, builder in (
        (ISSUE_TEMPLATE, build_issue_template),
        (RETURN_TEMPLATE, build_return_template),
    ):
        path = target / name
        builder().save(str(path))
        written.append(path)
    return written


if __name__ == "__main__":
    for written_path in write_templates():
        print(f"Zapisano {written_path}")
