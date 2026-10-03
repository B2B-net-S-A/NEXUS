"""Rodzaj notatki — jedna reguła dla listy, AI i wyszukiwania (0412, 03.10.2026).

Pomiar na produkcji 03.10.2026 (75 231 notatek): 16% to wpisy automatu
auto-match, 5% wątki mailowe z Traffita, 7% „nie odbiera”, 5% wpisy Delivery
Leada ze stawką do klienta — a żaden czytelnik notatek (nocny odczyt faktów,
bramka must, QC CV, podsumowanie AI) nie odróżniał ich od notatki z rozmowy.
„Must-have trafione: python” z wpisu automatu liczyło się jako dowód, że
kandydat zna Pythona.

Ten moduł jest czysty (bez bazy): ``classify`` nadaje rodzaj z treści, a stałe
mówią, co czyta AI, co wyszukiwanie i co widzi rola bez wglądu w stawkę do
klienta. Rodzaj zapisuje nasłuch w ``models/note.py`` (zapis przez ORM)
i ``note_kind_backfill.classify_pending`` (surowy SQL importu Traffita, wiersze
sprzed 0412).

Reguły czytają treść po zdjęciu znaczników HTML, małymi literami. Kolejność
w ``classify`` jest znacząca: pierwsza pasująca reguła wygrywa.
"""

from __future__ import annotations

import html
import re
from typing import Optional

SYSTEM_SOURCE = "system"
PREP_SOURCE = "teams_prep"

AUTOMATCH = "automatch"
APPLICATION_FORM = "application_form"
PREP_SUMMARY = "prep_summary"
EMAIL = "email"
CARD = "card"
DL_RATE = "dl_rate"
SCREENING_FACTS = "screening_facts"
DL_REVIEW = "dl_review"
CONTACT_ATTEMPT = "contact_attempt"
SCHEDULING = "scheduling"
MENTION = "mention"
STATUS = "status"
REJECTION = "rejection"
CONTRACTOR = "contractor"
HUMAN = "human"

ALL_KINDS: tuple[str, ...] = (
    AUTOMATCH,
    APPLICATION_FORM,
    PREP_SUMMARY,
    EMAIL,
    CARD,
    DL_RATE,
    SCREENING_FACTS,
    DL_REVIEW,
    CONTACT_ATTEMPT,
    SCHEDULING,
    MENTION,
    STATUS,
    REJECTION,
    CONTRACTOR,
    HUMAN,
)

# Tych rodzajów nie czyta AI ani bramka must: nie mówią nic o kandydacie
# (automat, terminy, „nie odbiera”) albo mówią o czymś innym, niż się wydaje
# (tytuł ogłoszenia, instrukcja „dopisz do CV”, stawka do klienta).
AI_EXCLUDED_KINDS: frozenset[str] = frozenset(
    {
        AUTOMATCH,
        APPLICATION_FORM,
        EMAIL,
        DL_RATE,
        DL_REVIEW,
        CONTACT_ATTEMPT,
        SCHEDULING,
        MENTION,
    }
)

# Wyszukiwanie słów kluczowych pomija tylko wpisy automatów: „Oferta: Java
# Developer” w notatce scrapera znajdowało testera pod hasłem „java”.
SEARCH_EXCLUDED_KINDS: frozenset[str] = frozenset({AUTOMATCH, APPLICATION_FORM})

# Notatki, które nocny odczyt faktów bierze w pierwszej kolejności.
AI_PRIORITY_KINDS: tuple[str, ...] = (CARD, SCREENING_FACTS)

# Notatki niosące stawkę do klienta — treść widzą tylko role z wglądem w tę
# stawkę (decyzja 23.09.2026: rekruter jej nie widzi).
CLIENT_RATE_KINDS: frozenset[str] = frozenset({DL_RATE})

CLIENT_RATE_SNIPPET = "Wpis o stawce do klienta."
CLIENT_RATE_PLACEHOLDER = (
    "Notatka Delivery Leada o stawce do klienta — niewidoczna dla Twojej roli."
)

# Etykiety trafiają na początek treści, więc reguły czytają tylko ten odcinek;
# długość liczymy z całości.
_SCAN_CHARS = 6000
_DL_RATE_MAX_CHARS = 200

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_MENTION = r"(?:@[^\s@]+ [^\s@]+|\$\$user_\d+\$\$)"
_AMOUNT = r"\d{2,3}(?:[.,]\d{1,2})?"
# „za 14 dni” to termin, nie stawka.
_NOT_TIME = r"(?!\d)(?!\s*(?:dni|dzień|dnia|tyg|tydz|godz|min|mies|msc|lat|rok))"

_AUTOMATCH_RE = re.compile(
    r"^(?:źródło: .{0,200}?auto-match score"
    r"|auto-match \d+/100 — kandydat dodany automatycznie)"
)
_FORM_MARK = "odpowiedzi z formularza aplikacji"
_MAILISH_RE = re.compile(
    r"from:|sent:|subject:|napisał\(a\)|wrote:|wysłano:|temat:"
    r"|pozdrawiam|best regards|kind regards|z poważaniem"
)
_CARD_NAME_RE = re.compile(r"imi[eę] i nazwisko")
_RATE_WORD_RE = re.compile(r"stawka|oczekiwania")
_AVAILABILITY_RE = re.compile(r"dost[eę]pno")
_QA_RE = re.compile(r"pytanie ?[1-9]|\bp ?[1-9] ?:|odpowied[zź] ?:")
_CARD_MARK_RE = re.compile(
    r"pytanie ?[1-9]|\bp ?[1-9] ?:|odpowied[zź] ?:|notatka ?:|motywacja ?[:–-]"
)
_DL_RATE_RE = re.compile(
    r"(?:wy[sś][lł]ijmy|pokazujemy|poka[zż]my|wysyłam|wysłałam|wysłałem"
    r"|wysłan[yae]|wysłać)[^.\n]{0,40}? za (?:stawkę )?" + _AMOUNT + _NOT_TIME
)
_DL_PAIR_RE = re.compile(
    rf"^(?:{_MENTION}\s*)*{_AMOUNT}\s*/\s*{_AMOUNT}(?:\s*(?:zł|pln))?\s*"
    rf"(?:{_MENTION}\s*)*$"
)
_DL_BARE_RE = re.compile(
    rf"^(?:(?:{_MENTION}\s*)+{_AMOUNT}(?:\s*(?:zł|pln)(?:/h)?)?"
    rf"|{_AMOUNT}(?:\s*(?:zł|pln)(?:/h)?)?\s*(?:{_MENTION}\s*)+)$"
)
_FACT_RATE_RE = re.compile(r"stawka|oczekiwania|chce \d|\d ?(?:zł|pln) ?/ ?h")
_FACT_OTHER_RE = re.compile(
    r"dost[eę]pno|wypowiedzen|asap|od zaraz|lokalizacj|tryb|zdaln|hybryd"
)
_DL_PASS_RE = re.compile(r"przepuszczam|mo[zż]na (?:go|ją|ja) wys[lł]a[cć]")
_DL_FIX_RE = re.compile(r"popraw|\bdone\b|bold|dopisz|zmień proszę|do cv\b")
_CONTACT_RE = re.compile(
    r"^(?:(?:nadal|dalej|wciąż|znowu|ponownie)\s+)?"
    r"(?:nie odbiera|nie odebra|n/o\b|brak kontaktu|poczta\b|nie odpowiada"
    r"|od razu rozłącza|brak sygnału|numer zajęty|zajęte\b|poszedł mail"
    r"|wyszedł mail|poleciał mail|wysłany mail|oddzwoni\b|call (?:w|jutro)\b"
    r"|no(?: x\d)?$|nadal$|dalej nic$)"
)
_TWO_DIGITS_RE = re.compile(r"\d{2}")
_SCHEDULE_WORD_RE = re.compile(
    r"interview|prep|spotkani|rozmow|termin|weryfikacja techniczna|\betap"
)
_CLOCK_RE = re.compile(r"\d{1,2}[.:]\d{2}")
_MENTION_ONLY_RE = re.compile(
    rf"^(?:(?:już|ok|okej)\s+)?(?:{_MENTION}\s*)+(?:ok|zrobione)?\.?$"
)
_STATUS_RE = re.compile(
    r"nie szuka|nie jest zainteresowan|niezainteresowan"
    r"|ma (?:już |dobry |fajny |zadowalaj\w+ )?projekt|podpisuje|podpisa[lł]"
    r"|znalaz[lł]|kontakt (?:za|w|od|pod koniec|po)\b|tylko zdaln|tylko uop"
    r"|tylko praca zdalna|odezwać się|wrócić (?:w|za|po)\b"
)
_REJECTION_RE = re.compile(
    r"^(?:brak doświadczenia|rejected|odrzucon|odpada|za słab|nie rekomendujemy)"
)
_CONTRACTOR_RE = re.compile(
    r"podwyżk|aneks|faktur|\bnda\b|niekaralno|onboarding|sprzęt|laptop"
    r"|przedłużeni|wypowiedzeni[ea] umowy"
)


def plain_text(content: Optional[str]) -> str:
    """Treść bez znaczników HTML, małymi literami, z pojedynczymi spacjami."""
    raw = html.unescape((content or "").replace("&nbsp;", " "))
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", raw)).strip().lower()


def classify(
    content: Optional[str],
    *,
    note_type: Optional[str] = None,
    external_source: Optional[str] = None,
) -> str:
    """Rodzaj notatki z jej treści, typu i pochodzenia."""
    text = plain_text(content)
    length = len(text)
    head = text[:_SCAN_CHARS]

    if external_source == SYSTEM_SOURCE or _AUTOMATCH_RE.search(head):
        return AUTOMATCH
    if _FORM_MARK in head:
        return APPLICATION_FORM
    if external_source == PREP_SOURCE:
        return PREP_SUMMARY
    if note_type == "email" and (length > 1500 or _MAILISH_RE.search(head)):
        return EMAIL

    has_rate_word = bool(_RATE_WORD_RE.search(head))
    if _CARD_NAME_RE.search(head) and has_rate_word:
        return CARD
    if has_rate_word and _AVAILABILITY_RE.search(head) and _CARD_MARK_RE.search(head):
        return CARD
    # Tylko krótki wpis o cenie. Dłuższa notatka, która przy okazji podaje
    # „wysłana za 85”, niesie też fakty o kandydacie i zostaje zwykłą notatką.
    if (
        (length < _DL_RATE_MAX_CHARS and _DL_RATE_RE.search(head))
        or _DL_PAIR_RE.match(head)
        or _DL_BARE_RE.match(head)
    ):
        return DL_RATE
    if _FACT_RATE_RE.search(head) and _FACT_OTHER_RE.search(head):
        return SCREENING_FACTS
    if _QA_RE.search(head):
        return CARD
    if (_DL_PASS_RE.search(head) and length < 400) or (
        _DL_FIX_RE.search(head) and length < 300
    ):
        return DL_REVIEW
    # „nie odbiera, ale stawkę ma 200” to już fakt — liczba zostawia notatkę.
    if length < 80 and _CONTACT_RE.match(head) and not _TWO_DIGITS_RE.search(head):
        return CONTACT_ATTEMPT
    if length < 400 and _SCHEDULE_WORD_RE.search(head) and _CLOCK_RE.search(head):
        return SCHEDULING
    if _MENTION_ONLY_RE.match(head):
        return MENTION
    if length < 400 and _STATUS_RE.search(head):
        return STATUS
    if _REJECTION_RE.match(head):
        return REJECTION
    if _CONTRACTOR_RE.search(head):
        return CONTRACTOR
    return HUMAN


def _sql_list(kinds: frozenset[str]) -> str:
    return ", ".join(f"'{kind}'" for kind in sorted(kinds))


def _sql_filter(alias: str, kinds: frozenset[str]) -> str:
    col = f"{alias}." if alias else ""
    return (
        f"({col}external_source IS DISTINCT FROM '{SYSTEM_SOURCE}' "
        f"AND ({col}kind IS NULL OR {col}kind NOT IN ({_sql_list(kinds)})))"
    )


def ai_readable_sql(alias: str = "") -> str:
    """Warunek SQL: notatka, którą wolno pokazać modelowi i bramce must.

    Wiersz bez rodzaju (sprzed uzupełnienia) przechodzi jak dotąd — poza
    wpisem automatu, który rozpoznaje samo pochodzenie.
    """
    return _sql_filter(alias, AI_EXCLUDED_KINDS)


def searchable_sql(alias: str = "") -> str:
    """Warunek SQL: notatka, w której szuka wyszukiwanie słów kluczowych."""
    return _sql_filter(alias, SEARCH_EXCLUDED_KINDS)


def _orm_filter(kinds: frozenset[str]):
    from sqlalchemy import and_, or_

    from app.models.note import Note

    return and_(
        Note.external_source.is_distinct_from(SYSTEM_SOURCE),
        or_(Note.kind.is_(None), Note.kind.notin_(sorted(kinds))),
    )


def ai_readable_clause():
    """To samo co ``ai_readable_sql`` dla zapytań ORM po ``Note``."""
    return _orm_filter(AI_EXCLUDED_KINDS)


def searchable_clause():
    """To samo co ``searchable_sql`` dla zapytań ORM po ``Note``."""
    return _orm_filter(SEARCH_EXCLUDED_KINDS)


def hides_client_rate(kind: Optional[str]) -> bool:
    """Czy treść notatki tego rodzaju niesie stawkę do klienta."""
    return kind in CLIENT_RATE_KINDS
