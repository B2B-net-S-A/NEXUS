"""Alior Bank — cztery pola z PDF-a zamówienia, reszta tabeli świadomie pomijana.

Zgłoszenie 09.2026: model przeczytał jednoosobowe zamówienie poprawnie, osoba
miała już szkic zamówienia, a mimo to PDF lądował w kolejce. Deterministyczny
ekstraktor oczekiwał kwot w formacie „1 155,00" i marży „13,81%", a dokument
ze zgłoszenia miał stawkę bazową bez groszy, marżę bez przecinka i stawkę
z jedną cyfrą po przecinku — zero wierszy, więc bramka widziała „Brak
niezależnego potwierdzenia osób i stawek", polityka dopisywała „Nie rozpoznano
tabeli Konsultantów", a uniwersalna detekcja VAT — „Nie ustalono, czy każda
stawka jest brutto czy netto".

Reguła czyta WYŁĄCZNIE:

1. **numer** — „Zamówienie nr: OIT/…". „Do Umowy Ramowej: OIT/…" stoi wyżej
   i powtarza się na każdej stronie — to numer umowy ramowej, nie zamówienia;
2. **imię i nazwisko** — kolumna „Imię i Nazwisko Konsultanta / członków
   Zespołu";
3. **okres** — najpierw zakres w nawiasie pod nazwiskiem
   „(05.10.2026-28.10.2026)"; bez niego „Moment wejścia w życie Zamówienia"
   (początek) i „czas oznaczony" z „Okresu obowiązywania" (koniec);
4. **stawkę** — kolumna „Razem stawka dla Banku [PLN netto]", za MD.

Rodzaj kompetencji, Liczba Roboczodni, Stawka bazowa, Marża, Total i warunki
szczególne nie trafiają do zamówienia i niczego nie blokują — ich relacja ze
stawką (albo z „Maksymalną wartością Zamówienia") nie jest powodem do
weryfikacji.

Stawka u Aliora jest NETTO z definicji: brak słowa „netto"/„brutto" przy
kwocie nie zatrzymuje zamówienia. Zatrzymuje je wyłącznie jawne „brutto"
w tabeli Konsultantów (nagłówek kolumny albo sama kwota) — i wtedy kwota NIE
jest przeliczana ÷ 1,23: to sprzeczność z regułą klienta, którą rozstrzyga
człowiek, a nie przypadek do automatycznego przeliczenia.

Układ z pipeline'u (pdfplumber). Komórki są wyśrodkowane w pionie, więc wiersz
liczbowy stoi między liniami komórki z nazwiskiem, a słowa kolumny kompetencji
przeplatają się z nazwiskiem::

    Wiktoria
    Testowa Business
    1 189 1 155,00 13,81% 1 340,00 253 260,00 zł
    (01.04.2031- Analyst
    31.12.2031)
    Łucja Próbna
    1 UI 18 1100 15% 1265,5 22 779,00 zł
    (05.10.2026-28.10.2026)

Kotwicą wiersza jest MARŻA — jedyny token z „%". Za nią stoją dokładnie dwie
kwoty: „Razem stawka dla Banku" i Total. Obie mają spację jako separator
tysięcy, więc podział ciągu cyfr bywa niejednoznaczny, gdy stawka nie ma
groszy („1 340 253 260,00 zł"). Wtedy i tylko wtedy rozstrzyga tożsamość
wiersza Total = Roboczodni × stawka — to reguła CZYTANIA kolumny, nie
kontrola: Total i Roboczodni nigdy nie trafiają do zamówienia, a brak
jednoznacznego podziału jest powodem dotyczącym stawki.

Zakres dat zamyka komórkę z nazwiskiem, więc linie między wierszami liczbowymi
dzielimy po ``dd.mm.rrrr)``. Nazwisko to słowa wiersza sprzed zakresu dat, bez
nagłówka tabeli i słownika kompetencji. Model czyta osoby niezależnie od tych
regexów: nazwisko z tabeli musi się z nim zgadzać, a jego stawka i okres — ze
stawką i okresem z tabeli. Każda rozbieżność idzie do człowieka.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Optional

from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clear_field,
    fold,
    labelled_date,
    labelled_text,
    normalize_amount,
    normalize_date,
    set_field,
)
from app.services.order_pdf_parser import (
    _contains_exact_tokens,
    _is_rate_conversion_reason,
    _name_match_score,
    _name_token_variants,
    _names_exactly_equivalent,
    apply_consultant_row_match,
)

#: Kolumna „Razem stawka dla Banku" jest stawką za MD (roboczodzień).
RATE_UNIT = "day"

REASON_NO_NUMBER = (
    "Nie znaleziono pola „Zamówienie nr:” (OIT/…) — sprawdź numer zamówienia"
)
REASON_NO_TABLE = (
    "Nie rozpoznano tabeli Konsultantów w PDF — sprawdź osoby i stawki ręcznie"
)
REASON_NO_PERIOD = (
    "Nie znaleziono okresu: ani zakresu w nawiasie pod nazwiskiem, ani "
    "„Moment wejścia w życie Zamówienia” / „czas oznaczony” — wpisz daty ręcznie"
)
REASON_GROSS = (
    "Stawka oznaczona w dokumencie jako brutto, mimo że dla Alior Bank "
    "domyślnie jest netto — zweryfikuj"
)

_NUMBER_LABEL = r"Zam[óo]wienie\s+nr\.?"
_START_LABEL = r"Moment\s+wej[śs]cia\s+w\s+[żz]ycie\s+Zam[óo]wienia"
# „czas oznaczony: 28.10.2026 lub do wyczerpania kwoty zamówienia" — fraza
# „lub do wyczerpania" NIE jest datą; ``labelled_date`` bierze samą datę.
_END_LABEL = r"czas\s+oznaczony"

_ROW_START_RE = re.compile(r"^(?P<lp>\d{1,2})\.?\s+(?P<rest>\S.*)$")
_MARGIN_RE = re.compile(r"(?<![\d.,])\d{1,2}(?:[.,]\d{1,2})?\s?%")
_NUMBER_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_CURRENCY_SUFFIX_RE = re.compile(r"(?:zł|zl|pln)\.?$", re.IGNORECASE)
_RATE_KIND_WORDS = frozenset({"netto", "brutto", "netto.", "brutto."})
# Kwota po złożeniu tokenów spacją: grupy tysięcy albo same cyfry, 0–2 miejsca.
_AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?: \d{3})+|\d+)(?:[.,]\d{1,2})?$")
# Zakres pod nazwiskiem: „(05.10.2026-28.10.2026)" albo „(od 05.10.2026 do …)".
_PERIOD_TOKEN_RE = re.compile(r"^\((?:od\b|\d{1,2}\.\d{1,2}\.\d)", re.IGNORECASE)
_PERIOD_START_RE = re.compile(
    r"\((?:od\s+)?(\d{1,2}\.\d{1,2}\.\d{4})\s*(?:[-–—]|do\b)", re.IGNORECASE
)
_PERIOD_END_RE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4})\s*\)")
#: Komórka z nazwiskiem ma w praktyce 1–4 linie; limit chroni przed wciągnięciem
#: tekstu sprzed tabeli, gdy ekstraktor zgubił nagłówek.
_MAX_CELL_LINES = 6
#: Rozstrzygnięcie podziału stawka/Total: Total liczony ze stawką po zaokrągleniu.
_TOTAL_TOLERANCE = Decimal("0.01")

#: Słowa, które występują WYŁĄCZNIE w nagłówku tabeli Konsultantów (po
#: zwinięciu diakrytyków). Linia z którymkolwiek z nich zamyka komórkę
#: z nazwiskiem od góry. „Zespołu" i „Rodzaj" świadomie poza listą: bywają też
#: w kolumnie kompetencji („Kierownik Zespołu"), a wtedy ucięłyby nazwisko.
_HEADER_WORDS = frozenset(
    {
        "l.p",
        "lp",
        "imie",
        "nazwisko",
        "konsultanta",
        "czlonkow",
        "kompetencji",
        "stanowisko",
        "kompetencja",
        "liczba",
        "roboczodni",
        "stawka",
        "bazowa",
        "pln",
        "netto",
        "brutto",
        "marza",
        "razem",
        "banku",
        "total",
    }
)
#: Słowa kolumny „Rodzaj kompetencji", które w układzie pdfplumbera trafiają do
#: tych samych linii co nazwisko („Testowa Business"). Skróty wielkimi literami
#: („UI", „QA", „DevOps") odpadają same — nie wyglądają jak człon nazwiska.
#: Słowa, które bywają nazwiskami, świadomie poza listą: nieznane słowo
#: kompetencji kończy się rozbieżnością z odczytem modelu, czyli kolejką.
_COMPETENCE_WORDS = frozenset(
    {
        # poziom
        "junior",
        "regular",
        "mid",
        "middle",
        "senior",
        "expert",
        "ekspert",
        "lead",
        "leader",
        "lider",
        "liderka",
        "principal",
        "chief",
        "head",
        "starszy",
        "starsza",
        "mlodszy",
        "mlodsza",
        "glowny",
        "glowna",
        "wiodacy",
        # role i obszary (EN)
        "analyst",
        "business",
        "system",
        "systems",
        "data",
        "developer",
        "engineer",
        "architect",
        "tester",
        "test",
        "testing",
        "designer",
        "design",
        "product",
        "owner",
        "project",
        "program",
        "programme",
        "manager",
        "management",
        "scrum",
        "master",
        "agile",
        "coach",
        "consultant",
        "specialist",
        "administrator",
        "admin",
        "operator",
        "support",
        "mobile",
        "backend",
        "frontend",
        "fullstack",
        "full",
        "stack",
        "front",
        "back",
        "end",
        "web",
        "cloud",
        "security",
        "network",
        "database",
        "release",
        "delivery",
        "integration",
        "platform",
        "infrastructure",
        "embedded",
        "software",
        "hardware",
        "solution",
        "solutions",
        "technical",
        "tech",
        "application",
        "applications",
        "service",
        "services",
        "automation",
        "manual",
        "performance",
        "quality",
        "assurance",
        "officer",
        "coordinator",
        "scientist",
        "modeler",
        "modeller",
        "writer",
        "graphic",
        "visual",
        "interaction",
        "research",
        "researcher",
        "java",
        "python",
        "javascript",
        "typescript",
        "react",
        "angular",
        "android",
        "kotlin",
        "scala",
        "golang",
        "oracle",
        "azure",
        "salesforce",
        "mainframe",
        "cobol",
        "dynamics",
        # role i obszary (PL)
        "analityk",
        "analityczka",
        "biznesowy",
        "biznesowa",
        "systemowy",
        "systemowa",
        "programista",
        "programistka",
        "inzynier",
        "inzynierka",
        "architekt",
        "architektka",
        "rozwiazan",
        "projektant",
        "projektantka",
        "testerka",
        "testow",
        "manualny",
        "manualna",
        "automatyczny",
        "automatyczna",
        "kierownik",
        "kierowniczka",
        "koordynator",
        "koordynatorka",
        "specjalista",
        "specjalistka",
        "konsultant",
        "konsultantka",
        "administratorka",
        "wsparcie",
        "wsparcia",
        "utrzymanie",
        "utrzymania",
        "danych",
        "baz",
        "sieci",
        "bezpieczenstwa",
        "aplikacji",
        "systemow",
        "oprogramowania",
        "wdrozen",
        "rozwoju",
        "zespol",
        "zespolu",
        "projektu",
        "projektow",
        "produktu",
        "jakosci",
        "infrastruktury",
        "techniczny",
        "techniczna",
        "mobilny",
        "mobilna",
        "mobilnych",
    }
)
_STOP_WORDS = _HEADER_WORDS | _COMPETENCE_WORDS | {"rodzaj", "bank", "alior"}

# Wątpliwość modelu co do WIERSZA osoby (nie da się odczytać / powiązać stawki,
# okresu, nazwiska). Zwykły komentarz modelu nie zatrzymuje zamówienia — jego
# wątpliwość co do czytanego pola tak.
_MODEL_DOUBT_RE = re.compile(
    r"nieczyteln|sprzeczn|niejednoznaczn|niepewn|watpliw|\bbrak\w*\b"
    r"|nie\s+(?:znaleziono|mozna|da\s+sie|udalo\s+sie|wiadomo|jest\s+jasne)"
)
_READ_FIELD_RE = re.compile(
    r"stawk|kwot|\bdat[ayeo]?\b|okres|termin|nazwisk|imie|imion|osob|konsultant"
    r"|numer|wiersz|powiaz|przypis"
)
_VAT_TOPIC_RE = re.compile(r"\b(?:brutto|netto|vat|gross|net)\b")

# Reguła sprzed 09.2026 czytała wyłącznie wiersze w tym kształcie i zapisywała
# je ZAMIAST odczytu modelu, gdy model nie zwrócił osób. Przy „Przelicz plan"
# na zapisie z tamtego okresu nie wiadomo, czy ``consultant_rows`` to odczyt
# modelu, czy tamta tabela — gdy ten wzorzec w ogóle trafia w dokument,
# zapisane wiersze nie mogą potwierdzać tabeli.
_LEGACY_AMT = r"\d[\d \u00a0]*,\d{2}"
_LEGACY_WORD = r"[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż/]+"
_LEGACY_ROW_RE = re.compile(
    rf"^\d{{1,2}}[ \t]+(?:\(\d{{1,2}}\.\d{{1,2}}\.\d{{4}}[-–]?\)?[ \t]+)?"
    rf"(?:{_LEGACY_WORD}(?:[ \t]+{_LEGACY_WORD})*[ \t]+)?"
    rf"\d{{1,4}}[ \t]+{_LEGACY_AMT}[ \t]+\d{{1,2}},\d{{2}}%[ \t]+"
    rf"{_LEGACY_AMT}[ \t]+{_LEGACY_AMT}[ \t]*z[łl]"
)

# Tematy powodów modelu, które przy braku tabeli dotyczą pól POMIJANYCH albo
# są rozstrzygnięte regułą klienta (netto, MD, „lub do wyczerpania").
_IGNORED_TOPIC_RE = re.compile(
    r"stawk\w*\s+bazow|\bbazow\w*|\bmarz\w*|\btotal\w*|subtotal|roboczodn\w*"
    r"|\bmd_total\b|\bliczb\w*\s+(?:md|dni|roboczo\w*)|\bilosc\w*|wartosc\w*"
    r"|razem\s+pln|maksymaln\w*|kompetenc\w*|stanowisk\w*|warunk\w*\s+szczegol\w*"
    r"|sprzet\w*|podwykonaw\w*|wypowiedz\w*|delegacj\w*|podroz\w*"
)
_HARD_PROBLEM_RE = re.compile(
    r"(?:nieczyteln|sprzeczn|niejednoznaczn|brak|nie\s+znaleziono)\w*"
    r"\s+(?:\S+\s+){0,2}?(?:stawk|kwot|dat|okres|nazwisk|osob|numer)"
)
_RESOLVED_TOPIC_RE = re.compile(
    r"\b(?:brutto|netto|vat|gross|net)\b|jednost\w*|wyczerpan\w*|miesieczn\w*"
)


# ── Numer i okres dokumentu ──────────────────────────────────────────────────


def order_number(text: str) -> Optional[str]:
    """Numer z pola „Zamówienie nr:" — nigdy numer umowy ramowej."""
    return labelled_text(_NUMBER_LABEL, text)


def document_period(text: str) -> tuple[Optional[str], Optional[str]]:
    """„Moment wejścia w życie Zamówienia" + „czas oznaczony" (Okres obowiązywania)."""
    return (
        labelled_date(_START_LABEL, text),
        labelled_date(_END_LABEL, text, end=True),
    )


# ── Wiersz liczbowy ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _NumericLine:
    lp: int
    #: Słowa między L.P a liczbami: fragmenty nazwiska, zakresu dat, kompetencji.
    head_words: tuple[str, ...]
    rate: Optional[Decimal]
    rate_problem: Optional[str]


def _split_rate(
    tail: list[str], workdays: Optional[int]
) -> tuple[Optional[Decimal], Optional[str]]:
    """„Razem stawka dla Banku" z tokenów za marżą (stawka, potem Total).

    Kolejne podziały ``tail[:s] | tail[s:]``: stawka musi być kwotą, Total
    (jeśli jest) — też. Jeden poprawny podział rozstrzyga; przy kilku wygrywa
    ten, dla którego Total = Roboczodni × stawka. Nic więcej z Total nie jest
    brane ani sprawdzane.
    """
    candidates: list[tuple[Decimal, Optional[Decimal]]] = []
    for split in range(1, len(tail) + 1):
        rate_text, total_text = " ".join(tail[:split]), " ".join(tail[split:])
        if not _AMOUNT_RE.match(rate_text):
            continue
        if total_text and not _AMOUNT_RE.match(total_text):
            continue
        rate = normalize_amount(rate_text)
        total = normalize_amount(total_text) if total_text else None
        if rate is not None and rate > 0:
            candidates.append((rate, total))
    if len(candidates) == 1:
        return candidates[0][0], None
    consistent = [
        rate
        for rate, total in candidates
        if workdays
        and total
        and abs(workdays * rate - total) <= total * _TOTAL_TOLERANCE
    ]
    if len(consistent) == 1:
        return consistent[0], None
    return None, (
        "nie udało się jednoznacznie odczytać kwoty z kolumny „Razem stawka dla Banku”"
    )


def _parse_numeric_line(line: str) -> Optional[_NumericLine]:
    """Wiersz tabeli: L.P, [słowa], Roboczodni, stawka bazowa, marża %, stawka, Total."""
    match = _ROW_START_RE.match(line.strip())
    if not match:
        return None
    rest = match.group("rest")
    margins = list(_MARGIN_RE.finditer(rest))
    if not margins:
        return None
    margin = margins[-1]
    head = rest[: margin.start()].split()
    # „zł"/„PLN" i dopiski „netto"/„brutto" przy kwocie nie są kolumnami —
    # rodzaj stawki ocenia ``table_marks_gross`` na surowym tekście wiersza.
    tail = [
        cleaned
        for token in rest[margin.end() :].split()
        if (cleaned := _CURRENCY_SUFFIX_RE.sub("", token))
        and cleaned.casefold() not in _RATE_KIND_WORDS
    ]
    if not tail or not all(_NUMBER_TOKEN_RE.match(token) for token in tail):
        return None
    # Końcówka przed marżą to Roboczodni i stawka bazowa — bez nich to nie
    # jest wiersz tabeli Konsultantów.
    run_start = len(head)
    while run_start > 0 and _NUMBER_TOKEN_RE.match(head[run_start - 1]):
        run_start -= 1
    run = head[run_start:]
    if not run:
        return None
    workdays = int(run[0]) if run[0].isdigit() else None
    rate, problem = _split_rate(tail, workdays)
    return _NumericLine(
        lp=int(match.group("lp")),
        head_words=tuple(head[:run_start]),
        rate=rate,
        rate_problem=problem,
    )


# ── Blok wiersza: nazwisko i okres ───────────────────────────────────────────


def _norm_word(token: str) -> str:
    return fold(token).strip("()[]{},.:;/\\\"'")


def _is_header_line(line: str) -> bool:
    return any(_norm_word(token) in _HEADER_WORDS for token in line.split())


def _is_name_part(token: str) -> bool:
    parts = token.split("-")
    return all(
        len(part) >= 2
        and part[0].isupper()
        and part[1:].isalpha()
        and part[1:].islower()
        for part in parts
    )


def _keeps_as_name(token: str) -> bool:
    return _is_name_part(token) and not any(
        _norm_word(part) in _STOP_WORDS for part in token.split("-")
    )


def _name_tokens(words: list[str]) -> list[str]:
    """Człony nazwiska w kolejności czytania; łączy nazwisko złamane na „-"."""
    out: list[str] = []
    pending: Optional[str] = None
    for raw in words:
        token = raw.strip(",;:")
        if pending is not None:
            joined, pending_word, pending = pending + token, pending[:-1], None
            if _keeps_as_name(joined):
                out.append(joined)
                continue
            if _keeps_as_name(pending_word):
                out.append(pending_word)
        if token.endswith("-") and _is_name_part(token[:-1]):
            pending = token
            continue
        if _keeps_as_name(token):
            out.append(token)
    if pending is not None and _keeps_as_name(pending[:-1]):
        out.append(pending[:-1])
    return out


@dataclass(frozen=True)
class _TableRow:
    lp: int
    name: str
    #: Wszystkie linie wiersza — dowód, że osoba stoi właśnie w TYM wierszu.
    block_text: str
    start_date: Optional[str]
    end_date: Optional[str]
    rate: Optional[Decimal]
    name_problem: Optional[str] = None
    rate_problem: Optional[str] = None
    period_problem: Optional[str] = None

    @property
    def label(self) -> str:
        return self.name or f"pozycja {self.lp}"

    @property
    def value_problems(self) -> list[str]:
        return [p for p in (self.rate_problem, self.period_problem) if p]


@dataclass(frozen=True)
class _Table:
    rows: tuple[_TableRow, ...]
    #: Nagłówek tabeli i linie wierszy — obszar, w którym „brutto" dotyczy stawki.
    region_text: str


def _block_start(lines: list[str], idx: int, floor: int) -> int:
    start = idx
    for j in range(idx - 1, max(floor, idx - _MAX_CELL_LINES) - 1, -1):
        if not lines[j].strip() or _is_header_line(lines[j]):
            break
        start = j
    return start


def _block_end(lines: list[str], start: int, idx: int, next_idx: Optional[int]) -> int:
    """Linia z ``dd.mm.rrrr)`` zamyka komórkę z nazwiskiem (i cały wiersz)."""
    if any(_PERIOD_END_RE.search(lines[j]) for j in range(start, idx)):
        return idx
    limit = (
        next_idx if next_idx is not None else min(len(lines), idx + _MAX_CELL_LINES + 1)
    )
    for j in range(idx, limit):
        if j > idx and (not lines[j].strip() or fold(lines[j]).startswith("razem")):
            break
        if _PERIOD_END_RE.search(lines[j]):
            return j
    return idx


def _build_row(
    lines: list[str], start: int, idx: int, end: int, numeric: _NumericLine
) -> _TableRow:
    words: list[str] = []
    for j in range(start, end + 1):
        line_words = list(numeric.head_words) if j == idx else lines[j].split()
        cut = next(
            (
                pos
                for pos, word in enumerate(line_words)
                if _PERIOD_TOKEN_RE.match(word)
            ),
            None,
        )
        words.extend(line_words if cut is None else line_words[:cut])
        if cut is not None:
            break
    tokens = _name_tokens(words)
    name = " ".join(tokens)
    label = name or f"pozycja {numeric.lp}"

    block_text = "\n".join(lines[start : end + 1])
    found_start = _PERIOD_START_RE.search(block_text)
    found_end = (
        _PERIOD_END_RE.search(block_text, found_start.end()) if found_start else None
    )
    start_date = (
        normalize_date(found_start.group(1), end=False) if found_start else None
    )
    end_date = normalize_date(found_end.group(1), end=True) if found_end else None
    period_problem = None
    if found_start and not (start_date and end_date):
        period_problem = (
            f"„{label}”: niepełny zakres dat w nawiasie pod nazwiskiem — sprawdź okres"
        )
        start_date = end_date = None
    elif start_date and end_date and start_date > end_date:
        period_problem = (
            f"„{label}”: zakres dat w nawiasie pod nazwiskiem jest odwrócony "
            f"({start_date} – {end_date}) — sprawdź okres"
        )
        start_date = end_date = None

    return _TableRow(
        lp=numeric.lp,
        name=name,
        block_text=block_text,
        start_date=start_date,
        end_date=end_date,
        rate=numeric.rate,
        name_problem=(
            None
            if 2 <= len(tokens) <= 4
            else f"„{label}”: nie udało się jednoznacznie odczytać imienia "
            "i nazwiska z tabeli — potwierdź osobę"
        ),
        rate_problem=f"„{label}”: {numeric.rate_problem}"
        if numeric.rate_problem
        else None,
        period_problem=period_problem,
    )


def _parse_table(text: str) -> _Table:
    lines = (text or "").splitlines()
    numeric = [
        (index, parsed)
        for index, line in enumerate(lines)
        if (parsed := _parse_numeric_line(line)) is not None
    ]
    rows: list[_TableRow] = []
    bounds: list[tuple[int, int]] = []
    previous_end = -1
    for position, (idx, parsed) in enumerate(numeric):
        next_idx = numeric[position + 1][0] if position + 1 < len(numeric) else None
        start = _block_start(lines, idx, floor=previous_end + 1)
        end = _block_end(lines, start, idx, next_idx)
        rows.append(_build_row(lines, start, idx, end, parsed))
        bounds.append((start, end))
        previous_end = end
    if not rows:
        return _Table(rows=(), region_text="")
    head = bounds[0][0]
    while head > max(0, bounds[0][0] - 12) and _is_header_line(lines[head - 1]):
        head -= 1
    # Nagłówek tabeli i linie wierszy. Bez stopki „Razem PLN" (suma, nie
    # stawka) i bez tekstu między wierszami (stopka/nagłówek kolejnej strony).
    parts = lines[head : bounds[0][0]]
    for start, end in bounds:
        parts.extend(lines[start : end + 1])
    return _Table(rows=tuple(rows), region_text="\n".join(parts))


# ── Wiersze osób: tabela autorytatywna, model tylko potwierdza ───────────────


def _row_from_table(row: _TableRow) -> ConsultantOrderRow:
    problems = [p for p in (row.name_problem, *row.value_problems) if p]
    return ConsultantOrderRow(
        consultant_name=row.label,
        rate_client=row.rate,
        rate_unit=RATE_UNIT if row.rate is not None else None,
        md_total=None,
        start_date=row.start_date,
        end_date=row.end_date,
        uncertain=bool(problems),
        uncertain_reason="; ".join(problems) or None,
    )


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    """Wiersze osób z samej tabeli PDF — bez modelu (bramka automatu, harness)."""
    return [_row_from_table(row) for row in _parse_table(text).rows]


def _clean_model_name(name: str) -> str:
    """Nazwisko z odczytu modelu bez dopisanych dat, nawiasów i cyfr."""
    cleaned = re.sub(r"\([^)]*\)?|\d", " ", name or "")
    return re.sub(r"\s+", " ", cleaned).strip(" ,;:-–—")


def _contains_person(text: str, name: str) -> bool:
    """Wszystkie człony osoby (po zwinięciu diakrytyków) występują w tekście."""
    haystacks = _name_token_variants(text, min_tokens=1)
    return any(
        _contains_exact_tokens(needle, list(haystack))
        for needle in _name_token_variants(name)
        for haystack in haystacks
    )


def _format_amount(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _concern_parts(reason: Optional[str]) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]+", reason or "") if part.strip()]


def _model_rate(model: ConsultantOrderRow) -> Optional[Decimal]:
    """Kwota z odczytu modelu — bez ewentualnego ÷ 1,23 ze starszego przebiegu."""
    return (
        model.rate_client_gross
        if model.rate_client_gross is not None
        else model.rate_client
    )


def _is_model_doubt(part: str) -> bool:
    """Czy powód modelu to wątpliwość co do czytanego pola, a nie komentarz."""
    folded = fold(part)
    if (
        _IGNORED_TOPIC_RE.search(folded)
        or not _MODEL_DOUBT_RE.search(folded)
        or not _READ_FIELD_RE.search(folded)
    ):
        return False
    if _VAT_TOPIC_RE.search(folded) and "nieczyteln" not in folded:
        # Rodzaj stawki rozstrzyga reguła klienta (netto), nie model.
        return False
    return not re.search(r"wyczerpan|jednost|miesieczn", folded)


def _cross_check(
    row: ConsultantOrderRow,
    model: ConsultantOrderRow,
    doc_period: tuple[Optional[str], Optional[str]],
) -> list[str]:
    """Stawka i okres z tabeli muszą zgadzać się z niezależnym odczytem modelu.

    Brak wartości w odczycie modelu NIE jest zgodą: prompt każe modelowi zostawić
    stawkę pustą właśnie wtedy, gdy nie umie jej powiązać z osobą.
    """
    problems: list[str] = []
    name = row.consultant_name
    model_rate = _model_rate(model)
    if row.rate_client is not None:
        if model_rate is None:
            problems.append(
                f"„{name}”: odczyt modelu nie potwierdził stawki z kolumny "
                "„Razem stawka dla Banku” — sprawdź stawkę"
            )
        elif model_rate != row.rate_client:
            problems.append(
                f"„{name}”: stawka z kolumny „Razem stawka dla Banku” "
                f"({_format_amount(row.rate_client)}) różni się od odczytu modelu "
                f"({_format_amount(model_rate)}) — sprawdź stawkę"
            )
    doc_start, doc_end = doc_period
    if row.start_date and row.end_date:
        if not (model.start_date or model.end_date):
            if (row.start_date, row.end_date) != (doc_start, doc_end):
                problems.append(
                    f"„{name}”: odczyt modelu nie potwierdził okresu w nawiasie pod "
                    f"nazwiskiem ({row.start_date} – {row.end_date}) — sprawdź okres"
                )
        elif (model.start_date and model.start_date != row.start_date) or (
            model.end_date and model.end_date != row.end_date
        ):
            problems.append(
                f"„{name}”: okres w nawiasie pod nazwiskiem "
                f"({row.start_date} – {row.end_date}) różni się od odczytu modelu "
                f"({model.start_date or '—'} – {model.end_date or '—'}) — sprawdź okres"
            )
    elif model.start_date or model.end_date:
        # Tabela nie ma zakresu pod nazwiskiem, więc obowiązuje okres dokumentu.
        # Inny okres w odczycie modelu znaczy, że zakres mógł być zapisany
        # w formie, której reguła nie zna — wtedy decyduje człowiek.
        start = row.start_date or doc_start
        end = row.end_date or doc_end
        if (model.start_date and model.start_date != start) or (
            model.end_date and model.end_date != end
        ):
            problems.append(
                f"„{name}”: okres z odczytu modelu "
                f"({model.start_date or '—'} – {model.end_date or '—'}) różni się "
                f"od okresu zamówienia ({start or '—'} – {end or '—'}) — sprawdź okres"
            )
    for part in _concern_parts(model.uncertain_reason) if model.uncertain else []:
        if _is_model_doubt(part):
            problems.append(f"„{name}”: odczyt modelu zgłasza wątpliwość: {part[:200]}")
    return problems


def _repeats(
    model: ConsultantOrderRow,
    row: ConsultantOrderRow,
    doc_period: tuple[Optional[str], Optional[str]],
) -> bool:
    """Ta sama pozycja wymieniona w odczycie drugi raz — identyczne wartości."""
    return (
        _model_rate(model) == row.rate_client
        and model.start_date == (row.start_date or doc_period[0])
        and model.end_date == (row.end_date or doc_period[1])
    )


@dataclass
class _Confirmed:
    row: ConsultantOrderRow
    #: Tożsamość: nazwisko nieczytelne w tabeli albo niepotwierdzone przez model.
    name_concerns: list[str] = field(default_factory=list)
    #: Wartości: stawka/okres nieczytelne albo różne od odczytu modelu.
    value_concerns: list[str] = field(default_factory=list)


def _confirm_rows(
    table: _Table,
    reading: list[ConsultantOrderRow],
    *,
    reading_state: str,
    doc_period: tuple[Optional[str], Optional[str]],
) -> tuple[list[_Confirmed], list[str]]:
    """Wiersze z tabeli potwierdzone odczytem modelu + osoby spoza odczytanej tabeli.

    Nazwisko z tabeli potwierdza model (równoważność po kolejności, diakrytykach
    i myślnikach). Gdy się nie zgadzają, a osoba z odczytu stoi w tym samym
    bloku PDF (tabela złapała słowo kompetencji spoza słownika), wiersz dostaje
    nazwisko z odczytu — żeby propozycja wskazała właściwą osobę — ale idzie do
    człowieka. Stawka i okres zawsze pochodzą z tabeli.

    Osoba z odczytu modelu bez odczytanego wiersza w tabeli (wiersz, którego
    liczb reguła nie rozpoznała — także druga pozycja tej samej osoby) zostaje
    w wynikach jako niepewna: zapis zamówienia bez niej byłby cichą utratą
    pozycji. Pominięte jest wyłącznie powtórzenie z IDENTYCZNĄ stawką i okresem.
    """
    confirmed: list[_Confirmed] = []
    used: set[int] = set()
    for table_row in table.rows:
        item = _Confirmed(
            row=_row_from_table(table_row),
            name_concerns=[table_row.name_problem] if table_row.name_problem else [],
            value_concerns=table_row.value_problems,
        )
        if reading_state == _READING_LEGACY:
            item.name_concerns.append(
                f"„{table_row.label}”: odczyt zapisany przed zmianą reguły Aliora nie "
                "potwierdza osób z tabeli — sprawdź osobę, okres i stawkę"
            )
        elif reading_state == _READING_MODEL:
            exact = [
                i
                for i, model in enumerate(reading)
                if i not in used
                and table_row.name
                and _names_exactly_equivalent(
                    _clean_model_name(model.consultant_name), table_row.name
                )
            ]
            loose = (
                []
                if exact
                else [
                    i
                    for i, model in enumerate(reading)
                    if i not in used
                    and _contains_person(
                        table_row.block_text, _clean_model_name(model.consultant_name)
                    )
                ]
            )
            if exact or len(loose) == 1:
                index = (exact or loose)[0]
                used.add(index)
                model = reading[index]
                if not exact:
                    model_name = _clean_model_name(model.consultant_name)
                    item.name_concerns = [
                        f"Imię i nazwisko w tabeli PDF odczytano jako „{table_row.label}”, "
                        f"a odczyt modelu wskazuje „{model_name}” — potwierdź osobę"
                    ]
                    item.row.consultant_name = model_name
                item.value_concerns = item.value_concerns + _cross_check(
                    item.row, model, doc_period
                )
            else:
                item.name_concerns.append(
                    f"„{table_row.label}”: osoby z tabeli nie potwierdził "
                    "odczyt modelu — sprawdź imię i nazwisko"
                )
        item.name_concerns = list(dict.fromkeys(item.name_concerns))
        item.value_concerns = list(dict.fromkeys(item.value_concerns))
        problems = item.name_concerns + item.value_concerns
        item.row.uncertain = bool(problems)
        item.row.uncertain_reason = "; ".join(problems) or None
        confirmed.append(item)

    extras: list[str] = []
    if reading_state != _READING_MODEL:
        return confirmed, extras
    for i, model in enumerate(reading):
        if i in used:
            continue
        name = _clean_model_name(model.consultant_name)
        twin = next(
            (
                item.row
                for item in confirmed
                if _names_exactly_equivalent(name, item.row.consultant_name)
            ),
            None,
        )
        if twin is not None and _repeats(model, twin, doc_period):
            continue
        concern = (
            f"„{name}”: pozycja z odczytu modelu nie ma odczytanego wiersza "
            "w tabeli Konsultantów PDF — sprawdź"
        )
        extras.append(concern)
        extra = _fallback_row(model)
        extra.consultant_name = name
        extra.uncertain = True
        extra.uncertain_reason = concern
        confirmed.append(_Confirmed(row=extra, name_concerns=[concern]))
    return confirmed, extras


_READING_MODEL = "model"
_READING_NONE = "none"
_READING_LEGACY = "legacy"


def _model_reading(
    result: OrderExtraction, document_text: str, *, reapplied: bool
) -> tuple[list[ConsultantOrderRow], str]:
    """Niezależny odczyt osób przez model i jego status.

    * ``model_rows`` zachowane przy pierwszym zastosowaniu reguły — to jest
      odczyt, z którym porównuje się tabelę także przy „Przelicz plan";
    * świeży odczyt (mail, formularz): ``consultant_rows`` prosto od modelu;
    * „Przelicz plan" na zapisie sprzed tej reguły: ``consultant_rows`` bywa
      tabelą starej reguły, nie modelem — ufamy im tylko, gdy stary wzorzec
      wiersza nie trafia w dokument (stara reguła nie mogła ich podstawić).

    Odczyt awaryjny (bez modelu) nie ma czym potwierdzać — takie wyniki
    zatrzymuje bramka automatu (``source != "claude"``).
    """
    if result.source != "claude":
        return list(result.model_rows or []), _READING_NONE
    if result.model_rows is not None:
        return list(result.model_rows), _READING_MODEL
    rows = [replace(row) for row in result.consultant_rows]
    if reapplied and any(
        _LEGACY_ROW_RE.match(line.strip()) for line in document_text.splitlines()
    ):
        return [], _READING_LEGACY
    return rows, _READING_MODEL


def _keeps_model_concern(part: str) -> bool:
    folded = fold(part)
    if _IGNORED_TOPIC_RE.search(folded):
        return False
    if _HARD_PROBLEM_RE.search(folded):
        return True
    return not _RESOLVED_TOPIC_RE.search(folded)


def _fallback_row(model: ConsultantOrderRow) -> ConsultantOrderRow:
    """Wiersz modelu, gdy tabeli nie rozpoznano — bez pól pomijanych i bez VAT."""
    row = replace(model, md_total=None)
    if row.rate_client_gross is not None:
        row.rate_client, row.rate_client_gross = row.rate_client_gross, None
    if row.rate_client is not None and row.rate_unit is None:
        row.rate_unit = RATE_UNIT
    if row.uncertain_reason:
        kept = [
            part
            for part in _concern_parts(row.uncertain_reason)
            if _keeps_model_concern(part)
        ]
        row.uncertain_reason = "; ".join(kept) or None
        row.uncertain = bool(kept)
    return row


# ── Pola dokumentu ───────────────────────────────────────────────────────────


def _clear_rate(result: OrderExtraction) -> None:
    """Bez stawki dokumentu; jednostka zostaje — MD to reguła klienta, nie odczyt."""
    clear_field(result, "rate_client")
    # Runda 7 (N4): kwota brutto ze starego odczytu wróciłaby w
    # ``apply_rate_rules`` jako stawka mimo powodu „wpisz ręcznie”.
    clear_field(result, "rate_client_gross")
    set_field(result, "rate_unit", RATE_UNIT)
    result.consultant_rate_matched = False


def _set_rate(result: OrderExtraction, rate: Decimal) -> None:
    clear_field(result, "rate_client_gross")
    set_field(result, "rate_client", rate)
    set_field(result, "rate_unit", RATE_UNIT)
    result.consultant_rate_matched = True


def _set_period(
    result: OrderExtraction, start: Optional[str], end: Optional[str]
) -> None:
    for name, value in (("start_date", start), ("end_date", end)):
        if value:
            set_field(result, name, value)
        else:
            clear_field(result, name)


def _apply_target(
    result: OrderExtraction,
    table: _Table,
    confirmed: list[_Confirmed],
    target: str,
    given_names: Optional[str],
    doc_period: tuple[Optional[str], Optional[str]],
) -> list[str]:
    """Pola formularza jednej osoby (Uzupełnij / Przedłuż / Nowe zamówienie).

    Tożsamość rozstrzyga kanoniczne imię i nazwisko z bazy znalezione w bloku
    wiersza PDF — deterministycznie, bez modelu. Stawka i okres z tego wiersza.
    """
    doc_start, doc_end = doc_period
    _clear_rate(result)
    if not table.rows:
        # Tabeli nie rozpoznano: wspólny, fail-closed matcher na wierszach modelu.
        before, result.uncertain_reasons = result.uncertain_reasons, []
        apply_consultant_row_match(
            result,
            target,
            consultant_given_names=given_names,
            rate_unit_default=RATE_UNIT,
        )
        added, result.uncertain_reasons = result.uncertain_reasons, before
        _set_period(result, doc_start, doc_end)
        return added
    # Wspólny, ścisły matcher osoby (imiona dokładnie, ta sama liczba członów,
    # najwyżej jedna przestawka): „Anna Nowak" nie jest „Anną Nowak-Kowalską",
    # a „Piotr Nowak" — „Janem Piotrem Nowakiem". Kandydat to nazwisko z tabeli
    # albo — gdy tabela złapała słowo kompetencji — nazwisko z odczytu modelu.
    hits = [
        i
        for i, row in enumerate(table.rows)
        if any(
            _name_match_score(target, name, consultant_given_names=given_names)
            is not None
            for name in {row.name, confirmed[i].row.consultant_name}
            if name
        )
    ]
    if len(hits) != 1:
        _set_period(result, doc_start, doc_end)
        if hits:
            return [
                f"Więcej niż jedna pozycja w tabeli Konsultantów pasuje do „{target}” "
                "— stawka wymaga ręcznej weryfikacji"
            ]
        return [
            f"Nie znaleziono pozycji konsultanta „{target}” w tabeli Konsultantów "
            "— stawkę wpisz ręcznie"
        ]
    row = table.rows[hits[0]]
    if row.rate is not None and row.rate_problem is None:
        _set_rate(result, row.rate)
    _set_period(result, row.start_date or doc_start, row.end_date or doc_end)
    return list(confirmed[hits[0]].value_concerns)


def _apply_document_fields(
    result: OrderExtraction,
    table: _Table,
    rows: list[ConsultantOrderRow],
    doc_period: tuple[Optional[str], Optional[str]],
) -> None:
    """Pola dokumentu bez wskazanej osoby (ścieżka mailowa, nowe zamówienie)."""
    doc_start, doc_end = doc_period
    if len(rows) == 1 and len(table.rows) == 1:
        if table.rows[0].rate is not None and table.rows[0].rate_problem is None:
            _set_rate(result, table.rows[0].rate)
        else:
            _clear_rate(result)
        _set_period(
            result, rows[0].start_date or doc_start, rows[0].end_date or doc_end
        )
        return
    _clear_rate(result)
    periods = {(row.start_date, row.end_date) for row in rows}
    common = next(iter(periods)) if len(periods) == 1 else (None, None)
    _set_period(result, doc_start or common[0], doc_end or common[1])


def _clear_ignored_fields(result: OrderExtraction) -> None:
    """Liczba Roboczodni, Total, stawka MD i ID konsultanta nie wpływają na zamówienie."""
    for name in ("md_total", "total_value", "rate_client_md", "consultant_ref"):
        clear_field(result, name)
    result.consultant_md_matched = False


# ── Polityka ─────────────────────────────────────────────────────────────────


def apply_alior_order_policy(
    result: OrderExtraction,
    document_text: str,
    *,
    target_consultant: Optional[str] = None,
    target_given_names: Optional[str] = None,
    reapplied: bool = False,
) -> OrderExtraction:
    """Cztery pola z tabeli + numer; powody wyłącznie z tych pól.

    Działa tak samo na świeżym odczycie (mail, formularze) i na zapisanym
    (``Przelicz plan``, ``reapplied=True``). Tabelę zawsze porównuje z tym samym
    niezależnym odczytem modelu (``model_rows``), a powody buduje od zera — więc
    ponowne zastosowanie daje ten sam wynik i niczego nie „potwierdza" samym
    sobą. Wolny tekst modelu o polach pomijanych (marża, Total, Roboczodni)
    i o VAT nie przechodzi.
    """
    table = _parse_table(document_text)
    reading, reading_state = _model_reading(result, document_text, reapplied=reapplied)
    result.model_rows = [replace(row) for row in reading]
    reasons: list[str] = []

    number = order_number(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
    else:
        clear_field(result, "title")
        result.title_needs_review = True
        reasons.append(REASON_NO_NUMBER)

    _clear_ignored_fields(result)
    doc_period = document_period(document_text)
    doc_start, doc_end = doc_period

    confirmed: list[_Confirmed] = []
    extras: list[str] = []
    if table.rows:
        confirmed, extras = _confirm_rows(
            table, reading, reading_state=reading_state, doc_period=doc_period
        )
        rows = [item.row for item in confirmed]
        result.currency = "PLN"
    else:
        rows = [_fallback_row(model) for model in reading]
    result.consultant_rows = rows

    if target_consultant:
        if not table.rows:
            reasons.append(REASON_NO_TABLE)
        reasons.extend(
            _apply_target(
                result,
                table,
                confirmed,
                target_consultant,
                target_given_names,
                doc_period,
            )
        )
        periods = [(result.start_date, result.end_date)]
    else:
        if table.rows:
            for item in confirmed[: len(table.rows)]:
                reasons.extend(item.name_concerns + item.value_concerns)
            reasons.extend(extras)
        else:
            reasons.append(REASON_NO_TABLE)
            reasons.extend(
                f"„{row.consultant_name}”: {row.uncertain_reason}"
                for row in rows
                if row.uncertain and row.uncertain_reason
            )
        _apply_document_fields(result, table, rows, doc_period)
        periods = [
            (row.start_date or doc_start, row.end_date or doc_end) for row in rows
        ] or [(doc_start, doc_end)]
    if any(not (start and end) for start, end in periods):
        reasons.append(REASON_NO_PERIOD)
    reversed_period = next(
        ((start, end) for start, end in periods if start and end and start > end),
        None,
    )
    if reversed_period:
        # Zakres w nawiasie jest sprawdzany przy odczycie wiersza; tu zostaje
        # okres z pól dokumentu („Moment wejścia w życie" / „czas oznaczony").
        reasons.append(
            f"Okres zamówienia jest odwrócony ({reversed_period[0]} – "
            f"{reversed_period[1]}) — sprawdź daty w dokumencie"
        )

    result.uncertain_reasons = list(dict.fromkeys(reasons))
    result.uncertain = bool(result.uncertain_reasons)
    return apply_rate_rules(result, document_text)


def table_marks_gross(text: str) -> bool:
    """Jawne „brutto" w tabeli Konsultantów: nagłówek kolumn albo wiersz osoby.

    Stopka „Razem PLN" (suma, czyli pomijany Total) i tekst między wierszami
    (stopka/nagłówek kolejnej strony) nie mówią nic o stawce.
    """
    return "brutto" in fold(_parse_table(text).region_text)


def apply_rate_rules(result: OrderExtraction, document_text: str) -> OrderExtraction:
    """Alior: stawka jest netto z definicji; jawne „brutto" → do weryfikacji.

    Zastępuje u Aliora uniwersalne rozpoznanie brutto/netto
    (``apply_document_rate_kind``): brak oznaczenia przy kwocie nie jest
    niepewnością, a kwota nigdy nie jest dzielona przez 1,23. Idempotentne —
    także na odczycie zapisanym przed tą regułą: wcześniejsze ÷ 1,23 jest
    cofane do kwoty z PDF-a, a powody „nie ustalono, czy brutto czy netto"
    znikają.
    """
    for item in [result, *result.consultant_rows]:
        if item.rate_client_gross is not None:
            item.rate_client, item.rate_client_gross = item.rate_client_gross, None
    result.confidence.pop("rate_client_gross", None)
    for row in result.consultant_rows:
        if row.uncertain_reason:
            kept = [
                part
                for part in _concern_parts(row.uncertain_reason)
                if not _is_rate_conversion_reason(part)
            ]
            row.uncertain_reason = "; ".join(kept) or None
            row.uncertain = bool(kept)
    result.uncertain_reasons = [
        reason
        for reason in result.uncertain_reasons
        if not _is_rate_conversion_reason(reason)
    ]
    rated = [row for row in result.consultant_rows if row.rate_client is not None]
    if (rated or result.rate_client is not None) and table_marks_gross(document_text):
        result.uncertain_reasons.append(REASON_GROSS)
        for row in rated:
            row.uncertain = True
            row.uncertain_reason = "; ".join(
                filter(None, [row.uncertain_reason, REASON_GROSS])
            )
    result.uncertain = bool(result.uncertain_reasons)
    return result
