"""Podział tekstu aktu na jednostki redakcyjne (``services/legal/parse.py``).

Fragmenty są fikcyjne, w formacie tekstów jednolitych z API ELI Sejmu
(linie PDF-u z rozmiarem czcionki, HTML z ``<h3>`` i ``xText``) i wersji
skonsolidowanej z CELLAR. Kształty sprawdzone na prawdziwych plikach
25.11.2026 (KC Dz. U. 2026 poz. 795, KSH Dz. U. 2024 poz. 18, RODO).
"""

from __future__ import annotations

from app.services.legal import parse
from app.services.legal.parse import PdfLine

BODY = 10.0
FOOT = 9.0

PDF_LINES = [
    PdfLine("©Kancelaria Sejmu s. 1/3", BODY),
    PdfLine("OBWIESZCZENIE", BODY),
    PdfLine(
        "„Art. 13. Do umów zawartych przed dniem wejścia w życie stosuje się", BODY
    ),
    PdfLine("Załącznik do obwieszczenia Marszałka Sejmu Rzeczypospolitej", BODY),
    PdfLine("USTAWA", BODY),
    PdfLine("z dnia 1 kwietnia 1999 r.", BODY),
    PdfLine("Kodeks przykładowy1)", BODY),
    PdfLine("TYTUŁ I", BODY),
    PdfLine("Przepisy ogólne", BODY),
    PdfLine("Art. 1. Ustawa reguluje stosunki przykładowe.", BODY),
    PdfLine("1) Niniejsza ustawa wdraża dyrektywę przykładową.", FOOT),
    PdfLine(
        "Art. 2. § 1. Oświadczenie złożone innej osobie jest skuteczne z chwilą, gdy do-",
        BODY,
    ),
    PdfLine("szło do niej w taki sposób, że mogła zapoznać się z jego treścią.", BODY),
    PdfLine("2026-06-22", BODY),
    PdfLine("Dziennik Ustaw – 4 – Poz. 795", BODY),
    PdfLine(
        "§ 2. Oświadczenie wyrażone w postaci elektronicznej jest złożone, gdy:", BODY
    ),
    PdfLine("1) wprowadzono je do środka komunikacji elektronicznej;", BODY),
    PdfLine("2) adresat mógł zapoznać się z jego treścią, w szczególności:", BODY),
    PdfLine("a) otworzył wiadomość,", BODY),
    PdfLine("b) potwierdził odbiór.", BODY),
    PdfLine(
        "§ 2[1]. Przepis § 2 stosuje się odpowiednio do pism w postaci dokumentowej.",
        BODY,
    ),
    PdfLine("Art. 2[1]. (uchylony)", BODY),
    PdfLine("Art. 3. 1. Wysokość opłaty ustala się corocznie.", BODY),
    PdfLine("2. Rada Ministrów przedstawia w terminie do dnia 15 czerwca", BODY),
    PdfLine("3. kwartały roku liczy się od stycznia.", BODY),
    PdfLine("Rozdział 2", BODY),
    PdfLine("Terminy", BODY),
    PdfLine(
        "Art. 4. Termin oznaczony w dniach kończy się z upływem ostatniego dnia.", BODY
    ),
    PdfLine("Załącznik nr 1", BODY),
    PdfLine("Art. 99. Tabela, nie przepis.", BODY),
]


def _by_ref(units):
    return {unit.ref: unit for unit in units}


def test_pdf_lines_give_units_without_notice_footnotes_and_page_noise() -> None:
    units = parse.parse_lines(parse.pdf_body_lines(PDF_LINES))
    by_ref = _by_ref(units)

    assert [u.ref for u in units if u.kind == parse.KIND_ART] == [
        "art. 1",
        "art. 2",
        "art. 2¹",
        "art. 3",
        "art. 4",
    ]
    # Obwieszczenie („Art. 13.” w cudzysłowie) i załącznik („Art. 99.”) odpadają.
    assert "art. 13" not in by_ref and "art. 99" not in by_ref
    # Przypis (mniejsza czcionka) nie dokleja się do art. 1 ani nie robi „pkt 1”.
    assert by_ref["art. 1"].text == "Art. 1. Ustawa reguluje stosunki przykładowe."
    assert "art. 1 pkt 1" not in by_ref
    # Przeniesienie wyrazu „do-” + „szło” łączy się w jedno słowo; stopka i data
    # wydruku między stronami znikają.
    assert by_ref["art. 2 § 1"].text.endswith(
        "gdy doszło do niej w taki sposób, że mogła zapoznać się z jego treścią."
    )
    assert "2026-06-22" not in by_ref["art. 2 § 1"].text
    assert by_ref["art. 2 § 2 pkt 2 lit. b"].text == "b) potwierdził odbiór."
    assert by_ref["art. 2 § 2¹"].key == "2 §2^1"
    assert by_ref["art. 2¹"].repealed is True
    assert by_ref["art. 2 § 2"].text.splitlines()[0].startswith("§ 2. Oświadczenie")
    assert "1) wprowadzono je" in by_ref["art. 2 § 2"].text


def test_numbered_line_out_of_sequence_is_text_not_a_new_unit() -> None:
    units = parse.parse_lines(parse.pdf_body_lines(PDF_LINES))
    by_ref = _by_ref(units)

    assert by_ref["art. 3 ust. 1"].text == "1. Wysokość opłaty ustala się corocznie."
    # „3. kwartały…” po ust. 2 to ust. 3 (kolejny numer), a nie tekst.
    assert "art. 3 ust. 3" in by_ref
    assert by_ref["art. 3"].kind == parse.KIND_ART
    assert by_ref["art. 3 ust. 2"].parent_key == "3"


def test_headings_follow_articles() -> None:
    units = parse.parse_lines(parse.pdf_body_lines(PDF_LINES))
    by_ref = _by_ref(units)

    assert by_ref["art. 1"].heading == "TYTUŁ I — Przepisy ogólne"
    assert by_ref["art. 4"].heading == "Rozdział 2 — Terminy"
    # Jednostka niższa dziedziczy nagłówek artykułu.
    assert by_ref["art. 2 § 1"].heading == "TYTUŁ I — Przepisy ogólne"


ELI_HTML = """<html><body>
<div class="part" id="_001"><h2 class="part"><span>Obwieszczenie</span></h2>
  <div class="unit unit_pass pro-text false" id="pass_2">
    <h3>2.</h3><div class="unit-inner"><div data-template="xText">nie obejmuje:</div>
    <div class="unit unit_arti pro-cite-text false" id="pass_2-arti_11">
      <h3><B>Art.&nbsp;11.</B></h3><div class="unit-inner"><div data-template="xText">cytat</div></div>
    </div></div>
  </div>
</div>
<div class="part" id="_002"><h2 class="part"><span>Załącznik</span> - Tekst jednolity
  <A class="gloss-link tooltip" href="#g"><sup>1)</sup><span>Przypis o dyrektywie</span></A></h2>
  <div class="unit unit_chpt pro-text false" id="chpt_1"><h3>Rozdział 1 Przepisy ogólne</h3>
  <div class="unit-inner">
    <div class="unit unit_arti pro-text false" id="arti_1">
      <h3 CLASS="pro-none"><B CLASS="b">Art.&nbsp;1.</B></h3>
      <div class="unit-inner"><div data-template="xText" CLASS="pro-text">Użyte w ustawie określenia oznaczają:</div>
        <div class="unit unit_pint pro-text false" id="arti_1-pint_1"><h3>1)</h3>
          <div class="unit-inner"><div data-template="xText">„rada” - radę przykładową;</div></div></div>
        <div class="unit unit_pint pro-text false" id="arti_1-pint_1a"><h3>1a)</h3>
          <div class="unit-inner"><div data-template="xText">„stawka” - stawkę za godzinę:</div>
          <div class="unit unit_lett pro-text false" id="arti_1-pint_1a-lett_a"><h3>a)</h3>
            <div class="unit-inner"><div data-template="xText">przy zleceniu,</div></div></div>
          </div></div>
      </div>
    </div>
    <div class="unit unit_arti pro-text false" id="arti_21_1">
      <h3 CLASS="pro-none"><B CLASS="b">Art.&nbsp;21<SUP>1</SUP>.</B></h3>
      <div class="unit-inner">
        <div class="unit unit_para pro-text false" id="arti_21_1-para_1"><h3><B>§&nbsp;1.</B></h3>
          <div class="unit-inner"><div data-template="xText">Spółka kieruje się interesem grupy.</div></div></div>
      </div>
    </div>
  </div></div>
</div></body></html>"""


def test_eli_html_takes_only_the_consolidated_text() -> None:
    units = parse.parse_lines(parse.eli_html_lines(ELI_HTML))
    by_ref = _by_ref(units)

    assert set(by_ref) == {
        "art. 1",
        "art. 1 pkt 1",
        "art. 1 pkt 1a",
        "art. 1 pkt 1a lit. a",
        "art. 21¹",
        "art. 21¹ § 1",
    }
    assert by_ref["art. 1 pkt 1a lit. a"].text == "a) przy zleceniu,"
    assert by_ref["art. 21¹ § 1"].key == "21^1 §1"
    assert by_ref["art. 1"].heading == "Rozdział 1 Przepisy ogólne"
    assert "Przypis" not in " ".join(u.text for u in units)


EURLEX = """<html><body>
<p class="title-article-norm">Artykuł 6</p>
<div class="eli-title"><p class="stitle-article-norm">Zgodność przetwarzania z prawem</p></div>
<div class="norm"><span class="no-parag">1.  </span>
  <div class="norm inline-element"><p class="norm">Przetwarzanie jest zgodne z prawem, gdy:</p>
  <div class="grid-container grid-list"><div class="list grid-list-column-1"><span>a) </span></div>
    <div class="grid-list-column-2"><p class="norm">osoba ▼M1 wyraziła zgodę ( 1 );</p></div></div>
  <div class="grid-container grid-list"><div class="list grid-list-column-1"><span>b) </span></div>
    <div class="grid-list-column-2"><p class="norm">przetwarzanie jest niezbędne do wykonania umowy;</p></div></div>
  </div></div>
<div class="norm"><span class="no-parag">2.  </span><div class="norm inline-element">Państwa mogą wprowadzić przepisy.</div></div>
<p class="footnote">( 1 ) Dyrektywa przykładowa.</p>
<p>ZAŁĄCZNIK I</p><p class="title-article-norm">Artykuł 7</p>
</body></html>"""


def test_eurlex_xhtml_paragraphs_letters_and_title() -> None:
    units = parse.parse_lines(parse.eurlex_lines(EURLEX))
    by_ref = _by_ref(units)

    assert set(by_ref) == {
        "art. 6",
        "art. 6 ust. 1",
        "art. 6 ust. 1 lit. a",
        "art. 6 ust. 1 lit. b",
        "art. 6 ust. 2",
    }
    assert by_ref["art. 6 ust. 1 lit. a"].text == "a) osoba wyraziła zgodę;"
    assert by_ref["art. 6"].heading == "Zgodność przetwarzania z prawem"


def test_keys_normalize_superscripts_and_spelling() -> None:
    assert parse.key_number("442¹") == "442^1"
    assert parse.key_number("442[1]") == "442^1"
    assert parse.key_number("442^1") == "442^1"
    assert parse.display_number("442[1]") == "442¹"
    assert parse.display_number("442^1") == "442¹"
    assert (
        parse.make_key("6", [(parse.KIND_UST, "1"), (parse.KIND_LIT, "b")])
        == "6 ust.1 lit.b"
    )
    assert parse.make_ref("61", [(parse.KIND_PAR, "1")]) == "art. 61 § 1"
