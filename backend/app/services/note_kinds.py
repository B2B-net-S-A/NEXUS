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
# Uwaga dla rekrutera zapisana przy ruchu karty (`services/stage_remarks.py`).
# Pochodzenie, a nie treść, rozstrzyga rodzaj: uwaga z kwotą („kandydat chce
# 150, wróć z 140”) inaczej stałaby się wpisem o stawce do klienta i byłaby
# zakryta adresatowi — także po edycji.
REMARK_SOURCE = "stage_remark"

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

# Nocny odczyt faktów czyta dodatkowo odpowiedzi z formularza aplikacji:
# oczekiwania, termin startu i staż podał sam kandydat (decyzja 03.10.2026:
# nic nie znika). Dowodem na technologię formularz nie jest — niesie tytuł
# ogłoszenia, nie umiejętności.
FACTS_EXCLUDED_KINDS: frozenset[str] = AI_EXCLUDED_KINDS - {APPLICATION_FORM}

# Wpisy automatów — nie są notatką o kandydacie na żadnym ekranie.
AUTOMAT_KINDS: frozenset[str] = frozenset({AUTOMATCH, APPLICATION_FORM})

# Wyszukiwanie słów kluczowych pomija wpisy automatów („Oferta: Java
# Developer” w notatce scrapera znajdowało testera pod hasłem „java”) oraz
# notatki ze stawką do klienta — inaczej `q=161` w zakresie „notatki”
# zdradzałoby zakrytą kwotę samym trafieniem.
SEARCH_EXCLUDED_KINDS: frozenset[str] = frozenset(
    {AUTOMATCH, APPLICATION_FORM, DL_RATE}
)

# Tych notatek filtr „Kontakt z kandydatem” nie liczy jako kontaktu.
CONTACT_EXCLUDED_KINDS: frozenset[str] = frozenset(
    {AUTOMATCH, APPLICATION_FORM, CONTACT_ATTEMPT, DL_RATE, DL_REVIEW, MENTION}
)

# Notatki, które nocny odczyt faktów bierze w pierwszej kolejności.
AI_PRIORITY_KINDS: tuple[str, ...] = (CARD, SCREENING_FACTS)

# Notatki niosące stawkę do klienta — treść widzą tylko role z wglądem w tę
# stawkę (decyzja 23.09.2026: rekruter jej nie widzi).
CLIENT_RATE_KINDS: frozenset[str] = frozenset({DL_RATE})

# Grupy notatek w Historii profilu kandydata (decyzja 03.10.2026: nic nie
# znika — każdy rodzaj ma swoją zakładkę). Kolejność = kolejność zakładek.
GROUP_TALKS = "talks"
GROUP_CONTACT = "contact"
GROUP_DELIVERY = "delivery"
GROUP_EMAIL = "email"
GROUP_AUTOMAT = "automat"
NOTE_GROUPS: tuple[str, ...] = (
    GROUP_TALKS,
    GROUP_CONTACT,
    GROUP_DELIVERY,
    GROUP_EMAIL,
    GROUP_AUTOMAT,
)
_GROUP_BY_KIND: dict[str, str] = {
    CONTACT_ATTEMPT: GROUP_CONTACT,
    SCHEDULING: GROUP_CONTACT,
    DL_RATE: GROUP_DELIVERY,
    DL_REVIEW: GROUP_DELIVERY,
    EMAIL: GROUP_EMAIL,
    AUTOMATCH: GROUP_AUTOMAT,
    APPLICATION_FORM: GROUP_AUTOMAT,
}


def group_of(kind: Optional[str], external_source: Optional[str] = None) -> str:
    """Zakładka Historii, do której trafia notatka.

    Wpis automatu rozpoznaje samo pochodzenie (jak w filtrze dla AI); notatka
    bez rodzaju albo o rodzaju spoza mapy jest rozmową — nic nie wypada.
    """
    if external_source == SYSTEM_SOURCE:
        return GROUP_AUTOMAT
    return _GROUP_BY_KIND.get(kind or "", GROUP_TALKS)


CLIENT_RATE_SNIPPET = "Wpis o stawce do klienta."
CLIENT_RATE_PLACEHOLDER = (
    "Notatka Delivery Leada o stawce do klienta — niewidoczna dla Twojej roli."
)

# Etykiety trafiają na początek treści, więc reguły czytają tylko ten odcinek;
# długość liczymy z całości.
_SCAN_CHARS = 6000
_DL_RATE_MAX_CHARS = 200
# „Pokazujemy za 178 zł na: <lista rekrutacji>” bywa dłuższe przez same tytuły
# rekrutacji. Pomiar 03.10.2026: 139 takich wpisów (200–400 znaków, bez słowa
# o kandydacie) było zwykłą notatką, więc rekruter widział w nich cenę.
_DL_RATE_LIST_MAX_CHARS = 400

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
# Notatka, która mówi coś o kandydacie, nie jest szumem: fałszywe wykluczenie
# (AI i bramka must jej nie zobaczą) kosztuje więcej niż fałszywe włączenie.
_SUBSTANCE_RE = re.compile(
    r"\bzna\b|\bznajomo|doświadcz|\bpracowa[lł]|\bpracuje\b|komercyjn"
)
# „Wyślijmy / pokazujemy za …” to forma Delivery Leada — zawsze wpis o cenie.
_DL_RATE_RE = re.compile(
    r"(?:wy[sś][lł]ijmy|pokazujemy|poka[zż]my)[^.\n]{0,40}? za (?:stawkę )?"
    + _AMOUNT
    + _NOT_TIME
)
# „Wysłałam za …” pisze też rekruter, często razem z faktami o kandydacie.
_SENT_RATE_RE = re.compile(
    r"(?:wysyłam|wysłałam|wysłałem|wysłan[yae]|wysłać)[^.\n]{0,40}? za "
    r"(?:stawkę )?" + _AMOUNT + _NOT_TIME
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
# Uwagi Delivery Leada do CV — całe słowa („poprawnie” to nie „popraw”)
# i tylko we wpisie skierowanym do kogoś (@osoba).
_DL_FIX_RE = re.compile(
    r"\bpoprawion\w*|\bpopraw(?:ki|ka|ek)?\b|\bdo poprawy\b|\bpoprawi[lł][ae]m\b"
    r"|\bdone\b|\bbold\w*|\bdopisz\b|\bzmień proszę|\bdo cv\b"
)
_HAS_MENTION_RE = re.compile(_MENTION)
_CONTACT_RE = re.compile(
    r"^(?:(?:nadal|dalej|wciąż|znowu|ponownie)\s+)?"
    r"(?:nie odbiera|nie odebra|n/o\b|brak kontaktu|poczta\b|nie odpowiada"
    r"|od razu rozłącza|brak sygnału|numer zajęty|zajęte\b|poszedł mail"
    r"|wyszedł mail|poleciał mail|wysłany mail|oddzwoni\b|call (?:w|jutro)\b"
    r"|no(?: x\d)?$|nadal$|dalej nic$)"
)
_TWO_DIGITS_RE = re.compile(r"\d{2}")
_SCHEDULE_WORD_RE = re.compile(
    r"interview|\bprep\w*|\bspotkani|\btermin|weryfikacja techniczna|drugi etap"
    r"|\brozmowa (?:o |w |dnia )?\d"
)
# Godzina z dwukropkiem, „godz.” albo data DD.MM — nie goła „3.11” z wersji.
_CLOCK_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b|\bgodz|\b(?:[0-2]?\d|3[01])\.(?:0[1-9]|1[0-2])\b"
)
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
    if external_source == REMARK_SOURCE:
        return DL_REVIEW
    text = plain_text(content)
    length = len(text)
    head = text[:_SCAN_CHARS]

    # Formularz przed pochodzeniem: notatka scrapera jest systemowa, a mimo
    # to niesie odpowiedzi kandydata, które czyta odczyt faktów.
    if _FORM_MARK in head:
        return APPLICATION_FORM
    if external_source == SYSTEM_SOURCE or _AUTOMATCH_RE.search(head):
        return AUTOMATCH
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
    # Forma Delivery Leada z listą rekrutacji ma wyższy limit, ale tylko gdy
    # nie mówi nic o kandydacie.
    substance = bool(_SUBSTANCE_RE.search(head))
    if (
        (length < _DL_RATE_MAX_CHARS and _DL_RATE_RE.search(head))
        or (
            length < _DL_RATE_LIST_MAX_CHARS
            and not substance
            and _DL_RATE_RE.search(head)
        )
        or (
            length < _DL_RATE_MAX_CHARS and not substance and _SENT_RATE_RE.search(head)
        )
        or _DL_PAIR_RE.match(head)
        or _DL_BARE_RE.match(head)
    ):
        return DL_RATE
    if _FACT_RATE_RE.search(head) and _FACT_OTHER_RE.search(head):
        return SCREENING_FACTS
    if _QA_RE.search(head):
        return CARD
    if (_DL_PASS_RE.search(head) and length < 400) or (
        length < 300 and _HAS_MENTION_RE.search(head) and _DL_FIX_RE.search(head)
    ):
        return DL_REVIEW
    # „nie odbiera, ale stawkę ma 200” to już fakt — liczba zostawia notatkę.
    if (
        length < 80
        and not substance
        and _CONTACT_RE.match(head)
        and not _TWO_DIGITS_RE.search(head)
    ):
        return CONTACT_ATTEMPT
    if (
        length < 400
        and not substance
        and _SCHEDULE_WORD_RE.search(head)
        and _CLOCK_RE.search(head)
    ):
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


def facts_readable_sql(alias: str = "") -> str:
    """Warunek SQL dla nocnego odczytu faktów (``FACTS_EXCLUDED_KINDS``)."""
    col = f"{alias}." if alias else ""
    return f"({col}kind = '{APPLICATION_FORM}' OR {_sql_filter(alias, FACTS_EXCLUDED_KINDS)})"


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


def not_automat_clause():
    """Zapytania ORM po ``Note``: bez wpisów automatów (podgląd, „ostatnia notatka”)."""
    return _orm_filter(AUTOMAT_KINDS)


def talks_clause():
    """Zapytania ORM po ``Note``: notatki z zakładki „Rozmowy” (``GROUP_TALKS``).

    „Ostatnia rozmowa” na liście kandydatów i w szybkim podglądzie — bez prób
    kontaktu, wpisów Delivery Leada, maili i automatu.
    """
    return _orm_filter(frozenset(_GROUP_BY_KIND))


def real_contact_clause():
    """Zapytania ORM po ``Note``: notatka, która znaczy „rozmawialiśmy”.

    Filtr „Kontakt z kandydatem” (nowa semantyka): próba kontaktu, wpis
    automatu, uwaga Delivery Leada i sama wzmianka nie są kontaktem. Mail
    i ustalenie terminu są.
    """
    return _orm_filter(CONTACT_EXCLUDED_KINDS)


def hides_client_rate(kind: Optional[str]) -> bool:
    """Czy treść notatki tego rodzaju niesie stawkę do klienta."""
    return kind in CLIENT_RATE_KINDS
