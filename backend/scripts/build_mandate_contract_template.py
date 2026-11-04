"""Builder: wzór działu „Umowa zlecenia” (z DPA) → szablon generatora umów.

Wzór od Artura z 26.10.2026 (``wzor_umowa_zlecenie_Z_DPA_.docx``, ostatnia
zmiana 04.09.2026): umowa, Załącznik nr 1 (Deklaracja Poufności) i Załącznik
nr 2 (umowa powierzenia przetwarzania danych). Zapisuje do
``app/templates/contract/`` (obok umowy B2B — katalog ``documents/`` trzyma
wyłącznie typy z rejestru dokumentów pochodnych):

    umowa_zlecenie_pl.docx  — szablon docxtpl
    umowa_zlecenie_pl.html  — lustro Jinja do podglądu

Zasady jak w ``build_b2b_document_templates.py`` (te same klocki):

* pola wzoru (``……``, ``___``, żółte podświetlenia) → placeholdery,
  formy „Panem/Panią”, „zamieszkałym/łą”… → ``{{ g.* }}``;
* czynności z § 1 ust. 1 to lista ``doc.task_items`` (litera + treść);
* Załącznik nr 2 (DPA) jest warunkowy (``doc.with_dpa``) razem ze wzmianką
  w § 7 i na liście załączników; cel przetwarzania z § 2 ust. 3 DPA pisany
  był pod jedno zlecenie (platforma AI) — teraz to pole ``doc.dpa_purpose``
  (decyzja Artura 26.10.2026);
* PESEL, dowód i adres zamieszkania idą wyłącznie do pliku — NEXUS ich nie
  zapisuje (``partner.*`` tylko w chwili renderu).

Numeracja ustępów, które cytują aneks i porozumienie zlecenia, zostaje bez
zmian: § 2 ust. 2 (okres), § 3 ust. 1 (stawka).

Uruchom po zmianie wzoru; wynik jest commitowany. Wzoru NIE commitujemy
(ma metadane z nazwiskami).

    python scripts/build_mandate_contract_template.py <wzór.docx> [katalog_wyjściowy]
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

import docx
from docx.document import Document as _Doc
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_b2b_document_templates import (  # noqa: E402
    COMPANY_PL_FULL,
    COMPANY_PL_SHORT,
    NAME_INSTR,
    BuildError,
    control_after,
    control_before,
    doc_to_html,
    dot,
    drop_empty_numbered,
    find,
    paragraphs,
    remove,
    scrub_package,
    set_text,
    sub,
    sub_in,
    verify,
    wrap_if,
)

KEY = "umowa_zlecenie_pl"
OUT_DIR = Path(__file__).resolve().parents[1] / "app" / "templates" / "contract"

RX_COMPANY_FULL = (
    r"B2B\.net S\.A\.\s*z siedzibą w Warszawie,\s*Aleje Jerozolimskie 180,\s*"
    r"02-486 Warszawa,\s*wpisaną do Rejestru Przedsiębiorców.*?"
    r"reprezentowaną przez Pana Artura Twardowskiego – Prezesa Zarządu,"
)
RX_COMPANY_DPA = (
    r"B2B\.net S\.A\.\s*z siedzibą w Warszawie,\s*Al\. Jerozolimskie 180,\s*"
    r"02-486 Warszawa,\s*NIP:\s*5711707392,\s*reprezentowaną przez Artura "
    r"Twardowskiego – Prezesa Zarządu,"
)
RX_PERSON = (
    r"^Panem/Panią\s*…+\s*,\s*zamieszkałym/łą pod adresem:\s*…+\s*,\s*"
    r"legitymującym/ą się dowodem osobistym o numerze:\s*…+\s*,\s*Pesel:\s*…+\s*,"
)


def _person(trailing: str = "") -> list:
    return [
        ("{{ g.g_pan }} " + NAME_INSTR, True),
        (
            ", {{ g.g_zamieszkaly }} pod adresem: "
            + dot("partner.home_address")
            + ", {{ g.g_legitymujacy }} dowodem osobistym o numerze: "
            + dot("partner.id_document")
            + ", PESEL: "
            + dot("partner.pesel")
            + ","
            + trailing,
            False,
        ),
    ]


def _page_break_before(p: Paragraph) -> Paragraph:
    prev = p._p.getprevious()
    while prev is not None and prev.tag == qn("w:p"):
        para = Paragraph(prev, p._parent)
        if 'w:type="page"' in prev.xml:
            return para
        if para.text.strip():
            break
        prev = prev.getprevious()
    raise BuildError(f"Brak podziału strony przed {p.text[:50]!r}")


def build(doc: _Doc) -> None:
    # ── Komparycja ──────────────────────────────────────────────────────────
    sub(
        doc,
        r"^zawarta dnia\s*…+\s*r\.",
        "zawarta dnia {{ document_date }} r.",
    )
    sub(doc, RX_COMPANY_FULL, COMPANY_PL_FULL)
    sub(doc, RX_PERSON + r"\s*$", _person())
    contact = find(doc, r"^Tel\.\s*…+\s*,\s*E-mail:\s*…+")
    set_text(
        contact,
        "Tel. " + dot("partner.phone") + ", E-mail: " + dot("partner.email"),
    )
    sub(
        doc,
        r"^Zwanym/Zwaną(?= dalej „Zleceniobiorcą”)",
        "{{ g.g_zwanym | capitalize }}",
    )

    # ── § 1 ust. 1 — lista czynności ─────────────────────────────────────────
    first = find(doc, r"^a\)\s*…+;")
    second = find(doc, r"^b\)\s*…+;")
    remove(second)
    set_text(first, "{{ t.letter }}) {{ t.text }}{{ t.sep }}")
    control_before(first, "for t in doc.task_items")
    control_after(first, "endfor")

    # ── § 2 ust. 2 — okres, § 3 ust. 1 — stawka ─────────────────────────────
    sub(
        doc,
        r"na okres od\s*…+\s*r\.\s*do\s*…+\s*r\.",
        "na okres od {{ doc.period_from }} r. do {{ doc.period_to }} r.",
    )
    sub(
        doc,
        r"stawkę w wysokości\s*…+\s*zł brutto za jedną godzinę \(słownie:.*?\)",
        "stawkę w wysokości {{ doc.gross_hourly_rate }} zł brutto za jedną godzinę "
        "(słownie: {{ doc.gross_hourly_rate_words }})",
    )

    # ── DPA warunkowo: § 7 ust. 8 i lista załączników ───────────────────────
    dpa_mention = find(doc, r"^W przypadku, gdy Zleceniobiorca przetwarza dane osobowe")
    wrap_if(dpa_mention, dpa_mention, "doc.with_dpa")
    annex_list = find(
        doc, r"^– Załącznik nr 2 – Umowa Powierzenia Przetwarzania Danych Osobowych$"
    )
    wrap_if(annex_list, annex_list, "doc.with_dpa")

    # ── Załącznik nr 1 — Deklaracja Poufności ───────────────────────────────
    sub(
        doc,
        r"do umowy zlecenia z dnia\s*_+",
        "do umowy zlecenia z dnia {{ document_date }} r.",
    )
    sub(doc, r"zapoznałem/łam", "{{ g.g_zapoznal }}")

    # ── Załącznik nr 2 — DPA ────────────────────────────────────────────────
    dpa_title = find(
        doc,
        r"^Załącznik nr 2 – Umowa Powierzenia Przetwarzania Danych Osobowych \(DPA\)$",
    )
    sub(doc, r"^Zawarta w dniu\s*…+\s*r\.", "Zawarta w dniu {{ document_date }} r.")
    sub(doc, RX_COMPANY_DPA, COMPANY_PL_SHORT)
    sub(
        doc,
        RX_PERSON + r"\s*zwanym/zwaną(?= dalej „Podmiotem Przetwarzającym”)",
        _person(" {{ g.g_zwanym }}"),
    )
    sub(
        doc,
        r"Umowy Zlecenia z dnia\s*…+\s*r\.",
        "Umowy Zlecenia z dnia {{ document_date }} r.",
    )
    purpose = find(doc, r"^3\.\tCel przetwarzania:")
    sub_in(purpose, r"(?<=Cel przetwarzania: ).*$", dot("doc.dpa_purpose"))
    last = paragraphs(doc)[-1]
    while not last.text.strip():
        last = Paragraph(last._p.getprevious(), last._parent)
    wrap_if(_page_break_before(dpa_title), last, "doc.with_dpa")


def _html_fixups(html: str) -> str:
    """Podgląd: nagłówki „§ N Tytuł” jako ``<h2>`` (we wzorze numer i tytuł
    są w jednym akapicie), a lista ustępów § 1 po czynnościach liczy od 2 —
    w DOCX numerację ciągnie Word, w HTML nowe ``<ol>`` zaczynałoby od 1."""
    html, headings = re.subn(
        r"^<p>(?:<strong>)?(§ \d+)(?:</strong>)? (?:<strong>)?(.+?)(?:</strong>)?</p>$",
        r"<h2>\1<br>\2</h2>",
        html,
        flags=re.M,
    )
    if headings != 14:
        raise BuildError(
            f"Podgląd: {headings} nagłówków §, oczekiwano 14 (8 + 6 w DPA)"
        )
    marker = "{% endfor %}\n<ol>"
    if html.count(marker) != 1:
        raise BuildError("Podgląd: brak listy ustępów po czynnościach § 1")
    return html.replace(marker, '{% endfor %}\n<ol start="2">')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="wzór umowy zlecenia (.docx)")
    parser.add_argument("out_dir", type=Path, nargs="?", default=OUT_DIR)
    args = parser.parse_args()
    doc = docx.Document(str(args.source))
    build(doc)
    drop_empty_numbered(doc)
    verify(doc, KEY)
    buf = io.BytesIO()
    doc.save(buf)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{KEY}.docx").write_bytes(
        scrub_package(buf.getvalue(), "Umowa zlecenia")
    )
    (args.out_dir / f"{KEY}.html").write_text(
        _html_fixups(doc_to_html(doc)), encoding="utf-8"
    )
    print(f"[{KEY}] ✓ → {args.out_dir}")


if __name__ == "__main__":
    main()
