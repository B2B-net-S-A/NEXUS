"""Builder: wzór działu „Umowa przedwstępna na współpracę B2B” → szablon dokumentu.

Wzór od Artura z 19.11.2026 (``Umowa przedwstępna draft 06052026.docx``):
umowa z osobą fizyczną, która dopiero założy działalność — zobowiązanie do
zawarcia umowy o współpracy B2B do wskazanego dnia, stawka godzinowa netto
i kara umowna za rezygnację bez uzasadnionej przyczyny. Typ dokumentu
``preliminary_b2b`` (rodzina ``preliminary``, każdy klient poza Centrum
e-Zdrowia). Zapisuje do ``app/templates/documents/``:

    preliminary_b2b_v2_pl.docx  — szablon docxtpl
    preliminary_b2b_v2_pl.html  — lustro Jinja do podglądu

Rewizja v2 (24.11.2026): § 6 ust. 1 w brzmieniu z aktualnego pliku działu —
forma dokumentowa albo kwalifikowany podpis, podpis zaufany i osobisty
wyłączone. Pliki v1 (``preliminary_b2b_pl.*``) zostają dla wydanych umów.

Tekst prawny zostaje słowo w słowo; zmienione są wyłącznie:

* pola wzoru (``___``, podświetlone daty i stawka) → placeholdery, formy
  „Panem/zamieszkałym/legitymującym się/zwanym” → ``{{ g.* }}``;
* dane B2B.net z rejestru firmy (``company.*``), jak w pozostałych wzorach;
* kara umowna (stałe 10.000 zł we wzorze) → pole ``penalty_amount``
  (decyzja Artura 19.11.2026, domyślnie 10 000 zł);
* § 6 ust. 1 — brzmienie z aktualnego pliku działu (v2, 24.11.2026):
  forma dokumentowa albo kwalifikowany podpis, bez podpisu zaufanego
  i osobistego (v1 dopuszczała każdą formę — decyzja z 21.10.2026);
* § 6 ust. 3 — jeden egzemplarz elektroniczny przy formie elektronicznej
  albo dokumentowej (bez zmian od v1).

PESEL, dowód i adres zamieszkania idą wyłącznie do pliku (pola ``sensitive``
w rejestrze typów). Uruchom po zmianie wzoru; wynik jest commitowany. Wzoru
NIE commitujemy (metadane z nazwiskami).

    python scripts/build_preliminary_b2b_template.py <wzór.docx> [katalog_wyjściowy]
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import docx
from docx.document import Document as _Doc

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_b2b_document_templates import (  # noqa: E402
    NAME_INSTR,
    OUT_DIR,
    BuildError,
    doc_to_html,
    dot,
    drop_empty_numbered,
    find,
    scrub_package,
    set_text,
    sub,
    verify,
)
from build_preliminary_participation_templates import FORM_CLAUSE  # noqa: E402

TEMPLATE_NAME = "preliminary_b2b_v2_pl"
TITLE = "Umowa przedwstępna na współpracę B2B"

RX_COMPANY = (
    r"B2B\.NET S\.A\.,\s*Al\. Jerozolimskie 180,\s*02-486 Warszawa,\s*wpisaną do "
    r"Rejestru Przedsiębiorców.*?NIP:\s*5711707392\s*oraz każde inne "
    r"przedsiębiorstwo, które będzie następcą prawnym B2B\.net S\.A\.(?= w tej)"
)
#: (tekst, pogrubienie) — jak ``COMPANY_PL_FULL``, plus klauzula następcy prawnego ze wzoru.
COMPANY: list[tuple[str, bool]] = [
    ("{{ company.name }}", True),
    (
        " z siedzibą w Warszawie, {{ company.address }}, wpisaną do Rejestru "
        "Przedsiębiorców prowadzonego przez {{ company.court }}, KRS pod nr "
        "{{ company.krs }}, NIP: {{ company.nip }}, o kapitale zakładowym "
        "{{ company.share_capital }}, oraz każde inne przedsiębiorstwo, które "
        "będzie następcą prawnym {{ company.name }}",
        False,
    ),
]

COPIES_CLAUSE = (
    "Umowa została sporządzona w dwóch jednobrzmiących egzemplarzach – po jednym "
    "dla każdej ze Stron. W przypadku zawarcia Umowy w formie elektronicznej "
    "albo dokumentowej Umowa zostaje sporządzona w jednym egzemplarzu w postaci "
    "elektronicznej, dostępnym dla obu Stron."
)


def build(doc: _Doc) -> None:
    # ── Komparycja ──────────────────────────────────────────────────────────
    sub(
        doc,
        r"^Podpisana w dniu\s*\d{2}\.\d{2}\.\d{4}\s*r\.",
        "Podpisana w dniu {{ document_date }} r.",
    )
    sub(doc, RX_COMPANY, COMPANY)
    sub(
        doc,
        r"reprezentowaną przez Artura Twardowskiego – Prezesa Zarządu",
        "reprezentowaną przez {{ company.representative }}",
    )
    sub(
        doc,
        r"^Panem\s*_+\s*zamieszkałym pod adresem:\s*(?:ul\.\s*)?_+\s*,\s*"
        r"legitymujący się dowodem osobistym o numerze:\s*_+\s*,\s*Pesel:\s*_+\s*$",
        [
            ("{{ g.g_pan }} " + NAME_INSTR, True),
            (
                ", {{ g.g_zamieszkaly }} pod adresem: "
                + dot("partner.home_address")
                + ", {{ g.g_legitymujacy }} dowodem osobistym o numerze: "
                + dot("partner.id_document")
                + ", PESEL: "
                + dot("partner.pesel")
                + ",",
                False,
            ),
        ],
    )
    sub(doc, r"^zwanym(?= w treści umowy „Przyszłym Wykonawcą”)", "{{ g.g_zwanym }}")

    # ── § 2 ust. 1 — termin umowy przyrzeczonej, § 3 ust. 1 — stawka ─────────
    sub(
        doc,
        r"nie później niż do dnia\s*\d{2}\.\d{2}\.\d{4}\s*r\.",
        "nie później niż do dnia {{ doc.valid_until }} r.",
    )
    sub(
        doc,
        r"stawki godzinowej wynoszącej\s*_+\s*zł netto",
        "stawki godzinowej wynoszącej {{ doc.hourly_rate }} zł netto",
    )

    # ── § 4 ust. 2 — kara umowna ────────────────────────────────────────────
    sub(
        doc,
        r"kary umownej w wysokości 10\.000 zł \(słownie: dziesięć tysięcy złotych\)",
        "kary umownej w wysokości {{ doc.penalty_amount }} zł "
        "(słownie: {{ doc.penalty_amount_words }})",
    )

    # ── § 6 ust. 1 — forma zawarcia (v2), ust. 3 — egzemplarze ─────────────
    set_text(
        find(doc, r"^Strony ustalają, że niniejsza Umowa może zostać zawarta"),
        FORM_CLAUSE,
    )
    set_text(
        find(doc, r"^Umowa została sporządzona w dwóch jednobrzmiących egzemplarzach"),
        COPIES_CLAUSE,
    )


def _replace_once(html: str, old: str, new: str) -> str:
    if html.count(old) != 1:
        raise BuildError(f"Podgląd: brak jednoznacznego {old[:60]!r}")
    return html.replace(old, new)


def _html_fixups(html: str) -> str:
    """Podgląd: w DOCX numerację ciągnie Word, w HTML każde ``<ol>`` po
    wtrąconym akapicie zaczynałoby od 1. Przypadki § 4 ust. 2 to podlista
    (osobna numeracja we wzorze), a adres IOD siedzi w hiperłączu, którego
    ``doc_to_html`` nie czyta."""
    html = _replace_once(
        html,
        "<li>W przypadku gdy Przyszły Wykonawca:</li>\n<li>",
        '<li>W przypadku gdy Przyszły Wykonawca:<ol type="a">\n<li>',
    )
    html = _replace_once(
        html,
        "zawarcia umowy o współpracy B2B,</li>\n</ol>",
        "zawarcia umowy o współpracy B2B,</li>\n</ol></li>\n</ol>",
    )
    html = _replace_once(
        html,
        "</p>\n<ol>\n<li>Kara umowna będzie płatna",
        '</p>\n<ol start="3">\n<li>Kara umowna będzie płatna',
    )
    html = _replace_once(
        html,
        "</p>\n<ol>\n<li>Podstawą przetwarzania",
        '</p>\n<ol start="3">\n<li>Podstawą przetwarzania',
    )
    html = _replace_once(
        html,
        "</p>\n<ol>\n<li>Przyszły Wykonawca posiada prawa",
        '</p>\n<ol start="6">\n<li>Przyszły Wykonawca posiada prawa',
    )
    return _replace_once(
        html,
        "Inspektora Ochrony Danych: e-mail:</li>",
        "Inspektora Ochrony Danych: e-mail: iod@b2bnetwork.pl</li>",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="wzór umowy przedwstępnej (.docx)")
    parser.add_argument("out_dir", type=Path, nargs="?", default=OUT_DIR)
    args = parser.parse_args()
    doc = docx.Document(str(args.source))
    build(doc)
    drop_empty_numbered(doc)
    verify(doc, TEMPLATE_NAME)
    buf = io.BytesIO()
    doc.save(buf)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{TEMPLATE_NAME}.docx").write_bytes(
        scrub_package(buf.getvalue(), TITLE)
    )
    (args.out_dir / f"{TEMPLATE_NAME}.html").write_text(
        _html_fixups(doc_to_html(doc)), encoding="utf-8"
    )
    print(f"[{TEMPLATE_NAME}] ✓ → {args.out_dir}")


if __name__ == "__main__":
    main()
