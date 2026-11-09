"""Sprzedaż → „Kogo znamy”: inne nazwy firmy z CV (P8, 09.11.2026).

Nazwy w CV są pisane różnie, a dopasowanie panelu jest dokładne po nazwie
kanonicznej, więc „mBank Hipoteczny” i „BRE Bank” nie doliczają się do karty
mBanku. Handlowiec patrzy na kartę i decyduje: „Dołącz” albo „Nie ta firma”.
Bez modelu AI i bez kolejki, bo to podpowiedź z tekstu CV, a decyzję podejmuje
człowiek w miejscu użycia.

Wariant powstaje na dwa sposoby:

- **Ta sama marka**: nazwa kanoniczna z CV zaczyna się od nazwy karty bez
  końcówek typu „Bank Polska”, „S.A.”. Gdy z karty zostaje jeden wyraz
  („Nordea Bank Abp” → „nordea”), za nim wolno stać już tylko takim końcówkom,
  bo sam pierwszy wyraz nie odróżnia firmy: „Credit Agricole” to nie „Credit
  Suisse”, a „Narodowy Bank Polski” to nie „Narodowy Fundusz Zdrowia”.
- **Most w jednym wpisie**: wpis „mBank (BRE Bank S.A.)” łączy nazwę karty
  z dokładnie jedną inną nazwą. Takiej nazwy nie da się znaleźć po marce, więc
  liczy się osobno, gdy łączą ją co najmniej trzy osoby i gdy co najmniej połowa
  osób z takimi wpisami przy tej nazwie wskazuje tę kartę. Pośrednik („7N / mBank”,
  „7N / Roche”) ma wielu klientów, więc mostem nie jest. Lista pracodawców
  („mBank, ING, Orange”) też nie.

Decyzje czyta serwer (``joined_names``) poza limitem 10 nazw z API dla CRM.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import String, bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCompanyAlias
from app.services.company_names import entry_says_current, normalize_company_name
from app.services.experience_end import is_current_end
from app.services.polish_ilike import contains_pattern

JOINED = "joined"
REJECTED = "rejected"

#: Najkrótsza nazwa kanoniczna, jak w ``integrations_companies._MIN_NAME_LEN``.
MIN_NAME_LEN = 3
#: Ile największych wariantów pokazuje pas na karcie.
TOP_VARIANTS = 3
#: Most liczy się od trzech różnych osób, bo przy dwóch przechodzi pośrednik
#: („mBank (7N CIM)”), którego inni klienci nie wyjdą w CV.
MIN_BRIDGE_PEOPLE = 3
MAX_BRIDGES = 10
MAX_OWN_CARDS = 5
#: Sufit wierszy skanu; przy ogólnej marce podpowiedź jest niepełna, ale szybka.
CV_ROW_CAP = 20000
STATEMENT_TIMEOUT_MS = 8000

_BRAND_MIN_LEN = 4
_GENERIC_FIRST_WORDS = frozenset(
    """bank grupa group polska poland the firma centrum software solutions it tech
    technology systems data global new digital consulting services energy smart best
    first general national international polski polskie instytut urzad miasto power
    info inter euro pro art net web next open one my""".split()
)

#: Końcówki, które nie odróżniają firmy: forma prawna, kraj, „bank”, „grupa”.
_DESCRIPTOR_WORDS = frozenset(
    """bank banku polska polski polskie polsce poland pl group grupa holding
    oddzial branch w sa spa ag ab abp publ asa se nv bv plc llc ltd limited inc
    corp gmbh kg sp z o oo spolka akcyjna""".split()
)

# Nazwy kanoniczne (po ``normalize_company_name``), czyli bez ogonków.
_NON_EMPLOYER_WORDS = re.compile(
    r"(?:^| )(?:freelanc\w*|self employ\w*|samozatrudn\w*|wlasna dzialalnosc"
    r"|dzialalnosc gospodarcza|jdg|nda|confidential|poufn\w*|student\w*"
    r"|uniwersytet\w*|university|politechnik\w*|akademi\w*|academy|szkol\w*|school"
    r"|liceum|technikum|uczelni\w*|college|wyzsza)(?: |$)"
)
_NON_EMPLOYER_EXACT = frozenset({"n a", "brak", "contractor", "independent"})

#: Nasza firma pod nazwami z CV i kartoteki. Listy osób ani wariantów nie ma sensu.
OWN_COMPANY_NAMES: frozenset[str] = frozenset(
    {"b2b network", "b2bnetwork", "b2b net", "b2bnet", "dynaminds"}
)

_ENTRY_PARTS = re.compile(r"[/(),;|\n]|\s[-–—]\s")

_CV_ENTRIES_SQL = text(
    """SELECT c.id AS candidate_id, e.elem->>'company' AS company,
           e.elem->>'start' AS start_, e.elem->>'end' AS end_
    FROM candidates c,
         jsonb_array_elements(
             CASE WHEN jsonb_typeof(c.experience) = 'array'
             THEN c.experience ELSE '[]'::jsonb END
         ) AS e(elem)
    WHERE lower(coalesce(e.elem->>'company', '')) LIKE ANY(:patterns)
    LIMIT :cap"""
).bindparams(bindparam("patterns", type_=ARRAY(String)))


@dataclass(frozen=True)
class CvEntry:
    """Jeden wpis doświadczenia, którego nazwa przeszła prefiltr."""

    candidate_id: int
    company: str
    start: Optional[str]
    end: Optional[str]


@dataclass
class Variant:
    """Nazwa z CV z osobami, które ją mają."""

    key: str
    people: set[int] = field(default_factory=set)
    current: set[int] = field(default_factory=set)
    spellings: Counter[str] = field(default_factory=Counter)

    @property
    def name(self) -> str:
        return self.spellings.most_common(1)[0][0]

    @property
    def people_count(self) -> int:
        return len(self.people)

    @property
    def current_count(self) -> int:
        return len(self.current)


@dataclass(frozen=True)
class Collected:
    variants: dict[str, Variant]
    bridges: dict[str, set[int]]


@dataclass(frozen=True)
class RestSummary:
    count: int = 0
    fewest: int = 0
    most: int = 0


def is_non_employer(canonical: str) -> bool:
    """Freelance, NDA, szkoły: nazwy, które nie są pracodawcą."""
    return canonical in _NON_EMPLOYER_EXACT or bool(
        _NON_EMPLOYER_WORDS.search(canonical)
    )


def is_own_company(canonical: str) -> bool:
    """Nasza własna firma, także z dopiskiem („B2B Network - projekty”)."""
    return any(
        canonical == own or canonical.startswith(f"{own} ") for own in OWN_COMPANY_NAMES
    )


def can_be_alias(canonical: str) -> bool:
    """Czy nazwę wolno doliczyć do karty firmy."""
    return (
        len(canonical) >= MIN_NAME_LEN
        and not is_non_employer(canonical)
        and not is_own_company(canonical)
    )


def brand_of(canonical: str) -> str:
    """Nazwa bez końcówek albo cała nazwa, gdy został wyraz, który nic nie wyróżnia."""
    words = canonical.split()
    while len(words) > 1 and words[-1] in _DESCRIPTOR_WORDS:
        words.pop()
    core = " ".join(words)
    if " " in core or (
        len(core) >= _BRAND_MIN_LEN and core not in _GENERIC_FIRST_WORDS
    ):
        return core
    return canonical


def _same_firm(canonical: str, seed: str) -> bool:
    """Czy nazwa z CV to ta sama firma co nazwa karty."""
    brand = brand_of(seed)
    if canonical == brand:
        return True
    if not canonical.startswith(f"{brand} "):
        return False
    if " " in brand or (brand == seed and brand not in _GENERIC_FIRST_WORDS):
        return True
    # Z karty został jeden wyraz, więc dalszy ciąg nazwy musi niczego nie dodawać.
    return set(canonical[len(brand) + 1 :].split()) <= _DESCRIPTOR_WORDS


def anchors_of(seeds: set[str]) -> set[str]:
    """Nazwy, po których wpis z dwiema częściami uznajemy za powiązany z kartą."""
    return seeds | {brand_of(seed) for seed in seeds}


def _entry_pair(raw: str) -> Optional[tuple[str, str]]:
    """Obie nazwy z wpisu, który ma dokładnie dwie części."""
    parts = [
        normalize_company_name(part)
        for part in _ENTRY_PARTS.split(raw)
        if part and part.strip()
    ]
    return (parts[0], parts[1]) if len(parts) == 2 else None


def _bridged_name(raw: str, anchors: set[str]) -> Optional[str]:
    """Druga nazwa z wpisu, który ma dokładnie dwie części, w tym nazwę karty."""
    pair = _entry_pair(raw)
    if pair is None:
        return None
    first, second = pair
    if first in anchors and second not in anchors:
        return second
    if second in anchors and first not in anchors:
        return first
    return None


def _add(variants: dict[str, Variant], key: str, entry: CvEntry) -> None:
    variant = variants.setdefault(key, Variant(key=key))
    variant.people.add(entry.candidate_id)
    variant.spellings[entry.company.strip()] += 1
    if is_current_end(entry.end) and entry_says_current(
        {"start": entry.start, "end": entry.end}
    ):
        variant.current.add(entry.candidate_id)


def collect(
    entries: Iterable[CvEntry], *, seeds: set[str], skip: set[str]
) -> Collected:
    """Warianty po marce i kandydaci na most z wpisów CV.

    ``seeds`` to nazwy kanoniczne karty, ``skip`` to nazwy już doliczone
    albo już rozstrzygnięte przez handlowca.
    """
    anchors = anchors_of(seeds)
    excluded = seeds | skip
    variants: dict[str, Variant] = {}
    bridges: dict[str, set[int]] = defaultdict(set)
    for entry in entries:
        canonical = normalize_company_name(entry.company)
        # Wpis z kilkoma częściami to lista firm albo opis, a nie inna nazwa karty.
        if (
            canonical not in excluded
            and not _ENTRY_PARTS.search(entry.company.strip())
            and can_be_alias(canonical)
            and any(_same_firm(canonical, seed) for seed in seeds)
        ):
            _add(variants, canonical, entry)
        other = _bridged_name(entry.company, anchors)
        if other and other not in excluded and can_be_alias(other):
            bridges[other].add(entry.candidate_id)
    return Collected(variants=variants, bridges=dict(bridges))


def exact_variants(entries: Iterable[CvEntry], names: set[str]) -> dict[str, Variant]:
    """Osoby przy dokładnie tych nazwach kanonicznych (nazwy mostów)."""
    variants: dict[str, Variant] = {}
    for entry in entries:
        canonical = normalize_company_name(entry.company)
        if canonical in names:
            _add(variants, canonical, entry)
    return variants


def supported_bridges(bridges: dict[str, set[int]]) -> list[str]:
    """Nazwy mostów z wystarczającym poparciem, najpierw te z największym."""
    supported = [
        name for name, people in bridges.items() if len(people) >= MIN_BRIDGE_PEOPLE
    ]
    supported.sort(key=lambda name: (-len(bridges[name]), name))
    return supported[:MAX_BRIDGES]


def names_mostly_bridged(
    entries: Iterable[CvEntry], names: Sequence[str], *, anchors: set[str]
) -> list[str]:
    """Nazwy, których wpisy z dwiema częściami prowadzą głównie do tej karty.

    ``entries`` to wszystkie wpisy CV z tymi nazwami, nie tylko te z nazwą karty.
    """
    with_card: dict[str, set[int]] = defaultdict(set)
    with_others: dict[str, set[int]] = defaultdict(set)
    for entry in entries:
        pair = _entry_pair(entry.company)
        if pair is None:
            continue
        for name, partner in (pair, pair[::-1]):
            if name in names:
                side = with_card if partner in anchors else with_others
                side[name].add(entry.candidate_id)
    return [
        name
        for name in names
        if with_card[name]
        and len(with_card[name]) >= len(with_others[name] - with_card[name])
    ]


def rank(variants: dict[str, Variant]) -> tuple[list[Variant], RestSummary]:
    """Trzy największe warianty i podsumowanie pozostałych."""
    ordered = sorted(variants.values(), key=lambda v: (-v.people_count, v.key))
    top, rest = ordered[:TOP_VARIANTS], ordered[TOP_VARIANTS:]
    if not rest:
        return top, RestSummary()
    sizes = [variant.people_count for variant in rest]
    return top, RestSummary(count=len(rest), fewest=min(sizes), most=max(sizes))


def search_patterns(raw_names: Sequence[str], *, whole: bool = False) -> list[str]:
    """Wzorce ``LIKE`` dla marek nazw; surowa pisownia łapie polskie znaki.

    SQL-owe ``lower()`` nie zdejmuje ogonków tak jak ``normalize_company_name``,
    więc „żabka” w CV pasuje tylko do surowego zapisu.
    """
    patterns: dict[str, None] = {}
    for raw in raw_names:
        canonical = normalize_company_name(raw)
        if len(canonical) < MIN_NAME_LEN:
            continue
        brand = canonical if whole else brand_of(canonical)
        patterns[contains_pattern(brand)] = None
        words = raw.strip().lower().split()
        patterns[contains_pattern(" ".join(words[: len(brand.split())]))] = None
    return list(patterns)


async def scan_cv_entries(db: AsyncSession, patterns: list[str]) -> list[CvEntry]:
    """Wpisy CV o nazwach pasujących do wzorców, jednym ``LIKE ANY``."""
    if not patterns:
        return []
    rows = await db.execute(
        _CV_ENTRIES_SQL.bindparams(patterns=patterns, cap=CV_ROW_CAP)
    )
    return [
        CvEntry(
            candidate_id=row.candidate_id,
            company=row.company,
            start=row.start_,
            end=row.end_,
        )
        for row in rows
    ]


async def decisions(db: AsyncSession, company_id: int) -> list[SalesCompanyAlias]:
    """Decyzje handlowców przy tej karcie, od najstarszej."""
    return list(
        (
            await db.execute(
                select(SalesCompanyAlias)
                .where(SalesCompanyAlias.company_id == company_id)
                .order_by(SalesCompanyAlias.id)
            )
        ).scalars()
    )


async def joined_names(db: AsyncSession, company_id: int) -> list[str]:
    """Nazwy dołączone do karty, dla dopasowania osób i klienta."""
    return [
        row.alias for row in await decisions(db, company_id) if row.status == JOINED
    ]
