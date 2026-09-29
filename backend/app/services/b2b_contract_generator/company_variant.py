"""Wariant umowy B2B dla spółki (ticket 8, 28.09.2026).

Wzór umowy jest pisany pod JDG. Dla spółki trzy rzeczy wyglądają inaczej:

1. **Komparycja** — dane z KRS zamiast „Panem … prowadzącym działalność pod
   firmą”. Ta część siedzi w SZABLONIE (warunek ``b2b.is_company`` w dwóch
   runach komparycji i w stronach umowy powierzenia), bo wartości zostają tam
   polami Jinja, escapowanymi jak cała reszta umowy.
2. **§ 12 „Osoby skierowane do realizacji Usług”** — wstawiany PRZED dawnym
   § 12, a wszystkie kolejne paragrafy przesuwają się o jeden.
3. **Załącznik nr 3** — wiersz „Osoba skierowana” pod datą rozpoczęcia usług.

Punkty 2 i 3 to przekształcenie JUŻ wyrenderowanego dokumentu, wykonywane PO
klauzulach Klienta (``clause_overrides``): klauzule Credit Agricole, BIK czy
Alior cytują „§ 12 ust. 3 Umowy Głównej” i dopiero po ich wstawieniu da się
przesunąć także te odwołania. Przesunięcie w treści szablonu Jinja nie
objęłoby tekstu wstawianego przez rejestr klauzul.

Przenumerowanie działa w dwóch strefach:

* **umowa główna** (do nagłówka „Załącznik nr 1”) — nagłówki ``§ N`` i każde
  odwołanie ``§ N`` z N ≥ 12, poza przepisami ustaw („art. 22 § 1 Kodeksu
  pracy”);
* **załączniki** — wyłącznie odwołania „§ N … Umowy Głównej” / „§ N … of the
  Main Agreement”. Załączniki mają WŁASNĄ numerację (umowa powierzenia § 1–5,
  załącznik Credit Agricole § 11–15) i jej nie wolno ruszać.

Brak kotwicy (nagłówka § 12, tabeli Załącznika nr 3) = wyjątek, nie cicha
umowa JDG wydana jako umowa spółki.
"""

from __future__ import annotations

import copy
import html
import re
from typing import Final

from app.services.b2b_contract_generator.clause_overrides import (
    Block,
    apply_ops_docx,
    apply_ops_html_counted,
)
from app.services.b2b_contract_generator.gender import is_female

VARIANT_SOLE_TRADER: Final[str] = "jdg"
VARIANT_COMPANY: Final[str] = "company"
CONTRACT_VARIANTS: Final[tuple[str, ...]] = (VARIANT_SOLE_TRADER, VARIANT_COMPANY)

#: Pierwszy paragraf umowy głównej, który przesuwa się o jeden (nowy § 12).
INSERTED_SECTION: Final[int] = 12


class CompanyVariantError(RuntimeError):
    """Dokument nie ma kotwicy, na której opiera się wariant dla spółki."""


def is_company(variant: str | None) -> bool:
    return variant == VARIANT_COMPANY


# ── § 12 „Osoby skierowane do realizacji Usług” ─────────────────────────────

_S12_PL: tuple[Block, ...] = (
    ("h", "§ 12"),
    ("sub", "Osoby skierowane do realizacji Usług"),
    (
        "p",
        "1. Partner może powierzyć wykonywanie Usług osobom fizycznym (dalej: "
        "„Osoby Skierowane”), które będą realizować Usługi na rzecz B2BNET, "
        "w tym bezpośrednio u Klienta B2BNET.",
    ),
    (
        "p",
        "2. Partner ponosi pełną odpowiedzialność za działania i zaniechania "
        "Osób Skierowanych jak za własne.",
    ),
    ("p", "3. Partner zobowiązuje się zapewnić, że każda Osoba Skierowana:"),
    (
        "i",
        "a) posiada odpowiednie kwalifikacje i doświadczenie wymagane do "
        "realizacji Usług,",
    ),
    (
        "i",
        "b) została zweryfikowana w zakresie umożliwiającym dostęp do środowisk "
        "Klienta B2BNET (w tym – jeśli wymagane – weryfikacja tożsamości, "
        "doświadczenia zawodowego lub niekaralności),",
    ),
    (
        "i",
        "c) jest związana zobowiązaniem do zachowania poufności co najmniej "
        "równoważnym z określonym w niniejszej Umowie,",
    ),
    (
        "i",
        "d) została zobowiązana do przestrzegania zasad ochrony danych "
        "osobowych zgodnych z RODO,",
    ),
    (
        "i",
        "e) została zapoznana z zasadami bezpieczeństwa informacji "
        "obowiązującymi u Klienta B2BNET,",
    ),
    ("i", "f) korzysta wyłącznie z autoryzowanych narzędzi i dostępów."),
    ("p", "4. Partner zapewnia, że Osoby Skierowane:"),
    ("i", "a) przetwarzają dane osobowe wyłącznie na polecenie B2BNET,"),
    ("i", "b) nie kopiują ani nie wynoszą danych poza środowisko Klienta,"),
    ("i", "c) nie udostępniają dostępów osobom trzecim,"),
    ("i", "d) nie wykorzystują informacji w celach innych niż realizacja Usług."),
    (
        "p",
        "5. Osoby Skierowane wykonują czynności w ramach organizacji Partnera "
        "i nie pozostają w stosunku pracy ani w innym stosunku prawnym z B2BNET "
        "ani Klientem B2BNET.",
    ),
    (
        "p",
        "6. Partner zobowiązuje się do zapewnienia, że Osoby Skierowane będą "
        "przestrzegać:",
    ),
    ("b", "•  regulaminów i polityk bezpieczeństwa Klienta B2BNET,"),
    ("b", "•  zasad dostępu do systemów IT,"),
    ("b", "•  wymogów dotyczących ochrony informacji (w tym tajemnicy bankowej)."),
    (
        "p",
        "7. Na żądanie B2BNET lub Klienta B2BNET Partner przedstawi potwierdzenie:",
    ),
    ("b", "•  zawarcia zobowiązań poufności,"),
    ("b", "•  zobowiązań RODO,"),
    ("b", "•  spełnienia wymogów bezpieczeństwa."),
    (
        "p",
        "8. Zmiana Osoby Skierowanej wymaga uprzedniej zgody B2BNET lub Klienta "
        "B2BNET.",
    ),
)

# Tłumaczenie spójne z terminologią szablonu EN („B2BNET Customer”, „GDPR”).
_S12_EN: tuple[Block, ...] = (
    ("h", "§ 12"),
    ("sub", "Persons designated to provide the Services"),
    (
        "p",
        "1. The Partner may entrust the performance of the Services to natural "
        'persons (hereinafter: "Designated Persons"), who will provide the '
        "Services for B2BNET, including directly at the B2BNET Customer.",
    ),
    (
        "p",
        "2. The Partner shall be fully liable for the acts and omissions of the "
        "Designated Persons as for its own.",
    ),
    ("p", "3. The Partner undertakes to ensure that each Designated Person:"),
    (
        "i",
        "a) has the appropriate qualifications and experience required to "
        "provide the Services,",
    ),
    (
        "i",
        "b) has been verified to the extent enabling access to the B2BNET "
        "Customer's environments (including – if required – verification of "
        "identity, professional experience or criminal record),",
    ),
    (
        "i",
        "c) is bound by a confidentiality obligation at least equivalent to the "
        "one set out in this Agreement,",
    ),
    (
        "i",
        "d) has been obliged to comply with personal data protection rules in "
        "accordance with the GDPR,",
    ),
    (
        "i",
        "e) has been familiarised with the information security rules "
        "applicable at the B2BNET Customer,",
    ),
    ("i", "f) uses only authorised tools and access rights."),
    ("p", "4. The Partner ensures that the Designated Persons:"),
    ("i", "a) process personal data only on the instructions of B2BNET,"),
    (
        "i",
        "b) do not copy or remove data outside the Customer's environment,",
    ),
    ("i", "c) do not share access rights with third parties,"),
    (
        "i",
        "d) do not use information for purposes other than the provision of "
        "the Services.",
    ),
    (
        "p",
        "5. The Designated Persons perform their activities within the "
        "Partner's organisation and are not in an employment relationship or "
        "any other legal relationship with B2BNET or the B2BNET Customer.",
    ),
    (
        "p",
        "6. The Partner undertakes to ensure that the Designated Persons comply with:",
    ),
    ("b", "•  the regulations and security policies of the B2BNET Customer,"),
    ("b", "•  the rules of access to IT systems,"),
    (
        "b",
        "•  the requirements concerning the protection of information "
        "(including banking secrecy).",
    ),
    (
        "p",
        "7. At the request of B2BNET or the B2BNET Customer, the Partner shall "
        "provide confirmation of:",
    ),
    ("b", "•  the conclusion of confidentiality undertakings,"),
    ("b", "•  GDPR undertakings,"),
    ("b", "•  compliance with security requirements."),
    (
        "p",
        "8. A change of a Designated Person requires the prior consent of "
        "B2BNET or the B2BNET Customer.",
    ),
)


def section_12_blocks(language: str) -> tuple[Block, ...]:
    return _S12_EN if language == "en" else _S12_PL


def assigned_person_label(language: str) -> str:
    return "Designated Person:" if language == "en" else "Osoba skierowana:"


# ── Przenumerowanie ─────────────────────────────────────────────────────────

_HEADING = re.compile(r"^(\s*§\s*)(\d+)(\s*\.?\s*)$")
# Odwołanie w treści: „§ 12”, „§12”. Grupa `num` — numer paragrafu.
_REF = re.compile(r"§(?P<sp>\s?)(?P<num>\d+)(?!\d)")
# Przepis ustawy: „art. 22 § 1”, „art. 78¹ §1” — nie paragraf tej umowy.
_STATUTE_BEFORE = re.compile(r"art\.\s*\d+[¹²³⁴⁵⁶⁷⁸⁹⁰]*\.?\s*$", re.IGNORECASE)
# Odwołanie z załącznika do umowy głównej. Środek to wyłącznie jednostki
# redakcyjne („ust. 3”, „ust. 4 lit. a)”, „section 4 letter a)”), żeby nie
# przeskoczyć do „§ 8 Umowy Głównej” w dalszej części zdania.
_MAIN_AGREEMENT_REF = re.compile(
    r"§(?P<sp>\s?)(?P<num>\d+)(?P<tail>"
    r"(?:\s+(?:ust\.|pkt|lit\.|sections?|points?|letter|item)\s*[0-9a-z]+\)?"
    r"(?:\s+(?:i|oraz|and)\s+[0-9a-z]+\)?)?)*"
    r"\s+(?:Umowy\s+Głównej|of\s+the\s+Main\s+Agreement))"
)
_FIRST_APPENDIX = re.compile(
    r"^\s*(?:za[łl]ącznik\s+nr\s*1\b|appendix\s+no\.?\s*1\b)", re.IGNORECASE
)


def _shift(num: int) -> int:
    return num + 1 if num >= INSERTED_SECTION else num


def _shift_heading(text: str) -> str:
    m = _HEADING.match(text)
    if not m:
        return text
    return f"{m.group(1)}{_shift(int(m.group(2)))}{m.group(3)}"


def _shift_main_refs(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        if _STATUTE_BEFORE.search(text[max(0, m.start() - 20) : m.start()]):
            return m.group(0)
        return f"§{m.group('sp')}{_shift(int(m.group('num')))}"

    return _REF.sub(repl, text)


def _shift_appendix_refs(text: str) -> str:
    return _MAIN_AGREEMENT_REF.sub(
        lambda m: f"§{m.group('sp')}{_shift(int(m.group('num')))}{m.group('tail')}",
        text,
    )


# ── DOCX ────────────────────────────────────────────────────────────────────


def _renumber_docx(doc) -> int:
    headings = 0
    in_main = True
    for p in doc.paragraphs:
        text = p.text or ""
        if in_main and _FIRST_APPENDIX.match(text):
            in_main = False
        if in_main and _HEADING.match(text.strip()) and p.runs:
            shifted = _shift_heading(text)
            if shifted != text:
                # Nagłówek „§ 12” to jeden run w szablonie; zbieramy tekst do
                # pierwszego, żeby nie zostawić „§ 1” + „2” po podziale.
                p.runs[0].text = shifted
                for extra in p.runs[1:]:
                    extra.text = ""
                headings += 1
            continue
        for run in p.runs:
            new = (
                _shift_main_refs(run.text)
                if in_main
                else _shift_appendix_refs(run.text)
            )
            if new != run.text:
                run.text = new
    # Tabele leżą w załącznikach — tylko odwołania do Umowy Głównej.
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for run in p.runs:
                        new = _shift_appendix_refs(run.text)
                        if new != run.text:
                            run.text = new
    return headings


def _set_cell_text(cell, text: str) -> None:
    paragraphs = cell.paragraphs
    for extra in paragraphs[1:]:
        extra._element.getparent().remove(extra._element)
    first = paragraphs[0]
    runs = first.runs
    if runs:
        runs[0].text = text
        for extra in runs[1:]:
            extra._element.getparent().remove(extra._element)
    else:
        first.add_run(text)


def _appendix_3_table(doc):
    for table in doc.tables:
        labels = [
            (row.cells[0].text or "").strip().lower() for row in table.rows if row.cells
        ]
        if any(
            label.startswith(("data rozpoczęcia", "start date")) for label in labels
        ):
            return table
    return None


def _add_assigned_person_row_docx(doc, *, label: str, value: str) -> None:
    table = _appendix_3_table(doc)
    if table is None:
        raise CompanyVariantError(
            "Nie znaleziono tabeli Załącznika nr 3 — nie można dopisać osoby "
            "skierowanej. Dokument NIE został wydany."
        )
    last = table.rows[-1]._tr
    new_tr = copy.deepcopy(last)
    last.addnext(new_tr)
    new_row = table.rows[-1]
    _set_cell_text(new_row.cells[0], label)
    _set_cell_text(new_row.cells[1], value)


def apply_company_variant_docx(doc, *, language: str, assigned_person: str) -> None:
    """Przekształć wyrenderowany DOCX umowy JDG w umowę spółki (§ 12 + Zał. 3)."""
    lang = "en" if language == "en" else "pl"
    shifted = _renumber_docx(doc)
    if shifted == 0:
        raise CompanyVariantError(
            "Nie znaleziono nagłówka § 12 umowy głównej — wariant dla spółki "
            "nie może wstawić § 12. Dokument NIE został wydany."
        )
    applied = apply_ops_docx(
        doc,
        [("insert_before_section", INSERTED_SECTION + 1, section_12_blocks(lang))],
    )
    if applied != 1:
        raise CompanyVariantError(
            "Nie udało się wstawić § 12 „Osoby skierowane do realizacji Usług”. "
            "Dokument NIE został wydany."
        )
    _add_assigned_person_row_docx(
        doc, label=assigned_person_label(lang), value=assigned_person or "………"
    )


# ── HTML (podgląd) ──────────────────────────────────────────────────────────

_H2_TAG = re.compile(r"<h2>(?P<body>.*?)</h2>", re.DOTALL)


def _split_main_html(rendered: str) -> int:
    for m in _H2_TAG.finditer(rendered):
        if _FIRST_APPENDIX.match(html.unescape(m.group("body"))):
            return m.start()
    return len(rendered)


def _renumber_html(rendered: str) -> tuple[str, int]:
    cut = _split_main_html(rendered)
    main, rest = rendered[:cut], rendered[cut:]
    count = 0

    def heading(m: re.Match[str]) -> str:
        nonlocal count
        body = m.group("body")
        if not _HEADING.match(body.strip()):
            return m.group(0)
        shifted = _shift_heading(body)
        if shifted != body:
            count += 1
        return f"<h2>{shifted}</h2>"

    # Najpierw nagłówki (tekst wewnątrz <h2>), potem odwołania w reszcie treści;
    # `_shift_main_refs` nie dotyka już przesuniętego nagłówka, bo działa na
    # akapitach poza <h2>.
    parts: list[str] = []
    last = 0
    for m in _H2_TAG.finditer(main):
        parts.append(_shift_main_refs(main[last : m.start()]))
        parts.append(heading(m))
        last = m.end()
    parts.append(_shift_main_refs(main[last:]))
    return "".join(parts) + _shift_appendix_refs(rest), count


_START_ROW_HTML = re.compile(
    r"<tr><td>\s*(?:Data rozpoczęcia[^<]*|Start date[^<]*)</td><td>.*?</td></tr>",
    re.DOTALL,
)


def apply_company_variant_html(
    rendered: str, *, language: str, assigned_person: str
) -> str:
    lang = "en" if language == "en" else "pl"
    out, shifted = _renumber_html(rendered)
    if shifted == 0:
        raise CompanyVariantError(
            "Nie znaleziono nagłówka § 12 umowy głównej w podglądzie."
        )
    out, applied = apply_ops_html_counted(
        out,
        [("insert_before_section", INSERTED_SECTION + 1, section_12_blocks(lang))],
    )
    if applied != 1:
        raise CompanyVariantError(
            "Nie udało się wstawić § 12 „Osoby skierowane do realizacji Usług” "
            "do podglądu."
        )
    row = _START_ROW_HTML.search(out)
    if row is None:
        raise CompanyVariantError("Nie znaleziono tabeli Załącznika nr 3 w podglądzie.")
    cell = html.escape(assigned_person or "………", quote=False)
    extra = (
        f"<tr><td>{html.escape(assigned_person_label(lang), quote=False)}</td>"
        f"<td>{cell}</td></tr>"
    )
    return out[: row.end()] + extra + out[row.end() :]


# ── Dane komparycji ─────────────────────────────────────────────────────────

_AMOUNT = re.compile(
    r"^\s*\d{1,3}(?:[ . ]?\d{3})*(?:,\d{1,2})?\s*(?:zł|pln)?\s*$", re.I
)


def format_share_capital(raw: str | None, language: str) -> str | None:
    """„5000” / „5 000,00” / „1360000,00” → „5.000,00 zł” (EN: „PLN 5,000.00”).

    Zapis z kropkami tysięcy to ten sam, którym umowa przedstawia kapitał
    B2B.net („1.360.000,00 zł”). Wartość, której nie da się przeczytać jako
    kwoty w złotych (np. „10 000 EUR”), trafia do umowy tak, jak ją wpisano —
    lepsza dosłowna niż zgadnięta."""
    text = (raw or "").strip()
    if not text:
        return None
    if not _AMOUNT.match(text):
        return text
    digits = re.sub(r"(?i)zł|pln", "", text).strip()
    whole, _, frac = digits.partition(",")
    whole = re.sub(r"[ . ]", "", whole)
    frac = (frac + "00")[:2]
    groups: list[str] = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    if language == "en":
        return f"PLN {','.join(groups)}.{frac}"
    return f"{'.'.join(groups)},{frac} zł"


_FUNCTION_EN: Final[dict[str, str]] = {
    "prezes zarządu": "President of the Management Board",
    "wiceprezes zarządu": "Vice-President of the Management Board",
    "członek zarządu": "Member of the Management Board",
    "prokurent": "Commercial Proxy (Prokurent)",
    "komplementariusz": "General Partner",
    "wspólnik": "Partner",
}


def representation_en(
    name: str | None, function: str | None, gender: str | None
) -> str | None:
    """„Mr Jan Kowalski – President of the Management Board” dla umowy EN."""
    person = (name or "").strip()
    if not person:
        return None
    title = "Ms" if is_female(gender) else "Mr"
    raw_function = (function or "").strip()
    translated = _FUNCTION_EN.get(raw_function.lower(), raw_function)
    return f"{title} {person} – {translated}" if translated else f"{title} {person}"


def representation_pl_fallback(
    name: str | None, function: str | None, gender: str | None
) -> str | None:
    """Fraza bez odmiany, gdy formularz nie przysłał gotowego biernika.

    Front liczy biernik i daje go do poprawy; tu zostaje wyłącznie zapas dla
    klienta API, który wysłał samo imię i nazwisko."""
    person = (name or "").strip()
    if not person:
        return None
    title = "Panią" if is_female(gender) else "Pana"
    raw_function = (function or "").strip()
    return f"{title} {person} – {raw_function}" if raw_function else f"{title} {person}"
