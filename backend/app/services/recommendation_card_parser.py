"""Odczyt „karty rekomendacji” z notatki rekrutera — czysta reguła, bez AI.

Rekruterzy wpisują kartę jako wolny tekst z etykietami („Stawka: 135”,
„Dostępność: ASAP”, „P1: … Odpowiedź: …”), głównie w Traffit (pomiar
03.10.2026: 10 115 notatek rodzaju ``card``, ok. 640 nowych miesięcznie).
Ten moduł zamienia taką notatkę na pola. Niczego nie zapisuje i nie zna bazy
— wynik jest zwykłym słownikiem, gotowym do JSONB.

Zasady:

* Etykiety rozpoznaje słownik wariantów (stary i nowy wzór działu). Wartość
  pola to tekst od etykiety do następnej etykiety; pola jednowierszowe biorą
  pierwszy niepusty wiersz.
* Wartość surowa (``raw``) zostaje zawsze. Wartość znormalizowana powstaje
  tylko wtedy, gdy da się ją odczytać bez zgadywania: stawka poza zakresem
  godzinowym, kwota miesięczna albo inna waluta zostają samym ``raw``.
* E-mail, telefon i adres LinkedIn z karty są rozpoznawane wyłącznie po to,
  żeby nie wpadły do sąsiedniego pola: etykieta kontaktu kończy poprzednie
  pole, a sam adres albo numer jest wycinany z każdej wartości. Do wyniku nie
  trafiają.
* Narodowość jest polem karty dla klienta. Nie jest wejściem żadnego modelu
  ani dopasowania — pilnuje tego wołający.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Optional

PARSER_VERSION = 1

# Notatka jest kartą, gdy ma co najmniej tyle rozpoznanych etykiet pól.
MIN_LABELS = 2

_SCAN_CHARS = 20000
_LINE_VALUE_MAX = 300
_TEXT_VALUE_MAX = 6000

# Limit długości znacznika trzyma czas liniowy dla tekstu z samych „<p ”.
_BREAK_RE = re.compile(
    r"<br\b[^>]{0,1000}>"
    r"|</?(?:p|div|li|ul|ol|tr|table|h[1-6]|blockquote)\b[^>]{0,1000}>",
    re.I,
)
_TAG_RE = re.compile(r"<[^>]{1,2000}>")
_SPACES_RE = re.compile(r"[^\S\n]+")
_BULLET_RE = re.compile(r"^[\s·•*▪◦\-–]+")

# (klucz, wzorzec etykiety, czy myślnik na początku wiersza też jest separatorem)
_LABEL_DEFS: tuple[tuple[str, str, bool], ...] = (
    ("name", r"imi[eę] i nazwisko", True),
    (
        "rate",
        r"stawka(?: b2b| godzinowa)?|oczekiwana stawka|oczekiwania finansowe"
        r"|oczekiwania|finanse",
        True,
    ),
    ("availability", r"dost[eę]pno[sś][cć]|okres wypowiedzenia|availability", True),
    ("availability", r"dost", False),
    (
        "work_mode",
        r"(?:preferowany )?tryb pracy|forma pracy|model pracy|miejsce pracy"
        r"|cz[eę]stotliwo[sś][cć] pracy [zw] biur\w+(?: w tygodniu)?"
        r"|mo[zż]liwo[sś][cć] pracy z biura|praca z biura",
        True,
    ),
    ("work_mode", r"tryb", False),
    ("location", r"lokalizacja", True),
    ("location", r"lok", False),
    (
        "nationality",
        r"narodowo[sś][cć]|narodow[sś][cć]|nardowo[sś][cć]|obywatelstwo",
        True,
    ),
    (
        "worked_at_client",
        # Trzecia osoba („pracował”), nie pytanie screeningowe („pracowałeś”).
        r"(?:informacja,? )?czy (?:kandydat(?:ka)? )?"
        r"(?:pracowa[lł]a?|by[lł]a? konsultant\w*)"
        r"(?: ju[zż]| wcze[sś]niej| kiedy[sś])* (?:u|dla|w) [^:\n]{0,80}?",
        True,
    ),
    (
        "english",
        r"(?:j[eę]zyk |j\. ?)?angielski|poziom angielskiego"
        r"|znajomo[sś][cć] angielskiego|j[eę]zyki(?: obce)?|english",
        True,
    ),
    ("english", r"angl|ang\.?|eng", False),
    ("project", r"nazwa projektu|request|zapotrzebowanie", True),
    ("project", r"req\.?", False),
    ("cv_filename", r"nazwa pliku(?: cv)?", True),
    ("cv_filename", r"cv(?: upload)?", False),
    (
        "client_manager",
        r"imi[eę] i nazwisko (?:wcze[sś]niejszego )?(?:prze[lł]o[zż]onego|managera)",
        True,
    ),
    ("red_flags", r"red flags?|red flagi|czerwone flagi|ryzyka", False),
    (
        "recommendation",
        r"notatka|uwagi|notes?|rekomendacja|podsumowanie"
        r"|why consider this candidate|why the candidate is worth considering"
        r"|dlaczego warto \w+ wybra[cć]|dlaczego (?:ten )?kandydat",
        False,
    ),
    ("motivation", r"motywacja(?: do zmiany(?: pracy)?)?", True),
    ("motivation", r"mot", False),
    ("contract_form", r"forma wsp[oó][lł]pracy|forma zatrudnienia", True),
    (
        "_contact",
        r"(?:numer|nr) telefonu(?: i e-?mail)?"
        r"|(?:adres )?(?:e[^\S\n]?[-–]?[^\S\n]?)?ma?il(?: \w{1,20})?"
        r"|telefon(?: \w{1,20})?|tel\.?|phone(?: number)?|mobile|kom[oó]rka"
        r"|(?:dane )?kontakt(?:owe)?|linkedin|data urodzenia|pesel",
        True,
    ),
    (
        "_other",
        r"wymiar pracy|(?:odpowiedzi na )?pytania(?: z profilu championa)?"
        r"|stanowisko|czy (?:aktywnie )?szuka(?: pracy)?|rodzaj wcze[sś]niejszej umowy",
        True,
    ),
)

_NOT_WORD = r"(?<![\wąćęłńóśźż@])"
# Początek wiersza: punktor i numer pozycji („8. Oczekiwania finansowe – 140”).
_LINE_PREFIX = r"^[^\S\n]*(?:[·•*▪◦-][^\S\n]*)?(?:\d{1,2}[.)][^\S\n]*)?"
# Dopisek w nawiasie między etykietą a separatorem: „Uwagi (po angielsku):”.
_PAREN = r"(?:[^\S\n]*[(\[][^)\]\n]{0,90}[)\]])?"
_DASH = _PAREN + r"[^\S\n]*\.?[^\S\n]*[–—-]"
_COLON = _PAREN + r"[^\S\n]*\.?[^\S\n]*:"


def _label_patterns() -> tuple[tuple[str, "re.Pattern[str]"], ...]:
    patterns = []
    for key, pattern, dash in _LABEL_DEFS:
        body = "(?:" + pattern + ")"
        patterns.append((key, re.compile(_NOT_WORD + body + _COLON, re.I)))
        if dash:
            # Stary wzór: „Stawka. – 240 zł/h”, „Imię i nazwisko – …”.
            patterns.append((key, re.compile(_LINE_PREFIX + body + _DASH, re.I | re.M)))
    return tuple(patterns)


_FIELD_RE = _label_patterns() + (
    # „Czy pracował u Klienta? nie” — pytajnik zamiast dwukropka.
    (
        "worked_at_client",
        re.compile(
            _NOT_WORD
            + r"czy (?:kandydat(?:ka)? )?pracowa[lł]a?[^?:\n]{0,40}\?"
            + r"(?=[^\S\n]*[^\s:][^:\n]{0,40}$)",
            re.I | re.M,
        ),
    ),
)
# Nieznana pozycja listy „4. Technologia – Python” kończy poprzednie pole.
_OTHER_ITEM_RE = re.compile(
    r"^[^\S\n]*\d{1,2}[.)][^\S\n]*[^\n–—:-]{2,40}[^\S\n][–—-][^\S\n]", re.M
)
_QUESTION_RE = re.compile(
    _LINE_PREFIX
    + r"(?:(?:pytanie|pyt\.?|question)[^\S\n]*(?:([1-9])[^\S\n]*[:.)–-]?|():)"
    + r"|[pq][^\S\n]*([1-9])[^\S\n]*[:.)])",
    re.I | re.M,
)
_NUMBERED_RE = re.compile(r"^[^\S\n]*([1-9])[.)][^\S\n]+(?=\S)", re.M)
_ANSWER_RE = re.compile(
    _NOT_WORD + r"(?:odpowied[zź](?: kandydata)?|odp\.?|answer)[^\S\n]*:", re.I
)
# Pytanie wpisane bez pytajnika: „Opowiedz o projekcie…”, „PL: Oceń swój poziom…”.
_ASKING_RE = re.compile(
    r"(?:(?:pl|en)\s*:\s*)?(?:opowiedz|opisz|podaj|prosz[eę]|wymie[nń]|oce[nń]|jak\w*"
    r"|czy|co|ile|kiedy|dlaczego|z jak\w+|w jak\w+|tell|describe|what|how|which"
    r"|why|do you|have you|can you|please)\b",
    re.I,
)
_NUMBER_ONLY_RE = re.compile(r"^\d{1,2}[.)]?$")
# Kontakt wpisany bez etykiety. Ograniczone długości trzymają czas liniowy.
_EMAIL_RE = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,4}")
_PHONE_RE = re.compile(
    r"(?<![\w.,/-])(?:\+|00)?(?:48[ -]?)?\d{3}[ -]?\d{3}[ -]?\d{3}(?![.,/-]?\d)"
)
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/\S{0,200}", re.I)
_HAS_DIGIT_OR_LINK_RE = re.compile(r"\d{3}|linkedin\.com", re.I)
# Etykieta, która została po wycięciu numeru: „…wypowiedzeniaTel:”,
# „Numer telefonu i e-mail.”.
_CONTACT_TAIL_RE = re.compile(
    r"(?:\b|(?<=[^\W\d_])(?=[A-Z][a-z]))"
    r"(?i:(?:numer|nr)\.? tel\w*(?: i e-?mail)?|tel(?:efon)?|e-?ma(?:i?l)|mail|kontakt"
    r"|(?<![^\s;,])[tem])"
    r"[\s.:+]*$"
)
_EMPTY_PARENS_RE = re.compile(r"\(\s*\)")

_SINGLE_LINE = frozenset(
    {
        "name",
        "rate",
        "availability",
        "work_mode",
        "location",
        "nationality",
        "worked_at_client",
        "english",
        "cv_filename",
        "contract_form",
        "client_manager",
    }
)

_THOUSANDS_RE = re.compile(r"\d{1,3}[ .]\d{3}\b|\d+\s*(?:k|tys)\b", re.I)
# „35-40 tys.”, „35,5k” — znacznik tysięcy za ostatnią liczbą kwoty.
_THOUSANDS_SUFFIX_RE = re.compile(r"\s*(?:k|tys)\b", re.I)
_RATE_NUMBER = r"(?<![\d.,])(\d{2,3}(?:[.,]\d{1,2})?)(?!\d)"
_RATE_RE = re.compile(_RATE_NUMBER + r"(?:\s*[-–/]\s*" + _RATE_NUMBER + r")?")
_FOREIGN_RE = re.compile(r"eur|€|usd|\$|gbp|£|chf", re.I)
_MONTHLY_RE = re.compile(r"mies|/\s*mc|\bmc\b|/\s*m\b|brutto|uop|etat", re.I)
_DAILY_RE = re.compile(r"/\s*md|\bmd\b|dzie[nń]|dziennie|/\s*d\b", re.I)
_HOURLY_RE = re.compile(r"/\s*h\b|/\s*godz|[nz]a godz|godzinow", re.I)
# Jednostka stoi między kwotą a następną liczbą albo nawiasem.
_UNIT_WINDOW_END_RE = re.compile(r"[\d(]")
_UNIT_WINDOW_CHARS = 40
_HOURLY_MIN, _HOURLY_MAX = 30, 500

_ASAP_RE = re.compile(r"asap|od zaraz|natychmiast|od r[eę]ki|immediately", re.I)
_NOTICE_RE = re.compile(
    # „1.5 miesiąca” nie jest ani jednym, ani pięcioma miesiącami.
    r"(?<![\d.,])(\d{1,2})(?![.,]\d)\s*(?:[-–]\s*\d{1,2}\s*)?"
    r"(tyg|tydz|week|mies|msc|m-c|month|dni|dzie[nń]|day|mc\b|m\b)",
    re.I,
)
_WORD_NOTICE_RE = re.compile(
    r"\b(jeden|jedno|dwa|dw[oó]ch|dwu|trzy|trzech)\s*[- ]?\s*(tyg|tydz|mies)", re.I
)
_WORD_NUMBERS = {"je": 1, "dw": 2, "tr": 3}
# „1,5 miesiąca”, „półtora miesiąca” — zapisujemy w tygodniach (6).
_HALF_MONTH_RE = re.compile(
    r"(?<![\d.,])(?:(\d)[.,]5|p[oó][lł]tora)\s*(?:mies|msc|m-c|month)", re.I
)
_ONE_MONTH_RE = re.compile(r"miesi[aą]c|miesi[eę]czn", re.I)
_ONE_WEEK_RE = re.compile(r"tydzie[nń]|tygodniow", re.I)
# „koniec miesiąca”, „półtora miesiąca”, „1.5 miesiąca” — słowo „miesiąc”
# nie znaczy tu „jeden miesiąc wypowiedzenia”.
# Data dostępności stoi na początku („od 1.07”) albo po słowie o starcie
# („może zacząć od 15.09”); inna data w zdaniu to dopisek („do 17.08 urlop”,
# „13 października (28.10 wyjazd…)”).
_DATE_LEAD_CHARS = 12
_DATE_START_BEFORE_RE = re.compile(
    r"(?:\bod|\bfrom|\bstart\w*|\brozpocz\w+|\bzacz\w+)\s+(?:dnia\s+)?"
    r"(?:[^\W\d]+\s+)?$",
    re.I,
)
_DATE_NOT_START_AFTER_RE = re.compile(r"\s*(?:urlop|wyjazd|wakacj)", re.I)
_NOT_ONE_PERIOD_RE = re.compile(
    r"(?:\d|koniec|ko[nń]c\w{1,3}|pocz[aą]t\w{0,4}|po[lł]ow\w{1,3}|p[oó][lł]tor\w{1,2}"
    r"|p[oó][lł])\s*$",
    re.I,
)
_DATE_RE = re.compile(
    r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b"
    r"(?!\s*(?:mies|msc|m-c|tyg|tydz|dni|dnia|week|month))"
)

_REMOTE_RE = re.compile(r"zdaln|remote", re.I)
_HYBRID_RE = re.compile(r"hybryd|hybrid", re.I)
_ONSITE_RE = re.compile(r"stacjonarn|on-?site", re.I)
# „2,3 dni” to zakres jak „2-3 dni”; „2.5 dnia” i „12” nie są jedną cyfrą.
_DIGIT = r"(?<!\d)(?<!\d[.,])(\d)(?!\d|\.\d)"
_UP_TO = r"(?:\s*[-–/,]\s*(\d{1,2})(?![.,]?\d))?"
_COUNT_UNIT = r"\s*(?:x|razy?|dni|dzie[nń]|days?|times?)?"
_COUNT = _DIGIT + _UP_TO + _COUNT_UNIT
# W miesiącu bywa „10 dni”, w tygodniu najwyżej 5.
_MONTH_COUNT = r"(?<!\d)(?<!\d[.,])(\d{1,2})(?!\d|\.\d)" + _UP_TO + _COUNT_UNIT
_WEEK_DAYS_MAX, _MONTH_DAYS_MAX = 5, 22
_PER = r"(?:/|\bw\s|\bna\s|\bper\s|\ba\s)\s*"
# „3 dni w tygodniu”, „2x/tyg” — ale nie „przez pierwsze 3 tygodnie”.
_PER_WEEK_RE = re.compile(
    _COUNT + r"[^.\n\d]{0,24}?(?:" + _PER + r"(?:tydz|tyg|week)|tygodniowo)", re.I
)
_PER_MONTH_RE = re.compile(
    _MONTH_COUNT
    + r"(?:[^.\n\d]{0,24}?(?:"
    + _PER
    + r"(?:mies|msc|month)|miesi[eę]cznie)|(?<=x)\s*(?:mies|msc))",
    re.I,
)
_DAYS_RE = re.compile(
    _DIGIT + _UP_TO + r"\s*(?:(?:dni|dzie[nń]|x|razy|on-?site)\b|[wz]\s+biur)",
    re.I,
)
# Czego dotyczy liczba dni: biura („2 dni w biurze”) czy pracy z domu
# („3 dni zdalnie”). Rozstrzyga najbliższe słowo w tym samym zdaniu.
_OFFICE_WORD_RE = re.compile(
    r"biur|office|stacjonarn|on-?site|hybryd|hybrid|na miejscu", re.I
)
_REMOTE_WORD_RE = re.compile(r"zdaln|remote|home|z domu", re.I)
# „6 dni stacjonarnie”, „4-6 dni w biurze” — więcej niż 5 dni to dni w miesiącu.
_MANY_DAYS_RE = re.compile(
    r"(?<!\d)(?<!\d[.,])(\d{1,2})(?!\d|\.\d)"
    + _UP_TO
    + r"\s*dni\b(?![^.\n\d]{0,24}?(?:tydz|tyg|week|rok|rocz|year|kwarta))",
    re.I,
)
_REMOTE_NEXT_RE = re.compile(r"\s*(?:zdaln|remote|z domu)", re.I)
_CLAUSE_END_RE = re.compile(r"[,.;:()/+\n]")
_REMOTE_JUST_BEFORE_RE = re.compile(r"(?:zdaln\w*|remote|z domu)\s*$", re.I)
_CONTEXT_CHARS = 30
_ONCE_WEEK_RE = re.compile(r"raz (?:w|na) tyg|raz w tygodniu|once a week", re.I)
_ONCE_MONTH_RE = re.compile(r"raz (?:w|na) mies|once a month", re.I)
_CITIES: tuple[tuple[str, "re.Pattern[str]"], ...] = tuple(
    (name, re.compile(pattern, re.I))
    for name, pattern in (
        ("Warszawa", r"warszaw|\bwawa\b|\bwawie\b|\bwaw\b|\bwwa\b|warsaw"),
        ("Gdynia", r"gdyni"),
        ("Gdańsk", r"gda[nń]sk"),
        ("Łódź", r"[lł][oó]d[zź]|\b[lł]odzi\b"),
        ("Kraków", r"krak[oó]w|cracow"),
        ("Wrocław", r"wroc[lł]aw"),
        ("Poznań", r"pozna[nń]"),
        ("Katowice", r"katowic"),
        ("Trójmiasto", r"tr[oó]jmi"),
    )
)

_CEFR = r"(?<![A-Za-z0-9])([ABC][12])(?![A-Za-z0-9])"
_CEFR_RE = re.compile(_CEFR, re.I)
_ENGLISH_CEFR_RE = re.compile(r"(?:ang\w*|english)\W{0,12}" + _CEFR, re.I)
_OTHER_LANGUAGE_RE = re.compile(
    r"polski|niemieck|german|francus|french|hiszpa|spanish|rosyjs|russian"
    r"|ukrai|w[lł]osk|italian",
    re.I,
)
_NATIVE_RE = re.compile(r"native|ojczyst", re.I)

_NO_ONLY_RE = re.compile(r"^(?:nie|no|n/?a|brak|nie dotyczy|nigdy|[-–—])[\s.!]*$", re.I)
_NO_START_RE = re.compile(
    r"^(?:nie|no|nigdy|brak(?! (?:informacji|danych|info)))\b", re.I
)
_UNKNOWN_RE = re.compile(
    r"^(?:nie wiem|nie wiadomo|nie pami[eę]ta|brak (?:informacji|danych|info)"
    r"|do ustalenia|\?)",
    re.I,
)
# „Nie, ale w UoP tak”, „Nie, aktualnie pracuje u klienta” — samo „nie” na
# początku nie rozstrzyga.
_NO_BUT_RE = re.compile(
    r"uop|umow|b2b|etat|etac|\btak\b|aktualnie|obecnie|podwykonaw", re.I
)
_YES_RE = re.compile(r"^(?:tak\b|yes\b)", re.I)
_UOP_RE = re.compile(r"uop|umow\w* o prac|etat|etac", re.I)
_B2B_RE = re.compile(r"b2b", re.I)
_NOT_UOP_RE = re.compile(
    r"\bnie\s+(?:\w+\s+){0,2}?(?:na\s+)?(?:uop|umow\w* o prac|etat|etac)", re.I
)
_NONE_FLAGS_RE = re.compile(r"^(?:brak\b.{0,30}|none|nie ma|nie|n/?a|[-–—])\.?$", re.I)
# Niewypełnione miejsce ze wzoru: „[dlaczego Kandydat?]”, „[brak / opis]”.
_PLACEHOLDER_RE = re.compile(r"^\[[^\]]*\]$")
_PLACEHOLDER_PREFIX_RE = re.compile(r"^\[[^\]]{0,300}\]\s*:?\s*(?=\S)")
# „[Santander] - Lider wdrożenia” — tu nawias jest częścią wartości.
_KEEPS_BRACKETS = frozenset({"name", "project", "cv_filename", "client_manager"})
_LABELLED_LINE_RE = re.compile(r"^[^:\n]{2,70}:(?:\s|$)")
_SHORT_LABEL_RE = re.compile(r"^[^:\n.,;]{2,45}:(?:\s|$)")
# „Mocne technologie – SQL, Python” — etykieta oddzielona półpauzą.
_DASH_LABEL_RE = re.compile(r"^[A-ZĄĆĘŁŃÓŚŹŻ][^:\n.,;–—]{1,34}\s[–—]\s")


@dataclass(frozen=True)
class ParsedCard:
    """Wynik odczytu jednej notatki."""

    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    answers: tuple[dict[str, Any], ...] = ()
    labels: tuple[str, ...] = ()

    @property
    def is_card(self) -> bool:
        return len(self.labels) >= MIN_LABELS or bool(self.answers)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "answers": list(self.answers),
            "labels": list(self.labels),
            "parser_version": PARSER_VERSION,
        }


def to_text(content: Optional[str]) -> str:
    """Treść notatki jako zwykły tekst z zachowanymi wierszami."""
    raw = (content or "")[:_SCAN_CHARS].replace("&nbsp;", " ")
    raw = _TAG_RE.sub("", _BREAK_RE.sub("\n", raw))
    lines = (
        _SPACES_RE.sub(" ", line).strip() for line in html.unescape(raw).split("\n")
    )
    return "\n".join(line for line in lines if line)


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def _other_unit(raw: str, start: int, end: int) -> bool:
    """Czy kwota jest podana za miesiąc albo dzień, a nie za godzinę.

    Jednostkę czytamy z tekstu przy pierwszej kwocie: „120 zł/h (+ 2000 zł/mc
    relokacja)” to stawka godzinowa z dopiskiem, „400 zł netto za MD” —
    dzienna. Jawne „/h” przed inną jednostką wygrywa („140 zł/h, wcześniej
    na UoP”).
    """
    before = raw[:start]
    if _MONTHLY_RE.search(before) or _DAILY_RE.search(before):
        return True
    window = raw[end : end + _UNIT_WINDOW_CHARS]
    if stop := _UNIT_WINDOW_END_RE.search(window):
        window = window[: stop.start()]
    others = [
        match.start()
        for match in (_MONTHLY_RE.search(window), _DAILY_RE.search(window))
        if match
    ]
    if not others:
        return False
    hourly = _HOURLY_RE.search(window)
    return hourly is None or hourly.start() > min(others)


def parse_rate(raw: str) -> dict[str, Any]:
    """Stawka: PLN za godzinę tylko wtedy, gdy nie trzeba zgadywać."""
    out: dict[str, Any] = {"raw": raw}
    if _FOREIGN_RE.search(raw):
        return out
    match = _RATE_RE.search(raw)
    if not match:
        return out
    # Kwota miesięczna („14 000 zł”, „5500 brutto (32,78 zł/h)”) zostaje surowa:
    # pierwsza liczba w tekście musi być stawką godzinową.
    if any(char.isdigit() for char in raw[: match.start()]):
        return out
    if _THOUSANDS_RE.match(raw, match.start()):
        return out
    if _THOUSANDS_SUFFIX_RE.match(raw, match.end()):
        return out
    value = _number(match.group(1))
    if _other_unit(raw, match.start(), match.end()):
        return out
    if not _HOURLY_MIN <= value <= _HOURLY_MAX:
        return out
    out.update(value=value, currency="PLN", period="h")
    if match.group(2):
        upper = _number(match.group(2))
        if value < upper <= _HOURLY_MAX:
            out["value_max"] = upper
    return out


def _notice(raw: str) -> Optional[dict[str, Any]]:
    """Okres wypowiedzenia — pierwsza wzmianka w tekście wygrywa."""
    found: list[tuple[int, int, str]] = []
    if match := _NOTICE_RE.search(raw):
        unit = match.group(2).lower()
        found.append(
            (
                match.start(),
                int(match.group(1)),
                "weeks"
                if unit.startswith(("tyg", "tydz", "week"))
                else "days"
                if unit.startswith(("dni", "dzie", "day"))
                else "months",
            )
        )
    if match := _HALF_MONTH_RE.search(raw):
        found.append((match.start(), int(match.group(1) or 1) * 4 + 2, "weeks"))
    if match := _WORD_NOTICE_RE.search(raw):
        found.append(
            (
                match.start(),
                _WORD_NUMBERS[match.group(1)[:2].lower()],
                "months" if match.group(2).lower() == "mies" else "weeks",
            )
        )
    if not found and _DATE_RE.search(raw):
        return None
    for pattern, unit in ((_ONE_MONTH_RE, "months"), (_ONE_WEEK_RE, "weeks")):
        match = pattern.search(raw)
        if match and not _NOT_ONE_PERIOD_RE.search(
            raw[max(0, match.start() - 14) : match.start()]
        ):
            found.append((match.start(), 1, unit))
    if not found:
        return None
    _, value, unit = min(found)
    return {"value": value, "unit": unit}


def _start_date(raw: str) -> Optional[str]:
    """Data, od której kandydat jest dostępny — nie każda data w zdaniu."""
    for match in _DATE_RE.finditer(raw):
        if _DATE_NOT_START_AFTER_RE.match(raw, match.end()):
            continue
        before = raw[max(0, match.start() - 40) : match.start()]
        if match.start() <= _DATE_LEAD_CHARS or _DATE_START_BEFORE_RE.search(before):
            return match.group(0)
    return None


def parse_availability(raw: str) -> dict[str, Any]:
    out: dict[str, Any] = {"raw": raw}
    if _ASAP_RE.search(raw):
        # „ASAP (w październiku tydzień urlopu)” — dopisek to nie wypowiedzenie.
        out["asap"] = True
    elif notice := _notice(raw):
        out["notice"] = notice
    elif date := _start_date(raw):
        out["date_text"] = date
    return out


def _side(text: str) -> Optional[str]:
    """„office” albo „remote” — które słowo pada w tekście pierwsze."""
    office = _OFFICE_WORD_RE.search(text)
    remote = _REMOTE_WORD_RE.search(text)
    if office and remote:
        return "office" if office.start() < remote.start() else "remote"
    if office:
        return "office"
    return "remote" if remote else None


def _count_side(raw: str, match: "re.Match[str]", *, weekly: bool) -> Optional[str]:
    """Czego dotyczy liczba: biura, pracy z domu czy nie wiadomo (None)."""
    if side := _side(match.group(0)):
        return side
    after = _CLAUSE_END_RE.split(raw[match.end() : match.end() + _CONTEXT_CHARS], 1)
    side = _side(after[0])
    # „1-2 spotkania w miesiącu lub remote” — wizyty w miesiącu są wizytami
    # w biurze, chyba że „zdalnie” stoi tuż za liczbą.
    if side == "remote" and not weekly and not _REMOTE_NEXT_RE.match(after[0]):
        side = None
    if side:
        return side
    before = _CLAUSE_END_RE.split(
        raw[max(0, match.start() - _CONTEXT_CHARS) : match.start()]
    )[-1]
    if _OFFICE_WORD_RE.search(before):
        return "office"
    # „zdalnie 5 dni w tygodniu” — ale „zdalnie + 1x w miesiącu” to wizyty.
    if weekly and _REMOTE_JUST_BEFORE_RE.search(before):
        return "remote"
    return None


def _onsite_days(
    raw: str,
    pattern: "re.Pattern[str]",
    limit: int,
    *,
    weekly: bool,
    at_least: int = 1,
) -> Optional[int]:
    """Liczba dni w biurze z pierwszej wzmianki, która nie mówi o pracy z domu."""
    remote_only = bool(_REMOTE_WORD_RE.search(raw)) and not _OFFICE_WORD_RE.search(raw)
    for match in pattern.finditer(raw):
        side = _count_side(raw, match, weekly=weekly)
        # „2-3 dni w tygodniu” = zgoda na najwyżej 3.
        value = max(int(match.group(1)), int(match.group(2) or 0))
        if side == "remote" or not at_least <= value <= limit:
            continue
        # „remote, 5 days a week” — pełny tydzień w tekście wyłącznie
        # o pracy zdalnej opisuje pracę zdalną, nie biuro.
        if weekly and side is None and remote_only and value == limit:
            continue
        return value
    return None


def parse_work_mode(raw: str) -> dict[str, Any]:
    out: dict[str, Any] = {"raw": raw}
    week = _onsite_days(raw, _PER_WEEK_RE, _WEEK_DAYS_MAX, weekly=True)
    if week is not None:
        out["onsite_days_per_week"] = week
    elif _ONCE_WEEK_RE.search(raw):
        out["onsite_days_per_week"] = 1
    elif (
        month := _onsite_days(raw, _PER_MONTH_RE, _MONTH_DAYS_MAX, weekly=False)
    ) is not None:
        out["onsite_days_per_month"] = month
    elif _ONCE_MONTH_RE.search(raw):
        out["onsite_days_per_month"] = 1
    elif (days := _onsite_days(raw, _DAYS_RE, _WEEK_DAYS_MAX, weekly=True)) is not None:
        # „2 dni z biura” bez okresu: w kartach to zawsze dni w tygodniu.
        out["onsite_days_per_week"] = days
    elif (
        many := _onsite_days(
            raw,
            _MANY_DAYS_RE,
            _MONTH_DAYS_MAX,
            weekly=False,
            at_least=_WEEK_DAYS_MAX + 1,
        )
    ) is not None:
        out["onsite_days_per_month"] = many
    has_days = "onsite_days_per_week" in out or "onsite_days_per_month" in out
    if _HYBRID_RE.search(raw) or has_days:
        out["mode"] = "hybrid"
    elif _ONSITE_RE.search(raw):
        out["mode"] = "onsite"
    elif _REMOTE_RE.search(raw):
        out["mode"] = "remote"
    if out.get("mode") != "remote":
        for name, pattern in _CITIES:
            if pattern.search(raw):
                out["office_city"] = name
                break
    return out


def parse_english(raw: str) -> dict[str, Any]:
    out: dict[str, Any] = {"raw": raw}
    level = _ENGLISH_CEFR_RE.search(raw)
    if level is None and not _OTHER_LANGUAGE_RE.search(raw):
        # „Języki: polski C2, angielski …” — poziom innego języka to nie angielski.
        level = _CEFR_RE.search(raw)
    if level:
        out["level"] = level.group(1).upper()
    elif _NATIVE_RE.search(raw) and not _OTHER_LANGUAGE_RE.search(raw):
        out["level"] = "native"
    return out


def parse_worked_at_client(raw: str) -> dict[str, Any]:
    out: dict[str, Any] = {"raw": raw}
    text = raw.strip()
    if _UNKNOWN_RE.match(text):
        return out
    if _NO_ONLY_RE.match(text):
        out["value"] = "no"
        return out
    if _NO_START_RE.match(text):
        if not _NO_BUT_RE.search(text):
            out["value"] = "no"
        return out
    uop, b2b = _UOP_RE.search(text), _B2B_RE.search(text)
    if uop and b2b:
        # Dwa rodzaje umowy w jednym zdaniu: „nie na etacie, tylko B2B” to
        # B2B; w pozostałych przypadkach ostrożnie — była umowa o pracę.
        out["value"] = "b2b" if _NOT_UOP_RE.search(text) else "uop"
    elif uop:
        out["value"] = "uop"
    elif b2b:
        out["value"] = "b2b"
    elif _YES_RE.match(text):
        out["value"] = "yes"
    return out


def parse_red_flags(raw: str) -> dict[str, Any]:
    out: dict[str, Any] = {"raw": raw}
    if _NONE_FLAGS_RE.match(raw.strip()):
        out["none"] = True
    return out


_NORMALIZERS = {
    "rate": parse_rate,
    "availability": parse_availability,
    "work_mode": parse_work_mode,
    "english": parse_english,
    "worked_at_client": parse_worked_at_client,
    "red_flags": parse_red_flags,
}


def normalize_field(key: str, raw: str) -> dict[str, Any]:
    """Pole karty z samego tekstu wartości — ta sama reguła co odczyt notatki."""
    normalize = _NORMALIZERS.get(key)
    return normalize(raw) if normalize else {"raw": raw}


_Label = tuple[int, int, str, Optional[int]]


def _numbered_questions(text: str, taken: list[_Label]) -> list[_Label]:
    """Pytania zapisane jako lista „1. … 2. …” bez słowa „Pytanie”.

    Lista liczy się tylko wtedy, gdy zaczyna się od 1, ma co najmniej dwie
    kolejne pozycje i pod którąś z nich jest odpowiedź — zwykłe wyliczenie
    w notatce nie staje się pytaniami.
    """
    starts = {item[0] for item in taken}
    run: list[tuple[int, int, int]] = []
    for match in _NUMBERED_RE.finditer(text):
        number = int(match.group(1))
        if match.start() in starts:
            continue
        if number == len(run) + 1:
            run.append((match.start(), match.end(), number))
        elif run and number == 1:
            break
    if len(run) < 2:
        return []
    bounds = sorted(starts | {item[0] for item in run} | {len(text)})
    for start, end, _ in run:
        stop = next(bound for bound in bounds if bound > start)
        if _split_question(text[end:stop])[1]:
            return [(start, end, "_question", number) for start, end, number in run]
    return []


def _bare_questions(text: str, taken: list[_Label]) -> list[_Label]:
    """Pytania bez numeru i etykiety: wiersz z pytajnikiem i odpowiedź pod nim."""
    starts = {item[0] for item in taken}
    found: list[_Label] = []
    offset = 0
    lines = text.split("\n")
    for index, line in enumerate(lines):
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if (
            len(line) >= 25
            and line.endswith("?")
            and following
            and not following.endswith("?")
            and offset not in starts
            and not _LABELLED_LINE_RE.match(line)
        ):
            found.append((offset, offset, "_question", len(found) + 1))
        offset += len(line) + 1
    return found if 2 <= len(found) <= 9 else []


def _labels(text: str) -> list[_Label]:
    """Wszystkie etykiety w tekście: (początek, koniec, klucz, numer pytania)."""
    found: list[_Label] = []
    for key, pattern in _FIELD_RE:
        found.extend((m.start(), m.end(), key, None) for m in pattern.finditer(text))
    found.extend(
        (m.start(), m.end(), "_question", int(m.group(1) or m.group(3) or 0))
        for m in _QUESTION_RE.finditer(text)
    )
    found.extend(
        (m.start(), m.end(), "_answer", None) for m in _ANSWER_RE.finditer(text)
    )
    known = {item[0] for item in found}
    found.extend(
        (m.start(), m.end(), "_other", None)
        for m in _OTHER_ITEM_RE.finditer(text)
        if m.start() not in known
    )
    if not any(item[2] == "_question" for item in found):
        found.extend(_numbered_questions(text, found) or _bare_questions(text, found))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[_Label] = []
    last_end = -1
    for item in found:
        if item[0] >= last_end:
            kept.append(item)
            last_end = item[1]
    return kept


def _is_mention_line(line: str) -> bool:
    """Wiersz z samych wzmianek: „@Marta Testowa, @Anna Testowa”."""
    if not line.startswith("@"):
        return False
    for part in line.split("@")[1:]:
        words = part.rstrip(" \t,.").split()
        if not 1 <= len(words) <= 2 or "," in part.rstrip(" \t,."):
            return False
    return True


def _without_contact(line: str) -> str:
    """Wiersz bez adresu e-mail, numeru telefonu i adresu LinkedIn."""
    if "@" not in line and not _HAS_DIGIT_OR_LINK_RE.search(line):
        return line
    cleaned = _PHONE_RE.sub("", _LINKEDIN_RE.sub("", _EMAIL_RE.sub("", line)))
    if cleaned == line:
        return line
    cleaned = _EMPTY_PARENS_RE.sub("", cleaned).strip(" \t,;|/")
    if cleaned.endswith(")") and "(" not in cleaned:
        cleaned = cleaned[:-1]
    return _CONTACT_TAIL_RE.sub("", cleaned).strip(" \t,;|/")


def _clean_lines(segment: str) -> list[str]:
    lines = (
        _without_contact(_BULLET_RE.sub("", line).strip())
        for line in segment.split("\n")
    )
    return [
        line
        for line in lines
        if line and not _NUMBER_ONLY_RE.match(line) and not _is_mention_line(line)
    ]


def _split_question(segment: str) -> tuple[str, str]:
    """Pytanie i odpowiedź z odcinka bez etykiety „Odpowiedź:”.

    Tekst w wierszu etykiety jest pytaniem, kolejne wiersze odpowiedzią.
    Gdy wiersz etykiety jest pusty („Pytanie 1:” i nowy wiersz), pytaniem są
    wiersze zakończone pytajnikiem; bez nich cały odcinek to odpowiedź —
    rekruterzy często wpisują pod numerem samą odpowiedź.
    """
    head = segment.partition("\n")[0]
    lines = _clean_lines(segment)
    if not lines:
        return "", ""
    asked = 0
    while asked < min(len(lines), 4) and lines[asked].endswith("?"):
        asked += 1
    if asked:
        return " ".join(lines[:asked]), "\n".join(lines[asked:])
    if not head.strip() and not (len(lines) > 1 and _ASKING_RE.match(lines[0])):
        return "", "\n".join(lines)
    first = lines[0]
    if len(lines) > 1:
        return first, "\n".join(lines[1:])
    cut = first.rfind("? ")
    if cut != -1 and len(first) - cut > 20:
        return first[: cut + 1], first[cut + 2 :].strip()
    return first, ""


# Pola karty, których nie czyta żaden model (narodowość) i których nie czyta
# generator CV (stawka, red flags, motywacja — to ustalenia handlowe, nie
# treść CV dla klienta).
AI_HIDDEN_FIELDS: frozenset[str] = frozenset({"nationality"})
CV_HIDDEN_FIELDS: frozenset[str] = frozenset(
    {"nationality", "rate", "red_flags", "motivation"}
)


_BULLET_START_RE = re.compile(r"^[^\S\n]*[·•*▪◦–-]")


def _hidden_span(text: str, end: int, stop: int, *, single_line: bool) -> int:
    """Koniec wartości ukrywanego pola (pozycja w ``text``).

    Tniemy ostrożnie — lepiej zostawić modelowi dalszy ciąg motywacji niż
    zabrać mu fakty o kandydacie (pomiar 03.10.2026: cięcie „do następnej
    etykiety” zabierało wiersze „Mocne technologie – …” pod „Motywacja –”).
    Wartość to jeden wiersz: reszta wiersza etykiety albo pierwszy niepusty
    wiersz pod nią. Wyjątek: lista punktów pod pustą etykietą („Red flags:”
    i punkty) znika w całości.
    """
    position = end
    seen_value = False
    bullets = False
    for index, line in enumerate(text[end:stop].split("\n")):
        if seen_value and not (bullets and _BULLET_START_RE.match(line)):
            return position
        if not seen_value and line.strip():
            seen_value = True
            bullets = (
                not single_line and index > 0 and bool(_BULLET_START_RE.match(line))
            )
        position += len(line) + 1
    return stop


def redact_card_text(content: Optional[str], hidden: frozenset[str]) -> str:
    """Treść notatki bez wskazanych pól karty — wejście dla modelu.

    Notatka bez żadnego z tych pól wraca bez zmian (co do znaku). Z notatki
    z takim polem zostaje zwykły tekst z wyciętą etykietą i jej wartością;
    reszta notatki, także wiersze bez etykiet, zostaje.
    """
    if not content:
        return ""
    text = to_text(content)
    labels = _labels(text)
    if not any(key in hidden for _, _, key, _ in labels):
        return content
    kept: list[str] = []
    cursor = 0
    for index, (start, end, key, _) in enumerate(labels):
        if key not in hidden or start < cursor:
            continue
        stop = labels[index + 1][0] if index + 1 < len(labels) else len(text)
        # Punkt listy przed etykietą („- motywacja: …”) znika razem z nią.
        line_start = text.rfind("\n", 0, start) + 1
        if not text[line_start:start].strip(" \t·•*▪◦–-"):
            start = max(line_start, cursor)
        kept.append(text[cursor:start])
        cursor = _hidden_span(text, end, stop, single_line=key in _SINGLE_LINE)
    kept.append(text[cursor:])
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def parse_card(content: Optional[str]) -> ParsedCard:
    """Odczytuje pola karty rekomendacji z treści notatki."""
    text = to_text(content)
    labels = _labels(text)
    fields: dict[str, dict[str, Any]] = {}
    answers: list[dict[str, Any]] = []
    seen: list[str] = []
    pending: Optional[dict[str, Any]] = None

    for index, (_, end, key, number) in enumerate(labels):
        stop = labels[index + 1][0] if index + 1 < len(labels) else len(text)
        segment = text[end:stop].strip(" \t")
        if key == "_question":
            next_key = labels[index + 1][2] if index + 1 < len(labels) else None
            if next_key == "_answer":
                question, answer = " ".join(_clean_lines(segment)), ""
            else:
                question, answer = _split_question(segment)
            pending = {
                "number": number or len(answers) + 1,
                "question": question[:2000],
                "answer": answer[:_TEXT_VALUE_MAX],
            }
            answers.append(pending)
            continue
        if key == "_answer":
            if pending is not None and not pending["answer"]:
                pending["answer"] = "\n".join(_clean_lines(segment))[:_TEXT_VALUE_MAX]
            continue
        pending = None
        if key in ("_contact", "_other") or key in fields:
            continue
        lines = _clean_lines(segment)
        if key == "red_flags" and not lines and segment.strip() in ("-", "–", "—"):
            lines = [segment.strip()]
        if not lines or _PLACEHOLDER_RE.match(lines[0]):
            continue
        if key not in _KEEPS_BRACKETS:
            lines[0] = _PLACEHOLDER_PREFIX_RE.sub("", lines[0])
        if key in _SINGLE_LINE:
            # Pusta etykieta, a pod nią wiersz z inną, nieznaną etykietą
            # („Narodowość:” / „Profil: Analityk”) — to nie jest wartość pola.
            if segment.startswith("\n") and _LABELLED_LINE_RE.match(lines[0]):
                continue
            raw = lines[0][:_LINE_VALUE_MAX]
            if key == "name":
                raw = raw.split(" (")[0].strip() or raw
        elif key == "project":
            raw = "; ".join(lines[:5])[:_LINE_VALUE_MAX]
        else:
            if key in ("motivation", "red_flags"):
                # „Motywacja: …” / „Projekty: …” — kolejny wiersz z własną
                # etykietą to już inne pole, nie dalszy ciąg motywacji.
                for position, line in enumerate(lines[1:], start=1):
                    if _SHORT_LABEL_RE.match(line) or _DASH_LABEL_RE.match(line):
                        lines = lines[:position]
                        break
            raw = "\n".join(lines)[:_TEXT_VALUE_MAX]
        normalize = _NORMALIZERS.get(key)
        fields[key] = normalize(raw) if normalize else {"raw": raw}
        seen.append(key)

    kept_answers = tuple(a for a in answers if a["question"] or a["answer"])
    return ParsedCard(fields=fields, answers=kept_answers, labels=tuple(seen))
