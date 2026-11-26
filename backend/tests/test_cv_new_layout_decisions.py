"""Decyzje Artura o wyglądzie „Nowego CV” jako testy renderera.

Każdy test odpowiada jednej decyzji z `docs/claude/generator-cv/decyzje-wygladu.md`
(identyfikator W1… na początku docstringu). Decyzje wracały po kilku dniach, bo
nic ich nie pilnowało; test sprawdza wynik renderu (HTML strony, SVG osi, raport
dopasowania, PDF, Word), nie stałe w kodzie. Zmiana decyzji = zmiana tamtego pliku
i tego testu w jednym PR-ze, za zgodą Artura.

Pilnowane moduły (sito PR-a wybiera ten plik po ich ścieżce):
app.services.cv_new_layout.page1, app.services.cv_new_layout.education,
app.services.cv_new_layout.highlight, app.services.cv_new_layout.wreath,
app.services.cv_new_layout.axis, app.services.cv_new_layout.fit,
app.services.cv_new_layout.styles, app.services.cv_new_layout.roles,
app.services.cv_new_layout.render, app.services.cv_new_layout.docx_render.

Testy z raportem dopasowania, PDF-em i Wordem potrzebują WeasyPrint; bez
bibliotek natywnych (libpango) są pomijane, jak `test_cv_new_layout_pdf.py`.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import io
import re
from typing import Optional

import pytest

from app.services.cv_new_layout import (
    LayoutSettings,
    NewCvDocument,
    fit_new_cv_page1,
    render_new_cv_html,
)
from app.services.cv_new_layout.document import HighlightChoice
from app.services.cv_new_layout.highlight import choice_from_extras
from tests._cv_new_layout_fixtures import (
    TODAY,
    blind,
    long_cv,
    short_cv,
    tiny_png,
)


def _has_weasyprint() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):  # brak libpango kończy import OSError
        return False
    return True


needs_weasyprint = pytest.mark.skipif(
    not _has_weasyprint(), reason="WeasyPrint niedostępny (brak libpango)"
)

RED = "#E73748"  # czerwień marki: tytuł, etykiety sekcji, bieżąca praca na osi
INK = "#141414"


# ---------- pomocnicze ----------


def _doc(data: dict, **kw) -> NewCvDocument:
    return NewCvDocument.from_cv_json(data, **kw)


def _html(data: dict, settings: Optional[LayoutSettings] = None, **kw) -> str:
    return render_new_cv_html(_doc(data, **kw), settings=settings, today=TODAY)


def _page1(html: str) -> str:
    return html[html.index("<div class='p1'>") : html.index("<div class='rest'>")]


def _rest(html: str) -> str:
    return html[html.index("<div class='rest'>") :]


def _section(html: str, title: str) -> str:
    """Blok strony 1 od nagłówka sekcji do następnej sekcji."""
    p1 = _page1(html)
    start = p1.index(f"<h2><span>{title}</span></h2>")
    end = p1.find("<div class='blk'>", start)
    return p1[start : end if end != -1 else len(p1)]


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def _css(html: str) -> str:
    css = html[html.index("<style>") + len("<style>") : html.index("</style>")]
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _decl(html: str, selector: str) -> dict[str, str]:
    """Deklaracje, które przeglądarka zastosuje dla `selector`: wszystkie reguły
    z tym selektorem po kolei, późniejsza wartość wygrywa."""
    out: dict[str, str] = {}
    for selectors, body in _RULE.findall(_css(html)):
        if selector not in (s.strip() for s in selectors.split(",")):
            continue
        for item in body.split(";"):
            key, sep, value = item.partition(":")
            if sep:
                out[key.strip()] = value.strip()
    return out


def _pt(value: str) -> float:
    return float(re.match(r"([\d.]+)pt", value).group(1))


def _axis(html: str) -> str:
    return re.search(r'<svg class="axis".*?</svg>', html, re.S).group(0)


_RECT = re.compile(
    r'<rect x="([-\d.]+)" y="[^"]+" width="([\d.]+)" height="[^"]+" fill="([^"]+)"'
)
_TEXT = re.compile(
    r'<text x="([-\d.]+)" y="([-\d.]+)" text-anchor="(\w+)"[^>]*>([^<]*)</text>'
)


def _rects(svg: str) -> list[tuple[float, float, str]]:
    """(x, szerokość, kolor) odcinków paska."""
    return [(float(x), float(w), fill) for x, w, fill in _RECT.findall(svg)]


def _texts(svg: str) -> list[tuple[float, float, str, str]]:
    """(x, y, wyrównanie, tekst) napisów osi; y < 0 = nad paskiem, y > 0 = pod nim."""
    return [(float(x), float(y), a, t) for x, y, a, t in _TEXT.findall(svg)]


def _words(svg: str) -> str:
    """Napisy osi po kolei jednym ciągiem — nazwa łamana na linie wraca w całości."""
    return " ".join(t for *_, t in _texts(svg))


def _with_roles(*roles: tuple[str, str, str]) -> dict:
    """CV z podanymi stanowiskami (daty, firma, stanowisko)."""
    data = short_cv()
    data["experience"] = [
        {
            "dates": dates,
            "company": company,
            "industry": "",
            "position": position,
            "technologies": [],
            "responsibilities": [],
        }
        for dates, company, position in roles
    ]
    return data


def _with_client(names: list[str]) -> dict:
    data = long_cv()
    data["client_names"] = names
    return data


def _medium_cv(groups: int, per_group: int) -> dict:
    """`long_cv` z mniejszą liczbą umiejętności — strona 1 bez skróceń."""
    data = long_cv()
    data["skills"] = [
        dict(g, content=", ".join(g["content"].rstrip(".").split(", ")[:per_group]))
        for g in data["skills"][:groups]
    ]
    return data


def _fit(data: dict, **kw):
    return fit_new_cv_page1(_doc(data, **kw), today=TODAY)


@pytest.fixture(scope="module")
def short_fit():
    return _fit(short_cv())


# ---------- nagłówek i stopka ----------


def test_w01_header_is_the_logo_and_footer_the_company_data():
    """W1: nagłówek strony to samo logo (bez hasła, maila i adresu strony),
    stopka to wyśrodkowane dane spółki."""
    html = _html(long_cv())
    css = _css(html)
    heads = re.findall(r"@top-left\{([^{}]*)\}", css)
    assert len(heads) == 2  # strona 1 i dalsze
    for head in heads:
        assert "content:''" in head and "b2bnetwork.svg" in head
    feet = re.findall(r"@bottom-center\{([^{}]*)\}", css)
    assert len(feet) == 2
    for foot in feet:
        assert re.search(r"content:'B2B\.net S\.A\. · [^']*KRS [^']*NIP ", foot)
    page = "".join(heads + feet) + _page1(html)
    for gone in ("Invisible Support", "Hub kompetencji", "office@", "b2bnetwork.pl"):
        assert gone not in page


# ---------- tytuł i pastylki ----------


def test_w02_title_is_the_position_with_the_name_under_a_thin_line():
    """W2: nagłówek T2 — stanowisko duże czerwone (19 pt), pod nim cienka linia
    i imię z nazwiskiem (12 pt); bez myślnika i bez „Kandydat na stanowisko”.
    CV Blind: samo stanowisko."""
    html = _html(long_cv())
    assert (
        "<div class='tcol'><h1 class='title'>Starszy analityk danych</h1>"
        "<div class='nm'>Łucja Przykładowa</div></div>"
    ) in html
    assert "Kandydat na stanowisko" not in html
    assert "Starszy analityk danych –" not in html
    title = _decl(html, "h1.title")
    assert " 19pt/" in title["font"] and "Poppins" in title["font"]
    assert title["color"] == RED
    name = _decl(html, ".trow .nm")
    assert " 12pt/" in name["font"] and name["border-top"].startswith(".3mm solid")
    hidden = _html(blind(long_cv()))
    assert "<h1 class='title'>Starszy analityk danych</h1></div>" in hidden
    assert "class='nm'" not in hidden


def _pills(html: str) -> list[tuple[str, str]]:
    return re.findall(r"<span class='pill'><b>(\w+)</b>([^<]*)</span>", html)


def test_w03_language_pills_only_from_b1():
    """W3: języki w pastylkach obok tytułu tylko od B1 (A1, A2, „podstawowy” i „basic”
    znikają, opis bez poziomu zostaje); ojczysty i dwujęzyczny = „ojczysty”,
    „C1/C2” w całości."""
    data = long_cv()
    data["languages"] = [
        "Polski - ojczysty lub dwujęzyczny",
        "Angielski - C1/C2",
        "Niemiecki - A2",
        "Rosyjski - podstawowy",
        "Francuski - basic",
        "Hiszpański - B1",
        "Włoski - komunikatywny",
    ]
    html = _html(data)
    trow = _page1(html)[: _page1(html).index("<div class='blk'>")]
    assert _pills(trow) == [
        ("PL", " ojczysty"),
        ("EN", " C1/C2"),
        ("ES", " B1"),
        ("IT", " komunikatywny"),
    ]
    assert "<div class='pills'>" in trow  # w tym samym rzędzie co tytuł


def test_w04_city_pill_with_pin():
    """W4: miasto kandydata w pastylce z pinezką: „, PL” obcięte, inny kraj zostaje
    kodem; bez miasta albo w CV Blind — bez pastylki."""
    home = _html(dict(long_cv(), candidate_location="Kraków, PL"))
    assert re.search(
        r"<span class='pill loc'><svg class='pin'.*?</svg>Kraków</span>", home
    )
    assert "Kraków, PL" not in home
    abroad = _html(dict(long_cv(), candidate_location="Berlin, DE"))
    assert "</svg>Berlin, DE</span>" in abroad
    assert "pill loc" not in _html(long_cv())
    assert "pill loc" not in _html(
        blind(dict(long_cv(), candidate_location="Kraków, PL"))
    )


# ---------- wyróżnik i wieniec ----------


def test_w05_highlight_under_the_name_without_frame_or_background():
    """W5: wyróżnik stoi między nazwiskiem a „Dlaczego nasz kandydat”: wieniec ze
    znakiem, etykieta i jedno zdanie, bez ramki i tła."""
    html = _html(_with_client(["Bank Przykładowy"]))
    p1 = _page1(html)
    assert (
        p1.index("class='nm'")
        < p1.index("<div class='hl'>")
        < p1.index("<div class='blk'>")
    )
    block = p1[p1.index("<div class='hl'>") : p1.index("<div class='blk'>")]
    assert block.count('class="hlw"') == 1
    assert "class='hlk'" in block and "class='hlt'" in block
    look = {**_decl(html, ".hl"), **_decl(html, ".hlt")}
    assert not [
        k
        for k in look
        if k.startswith(("border", "background", "box-shadow", "outline"))
    ]


def test_w06_automatic_highlight_is_work_at_the_client():
    """W6: wyróżnik automatyczny = praca u klienta rekrutacji: „Doświadczenie w {klient}
    · lata”, zdanie z dat i stanowiska, w wieńcu nazwa klienta do 8 znaków, inaczej
    staż; nigdy „Zna klienta od środka”. Blind i „off” — bez wyróżnika, „custom” —
    słowa rekrutera."""
    html = _html(_with_client(["Bank Przykładowy"]))
    block = _page1(html)[_page1(html).index("<div class='hl'>") :]
    assert (
        "<div class='hlk'>Doświadczenie w Bank Przykładowy · 2023–dziś</div>" in block
    )
    assert (
        "<div class='hlt'><b>3 lata 9 mies. jako Główny analityk danych</b>"
        " w Bank Przykładowy.</div>"
    ) in block
    assert re.search(
        r'class="hlw".*?>3 lata</text></svg>', block, re.S
    )  # nazwa > 8 znaków
    short = _page1(_html(_with_client(["Beta"])))
    assert re.search(r'class="hlw".*?>Beta</text></svg>', short, re.S)
    assert "Doświadczenie w Beta · 2021–2023" in short
    assert "Zna klienta od środka" not in html
    assert "class='hl'" not in _html(blind(_with_client(["Bank Przykładowy"])))
    off = _html(_with_client(["Bank Przykładowy"]), highlight=HighlightChoice("off"))
    assert "class='hl'" not in off
    custom = _html(
        long_cv(),
        highlight=HighlightChoice(
            "custom", "Wyróżnienie", "2015", "**Nagroda** zespołu."
        ),
    )
    assert (
        "<div class='hlk'>Wyróżnienie</div><div class='hlt'><b>Nagroda</b> zespołu.</div>"
        in custom
    )


def test_w07_wreath_only_next_to_the_highlight():
    """W7: wieniec tylko u góry — jeden na stronie, wyłącznie przy wyróżniku; bez
    wyróżnika strona nie ma wieńca, Edukacja nigdy, a stary wpis
    `page1_extras.wreath` nie zmienia renderu."""
    with_hl = _html(_with_client(["Bank Przykładowy"]))
    assert with_hl.count('class="hlw"') == 1
    hl = _page1(with_hl)[_page1(with_hl).index("<div class='hl'>") :]
    assert hl.index('class="hlw"') < hl.index("<div class='blk'>")
    for html in (with_hl, _html(long_cv())):
        edu = _section(html, "Edukacja")
        assert "hlw" not in edu and "0 0 32.0 32.0" not in edu
    data = dict(long_cv(), must_have=["PRINCE2 Practitioner"])
    data["certifications"] = data["certifications"] + [
        "PRINCE2 Practitioner - Axelos (2021)"
    ]
    old = _html(data, highlight=choice_from_extras({"wreath": "cert"}))
    body = old[old.index("<body>") :]
    assert 'class="hlw"' not in body and "0 0 32.0 32.0" not in body


# ---------- „Dlaczego nasz kandydat” ----------


def test_w08_why_has_three_sentences_without_bullets_between_thin_rules():
    """W8: „Dlaczego nasz kandydat” — najwyżej trzy zdania, bez punktorów,
    oddzielone cienkimi liniami poziomymi."""
    html = _html(long_cv())  # generator dał 4 punkty
    why = _section(html, "Dlaczego nasz kandydat")
    assert why.count("<li>") == 3 and "Czwarty punkt" not in html
    assert _decl(html, "ul.why")["list-style"] == "none"
    assert _decl(html, "ul.why li::before")["display"] == "none"
    assert "solid" in _decl(html, "ul.why li")["border-top"]
    assert "solid" in _decl(html, "ul.why li:last-child")["border-bottom"]


def test_w09_numbers_in_why_are_only_bold():
    """W9: liczby i fakty w zdaniach „Dlaczego” tylko pogrubione — bez większego
    kroju i bez czerwieni."""
    html = _html(long_cv())
    why = _section(html, "Dlaczego nasz kandydat")
    assert "<li><b>Ponad 15 lat</b> doświadczenia" in why
    bold = _decl(html, "ul.why li b")
    assert bold["font-weight"] == "700" and bold["color"] == INK
    assert "font-size" not in bold and "font" not in bold
    assert RED not in _decl(html, "ul.why li").get("color", "")


def test_w10_why_grows_with_the_page_font():
    """W10: zdania „Dlaczego” rosną razem z pismem strony 1."""
    big = _pt(
        _decl(_html(long_cv(), LayoutSettings(font_pt=11)), "ul.why li")["font-size"]
    )
    small = _pt(
        _decl(_html(long_cv(), LayoutSettings(font_pt=9)), "ul.why li")["font-size"]
    )
    assert big / small == pytest.approx(11 / 9, rel=0.01)
    assert big >= 11


# ---------- kolejność, etykiety, odstępy ----------


def test_w11_page1_order():
    """W11: kolejność strony 1 — tytuł z językami i miastem, wyróżnik, Dlaczego,
    Przebieg kariery, Umiejętności, Edukacja."""
    p1 = _page1(_html(_with_client(["Bank Przykładowy"])))
    marks = [
        "<div class='trow'>",
        "<div class='hl'>",
        "<span>Dlaczego nasz kandydat</span>",
        "<span>Przebieg kariery</span>",
        "<span>Umiejętności</span>",
        "<span>Edukacja</span>",
    ]
    where = [p1.index(m) for m in marks]
    assert where == sorted(where)


def test_w12_section_labels_are_red_tags_with_a_rule_to_the_edge():
    """W12: nagłówki sekcji strony 1 — biały napis na czerwonej etykiecie i czerwona
    linia do prawej krawędzi."""
    html = _html(long_cv())
    assert _page1(html).count("<h2><span>") == 4
    tag = _decl(html, ".p1 h2 span")
    assert tag["background"] == RED and tag["color"] == "#fff"
    rule = _decl(html, ".p1 h2::after")
    assert (
        rule["content"] == "''"
        and rule["flex"] == "1"
        and rule["border-top"].endswith(RED)
    )


def test_w13_fixed_gap_above_every_section():
    """W13: stały odstęp 5,5 mm nad każdą sekcją strony 1 („nie może się zlewać”),
    także gdy wolne miejsce rozsuwa sekcje."""
    for gap in (0.0, 3.0):
        html = _html(long_cv(), LayoutSettings(block_gap_mm=gap))
        p1 = _page1(html)
        assert p1.count("<div class='blk'><h2>") == p1.count("<h2>") == 4
        block = _decl(html, ".p1>.blk")
        assert block["padding-top"] == "5.5mm" and block["margin-top"] == f"{gap:.2f}mm"


# ---------- dopasowanie strony 1 ----------


@needs_weasyprint
def test_w14_page1_font_goes_down_from_11_pt(short_fit):
    """W14: pismo strony 1 od 11 pt w dół — mało treści dostaje 11 pt, nie dziury;
    10–11 pt to wypełnianie kartki, nie skrócenie w komunikacie."""
    assert short_fit.fits and short_fit.font_pt == 11.0 and short_fit.steps == ()
    assert short_fit.summary == "strona 1 mieści się · pismo 11 pt"
    medium = _fit(_medium_cv(8, 10))
    assert 10.0 <= medium.font_pt < 11.0, (
        "fikstura miała wyjść między 10 a 11 pt — dobierz liczbę umiejętności",
        medium,
    )
    assert medium.fits and medium.steps == ()


@needs_weasyprint
def test_w15_free_space_half_inside_sections_rest_between_them():
    """W15: wolne miejsce strony 1 — około połowy w środek sekcji (odstępy zdań,
    wierszy, osi), reszta równo między sekcje."""
    report = _fit(_medium_cv(5, 10))
    assert report.free_mm and report.free_mm > 10
    assert report.inner_mm > 0 and report.block_gap_mm > 0
    html = _html(_medium_cv(5, 10), report.settings)
    blocks = _page1(html).count("<div class='blk'>")
    between = report.block_gap_mm * blocks
    assert 0.35 <= 1 - between / report.free_mm <= 0.65, report
    assert _decl(html, ".p1>.blk")["margin-top"] == f"{report.block_gap_mm:.2f}mm"
    assert float(_decl(html, "ul.why li")["padding"].split("mm")[0]) > 2.1


@needs_weasyprint
def test_w16_page1_always_fits_font_first_then_shorter_lists():
    """W16: strona 1 zawsze na jednej kartce A4 — najpierw mniejsze pismo (do 9 pt),
    dopiero potem krótsze listy umiejętności („+N”, pełna lista na str. 2)."""
    import pdfplumber

    from app.services.cv_new_layout import render_new_cv_pdf_with_report

    pdf, report = render_new_cv_pdf_with_report(_doc(long_cv()), today=TODAY)
    assert report.fits and report.skill_cap is not None
    assert report.font_pt <= 9.0, report  # listy skracane dopiero przy 9 pt
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        pages = [re.sub(r"\s+", " ", p.extract_text() or "") for p in document.pages]
    for heading in (
        "DLACZEGO NASZ KANDYDAT",
        "PRZEBIEG KARIERY",
        "UMIEJĘTNOŚCI",
        "EDUKACJA",
    ):
        assert heading in pages[0]
    assert "Zakres zadań" not in pages[0] and "pełna lista na str. 2" in pages[0]
    assert pages[1].startswith("UMIEJĘTNOŚCI — PEŁNA LISTA")


# ---------- przebieg kariery ----------


def test_w17_career_axis_in_order_not_in_time_scale():
    """W17: przebieg kariery po kolei, nie w skali czasu — roczna praca nie jest
    kreską obok dziewięcioletniej, odcinki wypełniają szerokość bez przerw
    (także gdy w datach jest przerwa)."""
    data = _with_roles(
        ("01.2022 – obecnie", "Firma Obecna", "Analityk"),
        ("01.2019 - 12.2019", "Firma Krótka", "Analityk"),
        ("01.2010 - 12.2018", "Firma Długa", "Analityk"),
    )
    rects = _rects(_axis(_html(data)))
    assert len(rects) == 3
    widths = [w for _, w, _ in rects]
    assert sum(widths) == pytest.approx(180.0, abs=0.1)
    assert max(widths) / min(widths) < 4  # w skali czasu byłoby 9
    for (x1, w1, _), (x2, _, _) in zip(rects, rects[1:]):
        assert x2 == pytest.approx(x1 + w1, abs=0.02)


def test_w18_full_company_above_start_year_and_position_below():
    """W18: nad odcinkiem pełna nazwa firmy (bez formy prawnej i branży z edytora,
    nigdy „…”), pod nim rok rozpoczęcia i stanowisko; bieżąca praca czerwona,
    na końcu „dziś”."""
    data = _with_roles(
        ("01.2022 – obecnie", "Bank Przykładowy S.A.", "Analityk"),
        (
            "03.2019 - 12.2021",
            "Przykładowa Spółka Doradcza sp. z o.o. · Doradztwo",
            "Konsultant",
        ),
    )
    svg = _axis(_html(data))
    texts = _texts(svg)
    above = " ".join(t for _, y, _, t in texts if y < 0)
    below = [t for _, y, a, t in texts if y > 0 and a == "start"]
    assert above == "Przykładowa Spółka Doradcza Bank Przykładowy"
    assert [t for t in below if re.fullmatch(r"\d{4}", t)] == ["2019", "2022"]
    assert "Konsultant" in below and "Analityk" in below
    for gone in ("…", "sp. z o.o", "S.A.", "Doradztwo", "–"):
        assert gone not in svg
    rects = _rects(svg)
    assert rects[-1][2] == RED and rects[0][2] != RED
    assert texts[-1][2:] == ("end", "dziś")


def test_w19_consecutive_short_jobs_share_one_segment():
    """W19: kolejne krótkie zlecenia (< 9 mies.) jednym odcinkiem „A · B · C”, pod
    nim „3 krótkie projekty”."""
    data = _with_roles(
        ("05.2024 – obecnie", "Firma Kappa", "Tester"),
        ("11.2023 – 04.2024", "Firma Lambda", "Tester"),
        ("06.2023 – 10.2023", "Firma Mi", "Tester"),
        ("01.2023 – 05.2023", "Firma Ni", "Tester"),
        ("2019 - 2022", "Firma Ksi", "Tester"),
    )
    svg = _axis(_html(data))
    assert len(_rects(svg)) == 3
    words = _words(svg)
    assert "Firma Ni · Firma Mi · Firma Lambda" in words
    assert "3 krótkie projekty" in words


def _one_and_a_half_years(n: int) -> dict:
    roles = []
    for i in range(n):
        start = 2012 * 12 + i * 18
        end = start + 17
        roles.append(
            (
                f"{start % 12 + 1:02d}.{start // 12} - "
                + ("obecnie" if i == n - 1 else f"{end % 12 + 1:02d}.{end // 12}"),
                f"Firma {i}",
                "Analityk",
            )
        )
    return _with_roles(*reversed(roles))


def test_w20_at_most_seven_segments_oldest_as_earlier():
    """W20: najwyżej 7 odcinków; najstarsi w jednym jasnym odcinku „Wcześniej ·
    N stanowisk”, pod nim „m.in.” dwie najdłuższe firmy."""
    svg = _axis(_html(_one_and_a_half_years(9)))
    rects = _rects(svg)
    assert len(rects) == 7
    assert rects[0][2] not in (RED,) and rects[0][2] != rects[1][2]  # jasny odcinek
    words = _words(svg)
    assert re.search(r"Wcześniej · 3 stanowiska", words)
    assert "m.in. Firma 0, Firma 1" in words
    assert "Firma 8" in words


def test_w20_no_ten_or_twelve_year_window():
    """W20: okno 10/12 lat odrzucone — gdy pracodawcy się mieszczą, oś zaczyna się
    od pierwszej pracy."""
    data = _with_roles(
        ("01.2019 – obecnie", "Firma E", "Analityk"),
        ("01.2013 - 12.2018", "Firma D", "Analityk"),
        ("01.2007 - 12.2012", "Firma C", "Analityk"),
        ("01.2001 - 12.2006", "Firma B", "Analityk"),
        ("01.1996 - 12.2000", "Firma A", "Analityk"),
    )
    svg = _axis(_html(data))
    assert len(_rects(svg)) == 5 and "Wcześniej" not in svg
    years = [t for _, y, a, t in _texts(svg) if y > 0 and re.fullmatch(r"\d{4}", t)]
    assert years[0] == "1996"
    assert all(f"Firma {c}" in _words(svg) for c in "ABCDE")


def test_w21_only_the_main_path_and_one_segment_per_employer():
    """W21: na osi tylko główna ścieżka — stanowisko w całości w innym to projekt
    równoległy (opis od str. 2); kolejne stanowiska w tej samej firmie to jeden
    odcinek."""
    html = _html(long_cv())
    words = _words(_axis(html))
    assert "Logistyka Gamma" in words
    assert "Projekt Delta" not in words  # w całości w Logistyka Gamma
    assert "Projekt Delta" in _rest(html)
    data = _with_roles(
        ("01.2021 – obecnie", "Firma Beta", "Analityk"),
        ("01.2018 - 12.2020", "Firma Alfa", "Starszy analityk"),
        ("01.2015 - 12.2017", "Firma Alfa", "Analityk"),
    )
    svg = _axis(_html(data))
    assert len(_rects(svg)) == 2
    assert _words(svg).count("Firma Alfa") == 1


def test_w22_without_current_job_the_axis_ends_with_the_last_year():
    """W22: CV bez bieżącej pracy — oś kończy się rokiem ostatniej pracy, bez „dziś”."""
    data = _with_roles(
        ("01.2021 - 06.2023", "Firma B", "Analityk"),
        ("01.2018 - 12.2020", "Firma A", "Analityk"),
    )
    svg = _axis(_html(data))
    assert _texts(svg)[-1][2:] == ("end", "2023")
    assert "dziś" not in svg and RED not in [fill for *_, fill in _rects(svg)]


# ---------- umiejętności ----------


def test_w23_skills_index_with_bars_and_bold_keys_in_place():
    """W23: umiejętności jako indeks — kategoria po lewej, pozycje rozdzielone
    pionowymi kreskami; pozycje z rekrutacji pogrubione w swojej kategorii, bez
    osobnego wiersza „Kluczowe dla tej rekrutacji”."""
    data = short_cv()
    data["skills"] = [
        {"label": "Narzędzia", "content": "Confluence, Jira, Git"},
        {"label": "Testowanie", "content": "testy manualne, testy API"},
    ]
    data["highlight_keywords"] = ["Jira"]
    html = _html(data)
    skills = _section(html, "Umiejętności")
    assert re.search(
        r"<div class='s1r'><div class='s1c'>Narzędzia</div><div class='s1i'>"
        r"<span class='it k sep'>Jira</span>.<span class='it sep'>Confluence</span>"
        r".<span class='it'>Git</span></div></div>",
        skills,
    )
    assert "Kluczowe dla tej rekrutacji" not in html
    bar = _decl(html, ".s1i .it.sep::after")
    assert bar["content"] == "''" and bar["width"] == ".3mm"
    assert _decl(html, ".s1i .it.k")["font-weight"] == "700"


def test_w24_overflow_as_plus_n_with_the_full_list_on_page2():
    """W24: nadmiar pozycji kategorii jako „+N” z dopiskiem, pełna lista
    umiejętności na str. 2."""
    html = _html(long_cv(), LayoutSettings(font_pt=9, skill_cap=4))
    skills = _section(html, "Umiejętności")
    assert "<span class='more'> +10</span>" in skills
    assert "pełna lista na str. 2" in _plain(skills)
    assert "REST API 0.13" not in skills
    rest = _rest(html)
    assert "<h2>Umiejętności — pełna lista</h2>" in rest and "REST API 0.13" in rest


# ---------- edukacja ----------


def test_w25_education_always_two_columns_with_icons():
    """W25: Edukacja zawsze w dwóch kolumnach z ikonami (biret przy „Wykształceniu”,
    odznaka przy „Certyfikatach i szkoleniach”): kierunek, stopień · rok, uczelnia;
    certyfikat, wystawca · rok — z wyróżnikiem i bez niego."""
    for html in (_html(long_cv()), _html(_with_client(["Bank Przykładowy"]))):
        edu = _section(html, "Edukacja")
        assert re.search(
            r"<div class='edp'><div><div class='edh'><svg class='ic'.*?</svg>"
            r"<span>Wykształcenie</span></div><div class='edi'>"
            r"<div class='edf'>Informatyka</div><div class='edd'>Magister inżynier · 2008</div>"
            r"<div class='edu'>Politechnika Wzorcowa</div></div>",
            edu,
            re.S,
        )
        assert re.search(
            r"<div><div class='edh'><svg class='ic'.*?</svg>"
            r"<span>Certyfikaty i szkolenia · 10</span></div>"
            r"<div class='edi c'><div class='edf'>Azure Data Fundamentals</div>"
            r"<div class='edd'>Microsoft</div></div>",
            edu,
            re.S,
        )
        icons = re.findall(r"<svg class='ic'.*?</svg>", edu, re.S)
        assert len(icons) == 2 and icons[0] != icons[1]
        assert "<div class='edd'>Instytut Przykładowy · 2022</div>" in edu
    columns = _decl(html, ".edp")["grid-template-columns"].split()
    assert len(columns) == 2


def test_w26_school_shows_the_graduation_year_only():
    """W26: przy szkole tylko rok ukończenia, bez dat studiów od–do."""
    edu = _section(_html(long_cv()), "Edukacja")  # szkoła „2005 - 2008”
    assert "Magister inżynier · 2008" in edu
    assert "2005" not in edu


def test_w27_highest_finished_school_on_page1_the_rest_at_the_end():
    """W27: na stronie 1 najwyższe ukończone wykształcenie (przerwane studia się nie
    liczą), pozostałe szkoły w pełnej tabeli na końcu CV."""
    data = long_cv()
    data["education"] = [
        {"dates": "2010 - 2012", "degree": "Fizyka - doktor, studia przerwane",
         "institution": "Uniwersytet Testowy", "location": ""},
        {"dates": "1998 - 2002", "degree": "", "institution": "Liceum Ogólnokształcące nr 1",
         "location": ""},
        {"dates": "2002 - 2005", "degree": "Matematyka - licencjat",
         "institution": "Uniwersytet Testowy", "location": ""},
        {"dates": "2005 - 2008", "degree": "Informatyka - magister inżynier",
         "institution": "Politechnika Wzorcowa", "location": ""},
    ]  # fmt: skip
    html = _html(data)
    edu = _section(html, "Edukacja")
    assert "<div class='edf'>Informatyka</div>" in edu
    for other in ("Fizyka", "Matematyka", "Liceum"):
        assert other not in edu
    assert "+ 3 szkoły — pełna lista na końcu CV" in _plain(edu)
    table = re.search(r"<table class='edu'>.*?</table>", _rest(html), re.S).group(0)
    for school in (
        "Uniwersytet Testowy",
        "Liceum Ogólnokształcące nr 1",
        "Politechnika Wzorcowa",
    ):
        assert school in table


def _cert_names(edu: str) -> list[str]:
    return re.findall(r"<div class='edi c'><div class='edf'>([^<]+)</div>", edu)


def test_w28_at_most_three_certificates_on_page1():
    """W28: najwyżej 3 certyfikaty na stronie 1, reszta w pełnej liście na końcu CV;
    liczba w „Certyfikaty i szkolenia · N” to wszystkie."""
    html = _html(long_cv())  # 10 certyfikatów
    edu = _section(html, "Edukacja")
    assert len(_cert_names(edu)) == 3
    assert "Certyfikaty i szkolenia · 10" in edu
    assert "+ 7 certyfikatów — pełna lista na końcu CV" in _plain(edu)
    rest = _rest(html)
    assert all(f"Certyfikat danych {i}" in rest for i in range(9))


def test_w29_most_relevant_certificates_and_client_must_first():
    """W29: na stronę 1 idą certyfikaty najważniejsze dla roli, nie najnowsze;
    certyfikat z wymagań MUST klienta stoi pierwszy, kurs ani umiejętność się
    nie liczą."""
    data = dict(
        long_cv(),
        presentation_position="Kierownik projektu IT",
        must_have=["PRINCE2 Practitioner", "UX Design"],
    )
    data["certifications"] = [
        "Kurs UX Design - Akademia (2025)",
        "Inny certyfikat (2024)",
        "Certyfikat C (2023)",
        "PMP - PMI (2015)",
        "PRINCE2 Practitioner - Axelos (2012)",
    ]
    names = _cert_names(_section(_html(data), "Edukacja"))
    assert names[:2] == ["PRINCE2 Practitioner", "PMP"]
    assert "Inny certyfikat" not in names and "Certyfikat C" not in names


# ---------- od strony 2 ----------


def test_w30_roles_from_page2_are_form_tables_without_empty_rows():
    """W30: od strony 2 każde stanowisko jako tabela-formularz (Okres, Nazwa firmy,
    Stanowisko, Zakres zadań, Technologie); puste pola znikają, tabela nie dzieli
    się między strony."""
    data = long_cv()
    data["experience"][-1]["technologies"] = []
    data["experience"][-1]["responsibilities"] = []
    html = _html(data)
    tables = re.findall(r"<table class='role'>.*?</table>", _rest(html), re.S)
    assert len(tables) == len(data["experience"])
    heads = [re.findall(r"<th>([^<]+)</th>", t) for t in tables]
    assert heads[0] == [
        "Okres",
        "Nazwa firmy",
        "Stanowisko",
        "Zakres zadań",
        "Technologie",
    ]
    assert heads[-1] == ["Okres", "Nazwa firmy", "Stanowisko"]
    assert _decl(html, "table.role")["break-inside"] == "avoid"
    assert _decl(html, ".rest")["break-before"] == "page"


def test_w31_consent_and_rodo_close_the_cv():
    """W31: zrzut zgody i klauzula RODO na samym końcu CV, zrzut przed klauzulą."""
    rest = _rest(_html(long_cv(), consent_image=tiny_png()))
    last_role = rest.rindex("<table class='role'>")
    consent = rest.index("<div class='consent'>")
    rodo = rest.index("<div class='rodo'>")
    assert last_role < consent < rodo
    assert rest.rfind("<div") == rodo


# ---------- kroje ----------


def test_w32_poppins_and_source_sans_3_only():
    """W32: kroje Poppins (nagłówki, tytuł, etykiety) i Source Sans 3 (tekst strony 1),
    z plików w repo."""
    html = _html(long_cv())
    faces = set(re.findall(r"@font-face\{font-family:'([^']+)'", _css(html)))
    assert faces == {"Poppins", "Source Sans 3"}
    assert _decl(html, "body")["font-family"].startswith("Poppins")
    assert _decl(html, ".p1")["font-family"].startswith("'Source Sans 3'")
    for selector in ("h1.title", ".p1 h2"):
        assert "Poppins" in _decl(html, selector)["font"]
    families = set(re.findall(r'font-family="([^"]+)"', html))
    assert families <= {"Poppins", "Source Sans 3"}


# ---------- Word ----------


@needs_weasyprint
def test_w33_word_page1_is_the_pdf_image_then_editable_tables():
    """W33: Word „Nowego CV” (wariant B) — strona 1 to obraz strony 1 PDF, od strony 2
    tekst i tabele Worda, Poppins osadzony w pliku."""
    from docx import Document
    from docx.oxml.ns import qn

    from app.services.cv_new_layout import render_new_cv_pdf_with_report
    from app.services.cv_new_layout.docx_render import render_new_cv_docx

    doc = _doc(short_cv())
    pdf, report = render_new_cv_pdf_with_report(doc, today=TODAY)
    document = Document(
        io.BytesIO(
            render_new_cv_docx(
                doc,
                pdf,
                skill_cap=report.skill_cap,
                skill_groups=report.skill_groups,
                today=TODAY,
            )
        )
    )
    first = list(document.element.body)[0]
    assert first.findall(".//" + qn("w:drawing"))
    assert not "".join(t.text or "" for t in first.iter(qn("w:t"))).strip()
    cells = [c.text for t in document.tables for row in t.rows for c in row.cells]
    assert "Firma Kappa" in cells and "Zakres zadań" in cells
    settings = [c.tag.split("}")[1] for c in document.settings.element]
    assert "embedTrueTypeFonts" in settings
