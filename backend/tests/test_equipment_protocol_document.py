"""Protokół sprzętu = wzór recepcji słowo w słowo (dane fikcyjne).

Oczekiwany tekst niżej jest przepisany ze wzoru recepcji (16.10.2026) z polami
wypełnionymi fikcją — nie jest liczony z modułu szablonu, więc zmiana treści
klauzuli w kodzie wywraca test. Jedyny dopisek względem wzoru to numer
protokołu pod tytułem (makieta „Wydaj sprzęt”).
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import docx
import pytest

from app.services import cv_pdf_preview
from app.services.equipment import protocol_document as doc
from app.services.equipment import protocol_template

WZOR_WYDANIA = [
    "PROTOKÓŁ",
    "ZDAWCZO-ODBIORCZY",
    "nr PZO/2026/10/014",
    "",
    "Sporządzony w dniu 28.10.2026 r. roku w Warszawie,",
    "",
    "Strona przekazująca: ",
    "Spółka B2B.net SA, z siedzibą w Warszawie 02-486, Al. Jerozolimskie 180, "
    "z upoważnienia Zofia Testowa",
    "",
    "Strona przyjmująca Anna Przykładowa",
    "PRZEDMIOT PRZEKAZANIA",
    "",
    [
        ["Lp.", "Nazwa sprzętu", "Nr seryjny", "Ilość", "Cena", "Wartość"],
        [
            "1",
            "Laptop DELL Vostro 3530 (221) zasilacz, podkładka, mysz",
            "7KQ2X41",
            "1",
            "2589,00",
            "2589,00",
        ],
        [
            "2",
            "Telefon Samsung Galaxy A16",
            "IMEI: 350000000002290",
            "1",
            "897,76",
            "897,76",
        ],
        ["3", "Karta SIM +48 500 000 145", "ICCID: 8948000000000005132", "1", "—", "—"],
        ["4", "Słuchawki Evolve2 40 SE", "S/N:00000000012", "1", "416,97", "416,97"],
        ["5", "Karta dostępu nr 1611", "1611", "1", "—", "—"],
        ["", "", "", "", "Razem 3 903,73 zł", "3 903,73 zł"],
    ],
    "",
    "Wartość przedmiotu przekazania słownie: trzy tysiące dziewięćset trzy złote 73/100.",
    "",
    "Pan/Pani Anna Przykładowa oświadcza, iż przyjmuje na siebie odpowiedzialność "
    "materialną za mienie Spółki B2B.net SA powierzone na podstawie niniejszego "
    "protokołu z obowiązkiem jego zwrotu w stanie niepogorszonym. ",
    "",
    "Pan/Pani Anna Przykładowa zapoznał/-a się ze stanem technicznym powierzonego "
    "mienia i nie wnosi zastrzeżeń. ",
    "",
    "1.Sprzęt będzie oddany w dokładnie takim samym stanie, w jakim został przekazany.",
    "",
    "a. Wszelkie uszkodzenia lub zmiany w stanie sprzętu, które nie wynikają "
    "z normalnego użytkowania, zostaną udokumentowane i mogą skutkować dodatkowymi "
    "opłatami.",
    "b. Osoba odpowiedzialna za sprzęt będzie ponosić wszelkie opłaty związane "
    "z przywróceniem sprzętu do pierwotnego stanu, jeśli zostanie on oddany w stanie "
    "odmiennym od tego, w jakim został przekazany.",
    "Podpisując niniejszy protokół, osoba odbierająca sprzęt potwierdza, że "
    "zapoznała się z jego aktualnym stanem i akceptuje odpowiedzialność za "
    "utrzymanie go w tym samym stanie podczas użytkowania.",
    "c. Strony ustalają, że niniejszy protokół może być zawarty i podpisany w formie "
    "elektronicznej z wykorzystaniem podpisu zaufanego, o którym mowa w art. 3 pkt 14 "
    "ustawy z dnia 17 lutego 2005 r. o informatyzacji działalności podmiotów "
    "realizujących zadania publiczne. Strony uznają, że podpis zaufany użyty przez "
    "każdą ze stron jest równoważny z podpisem własnoręcznym dla celów prawnych "
    "i dowodowych.",
    "",
    "2.Osoba kończąca świadczenie usług zobowiązana jest do zwrotu powierzonego "
    "sprzętu osobiście w siedzibie biura, znajdującej się przy Alejach Jerozolimskich "
    "180 w Warszawie. W przypadku braku możliwości osobistego zwrotu, dopuszcza się "
    "przesłanie sprzętu na własny koszt za pośrednictwem firmy kurierskiej, na adres "
    "siedziby: B2B.NET S.A. Aleje Jerozolimskie 180, 02-486 Warszawa",
    "",
    "3. Zabrania się dokonywania jakichkolwiek zmian lub ingerencji w przekazany "
    "sprzęt; naruszenie zakazu skutkuje odpowiedzialnością materialną oraz "
    "obowiązkiem pokrycia kosztów przywrócenia sprzętu do stanu pierwotnego.",
    "",
    "Powyższy protokół został sporządzony w 2 jednobrzmiących egzemplarzach. ",
    "",
    "",
    "                  Strona przekazująca\t\t\t\t\t\t    Strona przyjmująca",
    "(podpis)" + " " * 48 + "\t" + " " * 52 + "(podpis)",
]


def _issue_view() -> doc.ProtocolView:
    return doc.ProtocolView(
        kind="wydanie",
        number="PZO/2026/10/014",
        protocol_date=date(2026, 10, 28),
        holder_name="Anna Przykładowa",
        issuer_name="Zofia Testowa",
        lines=(
            doc.LineView(
                1,
                "Laptop DELL Vostro 3530 (221) zasilacz, podkładka, mysz",
                "7KQ2X41",
                1,
                Decimal("2589.00"),
            ),
            doc.LineView(
                2,
                "Telefon Samsung Galaxy A16",
                "IMEI: 350000000002290",
                1,
                Decimal("897.76"),
            ),
            doc.LineView(
                3, "Karta SIM +48 500 000 145", "ICCID: 8948000000000005132", 1, None
            ),
            doc.LineView(
                4, "Słuchawki Evolve2 40 SE", "S/N:00000000012", 1, Decimal("416.97")
            ),
            doc.LineView(5, "Karta dostępu nr 1611", "1611", 1, None),
        ),
    )


def _flatten(blocks: list[dict]) -> list:
    return [
        block["text"] if block["type"] == "paragraph" else block["rows"]
        for block in blocks
    ]


def test_issue_protocol_text_equals_the_reception_template() -> None:
    rendered = _flatten(doc.document_blocks(doc.render_docx(_issue_view())))
    assert rendered == WZOR_WYDANIA


def test_sim_and_access_card_have_no_value_and_do_not_count() -> None:
    view = _issue_view()
    assert doc.protocol_total(view.lines) == Decimal("3903.73")
    context = doc.context_for(view)
    sim = context["lines"][2]
    assert (sim["price"], sim["value"]) == ("—", "—")
    assert context["total_words"] == "trzy tysiące dziewięćset trzy złote 73/100"


def test_amounts_follow_the_template_format() -> None:
    assert doc.amount(Decimal("2589")) == "2589,00"
    assert doc.total_amount(Decimal("1234567.5")) == "1 234 567,50"
    assert doc.total_amount(Decimal("0")) == "0,00"
    assert doc.amount(None) == "—"


def test_return_protocol_swaps_parties_and_lists_condition() -> None:
    view = doc.ProtocolView(
        kind="zwrot",
        number="PZO/2026/11/002",
        protocol_date=date(2026, 11, 30),
        holder_name="Anna Przykładowa",
        issuer_name="Zofia Testowa",
        lines=(
            doc.LineView(
                1,
                "Laptop DELL Vostro 3530 (221)",
                "7KQ2X41",
                1,
                None,
                "uszkodzony",
                "rysa",
            ),
            doc.LineView(2, "Karta SIM +48 500 000 145", None, 1, None, "zgubiony"),
        ),
    )
    rendered = _flatten(doc.document_blocks(doc.render_docx(view)))
    assert rendered[6:11] == [
        "Strona przekazująca: ",
        "Anna Przykładowa",
        "",
        "Strona przyjmująca ",
        "Spółka B2B.net SA, z siedzibą w Warszawie 02-486, Al. Jerozolimskie 180, "
        "z upoważnienia Zofia Testowa",
    ]
    table = next(item for item in rendered if isinstance(item, list))
    assert table[1] == [
        "1",
        "Laptop DELL Vostro 3530 (221)",
        "7KQ2X41",
        "1",
        "uszkodzony",
        "rysa",
    ]
    assert table[2][4] == "zgubiony (brak zwrotu)"
    assert not any("odpowiedzialność materialną" in str(item) for item in rendered)


def test_committed_templates_match_the_builder(tmp_path) -> None:
    """Plik w repo = wynik modułu szablonu (nikt nie edytuje .docx ręcznie)."""
    protocol_template.write_templates(tmp_path)
    for name in (protocol_template.ISSUE_TEMPLATE, protocol_template.RETURN_TEMPLATE):
        built = docx.Document(str(tmp_path / name))
        committed = docx.Document(str(protocol_template.TEMPLATE_DIR / name))
        assert [p.text for p in built.paragraphs] == [
            p.text for p in committed.paragraphs
        ]
        assert [[c.text for c in row.cells] for row in built.tables[0].rows] == [
            [c.text for c in row.cells] for row in committed.tables[0].rows
        ]


def test_template_field_typo_fails_loudly() -> None:
    with pytest.raises(Exception):
        doc._env().from_string("{{ brak_pola }}").render({})


async def test_pdf_goes_through_the_shared_libreoffice_queue(monkeypatch) -> None:
    seen: list[bytes] = []

    async def fake(docx_bytes: bytes) -> bytes:
        seen.append(docx_bytes)
        return b"%PDF-1.7 fikcja"

    monkeypatch.setattr(cv_pdf_preview, "pdf_from_docx", fake)
    pdf = await doc.render_pdf(_issue_view())
    assert pdf.startswith(b"%PDF")
    assert len(seen) == 1
    rendered = docx.Document(io.BytesIO(seen[0]))
    assert rendered.paragraphs[2].text == "nr PZO/2026/10/014"


async def test_pdf_unavailable_is_a_named_error(monkeypatch) -> None:
    async def broken(_docx: bytes) -> bytes:
        raise cv_pdf_preview.PdfPreviewUnavailable("no soffice")

    monkeypatch.setattr(cv_pdf_preview, "pdf_from_docx", broken)
    with pytest.raises(doc.ProtocolPdfUnavailable):
        await doc.render_pdf(_issue_view())
