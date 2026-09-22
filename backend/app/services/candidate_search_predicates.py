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
from app.services.polish_ilike import contains_pattern, polish_folded_ilike

# ═══════════════════════════════════════════════════════════════════════════
# Wersja semantyki
# ═══════════════════════════════════════════════════════════════════════════

Engine = Literal["list", "search"]
UnknownValues = Literal["include", "exclude"]

SEMANTICS_LEGACY = 1
SEMANTICS_UNIFIED = 2


@dataclass(frozen=True)
class Semantics:
    """Którą semantyką odpowiada żądanie (pole / parametr ``semantics_version``).

    * **v1** (brak pola) — KAŻDY silnik zwraca DOKŁADNIE to, co przed
      ujednoliceniem: zapisane wyszukiwania i alerty nie zmieniają wyniku bez
      zgody właściciela. Różnice między silnikami zostają (lista tnie osoby bez
      stawki/lokalizacji/stażu, wyszukiwarka dopasowuje tagi podłańcuchem itd.).
    * **v2** — jedna semantyka w obu: tabela decyzji z nagłówka modułu. Osoba
      BEZ danych (lokalizacja, staż, stawka) zostaje w wynikach i jest oznaczana
      w ``unknown_fields``; ``hide_unknown=true`` ją ukrywa.

    Całe nowe zachowanie jest opt-in przez v2. Nowe POLA (np. jawne kubełki
    umiejętności) działają w obu wersjach — nie mają znaczenia legacy.
    """

    version: int
    engine: Engine
    hide_unknown: Optional[bool] = None

    @property
    def unified(self) -> bool:
        return self.version >= SEMANTICS_UNIFIED

    @property
    def unknown(self) -> UnknownValues:
        """Los osoby bez danych dla filtrów lokalizacji i stażu."""
        if self.hide_unknown is not None:
            return "exclude" if self.hide_unknown else "include"
        if self.unified:
            return "include"
        return "exclude" if self.engine == "list" else "include"

    @property
    def rate_unknown(self) -> UnknownValues:
        """Los osoby bez (porównywalnej) stawki. Wyszukiwarka zostawiała ją od
        zawsze; lista v1 wycina — na tym stoją dzisiejsze alerty."""
        if self.hide_unknown is not None:
            return "exclude" if self.hide_unknown else "include"
        if self.unified or self.engine == "search":
            return "include"
        return "exclude"


def semantics_for(
    engine: Engine, version: Optional[int], hide_unknown: Optional[bool] = None
) -> Semantics:
    return Semantics(
        version=SEMANTICS_UNIFIED if (version or 1) >= 2 else SEMANTICS_LEGACY,
        engine=engine,
        hide_unknown=hide_unknown,
    )


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
    # Która reguła zadecydowała: ``email`` | ``phone`` | ``multi_token_name`` |
    # ``single_word_person_exists`` | ``single_word_no_person`` |
    # ``single_word_unchecked`` (bez sprawdzenia w bazie) | ``known_skill`` |
    # ``known_city`` | ``role_word`` | ``free_text`` | ``empty``.
    rule: str = "free_text"
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
            "rule": self.rule,
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

    Czysta część reguły (bez bazy). Ostrożna w stronę „opis": fałszywe „to
    osoba" zabiera wyszukiwaniu semantykę, fałszywe „to opis" kosztuje najwyżej
    gorszą kolejność. Osoba = 1–3 wyrazy z samych liter (myślnik/apostrof
    dozwolony), z których żaden nie jest znaną umiejętnością, miastem ani
    słowem roli. POJEDYNCZE słowo dostaje tu regułę ``single_word_unchecked`` —
    o tym, czy to naprawdę czyjeś imię/nazwisko, rozstrzyga ``interpret_text``.
    """
    raw = (q or "").strip()
    if not raw:
        return TextInterpretation(kind="empty", mode="semantic", rule="empty")

    if "@" in raw and len(raw) > 1 and _EMAIL_RE.match(raw):
        return TextInterpretation(
            kind="email", mode="literal", rule="email", email=raw.lower()
        )

    if _PHONE_QUERY_RE.match(raw):
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= _PHONE_QUERY_MIN_DIGITS:
            return TextInterpretation(
                kind="phone", mode="literal", rule="phone", phone_digits=digits[-9:]
            )

    tokens = raw.replace(",", " ").split()
    skills = tuple(t for t in tokens if _known_skill(t))
    locations = tuple(t for t in tokens if t.lower() in _KNOWN_CITIES)
    role_words = [t for t in tokens if t.lower() in _ROLE_WORDS]
    looks_like_name = (
        1 <= len(tokens) <= _MAX_NAME_TOKENS
        and not skills
        and not locations
        and not role_words
        and all(_NAME_TOKEN_RE.match(t) for t in tokens)
    )
    if looks_like_name:
        return TextInterpretation(
            kind="name",
            mode="literal",
            rule="multi_token_name" if len(tokens) > 1 else "single_word_unchecked",
            name_tokens=tuple(tokens),
        )

    if skills:
        rule = "known_skill"
    elif locations:
        rule = "known_city"
    elif role_words:
        rule = "role_word"
    else:
        rule = "free_text"
    other = tuple(t for t in tokens if t not in skills and t not in locations)
    return TextInterpretation(
        kind="text",
        mode="semantic",
        rule=rule,
        skills=skills,
        locations=locations,
        other_tokens=other,
    )


# Krótka pamięć odpowiedzi „czy istnieje osoba o takim imieniu/nazwisku".
# Jedno słowo wpisywane w ⌘K pyta o to przy każdym znaku; TTL jest krótki, bo
# nowo dodany kandydat ma być znajdowany po nazwisku niemal od razu.
_PERSON_TOKEN_TTL_SECONDS = 60.0
_PERSON_TOKEN_CACHE_MAX = 2048
_person_token_cache: dict[str, tuple[float, bool]] = {}


async def person_token_exists(db: Any, token: str) -> bool:
    """Czy w bazie jest kandydat, którego IMIĘ, NAZWISKO albo JEDEN CZŁON
    nazwiska dwuczłonowego (rozdzielonego myślnikiem) to dokładnie ``token``
    (bez wielkości liter i polskich znaków).

    Jedno zapytanie ``LIMIT 1``: indeks trigramowy na ``search_doc_unaccented``
    (migracja 0159) zawęża wiersze, a równość sprawdzamy już tylko na nich —
    bez skanu całej tabeli i bez nowego indeksu.
    """
    import time

    from app.services.advanced_candidate_search import (
        _POLISH_FOLD_DST,
        _POLISH_FOLD_SRC,
        _SEARCH_DOC_UNACCENT,
        _escape_like,
        fold_polish,
    )

    folded = fold_polish(token.strip())
    if not folded:
        return False
    now = time.monotonic()
    cached = _person_token_cache.get(folded)
    if cached is not None and cached[0] > now:
        return cached[1]

    def _fold(col: Any) -> ColumnElement:
        return func.lower(
            func.translate(func.coalesce(col, ""), _POLISH_FOLD_SRC, _POLISH_FOLD_DST)
        )

    stmt = (
        select(Candidate.id)
        .where(
            _SEARCH_DOC_UNACCENT.ilike(f"%{_escape_like(folded)}%", escape="\\"),
            or_(
                _fold(Candidate.name) == folded,
                _fold(Candidate.lastname) == folded,
                # jeden człon nazwiska dwuczłonowego: „Kowalska" → „Nowak-Kowalska"
                literal(folded)
                == func.any(func.string_to_array(_fold(Candidate.lastname), "-")),
            ),
        )
        .limit(1)
    )
    exists = (await db.execute(stmt)).first() is not None
    if len(_person_token_cache) >= _PERSON_TOKEN_CACHE_MAX:
        _person_token_cache.clear()
    _person_token_cache[folded] = (now + _PERSON_TOKEN_TTL_SECONDS, exists)
    return exists


async def interpret_text(db: Any, q: Optional[str]) -> TextInterpretation:
    """``detect_text_mode`` + rozstrzygnięcie POJEDYNCZEGO słowa w bazie.

    Jedno nieznane słowo jest dopasowywane dosłownie TYLKO wtedy, gdy istnieje
    kandydat o takim imieniu albo nazwisku; inaczej to opis („księgowa") i idzie
    ścieżką semantyczną. Dwa–trzy wyrazy wyglądające na osobę, e-mail i telefon
    nie pytają bazy.
    """
    from dataclasses import replace

    found = detect_text_mode(q)
    if found.rule != "single_word_unchecked":
        return found
    token = found.name_tokens[0]
    if await person_token_exists(db, token):
        return replace(found, rule="single_word_person_exists")
    return TextInterpretation(
        kind="text",
        mode="semantic",
        rule="single_word_no_person",
        other_tokens=(token,),
    )


def text_mode_to_apply(
    sem: Semantics, requested: Optional[str], interpretation: TextInterpretation
) -> Optional[Literal["literal", "semantic"]]:
    """Co zrobić z ``q``. ``None`` = dotychczasowa ścieżka silnika (lista:
    dosłownie; wyszukiwarka: wg ``search_mode``).

    * jawne ``literal`` / ``semantic`` wygrywa zawsze,
    * auto-detekcja osoby działa w v2 albo przy jawnym ``text_mode="auto"``;
      w v1 bez pola istniejące wyszukiwania zachowują dotychczasowe ``q``,
    * tekst, który NIE jest osobą, nie wymusza hybrydy — zostaje przy trybie
      wybranym przez rekrutera.
    """
    if requested == "literal":
        return "literal"
    if requested == "semantic":
        return "semantic"
    if (requested == "auto" or sem.unified) and interpretation.mode == "literal":
        return "literal"
    return None


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

    def clause(
        self, sem: Optional["Semantics"] = None, scope: Optional[str] = None
    ) -> Optional[ColumnElement]:
        """``AND(all…, OR(grupa)…, NOT none…)`` albo ``None``, gdy pusto.

        v2: CAŁE słowa (``java`` ≠ ``JavaScript``), gwiazdka i zakres pola
        (``keyword_terms``). v1 / brak semantyki: dotychczasowy podłańcuch.
        """
        unified = bool(sem is not None and sem.unified)
        return build_advanced_filter(
            list(self.q_all),
            list(self.q_any),
            list(self.q_none),
            [list(g) for g in self.extra_any_groups],
            whole_words=unified,
            scope=(scope or "all") if unified else "all",
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
    ids: Optional[Sequence[int]], sem: Semantics
) -> Optional[ColumnElement]:
    """Kategoria GŁÓWNA lub POBOCZNA (M2M), albo legacy FK sprzed backfillu.

    v1 wyszukiwarki: wyłącznie FK kategorii głównej (dotychczasowe zachowanie).
    """
    if not ids:
        return None
    if not sem.unified and sem.engine == "search":
        return Candidate.competence_category_id.in_(list(ids))
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
# Języki
# ═══════════════════════════════════════════════════════════════════════════

# CEFR w kolejności rosnącej; ``native`` jest osobnym faktem i spełnia każdy próg.
LANGUAGE_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2", "native")
# Próg, gdy żądanie podaje sam kod języka — ten sam co domyślny
# ``LanguageRequirement.min_level`` wyszukiwarki.
DEFAULT_LANGUAGE_LEVEL = "B2"
_LANGUAGE_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z-]{1,9}$")


class InvalidLanguageFilter(ValueError):
    """Wartość filtra języka nie ma kształtu ``kod`` albo ``kod:POZIOM``."""


def language_clause(code: str, min_level: Optional[str]) -> Optional[ColumnElement]:
    """Kandydat ma aktywny, znormalizowany fakt języka na poziomie ≥ progu.

    ``native`` spełnia każdy próg CEFR. Poziom nieznany/opisowy nie spełnia
    żadnego: etykiety opisowe są podpowiedzią, nigdy nie awansują po cichu do
    CEFR. Wspólne dla listy (`?languages=`) i wyszukiwarki (`languages`).
    """
    from app.models.candidate_language import CandidateLanguage  # noqa: PLC0415

    level = min_level or DEFAULT_LANGUAGE_LEVEL
    if level not in LANGUAGE_LEVELS:
        return None
    min_idx = LANGUAGE_LEVELS.index(level)
    accepted_levels = [lvl for lvl in LANGUAGE_LEVELS[min_idx:] if lvl != "native"]
    return (
        select(CandidateLanguage.id)
        .where(
            CandidateLanguage.candidate_id == Candidate.id,
            CandidateLanguage.deleted_at.is_(None),
            func.upper(CandidateLanguage.language_code) == code.upper(),
            and_(
                CandidateLanguage.is_level_unknown.is_(False),
                or_(
                    CandidateLanguage.is_native.is_(True),
                    CandidateLanguage.cefr_level.in_(accepted_levels),
                ),
            ),
        )
        .correlate(Candidate)
        .exists()
    )


def parse_language_filter(value: str) -> tuple[str, Optional[str]]:
    """``"en"`` / ``"en:B2"`` / ``"de:native"`` → ``("EN", poziom albo None)``.

    Kształt parametru listy (`?languages=`). ``None`` = sam kod, czyli próg
    domyślny (``DEFAULT_LANGUAGE_LEVEL``). Błędny kształt → ``InvalidLanguageFilter``
    z komunikatem po polsku.
    """
    raw = (value or "").strip()
    code, sep, level = raw.partition(":")
    code = code.strip()
    level = level.strip()
    if not _LANGUAGE_CODE_RE.match(code):
        raise InvalidLanguageFilter(
            f"Nieprawidłowy filtr języka „{raw}”: podaj kod języka (np. „en”) "
            "albo kod z poziomem (np. „en:B2”)."
        )
    if not sep:
        return code.upper(), None
    normalized = "native" if level.lower() == "native" else level.upper()
    if normalized not in LANGUAGE_LEVELS:
        raise InvalidLanguageFilter(
            f"Nieprawidłowy poziom języka w „{raw}”: dozwolone "
            f"{', '.join(LANGUAGE_LEVELS)}."
        )
    return code.upper(), normalized


def language_clauses(values: Optional[Iterable[str]]) -> list[ColumnElement]:
    """Filtr języków listy: każdy wpis musi być spełniony (AND), jak w
    wyszukiwarce. Błędny wpis → ``InvalidLanguageFilter``."""
    clauses: list[ColumnElement] = []
    for value in values or ():
        code, level = parse_language_filter(value)
        clause = language_clause(code, level)
        if clause is not None:
            clauses.append(clause)
    return clauses


# ═══════════════════════════════════════════════════════════════════════════
# Stawka, doświadczenie, tagi, lokalizacja
# ═══════════════════════════════════════════════════════════════════════════


def hourly_rate_clause(
    rate_min: Optional[Decimal], rate_max: Optional[Decimal], sem: Semantics
) -> Optional[ColumnElement]:
    """Stawka B2B PLN netto/h.

    v2 (i wyszukiwarka od zawsze): kandydat BEZ stawki przechodzi, tak samo
    stawka w walucie, której nie umiemy porównać — „nie wiemy" to nie „za
    drogi"; ``hide_unknown`` ich ukrywa. v1 listy: brak stawki i obca waluta
    odpadają (na tym stoją dzisiejsze alerty).
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
    known_and_matching = comparable & and_(*bounds)
    if sem.rate_unknown == "exclude":
        return known_and_matching
    return Candidate.expected_rate_hourly.is_(None) | ~comparable | known_and_matching


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


def _legacy_search_experience_bounds(
    years_min: Optional[int], years_max: Optional[int]
) -> list[ColumnElement]:
    bounds: list[ColumnElement] = []
    if years_min is not None:
        bounds.append(Candidate.years_it_experience >= years_min)
    if years_max is not None:
        bounds.append(Candidate.years_it_experience <= years_max)
    return bounds


def experience_clause(
    years_min: Optional[int], years_max: Optional[int], sem: Semantics
) -> Optional[ColumnElement]:
    """Lata doświadczenia — JEDNA reguła przedziału (z zapasem Traffita).

    ``sem.unknown`` rozstrzyga WYŁĄCZNIE los kandydata bez żadnego sygnału
    (ani liczby, ani koszyka). v1 wyszukiwarki zostaje przy dotychczasowym
    porównaniu samej kolumny ``years_it_experience`` (bez koszyka Traffita,
    pusta kolumna przechodzi); lista miała regułę przedziału od zawsze.
    """
    if years_min is None and years_max is None:
        return None
    if not sem.unified and sem.engine == "search":
        legacy = and_(*_legacy_search_experience_bounds(years_min, years_max))
        if sem.unknown == "include":
            return or_(Candidate.years_it_experience.is_(None), legacy)
        return legacy
    overlap = _experience_overlap(years_min, years_max)
    assert overlap is not None
    if sem.unknown == "include":
        _low, high = _experience_interval()
        return or_(high.is_(None), overlap)
    return overlap


def experience_stated_rank(
    years_min: Optional[int], years_max: Optional[int], sem: Semantics
) -> Optional[ColumnElement]:
    """ORDER BY / licznik: 1, gdy ZNANY staż kandydata pasuje do żądania."""
    if years_min is None and years_max is None:
        return None
    if not sem.unified and sem.engine == "search":
        return case(
            (
                and_(
                    Candidate.years_it_experience.is_not(None),
                    *_legacy_search_experience_bounds(years_min, years_max),
                ),
                1,
            ),
            else_=0,
        )
    return case((_experience_overlap(years_min, years_max), 1), else_=0)


def tag_match(tag: str) -> ColumnElement:
    """Kandydat MA tag — CAŁY tag, bez względu na wielkość liter.

    Do 09.2026 wyszukiwarka dopasowywała podłańcuch: tag ``java`` trafiał
    w ``javascript``, a ``vip`` w ``vip-2024``. Ten sam test tokenu JSON co
    przy umiejętnościach (oba kodowania).
    """
    blob = func.lower(func.coalesce(cast(Candidate.tags, String), ""))
    return _json_token_match(blob, [tag.strip().lower()])


def tags_clauses(tags: Optional[Iterable[str]], sem: Semantics) -> list[ColumnElement]:
    """Każdy z podanych tagów (AND). v1 wyszukiwarki: dotychczasowe dopasowanie
    PODŁAŃCUCHEM (``java`` trafia w ``javascript``) — poprawka jest w v2."""
    wanted = [t for t in (tags or []) if t and t.strip()]
    if not sem.unified and sem.engine == "search":
        blob = func.coalesce(cast(Candidate.tags, String), "")
        return [blob.ilike(contains_pattern(t), escape="\\") for t in wanted]
    return [tag_match(t) for t in wanted]


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


LocationScope = Literal["city_or_location", "location_only"]


def location_clauses(
    cities: Optional[Sequence[str]],
    countries: Optional[Sequence[str]],
    sem: Semantics,
    *,
    scope: Optional[str] = None,
) -> list[ColumnElement]:
    """Miasto (którekolwiek z podanych) i kraj (kod ISO, którykolwiek).

    ``sem.unknown``: los kandydata BEZ lokalizacji / kraju. Znana-i-niepasująca
    odpada zawsze. v1 listy zostaje przy dotychczasowym ``location ILIKE
    '%fraza%'`` — sama kolumna ``location``, bez foldu polskich znaków i bez
    escapowania (``%``/``_`` działają tam jak wieloznaczniki; poprawka jest w v2).
    """
    clauses: list[ColumnElement] = []
    wanted_cities = [c for c in (cities or []) if c and c.strip()]
    if wanted_cities and not sem.unified and sem.engine == "list":
        clauses.append(
            or_(*[Candidate.location.ilike(f"%{c}%") for c in wanted_cities])
        )
    elif wanted_cities and scope == "location_only":
        # Zawężenie do dotychczasowego zakresu listy (zapisy zmigrowane z v1):
        # sama kolumna `location`, bez foldu polskich znaków. Wieloznaczniki są
        # już dosłowne — to poprawka, nie poszerzenie.
        matched = or_(
            *[
                Candidate.location.ilike(contains_pattern(c), escape="\\")
                for c in wanted_cities
            ]
        )
        if sem.unknown == "include":
            clauses.append(or_(Candidate.location.is_(None), matched))
        else:
            clauses.append(matched)
    elif wanted_cities:
        matched = or_(*city_match_clauses(wanted_cities))
        if sem.unknown == "include":
            nowhere = and_(Candidate.city.is_(None), Candidate.location.is_(None))
            clauses.append(or_(nowhere, matched))
        else:
            clauses.append(matched)
    wanted = [c.strip().upper() for c in (countries or []) if c and c.strip()]
    if wanted:
        if not sem.unified and sem.engine == "search":
            in_country = Candidate.country.in_(wanted)
        else:
            in_country = func.upper(Candidate.country).in_(wanted)
        if sem.unknown == "include":
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


# ═══════════════════════════════════════════════════════════════════════════
# `unknown_fields` — oznaczenie wierszy, które przeszły „na brak danych"
# ═══════════════════════════════════════════════════════════════════════════

_TRAFFIT_EXPERIENCE_BUCKETS = frozenset({"Poniżej 2", "2-5", "5+"})


def unknown_count_rank(
    *,
    location_active: bool,
    country_active: bool,
    experience_active: bool,
    rate_active: bool,
) -> ColumnElement[int] | None:
    """Ile AKTYWNYCH filtrów wiersz przeszedł wyłącznie na brak danych — lustro
    SQL ``unknown_fields_for``. Lista sortuje po nim rosnąco, żeby osoby
    z potwierdzonym dopasowaniem szły przed osobami z plakietką „brak …"
    (test manualny 22.09.2026: przy filtrze „Kraków" 20 z 30 pierwszych
    wierszy nie miało żadnego miasta). ``None`` = żaden filtr nie aktywny.
    """
    parts: list[ColumnElement[int]] = []
    if location_active or country_active:
        no_place = (
            and_(Candidate.city.is_(None), Candidate.location.is_(None))
            if location_active
            else literal(False)
        )
        no_country = Candidate.country.is_(None) if country_active else literal(False)
        parts.append(case((or_(no_place, no_country), 1), else_=0))
    if experience_active:
        bucket = Candidate.cv_extracted_data["traffit_experience"].astext
        parts.append(
            case(
                (
                    and_(
                        Candidate.years_it_experience.is_(None),
                        or_(
                            bucket.is_(None),
                            bucket.not_in(sorted(_TRAFFIT_EXPERIENCE_BUCKETS)),
                        ),
                    ),
                    1,
                ),
                else_=0,
            )
        )
    if rate_active:
        currency = func.upper(
            func.trim(func.coalesce(Candidate.expected_rate_currency, ""))
        )
        parts.append(
            case(
                (
                    or_(
                        Candidate.expected_rate_hourly.is_(None),
                        currency.not_in(["", "PLN"]),
                    ),
                    1,
                ),
                else_=0,
            )
        )
    if not parts:
        return None
    return reduce(lambda a, b: a + b, parts)


def unknown_fields_for(
    candidate: Any,
    *,
    location_active: bool,
    country_active: bool,
    experience_active: bool,
    rate_active: bool,
) -> list[str]:
    """Które AKTYWNE filtry kandydat przeszedł wyłącznie dlatego, że nie mamy
    o nim danych. Lustro reguł SQL powyżej, liczone w Pythonie dla wierszy
    jednej strony. Kolejność stała: ``location``, ``experience``, ``rate``.
    """
    from app.services.candidate_profile_rate import (
        is_canonical_profile_rate_currency,
    )

    out: list[str] = []
    no_place = (
        location_active
        and getattr(candidate, "city", None) is None
        and getattr(candidate, "location", None) is None
    )
    no_country = country_active and getattr(candidate, "country", None) is None
    if no_place or no_country:
        out.append("location")
    if experience_active and getattr(candidate, "years_it_experience", None) is None:
        extracted = getattr(candidate, "cv_extracted_data", None)
        bucket = (
            extracted.get("traffit_experience") if isinstance(extracted, dict) else None
        )
        if bucket not in _TRAFFIT_EXPERIENCE_BUCKETS:
            out.append("experience")
    if rate_active and (
        getattr(candidate, "expected_rate_hourly", None) is None
        or not is_canonical_profile_rate_currency(
            getattr(candidate, "expected_rate_currency", None)
        )
    ):
        out.append("rate")
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Promień w km i województwo (lista) — ``pl_places``
# ═══════════════════════════════════════════════════════════════════════════


class UnknownPlace(ValueError):
    """Miasta w promieniu nie da się ustalić: nazwy nie ma w spisie miejscowości."""


def geo_clause(
    *,
    center: Optional[str],
    radius_km: Optional[int],
    voivodeships: Optional[Sequence[str]],
    sem: Semantics,
) -> Optional[ColumnElement]:
    """Kandydat mieszka w promieniu ``radius_km`` od ``center`` i/lub
    w jednym z województw. Porównanie po nazwie miejscowości (``city`` albo
    pierwszy człon ``location``) z listą nazw wyliczoną z ``pl_places`` —
    kandydaci nie mają współrzędnych. Kandydat z innym krajem niż PL odpada:
    zagraniczna nazwa bywa równa polskiej wsi. Osoba bez lokalizacji: jak
    w filtrze miasta (``sem.unknown``).
    """
    from sqlalchemy import Text, any_
    from sqlalchemy.dialects.postgresql import ARRAY

    from app.services import pl_places

    key_sets: list[set[str]] = []
    if radius_km:
        place = pl_places.resolve(center)
        if place is None:
            raise UnknownPlace(
                f"Nie znam miejscowości „{(center or '').strip()}” — wybierz ją "
                "z podpowiedzi albo usuń promień."
            )
        key_sets.append(
            set(pl_places.keys_within(place, min(radius_km, pl_places.MAX_RADIUS_KM)))
        )
    wanted_voivodeships = [
        v.strip().lower() for v in (voivodeships or []) if v and v.strip()
    ]
    unknown_voivodeships = sorted(
        set(wanted_voivodeships) - set(pl_places.VOIVODESHIPS)
    )
    if unknown_voivodeships:
        raise UnknownPlace(f"Nie znam województwa: {', '.join(unknown_voivodeships)}.")
    if wanted_voivodeships:
        key_sets.append(set(pl_places.keys_in_voivodeships(wanted_voivodeships)))
    if not key_sets:
        return None
    # Promień i województwo naraz = część wspólna (np. „Kraków + 100 km”,
    # ale tylko małopolskie).
    keys = sorted(set.intersection(*key_sets))
    arr = literal(keys, type_=ARRAY(Text))
    matched = and_(
        or_(
            pl_places.place_key_sql(Candidate.city) == any_(arr),
            pl_places.place_key_sql(Candidate.location) == any_(arr),
        ),
        or_(
            Candidate.country.is_(None),
            Candidate.country == "",
            func.upper(Candidate.country) == "PL",
        ),
    )
    if sem.unknown == "include":
        nowhere = and_(
            func.coalesce(Candidate.city, "") == "",
            func.coalesce(Candidate.location, "") == "",
        )
        return or_(nowhere, matched)
    return matched


# ═══════════════════════════════════════════════════════════════════════════
# Kontakt z kandydatem (lista) — notatki, rozmowy, maile z Traffita
# ═══════════════════════════════════════════════════════════════════════════


def contact_clause(
    *,
    mode: Optional[str],
    date_from: Optional[Any],
    date_to: Optional[Any],
    by_user_ids: Optional[Sequence[int]],
) -> Optional[ColumnElement]:
    """„Kontaktowaliśmy się” (``mode='yes'``) albo „nie kontaktowaliśmy się”
    (``'no'``) w okresie ``[date_from, date_to]`` (daty włącznie, w strefie
    biznesowej), opcjonalnie tylko przez wskazane osoby.

    Kontakt = notatka o kandydacie albo rozmowa telefoniczna. Maile,
    odpowiedzi, rozmowy i spotkania z Traffita import i tak promuje do notatek
    (``TraffitImporter.promote_notes``), więc osobna gałąź aktywności byłaby
    duplikatem — i kosztowała 3 s na skanie indeksu aktywności (zmierzone
    22.09.2026). ``NOT EXISTS`` na źródło, nie ``NOT IN`` na sumie zbiorów.
    """
    if mode not in ("yes", "no"):
        return None
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from app.core.scheduling import DEFAULT_TZ
    from app.models.call import Call
    from app.models.note import Note

    zone = ZoneInfo(DEFAULT_TZ)
    start = datetime.combine(date_from, time.min, tzinfo=zone) if date_from else None
    end = (
        datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=zone)
        if date_to
        else None
    )
    users = list(dict.fromkeys(by_user_ids or []))

    def window(at_col, user_col) -> list[ColumnElement]:
        conds: list[ColumnElement] = []
        if start is not None:
            conds.append(at_col >= start)
        if end is not None:
            conds.append(at_col < end)
        if users:
            conds.append(user_col.in_(users))
        return conds

    call_at = func.coalesce(Call.started_at, Call.created_at)
    note_exists = (
        select(Note.id)
        .where(
            Note.candidate_id == Candidate.id, *window(Note.created_at, Note.author_id)
        )
        .correlate(Candidate)
        .exists()
    )
    call_exists = (
        select(Call.id)
        .where(Call.candidate_id == Candidate.id, *window(call_at, Call.user_id))
        .correlate(Candidate)
        .exists()
    )
    contacted = or_(note_exists, call_exists)
    return contacted if mode == "yes" else not_(contacted)
