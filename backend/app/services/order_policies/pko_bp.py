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

Od 10.2026 (ticket 12) tabelę czytamy przede wszystkim z POŁOŻENIA słów pod
nagłówkami kolumn (``pko_bp_layout``): wielolinijkowy profil („Inżynier /
DevSecOpS / Senior") wstawiał środkową linię w linię wiersza, a słownik słów
profilu nie zna każdego profilu. ``apply_layout_table`` podmienia surową tabelę
w tekście na wiersze „Wykonawca N | kolumna: wartość | …", które czytają model,
ta reguła i bramka automatu. Reguła tekstowa niżej zostaje dla dokumentów bez
warstwy tekstu z położeniem (DOCX, skan) i dla tabeli, której nie da się
odczytać z układu.

Stawka z kolumny „Stawka PLN/MD netto" jest u PKO BP zawsze netto
(``apply_rate_rules``) — „brutto" w dokumencie dotyczy wyłącznie łącznej
wartości zamówienia, a gwiazdka przy kwocie znaczy „stawka negocjowana".
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from app.services.order_pdf_parser import _is_rate_conversion_reason
from app.services.order_policies import pko_bp_layout
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
        "devsecops",
        "secops",
        "mlops",
        "sre",
        "rpa",
        "etl",
        "bi",
    }
)


def order_number(text: str) -> Optional[str]:
    return labelled_text(ORDER_NUMBER_LABEL, text)


def _is_profile_word(token: str) -> bool:
    return fold(token).strip(",;:()") in _PROFILE_WORDS


_NAME_BOUNDARY_REASON_PREFIX = "Nie rozpoznano granicy imienia i nazwiska oraz profilu"


def split_name_and_profile(segment: str) -> tuple[str, Optional[str]]:
    """Imię i nazwisko z fragmentu linii przed datami; drugi element = powód niepewności.

    Kolumna „Imię i nazwisko Wykonawców" to dwa słowa (nazwisko z myślnikiem
    jest jednym słowem). Pewne są wyłącznie dwa układy: same dwa słowa albo
    dwa słowa, po których od razu zaczyna się profil. Wszystko inne zostaje
    jako wiersz niepewny — lepiej osoba do sprawdzenia niż cudzy kontrakt.
    """
    name = clean_person_name(segment)
    tokens = name.split()
    uncertain = f"{_NAME_BOUNDARY_REASON_PREFIX} w wierszu „{name}” — sprawdź osobę"
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


# Wiersz w JEDNEJ linii: nazwisko (z ewentualnym profilem), dwie daty ISO,
# a za nimi ogon z liczbą MD, stawką, lokalizacją i numerem SSGW.
_ROW_HEAD_RE = re.compile(
    r"^(?P<name>[^\d\n]{3,80}?)[ \t]+(?P<start>\d{4}-\d{2}-\d{2})[ \t]+"
    r"(?P<end>\d{4}-\d{2}-\d{2})(?P<tail>[^\n]*)",
    re.MULTILINE,
)
# Separator tysięcy w kwocie: zwykła spacja, NBSP, wąska NBSP (pdfplumber
# oddaje różne warianty) albo kropka („1.240,00").
_THOUSANDS = "[ \u00a0\u202f.]"
# Stawka: jedyna liczba wiersza z częścią setną.
_RATE_RE = re.compile(rf"(?:\d{{1,3}}(?:{_THOUSANDS}\d{{3}})+|\d+),\d{{2}}")
# Odstęp między kolumnami: spacja, tabulator, NBSP albo wąska NBSP.
_GAP = "[ \t\u00a0\u202f]"
# Liczba MD: liczba CAŁKOWITA bez separatora tysięcy, oddzielona od stawki.
_MD_PLAIN_RE = re.compile(rf"\A{_GAP}+(\d{{1,4}}){_GAP}+\Z")
# Wariant awaryjny: liczba MD z separatorem tysięcy (wynik z ostrzeżeniem).
_MD_SEPARATED_RE = re.compile(rf"\A{_GAP}+(\d{{1,3}}(?:{_THOUSANDS}\d{{3}})+){_GAP}+\Z")

REASON_MD_RATE_AMBIGUOUS = (
    "Nie da się jednoznacznie rozdzielić liczby MD i stawki w wierszu tabeli "
    "— wpisz obie wartości z PDF-a"
)
REASON_MD_SEPARATED = (
    "Liczba MD zapisana z separatorem tysięcy — sprawdź liczbę MD i stawkę "
    "w wierszu tabeli"
)


def _md_rate_splits(tail: str, md_re: re.Pattern[str]) -> list[tuple[str, str]]:
    """Wszystkie podziały ogona na (liczba MD, stawka), których nie wyklucza tekst."""
    splits: list[tuple[str, str]] = []
    for pos, char in enumerate(tail):
        if not (char.isascii() and char.isdigit()):
            continue
        if pos and (tail[pos - 1].isdigit() or tail[pos - 1] in ",."):
            continue  # środek dłuższej liczby, nie jej początek
        rate = _RATE_RE.match(tail, pos)
        if rate is None:
            continue
        # Gwiazdka przy kwocie znaczy „stawka negocjowana" i nie jest cyfrą.
        after = tail[rate.end() :].lstrip("*")
        if after[:1] not in ("", " ", "\t", "\u00a0", "\u202f"):
            continue  # kwota jest fragmentem czegoś dłuższego (np. numeru SSGW)
        md = md_re.fullmatch(tail[:pos])
        if md is not None:
            splits.append((md.group(1), rate.group(0)))
    return splits


def split_md_and_rate(
    tail: str,
) -> Optional[tuple[Optional[Decimal], Optional[Decimal], Optional[str]]]:
    """Liczba MD i stawka z ogona wiersza: „ 58 1 240,00* Warszawa 104214-1".

    Zwraca ``None``, gdy ogon nie niesie kompletu liczb — taka linia nie jest
    wierszem osoby (fail-closed, jak dotąd).

    Do 09.2026 dzielił je jeden regex, w którym liczba MD mogła zawierać
    spacje. Przy stawce od 1 000 zł zapisanej ze spacją („58 1 240,00")
    nawroty silnika regex dzieliły liczby po swojemu — MD „58 1" (=581)
    i stawka 240,00 — a wynik szedł do pól dokumentu BEZ zastrzeżenia.
    Stawki PKO BP za MD bywają czterocyfrowe, więc dotyczyło to realnych
    zamówień, a błąd wychodził dopiero na fakturze.

    Teraz podział jest jawny: stawka to jedyna liczba z częścią setną, a przed
    nią stoi liczba MD. Liczymy DWA odczyty — z liczbą MD bez separatora
    tysięcy („58 1 240,00" = 58 MD po 1240 zł) i z separatorem („1 200 900,00"
    = 1200 MD po 900 zł). Zgodne albo pojedyncze = wynik (ten z separatorem
    z ostrzeżeniem, bo ta sama treść czyta się też inaczej). Sprzeczne —
    „2 500 900,00" to 2 MD po 500 900 zł ALBO 2500 MD po 900 zł — zostawiają
    wiersz niepewny BEZ liczb: zgadnięta stawka zapisana jako pewna jest gorsza
    niż puste pole (ta sama reguła co w Credit Agricole), bo wychodzi dopiero
    na fakturze.
    """
    plain = _md_rate_splits(tail, _MD_PLAIN_RE)
    separated = _md_rate_splits(tail, _MD_SEPARATED_RE)
    if plain and separated and plain != separated:
        return None, None, REASON_MD_RATE_AMBIGUOUS
    if len(plain) == 1:
        md_text, rate_text = plain[0]
        return normalize_amount(md_text), normalize_amount(rate_text), None
    if len(separated) == 1:
        md_text, rate_text = separated[0]
        return (
            normalize_amount(md_text),
            normalize_amount(rate_text),
            REASON_MD_SEPARATED,
        )
    if plain or separated:  # obrona: kilka odczytów w jednym wariancie
        return None, None, REASON_MD_RATE_AMBIGUOUS
    return None


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    """Wiersze Wykonawców z tabeli (deterministycznie, fail-closed).

    Dwa układy tej samej tabeli, zależne od ekstraktora tekstu: pdfplumber
    (produkcja) oddaje WIERSZ w jednej linii — „Andrzej Iciek 2026-09-01
    2026-11-30 64 900,00 Warszawa 103587-1"; inne ekstraktory oddają komórki
    po jednej na linię. Obsługujemy oba: najpierw wiersz-w-linii, potem
    komórka-na-linię. Układ komórka-na-linię nie ma problemu z podziałem
    liczb — każda stoi w osobnej linii (``_NUMBER_RE``).
    """
    text = text or ""
    layout = [row for row, _profile in layout_entries(text)]
    if layout:
        return layout
    return _extract_rows_from_text(text)


def _extract_rows_from_text(text: str) -> list[ConsultantOrderRow]:
    rows: list[ConsultantOrderRow] = []
    for m in _ROW_HEAD_RE.finditer(text):
        numbers = split_md_and_rate(m.group("tail"))
        if numbers is None:
            continue
        md_total, rate_client, number_reason = numbers
        name, name_reason = split_name_and_profile(m.group("name"))
        reason = "; ".join(r for r in (name_reason, number_reason) if r) or None
        rows.append(
            ConsultantOrderRow(
                consultant_name=name,
                start_date=normalize_date(m.group("start"), end=False),
                end_date=normalize_date(m.group("end"), end=True),
                md_total=md_total,
                rate_client=rate_client,
                rate_unit="day",
                uncertain=reason is not None,
                uncertain_reason=reason,
            )
        )
    if rows:
        return rows
    return _extract_rows_cell_per_line(text)


# ── Tabela odczytana z położenia słów (``pko_bp_layout``) ──────────────────

_LAYOUT_ROW_RE = re.compile(
    rf"^{pko_bp_layout.ROW_PREFIX} \d+ \| (?P<cells>[^\n]*)$", re.MULTILINE
)
_LABEL_TO_COLUMN = {
    fold(label): col for col, label in pko_bp_layout.LABELS.items() if col != "rate"
}
_RATE_CELL_RE = re.compile(rf"(?:\d{{1,3}}(?:{_THOUSANDS}\d{{3}})+|\d+),\d{{2}}")
_MD_CELL_RE = re.compile(rf"\d{{1,3}}(?:{_THOUSANDS}\d{{3}})*(?:,\d{{1,2}})?")


def _layout_cells(line: str) -> tuple[dict[str, str], list[str]]:
    cells: dict[str, str] = {}
    reasons: list[str] = []
    for part in line.split(" | "):
        label, sep, value = part.partition(": ")
        if not sep:
            continue
        key = fold(label.strip())
        if key == "uwaga":
            reasons.extend(r.strip() for r in value.split(";") if r.strip())
        elif key.startswith("stawka"):
            cells["rate"] = value.strip()
        elif key in _LABEL_TO_COLUMN:
            cells[_LABEL_TO_COLUMN[key]] = value.strip()
    return cells, reasons


def layout_entries(text: str) -> list[tuple[ConsultantOrderRow, str]]:
    """Wiersze tabeli z układu PDF (``apply_layout_table``) razem z profilem.

    Imię i nazwisko idzie WYŁĄCZNIE z kolumny „Imię i nazwisko Wykonawców";
    profil wraca obok, tylko po to, żeby rozpoznać go w nazwisku od modelu
    (``_reconcile_names_with_table``) — nigdy do dopasowania osoby.
    """
    entries: list[tuple[ConsultantOrderRow, str]] = []
    for match in _LAYOUT_ROW_RE.finditer(text or ""):
        cells, reasons = _layout_cells(match.group("cells"))
        md_text = cells.get("md", "")
        rate_text = cells.get("rate", "").rstrip("*").strip()
        md_total = normalize_amount(md_text) if _MD_CELL_RE.fullmatch(md_text) else None
        rate_client = (
            normalize_amount(rate_text) if _RATE_CELL_RE.fullmatch(rate_text) else None
        )
        if (md_total is None or rate_client is None) and (
            pko_bp_layout.REASON_NUMBERS not in reasons
        ):
            reasons.append(pko_bp_layout.REASON_NUMBERS)
        start, end = cells.get("start", ""), cells.get("end", "")
        reason = "; ".join(dict.fromkeys(reasons)) or None
        entries.append(
            (
                ConsultantOrderRow(
                    consultant_name=clean_person_name(cells.get("name", "")),
                    start_date=normalize_date(start, end=False) if start else None,
                    end_date=normalize_date(end, end=True) if end else None,
                    md_total=md_total,
                    rate_client=rate_client,
                    rate_unit="day",
                    uncertain=reason is not None,
                    uncertain_reason=reason,
                ),
                cells.get("profile", ""),
            )
        )
    return entries


#: Nagłówek „Numer SSGW" jest tylko w tabeli Wykonawców; „Imię i nazwisko"
#: bywa też przy osobie kontaktowej nad tabelą, więc od niego nie szukamy.
_SSGW_RE = re.compile(r"\bSSGW\b")
_FOOTNOTE_RE = re.compile(r"^\s*\*\s*\D")
_HEADER_LINE_WORDS = frozenset(
    {
        "imie",
        "i",
        "nazwisko",
        "wykonawcow",
        "profil",
        "poczatek",
        "zaangazowania",
        "planowany",
        "koniec",
        "liczba",
        "md",
        "stawka",
        "pln/md",
        "netto",
        "brutto",
        "lokalizacja",
        "numer",
        "ssgw",
    }
)


def _is_header_line(line: str) -> bool:
    tokens = fold(line).split()
    return bool(tokens) and all(t in _HEADER_LINE_WORDS for t in tokens)


def apply_layout_table(text: str, words: Optional[list]) -> str:
    """Surowa tabela Wykonawców w tekście → wiersze odczytane z kolumn PDF-a.

    Tekst zostaje bez zmian, gdy słów nie ma (DOCX, skan), tabeli nie da się
    odczytać z układu albo układ dał MNIEJ wierszy niż reguła tekstowa — wtedy
    zgubiłby osobę, a lepiej zostać przy starym, sprawdzonym odczycie.
    """
    text = text or ""
    if not words or pko_bp_layout.TABLE_TITLE in text:
        return text
    table = pko_bp_layout.read_table(pko_bp_layout.words_from_payload(words))
    if table is None or len(table.rows) < len(_extract_rows_from_text(text)):
        return text
    block = pko_bp_layout.render_table(table)
    lines = text.split("\n")
    anchor = next((i for i, ln in enumerate(lines) if _SSGW_RE.search(ln)), None)
    if anchor is None:
        return f"{text.rstrip()}\n{block}\n"
    # Nagłówek to linie złożone wyłącznie ze słów nagłówka tabeli — w górę od
    # linii z „SSGW"; nic spoza tabeli nie zostanie wycięte.
    start = anchor
    while start > 0 and _is_header_line(lines[start - 1]):
        start -= 1
    end = next(
        (
            i
            for i in range(anchor + 1, len(lines))
            if _TABLE_END_RE.search(lines[i]) or _FOOTNOTE_RE.match(lines[i])
        ),
        None,
    )
    if end is None:
        # Bez końca tabeli nie wiadomo, co jeszcze do niej należy — surowy
        # tekst zostaje, a wiersze z układu stoją na końcu (czyta je reguła).
        return f"{text.rstrip()}\n{block}\n"
    return "\n".join([*lines[:start], block, *lines[end:]])


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


def _set_or_clear(result: OrderExtraction, name: str, value: object) -> None:
    """Pole z wiersza tabeli; brak wartości czyści pole, nie zapisuje ``None``."""
    if value is None:
        clear_field(result, name)
    else:
        set_field(result, name, value)


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

    entries = layout_entries(document_text)
    rows = [row for row, _profile in entries] or extract_rows(document_text)
    profiles = {id(row): profile for row, profile in entries}
    if len(rows) == 1:
        row = rows[0]
        set_field(result, "start_date", row.start_date)
        set_field(result, "end_date", row.end_date)
        # Wiersz, którego liczb nie dało się rozdzielić, zostawia PUSTE pole
        # dokumentu zamiast wartości udającej odczyt z tabeli.
        _set_or_clear(result, "rate_client", row.rate_client)
        set_field(result, "rate_unit", "day")
        _set_or_clear(result, "md_total", row.md_total)
    elif rows:
        # Wiele osób: pola dokumentu nie znaczą nic — okres i stawka są per wiersz.
        for name in ("rate_client", "rate_unit", "md_total"):
            clear_field(result, name)
    if rows and not result.consultant_rows:
        result.consultant_rows = rows
    else:
        _reconcile_names_with_table(result.consultant_rows, rows, profiles)

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
    rows: list[ConsultantOrderRow],
    table: list[ConsultantOrderRow],
    profiles: Optional[dict[int, str]] = None,
) -> None:
    """Nazwisko z doklejonym profilem („Jan Kowalski Tester Middle") → nazwisko z tabeli.

    Dotyczy wierszy modelu (który widzi ten sam sklejony tekst) i odczytu
    zapisanego przed poprawką reguły („Przelicz plan"). Zmiana zachodzi tylko,
    gdy tokeny wiersza zaczynają się od tokenów DOKŁADNIE JEDNEGO pewnego
    wiersza tabeli, a dopisek to wyłącznie słowa profilu — ze słownika albo
    z kolumny „Profil" tego wiersza odczytanej z układu PDF („DevSecOpS").
    Powód „nie rozpoznano granicy imienia i nazwiska" znika razem z dopiskiem.
    """
    profiles = profiles or {}
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
        profile_tokens = set(fold(profiles.get(id(source), "")).split())
        if all(
            _is_profile_word(t) or t.strip(",;:()") in profile_tokens
            for t in tokens[len(head) :]
        ):
            row.consultant_name = source.consultant_name
            if row.uncertain_reason:
                kept = [
                    part.strip()
                    for part in row.uncertain_reason.split(";")
                    if part.strip()
                    and not part.strip().startswith(_NAME_BOUNDARY_REASON_PREFIX)
                ]
                row.uncertain_reason = "; ".join(kept) or None
                row.uncertain = bool(kept)


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
