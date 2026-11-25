"""Builder: umowy przedwstępne z kandydatem prowadzącym działalność (25.11.2026).

Decyzja Artura: umowa przedwstępna Centrum e-Zdrowia i umowa przedwstępna na
współpracę B2B mają po dwa warianty, jak umowa o udziale w procesie
rekrutacyjnym — osoba fizyczna (PESEL, dowód, adres zamieszkania) albo
kandydat z jednoosobową działalnością (firma, adres z CEIDG, NIP, REGON).

Zapisuje do ``app/templates/documents/``:

* ``preliminary_cez_jdg_pl.{docx,html}`` — z ``preliminary_cez_v3_pl``,
* ``preliminary_b2b_jdg_pl.{docx,html}`` — z ``preliminary_b2b_v2_pl``.

Zmienia się wyłącznie komparycja kandydata: zdanie o adresie zamieszkania,
dowodzie i PESEL-u zastępują dane działalności w brzmieniu z umowy o udziale
(``build_preliminary_participation_templates._candidate``). Reszta treści
zostaje słowo w słowo, więc nowa rewizja wzoru osoby fizycznej wymaga
ponownego uruchomienia tego skryptu (``SOURCES``). Wynik jest commitowany;
skrypt NIE jest częścią ścieżki produkcyjnej.

    python3 scripts/build_preliminary_jdg_templates.py [katalog_wyjściowy]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import docx

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "app" / "templates" / "documents"

#: Dane działalności w miejscu danych osoby fizycznej (z przecinkiem na końcu,
#: jak zdanie, które zastępują).
JDG_PARTY = (
    ", {{ g.g_prowadzacy }} jednoosobową działalność gospodarczą pod firmą "
    "{{ partner.legal_name or '…' }}, adres: {{ partner.business_address or '…' }}, "
    "NIP: {{ partner.nip or '…' }}, REGON: {{ partner.regon or '…' }}, "
    "{{ g.g_wpisany }} do Centralnej Ewidencji i Informacji o Działalności "
    "Gospodarczej (CEIDG),"
)

#: CeZ: imię i adres w jednym akapicie, dowód i PESEL w dwóch następnych.
CEZ_PERSON_RUN = (
    ", {{ g.g_zamieszkaly }} pod adresem: {{ partner.home_address or '…' }}, "
    "{{ g.g_legitymujacy }}"
)
CEZ_DROPPED = (
    "dokumentem tożsamości o numerze: {{ partner.id_document or '…' }}, wydanym "
    "przez {{ partner.id_document_issuer or '…' }},",
    "PESEL: {{ partner.pesel or '…' }},",
)

#: B2B: imię, adres, dowód i PESEL w jednym akapicie.
B2B_PERSON_RUN = (
    ", {{ g.g_zamieszkaly }} pod adresem: {{ partner.home_address or '…' }}, "
    "{{ g.g_legitymujacy }} dowodem osobistym o numerze: "
    "{{ partner.id_document or '…' }}, PESEL: {{ partner.pesel or '…' }},"
)

#: (wzór osoby fizycznej, wzór JDG, run do zamiany, akapity do usunięcia).
SOURCES = (
    ("preliminary_cez_v3_pl", "preliminary_cez_jdg_pl", CEZ_PERSON_RUN, CEZ_DROPPED),
    ("preliminary_b2b_v2_pl", "preliminary_b2b_jdg_pl", B2B_PERSON_RUN, ()),
)


class BuildError(RuntimeError):
    pass


def _build_docx(source: str, target: str, person_run: str, dropped, out_dir: Path):
    doc = docx.Document(str(TEMPLATE_DIR / f"{source}.docx"))
    hits = [r for p in doc.paragraphs for r in p.runs if r.text == person_run]
    if len(hits) != 1:
        raise BuildError(f"{source}: komparycja {len(hits)} trafień, nie 1")
    hits[0].text = JDG_PARTY
    for text in dropped:
        paragraphs = [p for p in doc.paragraphs if p.text.strip() == text]
        if len(paragraphs) != 1:
            raise BuildError(f"{source}: akapit {text[:40]!r} — {len(paragraphs)}")
        element = paragraphs[0]._element
        element.getparent().remove(element)
    left = "\n".join(p.text for p in doc.paragraphs)
    for marker in ("PESEL", "id_document", "home_address"):
        if marker in left:
            raise BuildError(f"{target}: został {marker!r}")
    doc.save(str(out_dir / f"{target}.docx"))


def _build_html(source: str, target: str, person_run: str, dropped, out_dir: Path):
    text = (TEMPLATE_DIR / f"{source}.html").read_text(encoding="utf-8")
    html_run = person_run.lstrip(", ")
    if text.count(html_run) != 1:
        raise BuildError(f"{source}.html: komparycja nie jedno trafienie")
    text = text.replace(html_run, JDG_PARTY.lstrip(", "))
    for line in dropped:
        tag = f"<p>{line}</p>\n"
        if text.count(tag) != 1:
            raise BuildError(f"{source}.html: akapit {line[:40]!r}")
        text = text.replace(tag, "")
    for marker in ("PESEL", "id_document", "home_address"):
        if marker in text:
            raise BuildError(f"{target}.html: został {marker!r}")
    (out_dir / f"{target}.html").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", nargs="?", default=str(TEMPLATE_DIR))
    out_dir = Path(parser.parse_args().out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for source, target, person_run, dropped in SOURCES:
        _build_docx(source, target, person_run, dropped, out_dir)
        _build_html(source, target, person_run, dropped, out_dir)
        print(f"zapisano {target}.docx i .html")


if __name__ == "__main__":
    main()
