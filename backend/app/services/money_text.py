"""Kwoty, stawki i dostępność w wolnym tekście notatek.

Jeden wzorzec kwoty dla QC CV (poprawki AI, edytor) i dla materiału, który
idzie do modelu generatora CV. Notatka „150 PLN/h + VAT, dostępny 06.03.2023”
nie jest treścią CV: stawka to ustalenie handlowe, a dostępność widzi klient
tylko z profilu (audyt 13.10.2026: taka notatka szła do promptu generatora).
"""

from __future__ import annotations

import re

RATE_WORD_RE = re.compile(r"stawk|\brate\b|wynagrodz|salary|zarobk", re.IGNORECASE)

# Kwota pieniędzy, ściślej niż luźne „liczba + waluta”, które bierze
# „3 europejskich” i „5 złożonych” za euro i złote.
MONEY_RE = re.compile(
    r"\d[\d\s.,]*\s*(?:(?:tys|mln)\b\.?\s*|k\s*)?(?:zł|zl|pln|euro|eur|usd|€|\$)(?!\w)"
    r"(?:\s*/\s*(?:h|godz|md|dzie[nń]|mies)\w*)?"
    r"|[€$]\s*\d[\d\s.,]*\d|[€$]\s*\d"
    r"|\d[\d\s.,]*\s*/\s*(?:h|godz|md)\b",
    re.IGNORECASE,
)

# Kwota za czas pracy („150 PLN/h”, „1200 zł/md”, „160/h”) — to zawsze stawka,
# także bez słowa „stawka” obok.
_PER_TIME_RE = re.compile(r"/\s*(?:h|godz|md|dzie[nń]|mies)", re.IGNORECASE)

# Liczba bez waluty zaraz po słowie o pieniądzach: „stawka 150 B2B”, „rate
# 140”, „Wynagrodzenie: 18 000”, „zarabia 18k”, „Widełki 20-25k” (audyt
# 13.10.2026: przechodziły do generatora). Między słowem a liczbą najwyżej
# dwukropek albo „ok.”, „około”, „to”; procent i jednostka czasu albo skali
# odpadają — „success rate 95%” i „rate limiting 1000 req/s” to fakty.
_BARE_AMOUNT_RE = re.compile(
    r"\b(?:staw[kc]\w*|rate\b|wynagrodz\w*|salary|zarobk\w*|zarabia\w*|earns?\b"
    r"|wide[lł]k\w*|pensj\w*)"
    r"\s*[:=]?\s*(?:(?:ok\.?|około|okolo|to|of|at|about|is|was|wynosi\w*|min\.?"
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
    r"|\bnotice\s+period|\bnotice\s*:|\d+\s*(?:months?|weeks?)\s*(?:of\s+)?notice"
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
    r"\d+(?:[\s.,]\d+)*\s*(?:k\b|tys|(?:zł\s*)?(?:na\s+)?(?:b2b|uop)\b|netto|brutto)"
    r"|\b\d+(?:[\s.,]\d+)*\s*(?:k|tys\.?)?\s*(?:na\s+)?(?:b2b|uop)\b",
    re.IGNORECASE,
)
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


def is_rate_text(text: str) -> bool:
    """Czy fragment mówi o stawce: kwota za czas albo kwota przy słowie „stawka”
    (z walutą albo bez: „stawka 150 B2B”, „rate 140”)."""
    if _BARE_AMOUNT_RE.search(text or ""):
        return True
    for match in MONEY_RE.finditer(text or ""):
        if _PER_TIME_RE.search(match.group()) or RATE_WORD_RE.search(text):
            return True
    return False


def _is_candidate_money(part: str) -> bool:
    if is_rate_text(part) or _WANTED_AMOUNT_RE.search(part):
        return True
    if _PROJECT_BUDGET_RE.search(part):
        return False
    return bool(MONEY_RE.search(part)) or bool(
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
