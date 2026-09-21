"""Jedna semantyka filtrów dla OBU silników wyszukiwania kandydatów.

NEXUS ma dwa silniki, które UI połączy w jeden ekran „Kandydaci":

* **L** — lista ``GET /api/candidates`` (``app/api/candidates.py``; także ⌘K,
  eksport i alerty zapisanych wyszukiwań),
* **S** — wyszukiwarka ``POST /api/search/candidates`` (+ ``/diagnostics``;
  ``app/api/search.py`` + ``structured_candidate_search``).

Do 09.2026 każdy miał własne kopie tych samych filtrów i rozjeżdżały się one
w 11 udokumentowanych miejscach (``docs/sesja-2026-07-28-completion-report.md``).
Ten moduł jest JEDYNYM miejscem, w którym wolno zbudować predykat dla:
umiejętności (trzy kubełki), tekstu ``q`` (tryb + dopasowanie dosłowne),
„Otwarty na", kategorii kompetencji, stawki godzinowej, lat doświadczenia,
tagów, lokalizacji/kraju, grup ``q_all``/``q_any``/``q_none`` oraz statusu
i dostępności. Oba endpointy czytają te filtry WYŁĄCZNIE stąd; pilnuje tego
``tests/test_search_engines_contract.py`` (wyniki) i
``tests/test_candidate_search_predicates.py`` (struktura).

Decyzje właściciela produktu (09.2026) — wiążące dla obu endpointów:

==================  =========================================================
Umiejętności        „Musi mieć" = filtr TWARDY · „Mile widziane" = tylko
                    ranking · „Wyklucz" = filtr TWARDY. Bez kubełka → „Musi
                    mieć". Pola legacy zachowują dotychczasowe znaczenie
                    (patrz ``skill_buckets_from_list`` / ``…_from_search``).
Tekst ``q``         auto: nazwisko / e-mail / telefon → dopasowanie dosłowne,
                    reszta → dotychczasowa ścieżka silnika. Jawne ``text_mode``.
„Otwarty na"        LUB (którykolwiek z zaznaczonych).
Kategoria           główna LUB poboczna (M2M) LUB legacy FK.
Stawka godzinowa    kandydat BEZ stawki przechodzi.
Lata doświadczenia  jedna reguła: dokładna liczba, a gdy jej brak — przedział
                    z danych Traffita; nakładanie się przedziałów.
Tagi                cały tag, nie podłańcuch.
Lokalizacja         znaki ``%``/``_`` dosłownie; filtr kraju w obu.
Grupy ``q_*``       jeden parser.
==================  =========================================================

Moduł jest czysty: buduje klauzule SQLAlchemy, nie dotyka sesji. Jedyny wyjątek
to ``prepare_literal_text`` — ustawia ``pg_trgm.similarity_threshold`` dla
gałęzi literówek i dlatego potrzebuje połączenia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from functools import reduce
from typing import Any, Iterable, Literal, Optional, Sequence

from sqlalchemy import String, and_, case, cast, func, literal, not_, or_, select, text
from sqlalchemy.sql import ColumnElement

from app.models.candidate import Candidate
from app.services.advanced_candidate_search import (
    build_advanced_filter,
    single_phrase_filter,
)
from app.services.candidate_profile_rate import (
    canonical_profile_rate_currency_clause,
)
from app.services.polish_ilike import polish_folded_ilike

# ═══════════════════════════════════════════════════════════════════════════
# Umiejętności
# ═══════════════════════════════════════════════════════════════════════════

_MAX_SKILLS_PER_BUCKET = 40


def skills_text() -> ColumnElement:
    """Zrzut JSONB ``skills`` + ``verified_tech`` + ``tags`` jako tekst.

    Umiejętności bywają listą stringów albo listą słowników
    (``{name, level, years}``); rzutowanie na ``text`` daje surowy JSON, który
    pokrywa oba kształty. Trzy kolumny — tak jak lista kandydatów robiła od
    zawsze; dopóki powierzchnie brały różne zbiory kolumn, ten sam filtr dawał
    różne wyniki zależnie od ekranu.
    """
    return (
        func.coalesce(cast(Candidate.skills, String), "")
        + " "
        + func.coalesce(cast(Candidate.verified_tech, String), "")
        + " "
        + func.coalesce(cast(Candidate.tags, String), "")
    )


def _json_token_match(blob: ColumnElement, needles: Sequence[str]) -> ColumnElement:
    """``blob`` zawiera którąkolwiek igłę jako CAŁY token JSON.

    Zrzut JSONB to JSON, więc każda wartość stoi w cudzysłowach — wymaganie ich
    zamienia test podłańcuchowy na test całego tokenu (``"go"`` nie trafia
    w ``"django"``). DWA kodowania: część wierszy trzyma JSON podwójnie
    zakodowany (string JSON wewnątrz JSONB), gdzie granicą tokenu jest ``\\"``.
    ``strpos`` zamiast ``ILIKE`` świadomie — LIKE traktuje ``\\`` jako znak
    ucieczki i wzorzec na podwójne kodowanie degeneruje się po cichu; ``strpos``
    nie ma ani znaków ucieczki, ani wieloznaczników.
    """  # noqa: D301
    conditions: list[ColumnElement] = []
    for needle in needles:
        conditions.append(func.strpos(blob, f'"{needle}"') > 0)
        conditions.append(func.strpos(blob, f'\\"{needle}\\"') > 0)
    return or_(*conditions)


def skill_match(skill: str) -> ColumnElement:
    """Kandydat MA umiejętność — cały token, oba kodowania, rodzina aliasów.

    Zmierzone na produkcji 28.07.2026: goły ``%Go%`` przy „nie ma Go" wycinał
    196 osób, z których Go znało 15 (reszta: Django, MongoDB, Golang). Rodzina
    aliasów jest rozwijana TUTAJ (``mssql`` / ``ms sql`` / ``sql server`` …),
    bo dane kandydatów nie są kanonizowane; alternatywa siedzi wewnątrz
    predykatu, więc koniunkcja działa MIĘDZY umiejętnościami, nie między
    pisowniami tej samej.

    Ograniczenie świadome: w kształcie słownikowym zrzut zawiera też klucze
    ``"name"``/``"level"``/``"years"`` — chip nazwany jak klucz trafi sam
    w siebie. Właściwe rozwiązanie (złączenie z ``cortex_skill_facts``) wymaga
    pokrycia Cortexa powyżej ~60%.
    """
    # Import lokalny: `scoring_service` importuje modele i schematy, a ten moduł
    # ładuje się z `candidates.py` — import na górze pliku domyka cykl.
    from app.services.scoring_service import skill_name_variants

    needles = [w for w in skill_name_variants([skill]) if w] or [skill.lower()]
    return _json_token_match(func.lower(skills_text()), needles)


def split_pipe_group(value: str) -> list[str]:
    """``"python|java"`` → ``["python", "java"]`` (format drutu grupy LUB)."""
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def _dedupe_ci(terms: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(term)
    return out


# ── Parser wyrażenia (port `frontend/src/lib/skill-expression.ts`) ──────────
# Parytet pilnuje wspólny plik przypadków:
# `frontend/src/lib/__fixtures__/skill-expression-cases.json` — czyta go vitest
# i `tests/test_candidate_search_predicates.py`.

_EXPR_OPERATORS = {"and", "or", "not"}


def _is_separator(ch: str) -> bool:
    return ch.isspace() or ch == ","


def _tokenize_expression(expr: str) -> list[tuple[str, bool, bool]]:
    """→ lista ``(tekst, quoted, neg)``; lustro ``tokenize`` z frontu."""
    tokens: list[tuple[str, bool, bool]] = []
    n = len(expr)
    i = 0
    while i < n:
        while i < n and _is_separator(expr[i]):
            i += 1
        if i >= n:
            break
        neg = False
        if expr[i] == "-":
            neg = True
            i += 1
        if i < n and expr[i] == '"':
            i += 1
            start = i
            while i < n and expr[i] != '"':
                i += 1
            tokens.append((expr[start:i], True, neg))
            if i < n:
                i += 1
        else:
            start = i
            while i < n and not _is_separator(expr[i]):
                i += 1
            if i > start:
                tokens.append((expr[start:i], False, neg))
    return tokens


@dataclass(frozen=True)
class ParsedSkillExpression:
    """Wynik parsera — nazwy pól jak w ``SkillBuckets`` z frontu."""

    must: tuple[str, ...] = ()
    any_groups: tuple[tuple[str, ...], ...] = ()
    none: tuple[str, ...] = ()

    def as_wire(self) -> dict[str, Any]:
        return {
            "must": list(self.must),
            "anyGroups": [list(g) for g in self.any_groups],
            "none": list(self.none),
        }


def parse_skill_expression(expr: Optional[str]) -> ParsedSkillExpression:
    """``Python OR Java NOT PHP`` → kubełki. Gramatyka lewostronna, bez
    priorytetów: spacja/przecinek/``AND`` = nowy termin, ``OR`` dokleja do
    poprzedniej grupy, ``NOT``/``-`` wyklucza następny termin, ``"dwa słowa"``
    to jeden termin. Termin bez operatora trafia do „Musi mieć".

    Lustro 1:1 parsera z frontu — BEZ rozwijania ``|``. Format drutu ``a|b``
    rozumie warstwa kubełków (``_normalize_buckets``), wspólna dla wszystkich
    pól, więc wyrażenie ``python|java`` i tak kończy jako grupa LUB.
    """
    groups: list[list[str]] = []
    none: list[str] = []
    or_pending = False
    not_pending = False

    for raw, quoted, neg in _tokenize_expression(expr or ""):
        lower = raw.lower()
        if not quoted and lower in _EXPR_OPERATORS:
            if lower == "or":
                or_pending = True
            elif lower == "not":
                not_pending = True
            else:
                or_pending = False
            continue
        term = " ".join(raw.split())
        if not term:
            continue
        if neg or not_pending:
            not_pending = False
            or_pending = False
            if term.lower() not in {x.lower() for x in none}:
                none.append(term)
        else:
            if or_pending and groups:
                groups[-1].append(term)
            else:
                groups.append([term])
            or_pending = False

    must: list[str] = []
    any_groups: list[tuple[str, ...]] = []
    for group in groups:
        uniq = _dedupe_ci(group)
        if len(uniq) == 1:
            if uniq[0].lower() not in {x.lower() for x in must}:
                must.append(uniq[0])
        elif uniq:
            any_groups.append(tuple(uniq))
    return ParsedSkillExpression(
        must=tuple(must), any_groups=tuple(any_groups), none=tuple(none)
    )


@dataclass(frozen=True)
class SkillBuckets:
    """Trzy kubełki umiejętności — jedyny kształt, który rozumie SQL niżej.

    * ``required``            — każda MUSI być (twardo, AND),
    * ``required_any_groups`` — z każdej grupy co najmniej jedna (twardo),
    * ``preferred``           — tylko ranking; każda pozycja to grupa LUB
      (zwykle jednoelementowa) warta 1 punkt,
    * ``excluded``            — żadnej nie może być (twardo).
    """

    required: tuple[str, ...] = ()
    required_any_groups: tuple[tuple[str, ...], ...] = ()
    preferred: tuple[tuple[str, ...], ...] = ()
    excluded: tuple[str, ...] = ()

    @property
    def has_hard(self) -> bool:
        return bool(self.required or self.required_any_groups or self.excluded)


def _canonical(names: Iterable[str]) -> list[str]:
    """Zwija pisownie do nazw kanonicznych (deduplikacja rodzin).

    Dwie pisownie tej samej umiejętności w „Musi mieć" to JEDNO wymaganie —
    bez zwinięcia ``mssql AND "sql server"`` żądałoby obu zapisów naraz.
    Samo dopasowanie i tak rozwija rodzinę (``skill_match``).
    """
    from app.services.scoring_service import canonical_skill_names

    cleaned = [n.strip() for n in names if n and n.strip()]
    return [s for s in (canonical_skill_names(cleaned) or []) if s]


def _normalize_buckets(
    required: Iterable[str],
    required_any_groups: Iterable[Iterable[str]],
    preferred: Iterable[str],
    excluded: Iterable[str],
) -> SkillBuckets:
    """Wspólna normalizacja: ``|`` = grupa LUB w KAŻDYM polu, zwinięcie rodzin,
    limit rozmiaru (obrona przed rozdmuchanym planem zapytania)."""
    must: list[str] = []
    groups: list[tuple[str, ...]] = []
    for entry in required:
        parts = split_pipe_group(entry)
        if len(parts) > 1:
            canon = _canonical(parts)
            if canon:
                groups.append(tuple(canon))
        elif parts:
            must.extend(parts)
    for group in required_any_groups:
        flat: list[str] = []
        for entry in group:
            flat.extend(split_pipe_group(entry))
        canon = _canonical(flat)
        if canon:
            groups.append(tuple(canon))

    soft: list[tuple[str, ...]] = []
    for entry in preferred:
        canon = _canonical(split_pipe_group(entry))
        if canon:
            soft.append(tuple(canon))

    banned: list[str] = []
    for entry in excluded:
        # NOT (a LUB b) ≡ NOT a ORAZ NOT b — grupa w „Wyklucz" się spłaszcza.
        banned.extend(split_pipe_group(entry))

    return SkillBuckets(
        required=tuple(_canonical(must)[:_MAX_SKILLS_PER_BUCKET]),
        required_any_groups=tuple(groups[:_MAX_SKILLS_PER_BUCKET]),
        preferred=tuple(soft[:_MAX_SKILLS_PER_BUCKET]),
        excluded=tuple(_canonical(banned)[:_MAX_SKILLS_PER_BUCKET]),
    )


def skill_buckets_from_list(
    *,
    skills: Optional[Sequence[str]] = None,
    skill_combine: str = "and",
    skills_any: Optional[Sequence[str]] = None,
    skills_none: Optional[Sequence[str]] = None,
    skills_required: Optional[Sequence[str]] = None,
    skills_required_any_groups: Optional[Sequence[str]] = None,
    skills_preferred: Optional[Sequence[str]] = None,
    skills_excluded: Optional[Sequence[str]] = None,
) -> SkillBuckets:
    """Parametry listy (L) → kubełki. Pola legacy zachowują TWARDE znaczenie,
    żeby zapisane wyszukiwania i alerty zwracały to samo co dotąd:

    * ``skills`` + ``skill_combine=and`` → „Musi mieć" (każda),
    * ``skills`` + ``skill_combine=or``  → jedna grupa „którakolwiek",
    * ``skills_any`` (``a|b``, powtarzane) → grupy „którakolwiek",
    * ``skills_none`` (także ``a|b``)     → „Wyklucz".

    W GET-cie grupy jadą jako powtarzany parametr z ``|`` — także nowe
    ``skills_required_any_groups``.
    """
    required: list[str] = list(skills_required or [])
    groups: list[list[str]] = [
        split_pipe_group(g) for g in (skills_required_any_groups or [])
    ]
    legacy = [s for s in (skills or []) if s and s.strip()]
    if legacy:
        if (skill_combine or "and").strip().lower() == "or":
            flat: list[str] = []
            for entry in legacy:
                flat.extend(split_pipe_group(entry))
            groups.append(flat)
        else:
            required.extend(legacy)
    groups.extend(split_pipe_group(g) for g in (skills_any or []))
    excluded = list(skills_none or []) + list(skills_excluded or [])
    return _normalize_buckets(required, groups, skills_preferred or [], excluded)


def skill_buckets_from_search(req: Any) -> SkillBuckets:
    """Żądanie wyszukiwarki (S) → kubełki. Pola legacy zachowują znaczenie
    z SEARCH-P0-03: ``skills_must`` + ``skills_any`` to sygnał RANKINGOWY
    („Mile widziane"), twarde jest tylko ``skills_none`` („Wyklucz"). Twarde
    „Musi mieć" przychodzi wyłącznie jawnymi, nowymi polami.
    """
    preferred = (
        list(getattr(req, "skills_must", None) or [])
        + list(getattr(req, "skills_any", None) or [])
        + list(getattr(req, "skills_preferred", None) or [])
    )
    excluded = list(getattr(req, "skills_none", None) or []) + list(
        getattr(req, "skills_excluded", None) or []
    )
    required = list(getattr(req, "skills_required", None) or [])
    groups = [list(g) for g in (getattr(req, "skills_required_any_groups", None) or [])]
    return _normalize_buckets(required, groups, preferred, excluded)


def skills_required_clauses(buckets: SkillBuckets) -> list[ColumnElement]:
    """„Musi mieć": każda umiejętność + z każdej grupy co najmniej jedna."""
    clauses: list[ColumnElement] = [skill_match(s) for s in buckets.required]
    for group in buckets.required_any_groups:
        clauses.append(or_(*[skill_match(s) for s in group]))
    return clauses


def skills_excluded_clauses(buckets: SkillBuckets) -> list[ColumnElement]:
    """„Wyklucz": żadnej z wymienionych."""
    return [not_(skill_match(s)) for s in buckets.excluded]


def skills_preferred_rank(buckets: SkillBuckets) -> Optional[ColumnElement]:
    """ORDER BY: ile pozycji „Mile widziane" kandydat spełnia. Nigdy nie tnie."""
    if not buckets.preferred:
        return None
    points = [
        case((or_(*[skill_match(s) for s in group]), 1), else_=0)
        for group in buckets.preferred
    ]
    return reduce(lambda a, b: a + b, points)


# ═══════════════════════════════════════════════════════════════════════════
# Tekst `q` — tryb i dopasowanie dosłowne
# ═══════════════════════════════════════════════════════════════════════════

TextMode = Literal["auto", "literal", "semantic"]

_EMAIL_RE = re.compile(r"^[^@\s]*@[^@\s]*$")
_PHONE_QUERY_RE = re.compile(r"^\+?[\d\s().\-/]+$")
_PHONE_QUERY_MIN_DIGITS = 6
_NAME_TOKEN_RE = re.compile(r"^[^\W\d_]+(?:[-'’][^\W\d_]+)*$", re.UNICODE)
_MAX_NAME_TOKENS = 3

# Słowa, które wyglądają jak imię/nazwisko (same litery), a opisują rolę,
# poziom albo tryb pracy — z nimi zapytanie jest opisem, nie osobą.
_ROLE_WORDS = frozenset(
    """
    developer dev programista programistka inżynier inzynier engineer architekt
    architect tester testerka qa analityk analityczka analyst manager menedżer
    menedzer kierownik lead leader lider senior junior mid regular expert ekspert
    specjalista specjalistka specialist konsultant konsultantka consultant admin
    administrator devops sre fullstack frontend backend mobile data scientist
    designer projektant owner master scrum product project delivery support
    helpdesk security bezpieczeństwo bezpieczenstwo cloud chmura remote zdalnie
    hybrid hybrydowo onsite stacjonarnie b2b uop kontrakt freelancer praca
    doświadczenie doswiadczenie lat lata rok znajomość znajomosc język jezyk
    angielski niemiecki polski english german with and or not oraz lub bez
    """.split()
)

# Największe miasta — wyłącznie do OPISU zapytania („rozumiem »Kraków« jako
# miasto"); nie filtruje i nie zmienia wyniku.
_KNOWN_CITIES = frozenset(
    """
    warszawa krakow kraków wroclaw wrocław poznan poznań gdansk gdańsk gdynia
    sopot lodz łódź katowice szczecin lublin bydgoszcz bialystok białystok
    rzeszow rzeszów torun toruń gliwice opole kielce olsztyn zabrze trojmiasto
    trójmiasto
    """.split()
)


def phone_digits_clause(q: str) -> Optional[ColumnElement]:
    """Dopasowanie numeru telefonu niezależne od zapisu (spacje, myślniki, +48).

    Wyszukiwanie tekstowe porównuje podciąg ZAPISANEGO tekstu, więc
    „000 000 001” nie trafiało w numer zapisany jako „000000001”. Dla zapytań
    w kształcie numeru porównujemy same cyfry po obu stronach; przy 9+ cyfrach
    bierzemy ostatnie 9 — jak ``dedup_service`` — żeby prefiks kraju po jednej
    stronie nie psuł trafienia. ``None`` dla zapytań, które numerem nie są.
    """
    if not q or not _PHONE_QUERY_RE.match(q):
        return None
    digits = re.sub(r"\D", "", q)
    if len(digits) < _PHONE_QUERY_MIN_DIGITS:
        return None
    if len(digits) >= 9:
        digits = digits[-9:]
    return func.regexp_replace(
        func.coalesce(Candidate.phone, ""), r"[^0-9]", "", "g"
    ).like(f"%{digits}%")


@dataclass(frozen=True)
class TextInterpretation:
    """„Rozumiem to jako…" — maszynowy opis tego, jak odczytano ``q``.

    ``kind``: ``email`` | ``phone`` | ``name`` | ``text`` | ``empty``.
    ``mode``: tryb wynikający z samego tekstu (``literal`` | ``semantic``);
    o tym, co endpoint faktycznie zrobił, mówi ``text_mode_applied``.
    """

    kind: str
    mode: Literal["literal", "semantic"]
    name_tokens: tuple[str, ...] = ()
    email: Optional[str] = None
    phone_digits: Optional[str] = None
    skills: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    other_tokens: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "mode": self.mode,
            "name": list(self.name_tokens),
            "email": self.email,
            "phone": self.phone_digits,
            "skills": list(self.skills),
            "locations": list(self.locations),
            "other": list(self.other_tokens),
        }


# Zapas na wypadek pustej taksonomii (start procesu, narzędzia offline, testy):
# `ALIAS_MAP` ładuje się z bazy, a bez niej jednowyrazowe „python" wyglądałoby
# jak nazwisko i odbierało wyszukiwaniu semantykę. Lista jest krótka celowo —
# źródłem prawdy pozostaje taksonomia.
_COMMON_TECH_WORDS = frozenset(
    """
    python java javascript typescript react angular vue node nodejs golang go
    rust kotlin swift php ruby scala perl sql mssql postgres postgresql mysql
    oracle mongodb redis kafka rabbitmq docker kubernetes aws azure gcp terraform
    ansible jenkins linux unix windows devops sap abap salesforce selenium
    cypress playwright django flask fastapi spring hibernate dotnet csharp cobol
    android ios flutter html css sass spark hadoop airflow snowflake databricks
    tableau powerbi excel jira confluence scrum agile itil cisco vmware git
    graphql rest microservices embedded plc scada matlab
    """.split()
)


def _known_skill(token: str) -> bool:
    from app.services.scoring_service import ALIAS_MAP

    lowered = token.lower()
    return lowered in ALIAS_MAP or lowered in _COMMON_TECH_WORDS


def detect_text_mode(q: Optional[str]) -> TextInterpretation:
    """Czy ``q`` wygląda na OSOBĘ (nazwisko / e-mail / telefon), czy na opis.

    Reguła jest celowo ostrożna w stronę „opis": fałszywe „to osoba" zabiera
    wyszukiwaniu semantykę, fałszywe „to opis" kosztuje najwyżej gorszą
    kolejność. Osoba = 1–3 wyrazy z samych liter (myślnik/apostrof dozwolony),
    z których żaden nie jest znaną umiejętnością, miastem ani słowem roli.
    """
    raw = (q or "").strip()
    if not raw:
        return TextInterpretation(kind="empty", mode="semantic")

    if "@" in raw and len(raw) > 1 and _EMAIL_RE.match(raw):
        return TextInterpretation(kind="email", mode="literal", email=raw.lower())

    if _PHONE_QUERY_RE.match(raw):
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= _PHONE_QUERY_MIN_DIGITS:
            return TextInterpretation(
                kind="phone", mode="literal", phone_digits=digits[-9:]
            )

    tokens = raw.replace(",", " ").split()
    skills = tuple(t for t in tokens if _known_skill(t))
    locations = tuple(t for t in tokens if t.lower() in _KNOWN_CITIES)
    looks_like_name = (
        1 <= len(tokens) <= _MAX_NAME_TOKENS
        and not skills
        and not locations
        and all(_NAME_TOKEN_RE.match(t) for t in tokens)
        and not any(t.lower() in _ROLE_WORDS for t in tokens)
    )
    if looks_like_name:
        return TextInterpretation(
            kind="name", mode="literal", name_tokens=tuple(tokens)
        )

    other = tuple(t for t in tokens if t not in skills and t not in locations)
    return TextInterpretation(
        kind="text",
        mode="semantic",
        skills=skills,
        locations=locations,
        other_tokens=other,
    )


def resolve_text_mode(
    requested: Optional[str], interpretation: TextInterpretation
) -> Literal["literal", "semantic"]:
    """``auto`` → z tekstu; jawne ``literal``/``semantic`` wygrywa."""
    if requested == "literal":
        return "literal"
    if requested == "semantic":
        return "semantic"
    return interpretation.mode


def literal_text_threshold(q: str) -> Optional[float]:
    """Próg trigramowy gałęzi literówek albo ``None``, gdy jej nie ma."""
    stripped = (q or "").strip()
    if len(stripped) < 3:
        return None
    return 0.5 if " " in stripped else 0.2


def literal_text_clause(q: str) -> Optional[ColumnElement]:
    """Dopasowanie DOSŁOWNE — to samo w L i w S.

    Fraza w dowolnym przeszukiwanym polu (``single_phrase_filter``: FTS-prefiks
    albo podłańcuch, wariant bez polskich znaków, notatki) + literówki
    w imieniu/nazwisku/e-mailu (gdy ≥3 znaki) + numer telefonu niezależny od
    zapisu. Wołający MUSI wcześniej ustawić próg trigramowy
    (``prepare_literal_text``). ``None`` = fraza za krótka, by filtrować.
    """
    stripped = (q or "").strip()
    phrase = single_phrase_filter(
        stripped, fuzzy=literal_text_threshold(stripped) is not None
    )
    phone = phone_digits_clause(stripped)
    if phrase is not None and phone is not None:
        return or_(phrase, phone)
    return phrase if phrase is not None else phone


async def prepare_literal_text(db: Any, q: str) -> Optional[ColumnElement]:
    """Ustawia ``pg_trgm.similarity_threshold`` (SET LOCAL) i zwraca klauzulę."""
    threshold = literal_text_threshold(q)
    if threshold is not None:
        # Wartość jest jedną z dwóch stałych powyżej — nie pochodzi z wejścia.
        await db.execute(text(f"SET LOCAL pg_trgm.similarity_threshold = {threshold}"))
    return literal_text_clause(q)


# ═══════════════════════════════════════════════════════════════════════════
# Grupy q_all / q_any / q_none — jeden parser
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class QGroups:
    q_all: tuple[str, ...] = ()
    q_any: tuple[str, ...] = ()
    q_none: tuple[str, ...] = ()
    extra_any_groups: tuple[tuple[str, ...], ...] = ()

    @property
    def any_groups(self) -> tuple[tuple[str, ...], ...]:
        """Wszystkie grupy LUB: płaskie ``q_any`` jako grupa 0, potem reszta."""
        head = (self.q_any,) if self.q_any else ()
        return head + self.extra_any_groups

    def clause(self) -> Optional[ColumnElement]:
        """``AND(all…, OR(grupa)…, NOT none…)`` albo ``None``, gdy pusto."""
        return build_advanced_filter(
            list(self.q_all),
            list(self.q_any),
            list(self.q_none),
            [list(g) for g in self.extra_any_groups],
        )

    def as_lists(self) -> Optional[list[list[str]]]:
        """DODATKOWE grupy LUB (bez płaskiego ``q_any``) dla sortowania
        trafności i wycinków listy; ``None`` gdy brak — kształt, którego
        te dwa miejsca oczekiwały od zawsze."""
        return [list(g) for g in self.extra_any_groups] or None


def parse_q_groups(
    *,
    q_all: Optional[Sequence[str]] = None,
    q_any: Optional[Sequence[str]] = None,
    q_none: Optional[Sequence[str]] = None,
    q_any_groups: Optional[Sequence[Any]] = None,
) -> QGroups:
    """Jeden parser kubełków boolowskich dla obu silników.

    ``q_any`` to grupa 0; ``q_any_groups`` przyjmuje OBA kształty drutu: listę
    list (JSON wyszukiwarki) i napisy ``a|b`` (powtarzany parametr GET listy).
    Czyszczenie fraz (długość, duplikaty, limity) robi ``build_advanced_filter``.
    """
    groups: list[tuple[str, ...]] = []
    for group in q_any_groups or []:
        parts: list[str] = []
        if isinstance(group, str):
            parts = split_pipe_group(group)
        else:
            for entry in group or []:
                parts.extend(split_pipe_group(entry))
        if parts:
            groups.append(tuple(parts))
    return QGroups(
        q_all=tuple(q_all or ()),
        q_any=tuple(q_any or ()),
        q_none=tuple(q_none or ()),
        extra_any_groups=tuple(groups),
    )


# ═══════════════════════════════════════════════════════════════════════════
# „Otwarty na", kategoria, status, dostępność
# ═══════════════════════════════════════════════════════════════════════════

OPEN_TO_FIELDS = {
    "side_projects": Candidate.open_to_side_projects,
    "sales_support": Candidate.open_to_sales_support,
    "expert_consult": Candidate.open_to_expert_consult,
}


class InvalidOpenTo(ValueError):
    def __init__(self, invalid: list[str]):
        self.invalid = invalid
        super().__init__(
            f"Invalid open_to values: {invalid}. Allowed: {sorted(OPEN_TO_FIELDS)}."
        )


def open_to_clause(values: Optional[Iterable[str]]) -> Optional[ColumnElement]:
    """„Otwarty na": KTÓRYKOLWIEK z zaznaczonych (LUB)."""
    wanted = list(dict.fromkeys(values or []))
    if not wanted:
        return None
    invalid = [v for v in wanted if v not in OPEN_TO_FIELDS]
    if invalid:
        raise InvalidOpenTo(invalid)
    return or_(*[OPEN_TO_FIELDS[v].is_(True) for v in wanted])


def competence_category_clause(
    ids: Optional[Sequence[int]],
) -> Optional[ColumnElement]:
    """Kategoria GŁÓWNA lub POBOCZNA (M2M), albo legacy FK sprzed backfillu."""
    if not ids:
        return None
    from app.models.competence_category import CandidateCompetenceCategory

    return or_(
        Candidate.competence_category_id.in_(list(ids)),
        Candidate.id.in_(
            select(CandidateCompetenceCategory.candidate_id).where(
                CandidateCompetenceCategory.competence_category_id.in_(list(ids))
            )
        ),
    )


def status_clause(statuses: Optional[Sequence[Any]]) -> Optional[ColumnElement]:
    return Candidate.status.in_(list(statuses)) if statuses else None


def availability_clause(values: Optional[Sequence[Any]]) -> Optional[ColumnElement]:
    return Candidate.availability_status.in_(list(values)) if values else None


# ═══════════════════════════════════════════════════════════════════════════
# Stawka, doświadczenie, tagi, lokalizacja
# ═══════════════════════════════════════════════════════════════════════════

UnknownValues = Literal["include", "exclude"]


def hourly_rate_clause(
    rate_min: Optional[Decimal], rate_max: Optional[Decimal]
) -> Optional[ColumnElement]:
    """Stawka B2B PLN netto/h. Kandydat BEZ stawki przechodzi (decyzja 09.2026);
    stawka w walucie, której nie umiemy porównać, też — „nie wiemy" to nie
    „za drogi".
    """
    if rate_min is None and rate_max is None:
        return None
    bounds: list[ColumnElement] = []
    if rate_min is not None:
        bounds.append(Candidate.expected_rate_hourly >= rate_min)
    if rate_max is not None:
        bounds.append(Candidate.expected_rate_hourly <= rate_max)
    comparable = canonical_profile_rate_currency_clause(
        Candidate.expected_rate_currency
    )
    return (
        Candidate.expected_rate_hourly.is_(None)
        | ~comparable
        | (comparable & and_(*bounds))
    )


def _experience_interval() -> tuple[ColumnElement, ColumnElement]:
    """Przedział lat ``(od, do)``: dokładna liczba, a gdy jej brak — koszyk
    z Traffita (``Poniżej 2``→0–1, ``2-5``→2–5, ``5+``→5–60). NULL = brak sygnału.
    """
    traffit = Candidate.cv_extracted_data.op("->>")("traffit_experience")
    exact = Candidate.years_it_experience
    low = case(
        (exact.is_not(None), exact),
        (traffit == "Poniżej 2", literal(0)),
        (traffit == "2-5", literal(2)),
        (traffit == "5+", literal(5)),
        else_=None,
    )
    high = case(
        (exact.is_not(None), exact),
        (traffit == "Poniżej 2", literal(1)),
        (traffit == "2-5", literal(5)),
        (traffit == "5+", literal(60)),
        else_=None,
    )
    return low, high


def _experience_overlap(
    years_min: Optional[int], years_max: Optional[int]
) -> Optional[ColumnElement]:
    if years_min is None and years_max is None:
        return None
    low, high = _experience_interval()
    parts: list[ColumnElement] = [high.is_not(None)]
    if years_min is not None:
        parts.append(high >= years_min)
    if years_max is not None:
        parts.append(low <= years_max)
    return and_(*parts)


def experience_clause(
    years_min: Optional[int],
    years_max: Optional[int],
    *,
    unknown: UnknownValues,
) -> Optional[ColumnElement]:
    """Lata doświadczenia — JEDNA reguła przedziału (z zapasem Traffita).

    ``unknown`` rozstrzyga WYŁĄCZNIE los kandydata bez żadnego sygnału
    (ani liczby, ani koszyka): ``include`` zostawia go w wynikach (domyślne
    w S od 08.2026 — kolumna jest wypełniona dla ~1% bazy), ``exclude`` go
    wycina (domyślne w L — dotychczasowe zachowanie listy i alertów).
    """
    overlap = _experience_overlap(years_min, years_max)
    if overlap is None:
        return None
    if unknown == "include":
        _low, high = _experience_interval()
        return or_(high.is_(None), overlap)
    return overlap


def experience_stated_rank(
    years_min: Optional[int], years_max: Optional[int]
) -> Optional[ColumnElement]:
    """ORDER BY / licznik: 1, gdy ZNANY przedział kandydata pasuje do żądania."""
    overlap = _experience_overlap(years_min, years_max)
    if overlap is None:
        return None
    return case((overlap, 1), else_=0)


def tag_match(tag: str) -> ColumnElement:
    """Kandydat MA tag — CAŁY tag, bez względu na wielkość liter.

    Do 09.2026 wyszukiwarka dopasowywała podłańcuch: tag ``java`` trafiał
    w ``javascript``, a ``vip`` w ``vip-2024``. Ten sam test tokenu JSON co
    przy umiejętnościach (oba kodowania).
    """
    blob = func.lower(func.coalesce(cast(Candidate.tags, String), ""))
    return _json_token_match(blob, [tag.strip().lower()])


def tags_clauses(tags: Optional[Iterable[str]]) -> list[ColumnElement]:
    """Każdy z podanych tagów (AND)."""
    return [tag_match(t) for t in (tags or []) if t and t.strip()]


def city_match_clauses(cities: Sequence[str]) -> list[ColumnElement]:
    """Jeden predykat na miasto: ``city`` LUB ``location`` zawiera frazę —
    ``%``/``_`` dosłownie, bez wrażliwości na polskie znaki („Krakow" znajduje
    „Kraków"). Wspólne dla WHERE i dla rankingu, żeby nie mogły się rozjechać.
    """
    return [
        or_(
            polish_folded_ilike(func.coalesce(Candidate.city, ""), c),
            polish_folded_ilike(func.coalesce(Candidate.location, ""), c),
        )
        for c in cities
        if c and c.strip()
    ]


def location_clauses(
    cities: Optional[Sequence[str]],
    countries: Optional[Sequence[str]],
    *,
    unknown: UnknownValues,
) -> list[ColumnElement]:
    """Miasto (którekolwiek z podanych) i kraj (kod ISO, którykolwiek).

    ``unknown`` jak przy doświadczeniu: los kandydata BEZ lokalizacji / kraju.
    Znana-i-niepasująca odpada zawsze.
    """
    clauses: list[ColumnElement] = []
    city_clauses = city_match_clauses(list(cities or []))
    if city_clauses:
        matched = or_(*city_clauses)
        if unknown == "include":
            nowhere = and_(Candidate.city.is_(None), Candidate.location.is_(None))
            clauses.append(or_(nowhere, matched))
        else:
            clauses.append(matched)
    wanted = [c.strip().upper() for c in (countries or []) if c and c.strip()]
    if wanted:
        in_country = func.upper(Candidate.country).in_(wanted)
        if unknown == "include":
            clauses.append(or_(Candidate.country.is_(None), in_country))
        else:
            clauses.append(in_country)
    return clauses


def location_rank(cities: Optional[Sequence[str]]) -> Optional[ColumnElement]:
    """ORDER BY / licznik: ile z żądanych miast kandydat faktycznie podaje."""
    city_clauses = city_match_clauses(list(cities or []))
    if not city_clauses:
        return None
    return reduce(
        lambda a, b: a + b, [case((clause, 1), else_=0) for clause in city_clauses]
    )
