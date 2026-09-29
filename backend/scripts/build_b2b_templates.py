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

Wariant umowy dla spółki (ticket 8, 28.09.2026) — ``add_company_variant``
dokłada do komparycji warunek ``b2b.is_company``. ``build`` robi to zawsze;
na już zacommitowanych szablonach (źródła prawnika nie leżą w repo):

    python scripts/build_b2b_templates.py --company-variant
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
        "{{ b2b.g_pan }} {{ b2b.partner_instrumental or candidate.full_name or '"
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
        "Tel. {{ candidate.phone or '…' }}; Adres e-mail: {{ candidate.email or '…' }}",
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
        "{{ b2b.signing_date | pl_date }} r.",
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
        "Tel. {{ candidate.phone or '…' }}; E-mail address: "
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


# Komparycja: pogrubiamy TYLKO „Pan/Pani + imię i nazwisko". (head, splitter):
# bold = tekst od `head` do `splitter`; reszta normalna.
_KOMPARYCJA_SPLITS = [
    ("{{ b2b.g_pan }}", "{{ b2b.g_prowadzacy }}"),  # PL
    ("{{ b2b.g_mr }}", "conducting business"),  # EN
]


def format_komparycja(doc: _DocType) -> None:
    """Pogrub w komparycji wyłącznie „Panem/ią <Imię i nazwisko>" (np. „Panem
    Pawłem Żurawikiem"); firma, NIP, REGON, adres pozostają bez pogrubienia."""
    for p in doc.paragraphs:
        t = p.text
        for head, splitter in _KOMPARYCJA_SPLITS:
            hi, si = t.find(head), t.find(splitter)
            if hi == -1 or si == -1 or si <= hi:
                continue
            prefix, bold_part, rest = t[:hi], t[hi:si], t[si:]
            runs = p.runs
            font_name = runs[0].font.name if runs else None
            font_size = runs[0].font.size if runs else None
            for r in list(runs):
                r._element.getparent().remove(r._element)
            for text, is_bold in ((prefix, False), (bold_part, True), (rest, False)):
                if not text:
                    continue
                r = p.add_run(text)
                r.bold = is_bold
                if font_name:
                    r.font.name = font_name
                if font_size:
                    r.font.size = font_size
            break


# ── Wariant dla spółki: komparycja z KRS zamiast „Panem … prowadzącym …” ────
#
# Komparycja JDG to dwa runy: pogrubione „Panem Jan Kowalski ” i zwykły opis
# działalności. W obu dokładamy ``{% if b2b.is_company %}…{% else %}…{% endif %}``
# — cały warunek mieści się w JEDNYM runie, więc XML zostaje poprawny, a umowa
# JDG renderuje się znak w znak jak przed zmianą. To samo w stronach umowy
# powierzenia (Załącznik nr 2). § 12 i Załącznik nr 3 dokłada render
# (``company_variant``), nie szablon.

_COMPANY_MARK = "b2b.is_company"

_COMPANY_HEAD = "{{ candidate.legal_name or '" + _DOTS + "' }} "

_COMPANY_BODY = {
    "pl": (
        "z siedzibą {{ b2b.company.seat or '" + _DOTS + "' }}, pod adresem "
        "{{ candidate.business_address or '" + _DOTS + "' }}, wpisaną do Rejestru "
        "Przedsiębiorców Krajowego Rejestru Sądowego, prowadzonego przez "
        "{{ b2b.company.registry_court or '" + _DOTS + "' }}, pod numerem KRS: "
        "{{ b2b.company.krs or '" + _DOTS + "' }}, NIP: "
        "{{ candidate.nip or '" + _DOTS + "' }}, REGON: "
        "{{ candidate.regon or '" + _DOTS + "' }}, o kapitale zakładowym "
        "{{ b2b.company.share_capital or '" + _DOTS + "' }}, reprezentowaną przez "
        "{{ b2b.company.representation or '" + _DOTS + "' }}, "
    ),
    "en": (
        "with its registered office in {{ b2b.company.seat or '" + _DOTS + "' }}, "
        "at the address: {{ candidate.business_address or '" + _DOTS + "' }}, "
        "entered in the Register of Entrepreneurs of the National Court Register "
        "kept by {{ b2b.company.registry_court or '" + _DOTS + "' }}, under KRS "
        "number: {{ b2b.company.krs or '" + _DOTS + "' }}, NIP: "
        "{{ candidate.nip or '" + _DOTS + "' }}, REGON: "
        "{{ candidate.regon or '" + _DOTS + "' }}, with share capital of "
        "{{ b2b.company.share_capital or '" + _DOTS + "' }}, represented by "
        "{{ b2b.company.representation or '" + _DOTS + "' }}, "
    ),
}

# Opis spółki po treści runu z warunkiem — łatka HTML składa warunek od nowa
# (bez końcowej spacji), więc potrzebuje samego opisu spółki.
_COMPANY_BODY_BY_JDG: dict[str, str] = {}

_JDG_HEAD_MARK = {"pl": "{{ b2b.g_pan }}", "en": "{{ b2b.g_mr }}"}
_JDG_BODY_MARK = {"pl": "pod firmą:", "en": "under the name:"}


def _company_if(company: str, jdg: str) -> str:
    # `is defined` — ten sam HTML renderuje też „Generuj z szablonu” na
    # kontrakcie (`_contract_vars`, StrictUndefined), który wariantu nie zna.
    cond = f"{_COMPANY_MARK} is defined and {_COMPANY_MARK}"
    return f"{{% if {cond} %}}{company}{{% else %}}{jdg}{{% endif %}}"


def company_variant_pairs(doc: _DocType, lang: str) -> list[tuple[str, str]]:
    """(tekst runu JDG → tekst z warunkiem) dla komparycji umowy i DPA."""
    pairs: list[tuple[str, str]] = []
    for p in doc.paragraphs:
        runs = p.runs
        for head, body in zip(runs, runs[1:]):
            if (
                head.text.startswith(_JDG_HEAD_MARK[lang])
                and _JDG_BODY_MARK[lang] in body.text
                and _COMPANY_MARK not in head.text
            ):
                pairs.append((head.text, _company_if(_COMPANY_HEAD, head.text)))
                wrapped_body = _company_if(_COMPANY_BODY[lang], body.text)
                _COMPANY_BODY_BY_JDG[wrapped_body] = _COMPANY_BODY[lang]
                pairs.append((body.text, wrapped_body))
    return pairs


def add_company_variant(doc: _DocType, lang: str) -> int:
    """Owiń komparycję JDG warunkiem wariantu spółki. Zwraca liczbę komparycji."""
    wrapped = 0
    for p in doc.paragraphs:
        runs = p.runs
        for head, body in zip(runs, runs[1:]):
            if (
                head.text.startswith(_JDG_HEAD_MARK[lang])
                and _JDG_BODY_MARK[lang] in body.text
                and _COMPANY_MARK not in head.text
            ):
                head.text = _company_if(_COMPANY_HEAD, head.text)
                body.text = _company_if(_COMPANY_BODY[lang], body.text)
                wrapped += 1
    return wrapped


def add_company_variant_html(html: str, pairs: list[tuple[str, str]]) -> str:
    """To samo w lustrze HTML.

    Lustro nie jest kopią runów 1:1 — w umowie głównej po „REGON: …,” stoi od
    razu ``{% if b2b.correspondence_address %}`` (bez spacji z końca runu), więc
    szukamy CAŁEJ komparycji ``<strong>nagłówek</strong>opis`` bez końcowych
    białych znaków i podmieniamy każde wystąpienie osobno. Zwykłe
    ``str.replace`` samego runu trafiało tylko w umowę powierzenia, a nagłówek
    (identyczny w obu miejscach) owijało dwa razy."""
    heads = dict(pairs[0::2])
    bodies = dict(pairs[1::2])
    wrapped = 0
    for head_old, head_new in heads.items():
        for body_old, body_new in bodies.items():
            old = f"<strong>{_esc(head_old)}</strong>{_esc(body_old).rstrip()}"
            new = f"<strong>{_esc(head_new)}</strong>" + _esc(
                _company_if(
                    _COMPANY_BODY_BY_JDG[body_new].rstrip(), body_old.rstrip()
                )
            )
            count = html.count(old)
            html = html.replace(old, new)
            wrapped += count
    if wrapped != 2:
        raise RuntimeError(
            f"Oczekiwano 2 komparycji w HTML (umowa + DPA), podmieniono {wrapped}"
        )
    return html


def patch_company_variant() -> None:
    """Dołóż wariant spółki do ZACOMMITOWANYCH szablonów (idempotentnie)."""
    for lang in ("pl", "en"):
        docx_path = OUT_DIR / f"umowa_b2b_{lang}.docx"
        html_path = OUT_DIR / f"umowa_b2b_{lang}.html"
        doc = docx.Document(str(docx_path))
        pairs = company_variant_pairs(doc, lang)
        if not pairs:
            print(f"[{lang}] wariant spółki już jest — bez zmian")
            continue
        wrapped = add_company_variant(doc, lang)
        if wrapped != 2:
            raise SystemExit(
                f"[{lang}] oczekiwano 2 komparycji (umowa + DPA), jest {wrapped}"
            )
        doc.save(str(docx_path))
        html = add_company_variant_html(html_path.read_text(encoding="utf-8"), pairs)
        html_path.write_text(html, encoding="utf-8")
        print(f"[{lang}] ✅ wariant spółki: {wrapped} komparycje")


def _lowercase_net_in_paragraph(p: Paragraph, target: str = "B2B.NET") -> int:
    """Zamień „NET" na „net" w każdym wystąpieniu „B2B.NET" w akapicie.

    Operacja jest RÓWNEJ DŁUGOŚCI i mapuje znaki z powrotem na właściwe runy,
    więc pogrubienie/krój pisma zostają zachowane (nazwa bywa rozbita na kilka
    runów, np. „B2B." + „NET" + „ S.A.")."""
    runs = list(p.runs)
    texts = [r.text for r in runs]
    full = "".join(texts)
    if target not in full:
        return 0
    lower_pos: list[int] = []
    start = full.find(target)
    while start != -1:
        lower_pos += [start + 4, start + 5, start + 6]  # offsety „NET" w „B2B.NET"
        start = full.find(target, start + 1)
    starts, acc = [], 0
    for t in texts:
        starts.append(acc)
        acc += len(t)
    run_chars = [list(t) for t in texts]
    for g in lower_pos:
        for ri, t in enumerate(texts):
            if starts[ri] <= g < starts[ri] + len(t):
                run_chars[ri][g - starts[ri]] = run_chars[ri][g - starts[ri]].lower()
                break
    for ri, r in enumerate(runs):
        new = "".join(run_chars[ri])
        if new != texts[ri]:
            r.text = new
    return full.count(target)


def normalize_company_name(doc: _DocType) -> int:
    """Pełna nazwa spółki „B2B.NET S.A." → „B2B.net S.A." (małe „net").

    Skrót „B2BNET" (termin zdefiniowany w komparycji) NIE jest ruszany — łapiemy
    wyłącznie formę z kropką „B2B.NET", więc „B2BNET" zostaje nietknięty."""
    changed = sum(_lowercase_net_in_paragraph(p) for p in doc.paragraphs)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                changed += sum(_lowercase_net_in_paragraph(p) for p in cell.paragraphs)
    return changed


def keep_headings_with_content(doc: _DocType) -> None:
    """Nie zostawiaj nagłówka §/tytułu sekcji samego na końcu strony — Word
    przerzuci go z treścią na nową stronę (keep_with_next)."""
    paras = doc.paragraphs
    for i, p in enumerate(paras):
        t = p.text.strip()
        if not t:
            continue
        is_section = t.startswith("§") or bool(_HEAD_RE.match(t))
        prev = paras[i - 1].text.strip() if i > 0 else ""
        is_title_after_section = prev.startswith("§") and len(t) < 80
        if is_section or is_title_after_section:
            p.paragraph_format.keep_with_next = True


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


def _para_inner_html(p: Paragraph) -> str:
    """Inner HTML akapitu z zachowaniem pogrubienia run-ów (bold → <strong>)."""
    runs = p.runs
    if not runs:
        return _esc(p.text)
    return "".join(
        f"<strong>{_esc(r.text)}</strong>" if r.bold else _esc(r.text) for r in runs
    )


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
            parts.append(f"<p>{_para_inner_html(block)}</p>")
    return "\n".join(parts)


def build(lang: str, src: Path, rules) -> None:
    doc = docx.Document(str(src))
    hits = apply_rules(doc, rules)
    patch_appendix_table(doc, lang)
    unbold_partner(doc)
    format_komparycja(doc)  # bold tylko „Pan/Pani + imię i nazwisko"
    add_company_variant(doc, lang)  # komparycja spółki (ticket 8) — po podziale runów
    normalize_company_name(
        doc
    )  # „B2B.NET S.A." → „B2B.net S.A." (skrót „B2BNET" bez zmian)
    keep_headings_with_content(doc)  # nagłówek § nie zostaje sam na końcu strony
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
    required = ["candidate.full_name", "{{ b2b.contract_number"]
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
    if "--company-variant" in sys.argv[1:]:
        patch_company_variant()
        return
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
