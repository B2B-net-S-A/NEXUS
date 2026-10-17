"""Kwoty, stawki i dostępność w wolnym tekście notatek.

Jeden wzorzec kwoty dla QC CV (poprawki AI, edytor) i dla materiału, który
idzie do modelu generatora CV. Notatka „150 PLN/h + VAT, dostępny 06.03.2023”
nie jest treścią CV: stawka to ustalenie handlowe, a dostępność widzi klient
tylko z profilu (audyt 13.10.2026: taka notatka szła do promptu generatora).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

RATE_WORD_RE = re.compile(r"stawk|\brate\b|wynagrodz|salary|zarobk", re.IGNORECASE)

# Kwota pieniędzy, ściślej niż luźne „liczba + waluta”, które bierze
# „3 europejskich” i „5 złożonych” za euro i złote. Ciąg cyfr zaborczo
# (`*+`): po nim stoi waluta albo „/”, więc oddawanie znaków niczego nie
# zmienia, a na „1  1  1…” wracało kwadratowo (17.10.2026). Szukaj przez
# `money_matches` — `finditer` próbuje od każdej cyfry ciągu.
MONEY_RE = re.compile(
    r"\d[\d\s.,]*+\s*(?:(?:tys|mln)\b\.?\s*|k\s*)?(?:zł|zl|pln|euro|eur|usd|€|\$)(?!\w)"
    r"(?:\s*/\s*(?:h|godz|md|dzie[nń]|mies)\w*)?"
    r"|[€$]\s*\d[\d\s.,]*\d|[€$]\s*\d"
    r"|\d[\d\s.,]*+\s*/\s*(?:h|godz|md)\b",
    re.IGNORECASE,
)
_MONEY_START_RE = re.compile(r"[€$\d]")
_NUMBER_RUN_RE = re.compile(r"[\d\s.,]*+")

# Kwota za czas pracy („150 PLN/h”, „1200 zł/md”, „160/h”) — to zawsze stawka,
# także bez słowa „stawka” obok.
_PER_TIME_RE = re.compile(r"/\s*(?:h|godz|md|dzie[nń]|mies)", re.IGNORECASE)

# Liczba bez waluty zaraz po słowie o pieniądzach: „stawka 150 B2B”, „rate
# 140”, „Wynagrodzenie: 18 000”, „zarabia 18k”, „Widełki 20-25k” (audyt
# 13.10.2026: przechodziły do generatora). Między słowem a liczbą najwyżej
# dwukropek albo „ok.”, „około”, „to”; procent i jednostka czasu albo skali
# odpadają — „success rate 95%” i „rate limiting 1000 req/s” to fakty.
# Końcówka słowa najwyżej 40 znaków, odstępy po nim zaborczo: `\w*` i dwa
# `\s*` wracały kwadratowo na sklejonym słowie i ciągu spacji (17.10.2026).
# Dłuższej końcówki nie ma żadne słowo; dopasowania są te same co z `\w*`.
_BARE_AMOUNT_RE = re.compile(
    r"\b(?:staw[kc]\w{0,40}|rate\b|wynagrodz\w{0,40}|salary|zarobk\w{0,40}"
    r"|zarabia\w{0,40}|earns?\b|wide[lł]k\w{0,40}|pensj\w{0,40})"
    r"\s*+[:=]?+\s*+(?:(?:ok\.?|około|okolo|to|of|at|about|is|was|wynosi\w*|min\.?"
    r"|max\.?|~)\s*)*"
    r"\d+(?:[\s.,]\d+)*(?:\s*[-–]\s*\d+(?:[\s.,]\d+)*)?\s*(?:k|tys\.?)?(?![\w%])"
    r"(?!\s*(?:%|proc|lat\b|lata|rok|roku|years?|months?|mies|tyg|weeks?|dni|days?"
    r"|godz|hours?|os[oó]b|people|users|req|rps|ms\b))",
    re.IGNORECASE,
)

_MONTH = (
    r"(?:stycz|lut|mar|kwie|maj|czerw|lip|sierp|wrze|paźdz|pazdz|listop|grud"
    r"|jan|feb|apr|may|jun|jul|aug|sep|oct|nov|dec)"
)
# Kiedy kandydat może zacząć: „od zaraz”, „od 1.11”, „od listopada”, „za 2
# tygodnie”, „06.03.2023”, „15 listopada”. Gołej liczby tu nie ma —
# „dostępność 99,95%” i „dostępny 24/7” mówią o systemie (audyt 13.10.2026).
_WHEN = (
    r"od\s+(?:zaraz|razu|ręki|jutra|teraz|now|\d|początk|poniedział|przyszł"
    r"|nowego|" + _MONTH + r")|zaraz|natychmiast|asap"
    r"|za\s+(?:\d|miesiąc|tydzień|dwa|trzy|kilka)"
    r"|\d{1,2}\.\d{1,2}(?!\d|\s*%)|\d{1,2}\s+" + _MONTH + r"|\d+\s*(?:dni|tyg|mies)"
    r"|w\s+ciągu|po\s+(?:okresie|wypowiedz|zakończ)"
)
# Dostępność kandydata, nie systemu: „Kandydat dostępny od 1.11”, „dostępna
# 06.03.2023”, „od zaraz”, „1 miesiąc wypowiedzenia”, „Notice: 1 month”,
# „Can start in 2 weeks”, „Start: od 1.11”. „API dostępne w chmurze”,
# „aplikacja dostępna na iOS”, „System jest dostępny 24/7” i „dostępność
# systemu 99,9%” zostają.
_AVAILABILITY_RE = re.compile(
    r"\b(?:kandydat\w*|pan|pani)\s+(?:jest\s+|będzie\s+|bedzie\s+)?dostępn"
    r"|\bdostępn\w*\s+(?:" + _WHEN + r")"
    r"|\bdostępność\s*:"
    r"|\bwypowiedzeni\w*"
    r"|\bstart(?:u|em)?\s*(?::|" + _WHEN + r")"
    r"|\bgotow\w*\s+do\s+(?:startu|rozpocz|zmiany|pracy\s+od)"
    r"|\b(?:może|moze|mógłby|mogłaby|mogłby)\s+(?:zacząć|zaczac|rozpocząć|rozpoczac"
    r"|wystartować|dołączyć|dolaczyc)"
    r"|\brozpocz\w*\s+(?:pracy\s+|współpracy\s+)?(?:" + _WHEN + r")"
    r"|\bavailable\s+(?:from\s+(?:\d|now|" + _MONTH + r")|immediately|now"
    r"|in\s+\d|within)"
    r"|\b(?:is|will\s+be|candidate)\s+available"
    r"|\bavailability\s*:"
    r"|\bnotice\s+period|\bnotice\s*:|(?<!\d)\d+\s*(?:months?|weeks?)\s*(?:of\s+)?notice"
    r"|\b(?:can|could|will|able\s+to|ready\s+to)\s+start\b"
    r"|\bstart\s+(?:asap|immediately|now|right\s+away|in\s+\d|within"
    r"|from\s+(?:\d|now|" + _MONTH + r"))",
    re.IGNORECASE,
)

# Pieniądze kandydata w notatce bez słowa „stawka”: „Oczekuje 22k netto”,
# „Ma ofertę za 200 PLN dziennie”. Tylko dla materiału generatora — QC czyta
# ``is_rate_text`` i tej listy nie dostaje.
_CANDIDATE_MONEY_WORD_RE = re.compile(
    r"oczekiw\w*|expectation\w*|\bexpects?\b|\bnetto\b|\bbrutto\b", re.IGNORECASE
)
# Kwota, której kandydat chce, albo kwota przy formie umowy: „chce 22k”,
# „chce 150 na B2B”, „150 B2B”. „Pracuje od 3 lat na B2B” zostaje.
_WANTED_AMOUNT_RE = re.compile(
    r"\b(?:chc\w*|wants?|asks?\s+for|asking\s+for)\s+(?:min\.?\s*|około\s+|ok\.?\s*)?"
    r"\d+(?:[\s.,]\d+)*\s*(?:k\b|tys|(?:zł\s*)?(?:na\s+)?(?:b2b|uop)\b|netto|brutto)",
    re.IGNORECASE,
)
# Kwota przy formie umowy bez słowa „chce” („150 B2B”) — przez
# `_has_contract_amount`, bo `search` próbował od każdej liczby ciągu „1 1 1…”.
_CONTRACT_AMOUNT_RE = re.compile(
    r"\d+(?:[\s.,]\d+)*\s*(?:k|tys\.?)?\s*(?:na\s+)?(?:b2b|uop)\b", re.IGNORECASE
)
_CONTRACT_START_RE = re.compile(r"\b\d")
_DIGIT_CHAIN_RE = re.compile(r"\d++(?:[\s.,]\d++)*+")
# Budżet albo wartość projektu to fakt z CV: „Zarządzał budżetem 2 mln PLN”,
# „Prowadził projekt wart 5 mln PLN”.
_PROJECT_BUDGET_RE = re.compile(
    r"bud[żz]e(?:t|c)\w*\s+(?:projekt|o\s+warto|\d)|projekt\w*\s+o\s+bud[żz]ec"
    r"|zarządza\w*\s+bud[żz]et|(?:project|managed\s+(?:a\s+)?)\s*budget"
    r"|(?:projekt|wdroże|program|przetarg|project)\w*"
    r"\s+(?:\w+\s+)?(?:wart\w*|o\s+wartości|worth|valued)",
    re.IGNORECASE,
)


# Granice fragmentu: przecinek albo średnik ze spacją, kropka kończąca zdanie,
# nowa linia. „1,5 roku” i „06.03.2023” nie są granicą.
_SEGMENT_END_RE = re.compile(r"(?<=[,;])\s+|(?<=\.)\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ\d])|\n")


def money_matches(text: str | None) -> Iterator[re.Match[str]]:
    """Dopasowania `MONEY_RE` jak `finditer`, ale w czasie liniowym.

    Kwota zaczyna się na „€”/„$” albo na pierwszej cyfrze ciągu cyfr,
    odstępów, kropek i przecinków: od późniejszej cyfry tego ciągu dopasowanie
    sięgałoby tego samego końca ciągu, więc jest to samo albo żadne. Po
    nieudanej próbie reszta ciągu jest pomijana.
    """
    text = text or ""
    pos = 0
    while (start := _MONEY_START_RE.search(text, pos)) is not None:
        at = start.start()
        match = MONEY_RE.match(text, at)
        if match is not None:
            yield match
            pos = match.end()
        elif text[at].isdigit():
            pos = _NUMBER_RUN_RE.match(text, at).end()
        else:
            pos = at + 1


def _has_contract_amount(text: str) -> bool:
    """`\\b` + `_CONTRACT_AMOUNT_RE.search` w czasie liniowym: po nieudanej
    próbie od liczby na granicy słowa reszta ciągu liczb („1 2 3”, „1.2.3”) jest
    pomijana — od każdej następnej liczby tego ciągu wynik byłby ten sam."""
    pos = 0
    while (start := _CONTRACT_START_RE.search(text, pos)) is not None:
        at = start.start()
        if _CONTRACT_AMOUNT_RE.match(text, at):
            return True
        pos = _DIGIT_CHAIN_RE.match(text, at).end()
    return False


def is_rate_text(text: str) -> bool:
    """Czy fragment mówi o stawce: kwota za czas albo kwota przy słowie „stawka”
    (z walutą albo bez: „stawka 150 B2B”, „rate 140”)."""
    text = text or ""
    if _BARE_AMOUNT_RE.search(text):
        return True
    rate_word: bool | None = None
    for match in money_matches(text):
        if _PER_TIME_RE.search(match.group()):
            return True
        # Słowo szukane raz na tekst, nie raz na kwotę (kwadratowo przy wielu
        # kwotach bez słowa „stawka”).
        if rate_word is None:
            rate_word = RATE_WORD_RE.search(text) is not None
        if rate_word:
            return True
    return False


# Liczba bez waluty po słowie o pieniądzach jest stawką w CV tylko na końcu
# zdania albo przed formą rozliczenia: „Stawka: 150”, „Rate 140”, „Stawka 150
# B2B”, „Stawka 150 za godzinę”, „Stawka 150 + VAT”. Dalej stoi treść CV —
# „Naliczanie wynagrodzeń 300 pracowników”, „System wynagrodzeń 2.0 w SAP”.
_CV_BARE_TAIL_RE = re.compile(
    r"[^\S\n]*+(?:$|\n|[.,;:!?)\]]|/|\+\s*vat\b"
    r"|(?:b2b|uop|netto|brutto|net|gross|vat|zł|zl|pln|eur|euro|usd)(?!\w)"
    r"|(?:za|per|na)\s+(?:godz|h\b|hour|dzie|dni|day|md|mies|month|b2b|uop|fakt|rę|re))",
    re.IGNORECASE,
)
# Kwoty z walutą szukamy w oknie wokół słowa o pieniądzach: wzorzec kwoty
# wraca kwadratowo na długim ciągu cyfr bez waluty, a stawka stoi przy słowie.
_CV_RATE_WINDOW = 80
_BUDGET_BEFORE = 40


def is_cv_rate_text(text: str) -> bool:
    """Czy zdanie CV mówi o stawce — ściślej niż ``is_rate_text`` z notatek.

    W CV słowa „wynagrodzenie”, „stawka” i „rate” bywają dziedziną pracy
    (moduł płacowy, „error rate”), a w notatce o kandydacie prawie zawsze są
    jego pieniędzmi. Stawka w CV to: kwota za czas („150 zł/h”), kwota z walutą
    przy słowie o pieniądzach — chyba że to budżet projektu („o budżecie 2 mln
    PLN”) — albo liczba bez waluty po takim słowie na końcu zdania lub przed
    formą rozliczenia (`_CV_BARE_TAIL_RE`). Jedna reguła dla uwagi QC „Stawka
    w CV” i dla „Usuń stawkę” w edytorze.
    """
    text = text or ""
    for match in _BARE_AMOUNT_RE.finditer(text):
        if _CV_BARE_TAIL_RE.match(text, match.end()):
            return True
    for word in RATE_WORD_RE.finditer(text):
        start = max(0, word.start() - _CV_RATE_WINDOW)
        window = text[start : word.end() + _CV_RATE_WINDOW]
        for money in MONEY_RE.finditer(window):
            if _PER_TIME_RE.search(money.group()):
                return True
            before = window[max(0, money.start() - _BUDGET_BEFORE) : money.end()]
            if not _PROJECT_BUDGET_RE.search(before):
                return True
    return False


def _is_candidate_money(part: str) -> bool:
    if (
        is_rate_text(part)
        or _WANTED_AMOUNT_RE.search(part)
        or _has_contract_amount(part)
    ):
        return True
    if _PROJECT_BUDGET_RE.search(part):
        return False
    return next(money_matches(part), None) is not None or bool(
        re.search(r"\d", part) and _CANDIDATE_MONEY_WORD_RE.search(part)
    )


def strip_rates_and_availability(text: str | None) -> str:
    """Tekst bez fragmentów o pieniądzach i dostępności kandydata.

    W notatce o kandydacie każda kwota (poza budżetem projektu) to ustalenie
    handlowe: stawka, oczekiwania, cudza oferta. Usuwa cały fragment (do
    przecinka, średnika, końca zdania albo linii), bo sama kwota bez niego
    zostawiałaby „+ VAT, B2B” albo datę bez kontekstu.
    """
    if not text:
        return ""
    lines: list[str] = []
    for line in text.split("\n"):
        kept = [
            part
            for part in _SEGMENT_END_RE.split(line)
            if part.strip()
            and not _is_candidate_money(part)
            and not _AVAILABILITY_RE.search(part)
        ]
        joined = " ".join(p.strip() for p in kept).strip()
        if joined or not line.strip():
            lines.append(joined)
    return "\n".join(lines).strip()
