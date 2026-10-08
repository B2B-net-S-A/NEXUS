"""Które pozycje must-have ukrywają kandydatów i w jakiej postaci (27.09.2026).

Decyzja Artura: bramka must działa WYŁĄCZNIE na nazwach technologii. Klient
w sekcji „Must have” pisze też przykłady („CI/CD tools like Bitbucket,
Jenkins”), wersje („Java 8+”), języki („angielski B2”), branże („bankowość”),
metodyki i umiejętności miękkie. Te pozycje zostają w profilu rekrutacji
i w punktacji, ale nie ukrywają nikogo — badanie z 26.09
(``docs/audits/2026-09-26/tworzenie-rekrutacji-a-wyszukiwanie.md``) pokazało,
że to one ukrywały ludzi, których zespół potem wysyłał do klienta.

``gate_requirement(label)`` zwraca wymaganie bramki: oryginalną etykietę
(klucz weryfikacji rekrutera i nazwa na ekranie) i OPCJE — nazwy technologii,
z których wystarczy jedna („A lub B”, przykłady klienta). ``None`` = pozycja
nie bramkuje, a ``ignored_reason`` mówi dlaczego.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from app.services.skill_normalize import (
    is_gate_technology,
    is_non_technology_concept,
    strip_version,
    taxonomy_category,
)

# Przykłady klienta: „CI/CD tools like Bitbucket, Jenkins”, „bazy danych
# (np. Oracle, PostgreSQL)”, „narzędzia takie jak Jira”. Głowa to zwykle
# kategoria (odpada), opcje to technologie (wystarczy jedna).
_EXAMPLES = re.compile(
    r"^(?P<head>.*?)\s*[\(:\-–—]?\s*"
    r"\b(?:like|such\s+as|e\.\s?g\.?|eg\.|for\s+example|including|incl\.?|"
    r"np\.?|takie\s+jak|takich\s+jak|typu|m\.\s?in\.?)\s+"
    r"(?P<opts>.+?)\)?\s*\.?$",
    re.IGNORECASE,
)
# „Bazy danych (Oracle, PostgreSQL)” — nawias z listą po kategorii.
_PAREN_LIST = re.compile(r"^(?P<head>[^()]+?)\s*\((?P<opts>[^()]*[,/][^()]*)\)\s*$")
# Alternatywa w samej etykiecie: „Kafka lub RabbitMQ”, „Docker/Kubernetes”.
# „i”, „and”, „oraz” i przecinek to KONIUNKCJA („python i bash” = oba), więc
# nie tworzą opcji — taka etykieta nie bramkuje (punkt wymagań).
_ALT_SPLIT = re.compile(r"\s*(?:/|\||\blub\b|\balbo\b|\bor\b)\s*", re.I)
# W przykładach klienta („like Bitbucket, Jenkins”) wystarczy którykolwiek.
_EXAMPLE_SPLIT = re.compile(
    r"\s*(?:,|;|/|\||\blub\b|\balbo\b|\bor\b|\band\b|\boraz\b|\bi\b)\s*", re.I
)

_SLASH_GUARD = "\u2044"  # ukośnik ułamkowy — chroni „PL/SQL” przy dzieleniu

_LANGUAGE_WORDS = frozenset(
    {
        "angielski",
        "angielskiego",
        "angielskim",
        "english",
        "niemiecki",
        "niemieckiego",
        "german",
        "francuski",
        "french",
        "hiszpański",
        "hiszpanski",
        "spanish",
        "włoski",
        "wloski",
        "italian",
        "rosyjski",
        "russian",
        "ukraiński",
        "ukrainski",
        "ukrainian",
        "polski",
        "polish",
        "język",
        "jezyk",
        "języka",
        "jezyka",
        "języki",
        "language",
        "languages",
        "native",
        "fluent",
        "biegły",
        "biegly",
        "biegła",
        "biegla",
        "biegle",
        "komunikatywny",
        "komunikatywna",
    }
)
_CEFR = re.compile(r"(?<![a-z0-9])[abc][12]\+?(?![a-z0-9])", re.I)

_DOMAIN_WORDS = frozenset(
    {
        "bankowość",
        "bankowosc",
        "bankowości",
        "bankowosci",
        "bankowy",
        "bankowa",
        "bankowe",
        "banking",
        "bank",
        "banku",
        "finanse",
        "finansowy",
        "finansowa",
        "finansowe",
        "finansowym",
        "financial",
        "finance",
        "fintech",
        "insurance",
        "ubezpieczenia",
        "ubezpieczeniowy",
        "ubezpieczeniowa",
        "ubezpieczeń",
        "ubezpieczen",
        "telco",
        "telekomunikacja",
        "telecom",
        "e-commerce",
        "ecommerce",
        "retail",
        "automotive",
        "pharma",
        "farmacja",
        "medyczny",
        "medyczne",
        "medical",
        "healthcare",
        "sektor",
        "sector",
        "publiczny",
        "publiczna",
        "public",
        "energetyka",
        "energy",
        "logistyka",
        "logistics",
        "kyc",
        "aml",
        "płatności",
        "platnosci",
        "payments",
        "hipoteczne",
        "mortgage",
        "branża",
        "branza",
        "branży",
        "branzy",
        "domain",
        "domena",
        # Regulacje i normy — sekcja 4 Championa, nie technologia.
        "gdpr",
        "rodo",
        "dora",
        "nis2",
        "psd2",
        "mifid",
        "iso",
        "knf",
        "regulacje",
        "regulations",
        "compliance",
    }
)
_SOFT_WORDS = frozenset(
    {
        "komunikatywność",
        "komunikatywnosc",
        "komunikacja",
        "communication",
        "teamwork",
        "samodzielność",
        "samodzielnosc",
        "proaktywność",
        "proaktywnosc",
        "proactive",
        "problem",
        "solving",
        "analityczne",
        "analityczny",
        "analytical",
        "leadership",
        "przywództwo",
        "odpowiedzialność",
        "zaangażowanie",
        "kreatywność",
        "mindset",
        "stakeholder",
        "stakeholders",
        "interpersonal",
        "soft",
        "skills",
    }
)
# Kategorie i praktyki, a nie technologie: nikt nie ma ich w profilu dosłownie,
# a badanie z 26.09 pokazało, że wysłani „nie mają” ich w 70–99% przypadków.
_CATEGORY_WORDS = frozenset(
    {
        "bazy",
        "baz",
        "danych",
        "database",
        "databases",
        "narzędzia",
        "narzedzia",
        "narzędzi",
        "tools",
        "tool",
        "frameworki",
        "frameworks",
        "framework",
        "cloud",
        "chmura",
        "chmurowe",
        "metodyki",
        "metodyka",
        "methodologies",
        "methodology",
        "agile",
        "scrum",
        "safe",
        "kanban",
        "zwinne",
        "zwinna",
        "wzorce",
        "projektowe",
        "design",
        "patterns",
        "clean",
        "code",
        "mikroserwisy",
        "mikrousługi",
        "mikroserwisów",
        "microservices",
        "architektura",
        "architecture",
        "integracje",
        "integration",
        "integrations",
        "testy",
        "testing",
        "dokumentacja",
        "documentation",
        "sdlc",
        "devops",
        "systemy",
        "systems",
        "aplikacje",
        "applications",
        "relacyjne",
        "relational",
        "techniczna",
        "technical",
        "narzędzie",
        "narzedzie",
        "management",
        "oriented",
        "zorientowane",
        "principles",
        "zasady",
        "concepts",
        # 30.09.2026 (audyt B2): praktyki spoza słownika, które przechodziły
        # regułę składniową — „IT analysis” (3% wysłanych je „ma”), „Data
        # engineering” (32%), „IT operations”, „Test automation”, „IT consulting”.
        "analysis",
        "analiza",
        "engineering",
        "operations",
        "consulting",
        "administration",
        "assurance",
        "automation",
        "automatyzacja",
    }
)
# Słowa roli: „Java Developer” → Java; sama rola → nie bramkuje.
_ROLE_WORDS = frozenset(
    {
        "developer",
        "developera",
        "engineer",
        "specialist",
        "specjalista",
        "programista",
        "programmer",
        "konsultant",
        "consultant",
        "architekt",
        "architect",
        "analityk",
        "analyst",
        "tester",
        "manager",
        "menedżer",
        "lead",
        "senior",
        "junior",
        "mid",
        "expert",
        "ekspert",
        "admin",
        "administrator",
        "owner",
        "qa",
        "pmo",
    }
)
_REASONS = ("language", "domain", "soft", "category", "role", "prose")

# Głowa przykładów klienta, po której opcje z nawiasu/„np.” liczą się jako
# wymóg: kategoria („Bazy danych (Oracle, PostgreSQL)”) albo technologia.
# Wstęp „znajomość / doświadczenie z” i odmiany słów kategorii nie zmieniają
# tego; każde inne słowo robi z głowy zdanie („Doświadczenie z integracją
# systemów (on-premise, hybrid)”) i przykłady przestają być wymogiem (30.09.2026).
_HEAD_FILLER_WORDS = frozenset(
    {
        "znajomość",
        "znajomosc",
        "znajomości",
        "znajomosci",
        "knowledge",
        "of",
        "experience",
        "with",
        "in",
        "doświadczenie",
        "doswiadczenie",
        "w",
        "z",
        "ze",
        "praktyczna",
        "praktyczne",
        "practical",
        "dobra",
        "good",
        "bardzo",
        "hands-on",
        "commercial",
        "komercyjne",
        "min.",
        "minimum",
    }
)
_HEAD_CATEGORY_WORDS = _CATEGORY_WORDS | frozenset(
    {
        "bazami",
        "bazach",
        "bazą",
        "baza",
        "narzędziami",
        "narzedziami",
        "narzędziach",
        "narzedziach",
        "frameworkami",
        "frameworkach",
        "chmurą",
        "chmura",
        "chmurze",
        "chmurowymi",
        "systemami",
        "platformy",
        "platforms",
        "platform",
        "platforma",
        "platformami",
        "kolejki",
        "kolejkami",
        "queues",
        "messaging",
        "języki",
        "jezyki",
        "językami",
        "programowania",
        "programming",
        "biblioteki",
        "libraries",
        "technologie",
        "technologies",
        "rozwiązania",
        "solutions",
        "serwery",
        "servers",
        "ci/cd",
    }
)

# Ukośnik w samej nazwie technologii — nie alternatywa.
_SLASH_NAMES = frozenset(
    {"ci/cd", "pl/sql", "tcp/ip", "ui/ux", "i/o", "a/b", "tdd/bdd"}
)


@dataclass(frozen=True)
class GateRequirement:
    """Jedno wymaganie bramki: oryginalna etykieta + nazwy (wystarczy jedna)."""

    label: str
    options: tuple[str, ...]


def _clean(text: str) -> str:
    # Kropka z przodu zostaje („.NET”); z tyłu to koniec zdania.
    return " ".join(unicodedata.normalize("NFC", text or "").split()).rstrip(" .")


def _words(text: str) -> list[str]:
    return re.findall(r"[0-9a-ząćęłńóśźż#+.\-]+", text.lower())


def _option_reason(name: str) -> Optional[str]:
    """Powód odrzucenia pojedynczej nazwy albo ``None`` (technologia)."""
    from app.services.dealbreaker_filters import is_syntactic_technology_name

    words = _words(name)
    if not words:
        return "prose"
    lowered = name.lower().strip()
    if _CEFR.search(lowered) or any(w in _LANGUAGE_WORDS for w in words):
        return "language"
    if any(w in _DOMAIN_WORDS for w in words):
        return "domain"
    if any(w in _SOFT_WORDS for w in words):
        return "soft"
    # Kategoria albo praktyka w nazwie („Data architecture”, „Cloud
    # networking”) — nazwa spoza słownika z takim słowem nie jest technologią.
    if any(w in _CATEGORY_WORDS for w in words):
        return "category"
    if all(w in _ROLE_WORDS for w in words):
        return "role"
    if not is_syntactic_technology_name(name):
        return "prose"
    return None


def _normalize_option(raw: str) -> tuple[Optional[str], Optional[str]]:
    """Nazwa technologii bez wersji i słów roli albo (``None``, powód)."""
    from app.services.scoring_service import ALIAS_MAP

    text = _clean(raw)
    if not text:
        return None, "prose"
    if text.lower() in ALIAS_MAP or text.lower() in _SLASH_NAMES:
        # Nazwa ze słownika bywa rolą albo metodyką („QA”, „Software
        # developer”, „IT analysis”, „Scrum”) — do 30.09 ten skrót omijał
        # sprawdzenie i rola ukrywała 99,7% wysłanych (audyt B2).
        concept = _taxonomy_concept_reason(text)
        return (None, concept) if concept else (text, None)
    base, _version = strip_version(text)
    kept = [w for w in base.split() if w.lower().strip(".,") not in _ROLE_WORDS]
    if not kept:
        return None, "role"
    name = " ".join(kept)
    if name.lower() in ALIAS_MAP:
        concept = _taxonomy_concept_reason(name)
        return (None, concept) if concept else (name, None)
    reason = _option_reason(name)
    return (None, reason) if reason else (name, None)


def _taxonomy_concept_reason(name: str) -> Optional[str]:
    """Powód, gdy nazwa ze słownika jest rolą albo metodyką; inaczej ``None``."""
    if not is_non_technology_concept(name):
        return None
    return "role" if (taxonomy_category(name) or "").startswith("role_") else "category"


def _head_allows_examples(head: str) -> bool:
    """Czy głowa przykładów to kategoria albo technologia, a nie zdanie."""
    from app.services.scoring_service import ALIAS_MAP

    rest = [
        w
        for w in head.split()
        if w.lower().strip(".,:") not in _HEAD_FILLER_WORDS
        and w.lower().strip(".,:") not in _HEAD_CATEGORY_WORDS
    ]
    if not rest:
        return True
    # Reszta głowy musi być nazwą ze słownika; nazwa „składniowo poprawna”
    # („integracją systemów”) to już zdanie.
    phrase = " ".join(rest).lower().strip(".,:")
    return phrase in ALIAS_MAP or phrase in _SLASH_NAMES


def _guard_slash_names(text: str) -> str:
    for name in _SLASH_NAMES:
        text = re.sub(
            rf"(?<![0-9a-z]){re.escape(name)}(?![0-9a-z])",
            lambda m: m.group(0).replace("/", _SLASH_GUARD),
            text,
            flags=re.I,
        )
    return text


def _split_options(text: str, pattern: re.Pattern[str]) -> list[str]:
    parts = pattern.split(_guard_slash_names(text))
    return [p for p in (_clean(x.replace(_SLASH_GUARD, "/")) for x in parts) if p]


def _analyse(label: str) -> tuple[Optional[GateRequirement], Optional[str]]:
    text = _clean(label)
    if not text:
        return None, "prose"
    # Wersja odcięta PRZED podziałem na opcje: „React.js (v18 or higher)” to
    # jedna technologia, a „or” w nawiasie wersji nie jest alternatywą.
    text = strip_version(text)[0]
    raw_options: list[str]
    example = _EXAMPLES.match(text) or _PAREN_LIST.match(text)
    if example:
        head = _clean(example.group("head")).strip("(:-–— ")
        if not _head_allows_examples(head):
            return None, "prose"
        raw_options = _split_options(example.group("opts"), _EXAMPLE_SPLIT)
        # Głowa będąca technologią („CI/CD tools like …” → CI/CD) też spełnia.
        head_name, _ = _normalize_option(
            " ".join(w for w in head.split() if w.lower() not in _CATEGORY_WORDS)
        )
        if head_name:
            raw_options.insert(0, head_name)
        options: list[str] = []
        for raw in raw_options:
            name, _reason = _normalize_option(raw)
            if name and name.lower() not in {o.lower() for o in options}:
                options.append(name)
        if not options:
            return None, "category"
        return GateRequirement(label=label, options=tuple(options)), None
    if text.lower() in _SLASH_NAMES:
        raw_options = [text]
    else:
        raw_options = (
            _split_options(text, _ALT_SPLIT) if _ALT_SPLIT.search(text) else [text]
        )
    options = []
    for raw in raw_options:
        name, reason = _normalize_option(raw)
        if name is None:
            # Alternatywa z pozycją nietechniczną („Kafka lub doświadczenie
            # z kolejkami”) nie daje się sprawdzić — nie ukrywa.
            return None, reason
        if name.lower() not in {o.lower() for o in options}:
            options.append(name)
    return GateRequirement(label=label, options=tuple(options)), None


@lru_cache(maxsize=8192)
def gate_requirement(label: str) -> Optional[GateRequirement]:
    """Wymaganie bramki dla etykiety must albo ``None`` (nie bramkuje)."""
    return _analyse(label)[0]


@lru_cache(maxsize=8192)
def ignored_reason(label: str) -> Optional[str]:
    """Dlaczego etykieta nie bramkuje: language/domain/soft/category/role/prose."""
    requirement, reason = _analyse(label)
    return None if requirement is not None else reason


def critical_eligible(label: str) -> bool:
    """Czy pozycję must wolno oznaczyć jako krytyczną: bramkuje, a KAŻDA
    opcja jest technologią ze słownika (``is_gate_technology``).

    Węższe niż ``gate_requirement``: nazwa spoza słownika („Temenos T24”)
    dalej liczy się w punktach i dowodzie, ale krytyczną zostaje dopiero wtedy,
    gdy słownik ją zna (audyt 30.09, B2: 41,5% → 6,0% wysłanych ukrytych).
    """
    requirement = gate_requirement(label)
    return requirement is not None and all(
        is_gate_technology(option) for option in requirement.options
    )


def critical_selectable(label: str) -> bool:
    """Czy Delivery Lead może WYBRAĆ pozycję must jako krytyczną (08.10.2026).

    Szersze niż ``critical_eligible``: wystarczy, że pozycja bramkuje
    (``gate_requirement``), czyli jest nazwą technologii albo narzędzia — także
    takiego, którego słownik nie zna („Camunda BPM”, „TestNG”, „Qualys”).
    Bramka szuka wtedy tej nazwy w profilu, CV i notatkach. Do tej daty wybór
    ograniczał słownik: w 16 najnowszych rekrutacjach 9 skończyło z „Brak
    krytycznych”, bo narzędzi z requestu nie dało się oznaczyć. Podpowiedź
    z historii, wymóg decyzji przy przekazaniu i tytuł dla rekrutera zostają
    przy ``critical_eligible`` — tam nikt nie potwierdza wyboru.
    """
    return gate_requirement(label) is not None


_NOT_SELECTABLE_SENTENCES = {
    "language": "To język, nie technologia — sprawdzisz go w rozmowie.",
    "domain": "To branża, nie technologia — daje punkty, nie ukrywa kandydatów.",
    "soft": "To umiejętność miękka — daje punkty, nie ukrywa kandydatów.",
    "category": "To kategoria albo metodyka, nie konkretna technologia.",
    "role": "To rola, nie technologia.",
    "prose": "To opis, nie nazwa technologii ani narzędzia.",
}


def not_selectable_sentence(label: str) -> Optional[str]:
    """Zdanie dla Delivery Leada, dlaczego pozycji nie da się oznaczyć jako
    krytycznej; ``None``, gdy się da."""
    reason = ignored_reason(label)
    if reason is None:
        return None
    return _NOT_SELECTABLE_SENTENCES.get(reason, _NOT_SELECTABLE_SENTENCES["prose"])


def clear_cache() -> None:
    """Po przeładowaniu słownika umiejętności (``ALIAS_MAP``)."""
    gate_requirement.cache_clear()
    ignored_reason.cache_clear()
