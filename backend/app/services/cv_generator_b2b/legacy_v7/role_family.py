"""Role tego samego zawodu dla lat „jako X” w „Dlaczego nasz kandydat”.

Decyzja Artura z 20.11.2026 (wariant B). Prompt 14 każe pisać w punkcie 1
„N lat w IT, w tym M lat jako X”, gdzie M to suma dat WSZYSTKICH ról tego
zawodu, a kod liczył tylko role, których nazwa zawiera X dosłownie. „Senior
Business Analyst” i „Analityk systemowy” nie wchodziły więc do stażu „jako
analityk biznesowo-systemowy” i „w tym 16 lat” stawało się „ponad 1 rok”.
Pomiar na kopii produkcji (60 dni do 18.11.2026, 1874 CV): 78 CV z liczbą
„jako X” niższą o co najmniej rok niż staż w zawodzie, 31 o trzy lata i więcej.

Zawód rozpoznaje rdzeń nazwy ze słownika PL↔EN (analityk = analyst,
programista = developer, tester = QA), a nie przymiotniki domeny (biznesowy,
systemowy, IT) ani stopień. Technologia z X (Java, SAP, .NET…) musi stać
w nazwie roli albo w jej technologiach, a „Senior”/„Junior” z X w nazwie roli.
Wątpliwość = rola nie wchodzi. Reguła: docs/claude/generator-cv/lata-jako-x-rodzina-zawodu.md.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# Rdzenie słów: słowo pasuje, gdy zaczyna się od rdzenia. „x$” = tylko całe
# słowo, a rdzeń do trzech liter (qa, ux, sre) zawsze całym słowem.
Stems = tuple[str, ...]

# Rdzeń, który sam nazywa zawód.
_PROFESSIONS: dict[str, Stems] = {
    "analyst": ("analityk", "analityczk", "analyst"),
    "developer": ("programist", "developer", "deweloper", "programmer", "dev$"),
    "tester": ("tester", "sdet$", "qa$"),
    "architect": ("architekt", "architect"),
    "designer": ("projektant", "designer", "ux$", "ui$"),
    "devops": ("devops", "sre$"),
    "admin": ("administrator", "sysadmin", "admin$", "dba$"),
    "scientist": ("scientist",),
    "informatyk": ("informatyk",),
}
# Rdzeń ogólny („Engineer”, „Kierownik”): zawód mówi dopiero reszta nazwy.
_GENERAL: dict[str, Stems] = {
    "engineer": ("inzynier", "engineer"),
    "manager": ("kierownik", "manager", "menedzer", "menadzer"),
    "consultant": ("konsultant", "consultant"),
    "specialist": ("specjalist", "specialist", "ekspert", "expert"),
    "lead": ("lider", "leader", "lead$"),
    "coordinator": ("koordynator", "coordinator"),
    "director": ("dyrektor", "director"),
    "owner": ("owner",),
    "master": ("master",),
    "officer": ("officer",),
    "technician": ("technik$", "technician"),
}
_TESTING: Stems = ("qa$", "test", "testow", "testing", "testy$", "testowan", "quality")
# Zawód z rdzenia ogólnego i słowa obok: „Cloud Engineer”, „Kierownik projektu”.
_QUALIFIED: tuple[tuple[str, Stems], ...] = (
    ("tester", _TESTING),
    (
        "developer",
        (
            "software",
            "oprogramowan",
            "backend",
            "frontend",
            "fullstack",
            "java",
            "python",
            "net$",
            "dotnet",
            "c#$",
            "c++$",
            "javascript",
            "js$",
            "php$",
            "ruby",
            "golang",
            "mobile",
            "ios$",
            "android",
            "embedded",
            "web$",
            "react",
            "angular",
            "node",
            "kotlin",
            "scala",
            "typescript",
        ),
    ),
    (
        "devops",
        (
            "devops",
            "sre$",
            "cloud",
            "platform",
            "reliability",
            "infrastructure",
            "infrastruktur",
            "chmur",
            "kubernetes",
            "k8s$",
        ),
    ),
    ("data_engineer", ("data$", "danych", "etl$", "bigdata", "dwh$", "hurtowni")),
    ("network", ("network", "sieci$", "sieciow", "lan$", "wan$", "telekomunikac")),
    ("security", ("security", "bezpieczenst", "cyber", "soc$", "iam$")),
    # „Projektowania systemów” to nie kierownik projektu, więc formy całym słowem.
    (
        "project",
        (
            "project",
            "projekt$",
            "projektu$",
            "projektow$",
            "projektami$",
            "projekty$",
            "delivery",
            "program$",
            "programu$",
            "programme",
            "pmo$",
        ),
    ),
    ("product", ("product", "produkt")),
    ("scrum", ("scrum", "agile")),
    ("support", ("support", "wsparci", "helpdesk", "desk$", "serwis")),
    ("sap", ("sap$", "abap$")),
    ("implementation", ("wdrozen", "wdrozeni", "implementation", "implementac")),
)
# Gdy nic konkretniejszego: „Specjalista IT”, „System Engineer”.
_FALLBACK: tuple[tuple[str, Stems], ...] = (
    ("it_general", ("it$", "informatyk", "technologi", "teleinformatyczn")),
    ("systems", ("system", "systemow")),
)
# Analityk IT, biznesowy albo danych. „Cash Management Analyst”, „Tax Content
# Analyst” czy „Underwriting Analyst” to inne zawody (przegląd 20.11.2026).
_IT_ANALYST: Stems = (
    "business",
    "biznes",
    "system",
    "it$",
    "functional",
    "funkcjonaln",
    "techniczn",
    "technical",
    "solution",
    "rozwiazan",
    "requirement",
    "wymagan",
    "data$",
    "danych",
    "bi$",
    "process",
    "proces",
    "product",
    "produkt",
    "integrac",
    "integration",
    "application",
    "aplikac",
    "erp$",
    "crm$",
    "sap$",
    "software",
    "oprogramowan",
    "informatyczn",
)
_DOMAIN_ANALYST = "analyst_domain"
_IGNORED = frozenset(
    {
        "senior",
        "sr",
        "junior",
        "jr",
        "mid",
        "regular",
        "starszy",
        "starsza",
        "mlodszy",
        "mlodsza",
        "glowny",
        "glowna",
        "principal",
        "staff",
        "chief",
        "ds",
        "d",
        "s",
        "i",
        "ii",
        "iii",
        "iv",
        "the",
        "of",
        "and",
        "oraz",
        "w",
        "we",
        "z",
        "dla",
        "na",
        "a",
        "an",
        "to",
        "do",
        "spraw",
        "freelance",
        "b2b",
        "contractor",
        "kontraktor",
        "external",
    }
)
_SENIOR = frozenset({"senior", "sr", "starszy", "starsza"})
_JUNIOR = frozenset({"junior", "jr", "mlodszy", "mlodsza"})
# Technologia w nazwie X zawęża zawód: „Java Developer” to nie lata w PHP.
_TECHNOLOGIES = frozenset(
    {
        "java",
        "kotlin",
        "scala",
        "python",
        "php",
        "ruby",
        "golang",
        "go",
        "net",
        "c#",
        "c++",
        "javascript",
        "typescript",
        "react",
        "angular",
        "vue",
        "node",
        "frontend",
        "backend",
        "fullstack",
        "mobile",
        "ios",
        "android",
        "flutter",
        "embedded",
        "sap",
        "abap",
        "salesforce",
        "oracle",
        "sql",
        "plsql",
        "etl",
        "bi",
        "tableau",
        "qlik",
        "sharepoint",
        "dynamics",
        "servicenow",
        "pega",
        "aws",
        "azure",
        "gcp",
        "linux",
        "mainframe",
        "cobol",
        "data",
        "ml",
        "ai",
        "mulesoft",
        "informatica",
        "talend",
        "sas",
        "spark",
        "hadoop",
        "databricks",
        "snowflake",
        "kafka",
        "unix",
        "vmware",
        "cisco",
        "rpa",
        "uipath",
        "guidewire",
        "delphi",
        "perl",
        "rust",
        "swift",
        "xamarin",
        "qt",
        "plc",
        "scada",
        "hana",
        "crm",
        "erp",
        "mssql",
        "postgresql",
        "mysql",
        "mongodb",
    }
)
_TECHNOLOGY_ALIASES = {
    "danych": "data",
    "dotnet": "net",
    "nodejs": "node",
    "js": "javascript",
    "ts": "typescript",
    "powerbi": "bi",
    "cpp": "c++",
    "postgres": "postgresql",
}
# „jako X w Acme”, „as X (IAM) at Qurate”: staż w jednej firmie, nie w zawodzie.
_COMPANY_RE = re.compile(
    r"\s(?:w|we|u|at|in|for|dla|przy)\s+(?:firmie\s+|spółce\s+|the\s+)?"
    r"(?!(?:IT|QA|UX|UI|BI)\b)[A-ZŁŚŻŹĆŃÓĘĄ0-9]"
)
_CLAUSE_END_RE = re.compile(r"[,;]|\.(?:\s|$)")


def _words(text: object) -> list[str]:
    folded = str(text or "").replace("ł", "l").replace("Ł", "L")
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^\w+#]+", " ", folded).split()


def _hit(word: str, stems: Stems) -> bool:
    for stem in stems:
        if stem.endswith("$"):
            if word == stem[:-1]:
                return True
        elif word == stem if len(stem) <= 3 else word.startswith(stem):
            return True
    return False


def _profile(title: object) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(zawody, rdzenie ogólne, pozostałe słowa) nazwy stanowiska."""
    words = _words(title)
    found = {
        name for w in words for name, stems in _PROFESSIONS.items() if _hit(w, stems)
    }
    general = {
        name for w in words for name, stems in _GENERAL.items() if _hit(w, stems)
    }
    heads = {
        w
        for w in words
        if any(_hit(w, s) for s in _PROFESSIONS.values())
        or any(_hit(w, s) for s in _GENERAL.values())
    }
    rest = frozenset(w for w in words if w not in heads and w not in _IGNORED)
    if "analyst" in found:
        if any(_hit(w, _TESTING) for w in words):
            found = (found - {"analyst"}) | {"tester"}  # „QA Analyst” to tester
        elif rest and not any(_hit(w, _IT_ANALYST) for w in rest):
            found = (found - {"analyst"}) | {_DOMAIN_ANALYST}
    if not found and general:
        found = {
            name for name, stems in _QUALIFIED if any(_hit(w, stems) for w in words)
        }
        if not found:
            found = {
                name for name, stems in _FALLBACK if any(_hit(w, stems) for w in words)
            }
    return frozenset(found), frozenset(general), rest


def _technologies(texts: Iterable[object]) -> set[str]:
    out = set()
    for text in texts:
        for word in _words(text):
            word = _TECHNOLOGY_ALIASES.get(word, word)
            if word in _TECHNOLOGIES:
                out.add(word)
    return out


def same_profession(
    phrase: str, position: object, technologies: Iterable[object] = ()
) -> bool:
    """Czy stanowisko to ten sam zawód co X z „N lat jako X”."""
    want, want_general, want_rest = _profile(phrase)
    have, have_general, have_rest = _profile(position)
    if _DOMAIN_ANALYST in want and _DOMAIN_ANALYST in have:
        same = bool(want_rest & have_rest)  # analityk dziedzinowy tylko tej dziedziny
    elif want or have:
        same = bool((want & have) - {_DOMAIN_ANALYST})
    else:
        same = bool(want_general & have_general) and (
            bool(want_rest & have_rest) or not (want_rest or have_rest)
        )
    if not same:
        return False
    phrase_words, position_words = set(_words(phrase)), set(_words(position))
    for level in (_SENIOR, _JUNIOR):
        if phrase_words & level and not position_words & level:
            return False
    need = _technologies([phrase])
    return not need or bool(need & _technologies([position, *technologies]))


def names_company(after_phrase: str) -> bool:
    """Czy zdanie po X przypina staż do firmy („… w Acme”, „… at EY”)."""
    end = _CLAUSE_END_RE.search(after_phrase)
    clause = after_phrase[: end.start()] if end else after_phrase
    return bool(_COMPANY_RE.search(clause))
