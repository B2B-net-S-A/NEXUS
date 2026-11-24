"""Bramka przetargów: reguły z instrukcji Kingi, edytowalne bez programisty.

Ogłoszenie wchodzi do bramki, gdy tytuł ma frazę z listy albo główny kod CPV
zaczyna się od kodu usług IT. Potem odpada, w tej kolejności: nie jest usługą
(dostawa, roboty budowlane), przedmiot ma słowo z listy odrzucanych,
zamawiający ma słowo z listy odrzucanych, termin składania ofert minął.

Dopasowanie słowa jest odporne na odmianę i polskie znaki: „umowa ramowa”
znajdzie „umowy ramowej”, „szkolenie” — „szkoleń”, bo liczy się rdzeń słowa (bez
końcowych samogłosek) z końcówką zaczynającą się od samogłoski. Słowo pochodne
już nie pasuje: „dostawa” nie łapie „dostawcy”. Skrót wielkimi literami jako cała fraza („IT”,
„DORA”, „MPK”) pasuje tylko dosłownie, bo „it” bywa zwykłym słowem. Reguły leżą
w ``app_settings`` pod ``RULES_KEY``; bez wpisu obowiązują wartości domyślne.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

RULES_KEY = "sales_tender_rules"

#: Frazy z instrukcji Kingi (Biznes Polska, „słowa kluczowe”).
DEFAULT_PHRASES: tuple[str, ...] = (
    "IT",
    "body leasing",
    "team leasing",
    "developer",
    "programista",
    "zespół IT",
    "specjalista IT",
    "rekrutacja IT",
    "outsourcing",
    "umowa ramowa",
    "cloud",
    "cybersecurity",
    "testy penetracyjne",
    "migracja",
    "DORA",
    "NIS 2",
)
#: „Jakie przedmioty ogłoszeń odrzucam” z instrukcji Kingi.
DEFAULT_REJECT_SUBJECT: tuple[str, ...] = (
    "dostawa",
    "zakup",
    "licencja",
    "subskrypcja",
    "szkolenie",
    "sprzęt",
    "urządzenie",
    "wyposażenie",
    # „zakup dostępów”, „odnowienie subskrypcji”, „przedłużenie licencji”: tytuły
    # mówią „Usługa dostępu do…”, „Odnowienie wsparcia…” bez słowa „zakup”.
    "dostęp",
    "odnowienie",
    "przedłużenie",
)
#: „Jakich zamawiających odrzucam”; wielkość zamówienia oceni dopiero Analityk.
DEFAULT_REJECT_BUYER: tuple[str, ...] = (
    "gmina",
    "urząd gminy",
    "starostwo",
    "powiat",
    "szkoła",
    "przedszkole",
    "uczelnia",
    "uniwersytet",
    "politechnika",
    "akademia",
    "szpital",
    "SP ZOZ",
    "SPZOZ",
    "przychodnia",
    "dom kultury",
    "biblioteka",
    "muzeum",
    "ośrodek pomocy społecznej",
    "spółdzielnia",
    "wodociągi",
    "MPK",
    "MPGK",
)
#: Usługi IT (72…, bez 721 — doradztwo sprzętowe) oraz dostarczanie personelu
#: i pośrednictwo pracy (7962…, 7961…), gdzie trafia body leasing.
IT_CPV_PREFIXES: tuple[str, ...] = (
    "720",
    "722",
    "723",
    "724",
    "725",
    "726",
    "727",
    "728",
    "729",
    "7961",
    "7962",
)

MAX_ITEMS = 80
MAX_ITEM_CHARS = 60

#: Nazwy reguł odsiewu na ekranie.
RULE_LABELS: dict[str, str] = {
    "order_type": "Nie usługa",
    "subject": "Przedmiot",
    "buyer": "Zamawiający",
    "expired": "Termin minął",
}
ORDER_TYPE_LABELS: dict[str, str] = {
    "supplies": "dostawa",
    "works": "roboty budowlane",
}

_VOWELS = "aeiouy"
_FOLD = str.maketrans({"ł": "l", "Ł": "L"})
_SEPARATOR = r"[\s\-–/]+"


@dataclass(frozen=True)
class TenderRules:
    phrases: tuple[str, ...] = DEFAULT_PHRASES
    reject_subject: tuple[str, ...] = DEFAULT_REJECT_SUBJECT
    reject_buyer: tuple[str, ...] = DEFAULT_REJECT_BUYER
    only_services: bool = True
    #: Opiekun szans zakładanych przez bramkę; ``None`` = „Bez opiekuna”.
    owner_user_id: Optional[int] = None


@dataclass(frozen=True)
class Notice:
    """Ogłoszenie z rejestru w jednym kształcie dla BZP i TED."""

    source: str
    number: str
    title: str
    buyer_name: str
    published_at: datetime
    buyer_nip: Optional[str] = None
    buyer_city: Optional[str] = None
    cpv_codes: tuple[str, ...] = ()
    cpv_label: Optional[str] = None
    order_type: Optional[str] = None
    url: Optional[str] = None
    deadline_date: Optional[date] = None
    deadline_at: Optional[datetime] = None
    below_eu: Optional[bool] = None
    #: Identyfikator postępowania: TED ``procedure-identifier``, BZP ``tenderId``.
    #: Kolejna publikacja tego samego postępowania to zmiana, nie nowy przetarg.
    procedure_id: Optional[str] = None


@dataclass(frozen=True)
class Decision:
    """Wynik bramki dla ogłoszenia, które przeszło frazy albo kody CPV."""

    passed: bool
    match: str
    rule: Optional[str] = None
    detail: Optional[str] = None


def fold(text: str) -> str:
    """Małe litery bez polskich znaków („Szkoleń” → „szkolen”)."""

    decomposed = unicodedata.normalize("NFKD", text.translate(_FOLD).lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _is_acronym(token: str) -> bool:
    letters = [ch for ch in token if ch.isalpha()]
    return bool(letters) and token.isupper() and len(token) <= 5


def _token_pattern(token: str, *, last: bool) -> str:
    """Wzorzec słowa na tekście bez polskich znaków; granica słowa tylko na końcu frazy,
    bo w środku pilnuje jej separator, a liczba może być doklejona („NIS2”)."""

    folded = fold(token)
    end = r"(?!\w)" if last else ""
    if folded.isdigit() or len(folded) <= 3:
        return re.escape(folded) + end
    stem = folded.rstrip(_VOWELS)
    if len(stem) < 4:
        stem = folded
    # Po rdzeniu tylko końcówka od samogłoski: „dostaw” łapie „dostawy”, „dostawę”,
    # „dostaw”, ale nie „dostawcy” — inne słowo („Wybór dostawcy usługi SOC”).
    return re.escape(stem) + rf"(?:[{_VOWELS}]\w*)?(?!\w)"


@lru_cache(maxsize=512)
def _compile(phrase: str) -> tuple[bool, re.Pattern[str]]:
    """(czy dopasować do oryginału z wielkością liter, wzorzec)."""

    tokens = phrase.split()
    if len(tokens) == 1 and _is_acronym(tokens[0]):
        return True, re.compile(rf"(?<!\w){re.escape(tokens[0])}(?!\w)")
    parts: list[str] = []
    for index, token in enumerate(tokens):
        if index:
            parts.append(r"[\s\-]*" if fold(token).isdigit() else _SEPARATOR)
        parts.append(_token_pattern(token, last=index == len(tokens) - 1))
    return False, re.compile(r"(?<!\w)" + "".join(parts))


def first_match(text: str, phrases: tuple[str, ...]) -> Optional[str]:
    """Pierwsza fraza z listy, która występuje w tekście."""

    if not text:
        return None
    folded = fold(text)
    for phrase in phrases:
        if not phrase.split():
            continue
        exact, pattern = _compile(phrase)
        if pattern.search(text if exact else folded):
            return phrase
    return None


def it_match(notice: Notice, rules: TenderRules) -> Optional[str]:
    """Fraza albo kod CPV, przez które ogłoszenie wchodzi do bramki."""

    phrase = first_match(notice.title, rules.phrases)
    if phrase is not None:
        return f"fraza „{phrase}”"
    for code in notice.cpv_codes:
        if code.startswith(IT_CPV_PREFIXES):
            return f"CPV {code}"
    return None


def evaluate(
    notice: Notice, rules: TenderRules, *, today: date, now: datetime
) -> Optional[Decision]:
    """``None`` — ogłoszenie spoza IT (nie trafia do bazy); inaczej decyzja bramki."""

    match = it_match(notice, rules)
    if match is None:
        return None
    if rules.only_services and notice.order_type not in (None, "services"):
        label = ORDER_TYPE_LABELS.get(notice.order_type or "", notice.order_type)
        return Decision(False, match, "order_type", label)
    subject = first_match(notice.title, rules.reject_subject)
    if subject is not None:
        return Decision(False, match, "subject", subject)
    buyer = first_match(notice.buyer_name, rules.reject_buyer)
    if buyer is not None:
        return Decision(False, match, "buyer", buyer)
    if is_expired(notice, today=today, now=now):
        return Decision(False, match, "expired", None)
    return Decision(True, match)


def is_expired(notice: Notice, *, today: date, now: datetime) -> bool:
    if notice.deadline_at is not None:
        return notice.deadline_at <= now
    return notice.deadline_date is not None and notice.deadline_date < today


def _clean_list(values: Any) -> tuple[str, ...]:
    """Lista z ekranu: bez pustych, bez powtórek (bez wielkości liter), z limitem."""

    if not isinstance(values, (list, tuple)):
        return ()
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = " ".join(str(value).split())[:MAX_ITEM_CHARS]
        key = fold(item)
        if item and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return tuple(cleaned[:MAX_ITEMS])


def from_value(value: Any) -> TenderRules:
    """Reguły z wpisu ``app_settings``; brakujące pole bierze wartość domyślną."""

    if not isinstance(value, dict):
        return TenderRules()
    rules = TenderRules()
    for name in ("phrases", "reject_subject", "reject_buyer"):
        if name in value:
            rules = replace(rules, **{name: _clean_list(value[name])})
    if isinstance(value.get("only_services"), bool):
        rules = replace(rules, only_services=value["only_services"])
    owner = value.get("owner_user_id")
    if isinstance(owner, int) and not isinstance(owner, bool):
        rules = replace(rules, owner_user_id=owner)
    return rules


def to_value(rules: TenderRules) -> dict[str, Any]:
    return {
        "phrases": list(rules.phrases),
        "reject_subject": list(rules.reject_subject),
        "reject_buyer": list(rules.reject_buyer),
        "only_services": rules.only_services,
        "owner_user_id": rules.owner_user_id,
    }


async def load(db: AsyncSession) -> TenderRules:
    row = await db.get(AppSetting, RULES_KEY)
    return from_value(row.value if row is not None else None)


async def save(
    db: AsyncSession, rules: TenderRules, *, user_id: Optional[int]
) -> TenderRules:
    """Zapisz reguły (po ``_clean_list``); commit robi wywołujący."""

    cleaned = from_value(to_value(rules))
    row = await db.get(AppSetting, RULES_KEY, with_for_update=True)
    if row is None:
        db.add(AppSetting(key=RULES_KEY, value=to_value(cleaned), updated_by=user_id))
    else:
        row.value = to_value(cleaned)
        row.updated_by = user_id
    return cleaned
