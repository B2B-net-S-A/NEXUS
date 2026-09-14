"""PKO Bank Polski — „Zamówienie nr", tabela Wykonawców z okresem i stawką MD.

Układ z korpusu (nagłówki tabeli rozbite po jednym na linię, potem wiersze)::

    Zamówienie nr 1830/2026
    Zgodnie z postanowieniem Umowy ramowej numer DIT-2025-0005 …   ← NIE numer zamówienia
    1. Wykonawcy, Profile, Terminy, Stawki:
    Imię i nazwisko / Wykonawców / Profil / Początek / Zaangażowania /
    Planowany Koniec / Zaangażowania / Liczba MD / Stawka / PLN/MD netto /
    Lokalizacja / Numer SSGW
    Andrzej Iciek / Projektant / UI/UX Senior / 2026-09-01 / 2026-11-30 / 64 / 900,00 / …
    Łączna wartość zamówienia wynosi: 57 600,00 PLN netto …

Wiersz osoby: nazwisko, potem profil (1–2 linie), potem DWIE daty ISO, liczba MD
i stawka. Parsujemy fail-closed: wiersz bez kompletu dwóch dat i dwóch liczb
nie jest wierszem.

Profil JEDNOLINIOWY („Tester Middle") pdfplumber stawia w tej samej linii co
nazwisko, między nim a datami: „Piotr Michałowski Tester Middle 2026-10-01 …".
Do 09.2026 cały ten fragment szedł jako nazwisko, więc resolver nie trafiał
w istniejącego konsultanta i plan proponował nowego kontraktora. Granicę
nazwiska i profilu wyznacza słownik słów profilu; granica niepewna = wiersz
niepewny (do sprawdzenia), nigdy zgadywanie.

Stawka z kolumny „Stawka PLN/MD netto" jest u PKO BP zawsze netto
(``apply_rate_rules``) — „brutto" w dokumencie dotyczy wyłącznie łącznej
wartości zamówienia, a gwiazdka przy kwocie znaczy „stawka negocjowana".
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from app.services.order_pdf_parser import _is_rate_conversion_reason
from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clean_person_name,
    clear_field,
    fold,
    labelled_text,
    normalize_amount,
    normalize_date,
    set_field,
)

ORDER_NUMBER_LABEL = r"Zam[óo]wienie\s+nr\.?"
_HEADER_END_RE = re.compile(r"Numer\s+SSGW", re.IGNORECASE)
_TABLE_END_RE = re.compile(r"[ŁL][aą]czna\s+warto[śs][ćc]", re.IGNORECASE)
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMBER_RE = re.compile(r"^\d[\d\s  .]*(?:,\d{1,2})?\*?$")
_NAME_RE = re.compile(r"^[^\d]{3,80}$")


# Nagłówek kolumny stawki. Dokument PKO BP mówi „Stawka PLN/MD netto"; jawne
# „PLN/MD brutto" byłoby zmianą szablonu i idzie do weryfikacji.
_RATE_HEADER_GROSS_RE = re.compile(r"PLN\s*/\s*MD\s+brutto", re.IGNORECASE)

REASON_GROSS_HEADER = (
    "Kolumna stawki w tabeli PKO BP jest oznaczona jako brutto — sprawdź stawkę"
)

#: Słowa profilu (po ``fold``): poziomy i role z katalogu profili PKO BP
#: („Tester Middle", „Projektant UI/UX Senior", „Analityk Biznesowy Expert").
_PROFILE_WORDS = frozenset(
    {
        # poziomy
        "junior",
        "middle",
        "mid",
        "regular",
        "senior",
        "expert",
        "ekspert",
        "ekspertka",
        "lead",
        "principal",
        "starszy",
        "starsza",
        "mlodszy",
        "mlodsza",
        # role
        "tester",
        "testerka",
        "programista",
        "programistka",
        "developer",
        "deweloper",
        "analityk",
        "analityczka",
        "architekt",
        "architektka",
        "projektant",
        "projektantka",
        "kierownik",
        "kierowniczka",
        "konsultant",
        "konsultantka",
        "specjalista",
        "specjalistka",
        "administrator",
        "administratorka",
        "inzynier",
        "inzynierka",
        "koordynator",
        "koordynatorka",
        "manager",
        "menedzer",
        "scrum",
        "master",
        "devops",
        "designer",
        "owner",
        "product",
        "project",
        "business",
        "data",
        "qa",
        "ui/ux",
        "ux/ui",
        "ux",
        "ui",
        "sap",
        "java",
        "python",
        "frontend",
        "front-end",
        "backend",
        "back-end",
        "fullstack",
        "full-stack",
        "dba",
        "security",
        "cloud",
    }
)


def order_number(text: str) -> Optional[str]:
    return labelled_text(ORDER_NUMBER_LABEL, text)


def _is_profile_word(token: str) -> bool:
    return fold(token).strip(",;:()") in _PROFILE_WORDS


def split_name_and_profile(segment: str) -> tuple[str, Optional[str]]:
    """Imię i nazwisko z fragmentu linii przed datami; drugi element = powód niepewności.

    Kolumna „Imię i nazwisko Wykonawców" to dwa słowa (nazwisko z myślnikiem
    jest jednym słowem). Pewne są wyłącznie dwa układy: same dwa słowa albo
    dwa słowa, po których od razu zaczyna się profil. Wszystko inne zostaje
    jako wiersz niepewny — lepiej osoba do sprawdzenia niż cudzy kontrakt.
    """
    name = clean_person_name(segment)
    tokens = name.split()
    uncertain = (
        f"Nie rozpoznano granicy imienia i nazwiska oraz profilu w wierszu "
        f"„{name}” — sprawdź osobę"
    )
    if any(_is_profile_word(t) for t in tokens[:2]):
        # Nazwisko zawinięte na dwie linie: w linii wiersza został sam profil.
        return name, uncertain
    if len(tokens) <= 2:
        return name, None
    first_profile = next(
        (i for i, t in enumerate(tokens) if i >= 2 and _is_profile_word(t)), None
    )
    if first_profile == 2:
        return " ".join(tokens[:2]), None
    if first_profile is not None:
        return " ".join(tokens[:first_profile]), uncertain
    return name, uncertain


_ROW_LINE_RE = re.compile(
    r"^(?P<name>[^\d\n]{3,80}?)[ \t]+(?P<start>\d{4}-\d{2}-\d{2})[ \t]+(?P<end>\d{4}-\d{2}-\d{2})"
    r"[ \t]+(?P<md>\d[\d  ]*)[ \t]+(?P<rate>\d[\d  .]*,\d{2})\b",
    re.MULTILINE,
)


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    """Wiersze Wykonawców z tabeli (deterministycznie, fail-closed).

    Dwa układy tej samej tabeli, zależne od ekstraktora tekstu: pdfplumber
    (produkcja) oddaje WIERSZ w jednej linii — „Andrzej Iciek 2026-09-01
    2026-11-30 64 900,00 Warszawa 103587-1"; inne ekstraktory oddają komórki
    po jednej na linię. Obsługujemy oba: najpierw wiersz-w-linii, potem
    komórka-na-linię.
    """
    text = text or ""
    rows: list[ConsultantOrderRow] = []
    for m in _ROW_LINE_RE.finditer(text):
        name, reason = split_name_and_profile(m.group("name"))
        rows.append(
            ConsultantOrderRow(
                consultant_name=name,
                start_date=normalize_date(m.group("start"), end=False),
                end_date=normalize_date(m.group("end"), end=True),
                md_total=normalize_amount(m.group("md")),
                rate_client=normalize_amount(m.group("rate")),
                rate_unit="day",
                uncertain=reason is not None,
                uncertain_reason=reason,
            )
        )
    if rows:
        return rows
    return _extract_rows_cell_per_line(text)


def _extract_rows_cell_per_line(text: str) -> list[ConsultantOrderRow]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(lines) if _HEADER_END_RE.search(ln)), None)
    if start is None:
        return []
    rows: list[ConsultantOrderRow] = []
    i = start + 1
    while i < len(lines) and not _TABLE_END_RE.search(lines[i]):
        name_line = lines[i]
        if not _NAME_RE.match(name_line):
            i += 1
            continue
        dates: list[str] = []
        numbers: list[Decimal] = []
        j = i + 1
        while j < len(lines) and not _TABLE_END_RE.search(lines[j]) and j < i + 12:
            ln = lines[j]
            if _ISO_RE.match(ln):
                dates.append(ln)
            elif _NUMBER_RE.match(ln):
                amount = normalize_amount(ln.rstrip("*"))
                if amount is not None:
                    numbers.append(amount)
            if len(dates) >= 2 and len(numbers) >= 2:
                break
            j += 1
        if len(dates) >= 2 and len(numbers) >= 2:
            rows.append(
                ConsultantOrderRow(
                    consultant_name=clean_person_name(name_line),
                    start_date=normalize_date(dates[0], end=False),
                    end_date=normalize_date(dates[1], end=True),
                    md_total=numbers[0],
                    rate_client=numbers[1],
                    rate_unit="day",
                    uncertain=False,
                )
            )
            i = j + 1
        else:
            i += 1
    return rows


def apply_pko_bp_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    number = order_number(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
    else:
        clear_field(result, "title")
        result.title_needs_review = True

    rows = extract_rows(document_text)
    if len(rows) == 1:
        row = rows[0]
        set_field(result, "start_date", row.start_date)
        set_field(result, "end_date", row.end_date)
        set_field(result, "rate_client", row.rate_client)
        set_field(result, "rate_unit", "day")
        set_field(result, "md_total", row.md_total)
    elif rows:
        # Wiele osób: pola dokumentu nie znaczą nic — okres i stawka są per wiersz.
        for name in ("rate_client", "rate_unit", "md_total"):
            clear_field(result, name)
    if rows and not result.consultant_rows:
        result.consultant_rows = rows
    else:
        _reconcile_names_with_table(result.consultant_rows, rows)

    reasons: list[str] = []
    reasons.extend(
        row.uncertain_reason for row in rows if row.uncertain and row.uncertain_reason
    )
    if result.title is None:
        reasons.append("Nie znaleziono pola „Zamówienie nr” — sprawdź numer zamówienia")
    if not rows:
        reasons.append(
            "Nie rozpoznano tabeli Wykonawców (okres, MD, stawka) — wpisz ręcznie"
        )
    result.uncertain_reasons = reasons
    result.uncertain = bool(reasons)
    return result


def _name_tokens(name: str) -> list[str]:
    return fold(clean_person_name(name)).split()


def _reconcile_names_with_table(
    rows: list[ConsultantOrderRow], table: list[ConsultantOrderRow]
) -> None:
    """Nazwisko z doklejonym profilem („Jan Kowalski Tester Middle") → nazwisko z tabeli.

    Dotyczy wierszy modelu (który widzi ten sam sklejony tekst) i odczytu
    zapisanego przed poprawką reguły („Przelicz plan"). Zmiana zachodzi tylko,
    gdy tokeny wiersza zaczynają się od tokenów DOKŁADNIE JEDNEGO pewnego
    wiersza tabeli, a dopisek to wyłącznie słowa profilu.
    """
    confident = [(t, _name_tokens(t.consultant_name)) for t in table if not t.uncertain]
    for row in rows:
        tokens = _name_tokens(row.consultant_name)
        matches = [
            (t, head)
            for t, head in confident
            if head and len(head) < len(tokens) and tokens[: len(head)] == head
        ]
        if len(matches) != 1:
            continue
        source, head = matches[0]
        if all(_is_profile_word(t) for t in tokens[len(head) :]):
            row.consultant_name = source.consultant_name


def apply_rate_rules(result: OrderExtraction, document_text: str) -> OrderExtraction:
    """PKO BP: stawka z kolumny „Stawka PLN/MD netto" jest zawsze netto.

    Zastępuje uniwersalne rozpoznanie brutto/netto, które przy „880,00*" nie
    widziało oznaczenia, a „brutto" z łącznej wartości zamówienia blokowało
    domniemanie netto. Nigdy nie dzieli przez 1,23; idempotentne — wcześniejsze
    przeliczenie jest cofane do kwoty z PDF-a. Jawne „PLN/MD brutto" w nagłówku
    kolumny stawki → weryfikacja.
    """
    for item in [result, *result.consultant_rows]:
        if item.rate_client_gross is not None:
            item.rate_client, item.rate_client_gross = item.rate_client_gross, None
    result.confidence.pop("rate_client_gross", None)
    for row in result.consultant_rows:
        if row.uncertain_reason:
            kept = [
                part.strip()
                for part in row.uncertain_reason.split(";")
                if part.strip() and not _is_rate_conversion_reason(part)
            ]
            row.uncertain_reason = "; ".join(kept) or None
            row.uncertain = bool(kept)
    result.uncertain_reasons = [
        reason
        for reason in result.uncertain_reasons
        if not _is_rate_conversion_reason(reason)
    ]
    rated = [row for row in result.consultant_rows if row.rate_client is not None]
    if (rated or result.rate_client is not None) and _RATE_HEADER_GROSS_RE.search(
        document_text or ""
    ):
        result.uncertain_reasons.append(REASON_GROSS_HEADER)
    result.uncertain = bool(result.uncertain_reasons)
    return result
