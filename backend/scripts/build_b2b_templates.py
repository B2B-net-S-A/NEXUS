"""One-shot builder: oryginalne umowy B2B (PL/EN) → szablony Generatora.

Wczytuje dwa pliki prawnika (z ~/Downloads), wstawia placeholdery Jinja w
miejscach „na żółto"/blankach i zapisuje 4 commitowane artefakty do
``backend/app/templates/contract/``:

    umowa_b2b_pl.docx / umowa_b2b_en.docx   — szablon docxtpl ({{ }} + {{ scope_rt }})
    umowa_b2b_pl.html / umowa_b2b_en.html   — lustro Jinja (ten sam zestaw zmiennych)

Placeholdery używają tej samej przestrzeni nazw co ``_contract_vars`` w
``app/api/contract_templates.py`` (candidate / client / contract / b2b), więc
jeden zestaw danych zasila zarówno DOCX (docxtpl) jak i HTML (draft/PDF/Autenti).

Uruchom raz; wynik jest commitowany. NIE jest częścią ścieżki produkcyjnej.

    python scripts/build_b2b_templates.py [pl_src.docx en_src.docx]
"""

from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path

import docx
from docx.document import Document as _DocType
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

HOME = Path.home()
DEFAULT_PL = HOME / "Downloads" / "Umowa B2B (draft 2026)od 02.03.2026.docx"
DEFAULT_EN = HOME / "Downloads" / "Umowa B2B (draft) od 02.03.2026 EN.docx"

OUT_DIR = Path(__file__).resolve().parents[1] / "app" / "templates" / "contract"

# Marker rozpoznawany przez generator HTML w komórce „zakres usług".
# W DOCX komórka dostaje docxtpl paragraph-loop ({%p for it in b2b.scope_items %}),
# w HTML zamieniany na pętlę <ul>{% for %}.
SCOPE_MARKER = "b2b.scope_items"

# Krótki „placeholder wizualny" dla niewypełnionych pól (jak oryginalne kropki).
_DOTS = "………"

# ── Mapy podstawień (operują na paragraph.text; \s obejmuje \n z <w:br/>) ─────
# Każdy wpis: (regex, replacement). Replacement niesie pełny kanoniczny tekst.

PL_RULES: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"nr\s+[.…]+\s*/\s*2026"),
        f"nr {{{{ b2b.contract_number or '{_DOTS}' }}}}",
    ),
    (
        re.compile(r"zawarta w dniu\s+[.…]+\s+roku w Warszawie"),
        "zawarta w dniu {{ b2b.signing_date | pl_date }} roku w Warszawie",
    ),
    (
        re.compile(
            r"Panem/ią\s+_+\s+prowadzącym/cą działalność gospodarczą pod firmą:"
            r"\s*_+,\s*zarejestrowaną[^_]*?pod adresem:\s*_+,\s*00-000\s*_+,"
            r"\s*NIP:\s*_+,\s*REGON:\s*_+,"
        ),
        "{{ b2b.g_pan }} {{ candidate.full_name or '"
        + _DOTS
        + "' }} {{ b2b.g_prowadzacy }} działalność gospodarczą pod firmą: "
        "{{ candidate.legal_name or '" + _DOTS + "' }}, zarejestrowaną w Centralnej "
        "Ewidencji i Informacji o Działalności Gospodarczej pod adresem: "
        "{{ candidate.business_address or '" + _DOTS + "' }}, NIP: "
        "{{ candidate.nip or '" + _DOTS + "' }}, REGON: "
        "{{ candidate.regon or '" + _DOTS + "' }},",
    ),
    (
        re.compile(r"Tel\.\s*[.…]+\s*Adres e-mail:\s*[.…]+"),
        "Tel. {{ candidate.phone or '…' }} Adres e-mail: {{ candidate.email or '…' }}",
    ),
    (
        # §12 doręczenia — e-mail Partnera = ten z „Dane Partnera (firma)".
        re.compile(
            r"Dla Partnera:\s*Adres e-mail Partnera wskazany w komparycji Umowy\.?"
        ),
        "Dla Partnera: {{ candidate.email or '" + _DOTS + "' }}",
    ),
    (
        re.compile(r"specjalizuje się w obszarze\s+_+\s*\([^)]*\)"),
        "specjalizuje się w obszarze {{ b2b.area_label or '" + _DOTS + "' }}",
    ),
    (
        re.compile(
            r"stawki godzinowej w wysokości\s+[.…]+\s*zł\s*"
            r"\(słownie:\s*[.…]+\)\s*netto\s*\+\s*VAT"
        ),
        "stawki godzinowej w wysokości {{ contract.rate_candidate or '…' }} "
        "{{ contract.currency or 'PLN' }} (słownie: {{ b2b.rate_in_words or '"
        + _DOTS
        + "' }}) netto + VAT",
    ),
    (
        re.compile(r"podjęcia świadczenia Usług z dniem\s+[.…]+"),
        "podjęcia świadczenia Usług {{ b2b.start_clause }}",
    ),
    (
        re.compile(r"do umowy nr\s+[.…]+\s+z dnia\s+[.…]+"),
        "do umowy nr {{ b2b.contract_number or '…' }} z dnia "
        "{{ b2b.signing_date | pl_date }}",
    ),
    (
        re.compile(
            r"Zawarta w Warszawie, dnia\s+_+\s+jako Załącznik nr 2 do Umowy o "
            r"współpracę B2B nr\s+_+"
        ),
        "Zawarta w Warszawie, dnia {{ b2b.signing_date | pl_date }} jako Załącznik "
        "nr 2 do Umowy o współpracę B2B nr {{ b2b.contract_number or '…' }}",
    ),
    # Formy zależne od płci Partnera (komparycja gł. „zwany/ą", DPA „zwanym",
    # deklaracja „zapoznałem"). „zwaną dalej Administratorem" (B2BNET = spółka,
    # stała forma żeńska) celowo NIE jest ruszane.
    (
        re.compile(r"zwany/ą(\s+w dalszej części umowy)"),
        r"{{ b2b.g_zwany }}\1",
    ),
    (
        re.compile(r"zwanym(?:/ą)?(\s+dalej\s+„?Podmiotem)"),
        r"{{ b2b.g_zwanym }}\1",
    ),
    (
        re.compile(r"\bzapoznałem(\s+się)"),
        r"{{ b2b.g_zapoznal }}\1",
    ),
    (re.compile(r"\[NUMER\]"), "{{ b2b.contract_number or '…' }}"),
]

EN_RULES: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"No\.\s+[.…]+\s*/\s*2026"),
        f"No. {{{{ b2b.contract_number or '{_DOTS}' }}}}",
    ),
    (
        re.compile(r"concluded on\s+[.…]+\s+in Warsaw"),
        "concluded on {{ b2b.signing_date | pl_date }} in Warsaw",
    ),
    (
        re.compile(
            r"Mr/Ms\s+_+\s+conducting business activity under the name:\s*_+,"
            r"\s*registered[^_]*?at the address:\s*_+,\s*00-000\s*_+,"
            r"\s*NIP:\s*_+,\s*REGON:\s*_+,"
        ),
        "{{ b2b.g_mr }} {{ candidate.full_name or '"
        + _DOTS
        + "' }} conducting business "
        "activity under the name: {{ candidate.legal_name or '" + _DOTS + "' }}, "
        "registered in the Central Register and Information on Economic Activity at "
        "the address: {{ candidate.business_address or '" + _DOTS + "' }}, NIP: "
        "{{ candidate.nip or '" + _DOTS + "' }}, REGON: "
        "{{ candidate.regon or '" + _DOTS + "' }},",
    ),
    (
        re.compile(r"Tel\.\s*[.…]+\s*E-mail address:\s*[.…]+"),
        "Tel. {{ candidate.phone or '…' }} E-mail address: "
        "{{ candidate.email or '…' }}",
    ),
    (
        # §12 notices — Partner e-mail = the one from "Dane Partnera (firma)".
        re.compile(
            r"For the Partner:\s*The Partner.s email address indicated in the "
            r"preamble to the Agreement\.?"
        ),
        "For the Partner: {{ candidate.email or '" + _DOTS + "' }}",
    ),
    (
        re.compile(r"specializes in the area of\s+_+\s*\([^)]*\)"),
        "specializes in the area of {{ b2b.area_label or '" + _DOTS + "' }}",
    ),
    (
        re.compile(
            r"hourly rate of PLN\s+[.…]+\s*\(in words:\s*[.…]+\)\s*"
            r"net\s*\+\s*VAT"
        ),
        "hourly rate of {{ contract.rate_candidate or '…' }} "
        "{{ contract.currency or 'PLN' }} (in words: {{ b2b.rate_in_words or '"
        + _DOTS
        + "' }}) net + VAT",
    ),
    (
        re.compile(r"commence the provision of Services on\s+[.…]+"),
        "commence the provision of Services {{ b2b.start_clause }}",
    ),
    (
        re.compile(r"to agreement No\.\s+[.…]+\s+dated\s+[.…]+"),
        "to agreement No. {{ b2b.contract_number or '…' }} dated "
        "{{ b2b.signing_date | pl_date }}",
    ),
    (
        re.compile(
            r"Concluded in Warsaw on\s+_+\s+as Appendix No\. 2 to the B2B "
            r"Cooperation Agreement no:\s*_+"
        ),
        "Concluded in Warsaw on {{ b2b.signing_date | pl_date }} as Appendix No. 2 "
        "to the B2B Cooperation Agreement no: {{ b2b.contract_number or '…' }}",
    ),
    (re.compile(r"\[NUMBER\]"), "{{ b2b.contract_number or '…' }}"),
]

# Wartości komórek tabeli Zał.3 (po indeksie wiersza) → placeholder.
TABLE_CELL_VALUE = {
    1: "{{ client.legal_name or client.name or '" + _DOTS + "' }}",
    2: "{{ b2b.project_city or '" + _DOTS + "' }}",
    3: "{{ b2b.project_description or '" + _DOTS + "' }}",
    4: "{{ contract.start_date | pl_date }}",
}


def set_para_text(p: Paragraph, text: str) -> None:
    """Zastąp tekst paragrafu zachowując formatowanie pierwszego run-a."""
    runs = p.runs
    if runs:
        runs[0].text = text
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
    else:
        p.add_run(text)


def set_cell_text(cell, text: str) -> None:
    paras = cell.paragraphs
    for p in paras[1:]:
        p._element.getparent().remove(p._element)
    set_para_text(paras[0], text)


def apply_rules(doc: _DocType, rules: list[tuple[re.Pattern, str]]) -> int:
    hits = 0
    for p in doc.paragraphs:
        original = p.text
        new = original
        for rx, repl in rules:
            new = rx.sub(repl, new)
        if new != original:
            set_para_text(p, new)
            hits += 1
    return hits


def patch_appendix_table(doc: _DocType, lang: str) -> None:
    if not doc.tables:
        raise RuntimeError("Brak tabeli Załącznika nr 3 w dokumencie")
    tbl = doc.tables[0]
    for ri, value in TABLE_CELL_VALUE.items():
        if ri < len(tbl.rows):
            set_cell_text(tbl.rows[ri].cells[1], value)
    # Wiersz „Szczegółowy zakres Usług" usunięty (decyzja Artura 2026-06-06):
    # opis i zakres trafiają w całości do pola „Opis projektu i zakres usług".


def unbold_partner(doc: _DocType) -> None:
    """Dane Partnera (komparycja, kontakt, §doręczenia) nie mają być pogrubione.

    Oryginał miał te pola „na żółto" pogrubione → po podstawieniu placeholderów
    run zostawał bold. Zdejmujemy bold z akapitów zawierających dane Partnera
    (`{{ candidate. }}`)."""
    for p in doc.paragraphs:
        if "{{ candidate." in p.text:
            for r in p.runs:
                r.bold = False


# ── HTML generation (lustro z przekształconego docx) ─────────────────────────

_HEAD_RE = re.compile(
    r"^(§|ZAŁĄCZNIK|Załącznik|APPENDIX|Appendix|DEKLARACJA|DECLARATION|"
    r"UMOWA POWIERZENIA|DATA PROCESSING|KLIENT PROJEKTU|PROJECT CUSTOMER)"
)


def _esc(s: str) -> str:
    # Escapuje &<> ; nie rusza apostrofów ani nawiasów klamrowych Jinja.
    return _html.escape(s, quote=False)


def _iter_blocks(doc: _DocType):
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _table_html(tbl: Table) -> str:
    out = ["<table>"]
    for row in tbl.rows:
        out.append("<tr>")
        for cell in row.cells:
            ctext = cell.text.strip()
            if SCOPE_MARKER in ctext:
                inner = (
                    "<ul>{% for it in b2b.scope_items %}<li>{{ it }}</li>"
                    "{% endfor %}</ul>"
                )
            else:
                inner = _esc(ctext)
            out.append(f"<td>{inner}</td>")
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def doc_to_html(doc: _DocType) -> str:
    parts: list[str] = []
    first_done = False
    for block in _iter_blocks(doc):
        if isinstance(block, Table):
            parts.append(_table_html(block))
            continue
        text = block.text.strip()
        if not text:
            continue
        style = (block.style.name or "") if block.style else ""
        if not first_done:
            parts.append(f"<h1>{_esc(text)}</h1>")
            first_done = True
        elif style.startswith("Title") or _HEAD_RE.match(text):
            parts.append(f"<h2>{_esc(text)}</h2>")
        else:
            parts.append(f"<p>{_esc(text)}</p>")
    return "\n".join(parts)


def build(lang: str, src: Path, rules) -> None:
    doc = docx.Document(str(src))
    hits = apply_rules(doc, rules)
    patch_appendix_table(doc, lang)
    unbold_partner(doc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    docx_path = OUT_DIR / f"umowa_b2b_{lang}.docx"
    html_path = OUT_DIR / f"umowa_b2b_{lang}.html"
    doc.save(str(docx_path))
    html = doc_to_html(doc)
    html_path.write_text(html, encoding="utf-8")

    # ── Weryfikacja ──
    # Tekst paragrafów + komórek tabeli (scope_rt siedzi w tabeli).
    table_text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    full_text = "\n".join(p.text for p in doc.paragraphs) + "\n" + table_text
    # „Data blanks" = pola danych nadal puste (po etykiecie). Linie podpisów
    # (same podkreślenia bez etykiety) są POPRAWNE i pomijane.
    data_blanks = re.findall(
        r"(?:firmą|adresem|NIP|REGON|name|address|obszarze|area of):\s*_{3,}",
        full_text,
    ) + re.findall(r"\[NUMER\]|\[NUMBER\]", full_text)
    required = ["{{ candidate.full_name", "{{ b2b.contract_number"]
    missing = [r for r in required if r not in full_text]
    print(f"[{lang}] rules applied to {hits} paragraphs")
    print(f"[{lang}] docx → {docx_path}")
    print(f"[{lang}] html → {html_path} ({len(html)} bytes)")
    print(f"[{lang}] unfilled data fields: {data_blanks or 'none ✓'}")
    print(f"[{lang}] missing placeholders: {missing or 'none ✓'}")
    if data_blanks or missing:
        print(f"[{lang}] ⚠️  WERYFIKACJA NIEUDANA — sprawdź regexy")
    else:
        print(f"[{lang}] ✅ weryfikacja OK (linie podpisów zostają puste)")


def main() -> None:
    pl_src = Path(sys.argv[1]) if len(sys.argv) > 2 else DEFAULT_PL
    en_src = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_EN
    for path in (pl_src, en_src):
        if not path.is_file():
            raise SystemExit(f"Brak pliku źródłowego: {path}")
    build("pl", pl_src, PL_RULES)
    build("en", en_src, EN_RULES)
    print("\n✅ Gotowe — 4 artefakty w", OUT_DIR)


if __name__ == "__main__":
    main()
