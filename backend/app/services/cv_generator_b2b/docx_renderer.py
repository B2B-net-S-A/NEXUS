"""DOCX renderer — 1:1 port of `lib/generate_cv.py` from artur-t-96/CV-Generator.

Renders a B2B Network-branded CV from a structured candidate dict + the
shared template `szablon_firmowy.docx`. Supports PL/EN, blind anonymization
and MUST-HAVE keyword bolding.

The candidate dict shape matches what Claude returns from the extraction
prompt — see :mod:`app.services.cv_generator_b2b.prompts`.

Public entrypoint: :func:`render_cv_to_bytes`.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

from app.services.skill_normalize import is_taxonomy_technology, tech_alias_forms

logger = logging.getLogger(__name__)


COLOR_HEADER = RGBColor(225, 79, 79)
COLOR_TEXT = RGBColor(55, 53, 53)

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


_STOP_WORDS = {
    # Polski
    "w",
    "i",
    "o",
    "z",
    "do",
    "na",
    "dla",
    "od",
    "po",
    "we",
    "ze",
    "lub",
    "oraz",
    "jako",
    "przy",
    "przez",
    "pod",
    "nad",
    "przed",
    "sie",
    "to",
    "jest",
    "sa",
    "byl",
    "byla",
    "byly",
    "nie",
    "tak",
    # Angielski
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "and",
    "or",
    "with",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
}


# Characters that may be part of a technology name — used as custom word
# boundaries so "Git" never bolds "digital" and "C++" / "C#" / ".NET" still
# match as whole terms.
_WORD_CHARS = "0-9A-Za-z_#+ąćęłńóśźżĄĆĘŁŃÓŚŹŻàâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ"


# Proficiency / filler words a recruiter often types alongside a real skill
# ("Figma – zaawansowana znajomość", "Docker (mile widziane)"). A champion
# keyword whose every token is generic is dropped so prose words never get
# bolded; a parenthetical made of these is treated as a qualifier, not an alias.
_GENERIC_WORDS = {
    # PL — proficiency / filler / requirement language
    "zaawansowana",
    "zaawansowany",
    "zaawansowane",
    "podstawowa",
    "podstawowy",
    "podstawowe",
    "srednia",
    "srednio",
    "sredniozaawansowana",
    "sredniozaawansowany",
    "biegla",
    "biegły",
    "biegly",
    "biegle",
    "komunikatywna",
    "komunikatywny",
    "znajomosc",
    "znajomość",
    "doswiadczenie",
    "doświadczenie",
    "mile",
    "widziane",
    "widziana",
    "widziany",
    "dobra",
    "dobry",
    "dobre",
    "bardzo",
    "atut",
    "atutem",
    "plus",
    "wymagane",
    "wymagana",
    "wymagany",
    "opcjonalnie",
    "opcjonalne",
    "poziom",
    "umiejetnosc",
    "umiejętność",
    "umiejetnosci",
    "umiejętności",
    "preferowana",
    "preferowane",
    "preferowany",
    "ogolna",
    "ogólna",
    "praktyczna",
    "praktyczne",
    "must",
    "have",
    "nice",
    # EN — proficiency / filler / requirement language
    "advanced",
    "basic",
    "intermediate",
    "fluent",
    "proficient",
    "proficiency",
    "knowledge",
    "experience",
    "required",
    "optional",
    "good",
    "strong",
    "level",
    "skills",
    "skill",
    "preferred",
    "general",
    "practical",
    "familiarity",
    "technology",
    "technologies",
    "position",
    "positions",
    "creation",
    "possesses",
    # PL — requirement-prose nouns/verbs a champion entry wraps a real skill in.
    # These are NEVER the meaningful part of a technology, so they must never
    # bold the CV prose ("tworzenie", "technologie", "stanowisku" etc.).
    "technologia",
    "technologie",
    "technologii",
    "technologią",
    "technologiami",
    "technologiach",
    "stanowisko",
    "stanowisku",
    "stanowiska",
    "stanowisk",
    "stanowiskach",
    "tworzenie",
    "tworzenia",
    "tworzeniu",
    "kluczowy",
    "kluczowa",
    "kluczowe",
    "kluczowych",
    "kluczowym",
    "kluczowymi",
    "posiada",
    "posiadanie",
    "posiadania",
    "wymagania",
    "wymaganiami",
    "rozwój",
    "rozwoju",
    "rozwojem",
    "lider",
    "lidera",
    "liderem",
    "liderzy",
}


def _is_alias_like(text: str) -> bool:
    """True iff a parenthetical reads like a tech alias, not a qualifier.

    "K8s" / ".NET" / "PL/SQL" → alias (bold it too); "zaawansowana znajomość"
    or "Design System" → qualifier/phrase (bold only the base term).
    """
    s = text.strip()
    if not s or len(s) > 12 or re.search(r"\s", s):
        return False
    return any(ch.isalnum() for ch in s)


def _is_generic_phrase(text: str) -> bool:
    """True iff every word in `text` is a stop/proficiency word (skip bolding)."""
    tokens = re.findall(rf"[{_WORD_CHARS}]+", text.lower())
    if not tokens:
        return True
    return all(t in _GENERIC_WORDS or t in _STOP_WORDS or len(t) < 2 for t in tokens)


def _is_filler_word(word: str) -> bool:
    """True iff `word` is a proficiency/requirement/stop word (no real meaning)."""
    norm = re.sub(rf"[^{_WORD_CHARS}]", "", word.lower())
    return bool(norm) and (norm in _GENERIC_WORDS or norm in _STOP_WORDS)


def _core_keyword(phrase: str) -> str:
    """Trim leading/trailing filler so the real term inside a champion entry
    still bolds — WITHOUT fragmenting a verbose requirement into generic words.

    Champion entries are often natural language ("Znajomość Java") rather than
    bare tech tokens. We strip filler (proficiency / requirement / stop words)
    from BOTH ends and keep the core as ONE phrase; the CV prose is matched
    against that core only. A wordy requirement therefore stays whole and only
    matches verbatim, so its generic words ("tworzenie", "rozwój") can never
    bold the prose on their own — that earlier over-bolding is what recruiters
    reported ("bolds random words like 'tworzenie'/'technologie'").

        "Znajomość Java"               → "Java"
        "Dobra znajomość Spring Boot"  → "Spring Boot"
        "Design System"               → "Design System"   (no filler — unchanged)
        "Tworzenie i rozwój aplikacji" → "Tworzenie i rozwój aplikacji"
                                          (kept whole — matched verbatim only)
        "mile widziane"               → ""                (all filler — dropped)
    """
    words = phrase.split()
    while words and _is_filler_word(words[0]):
        words.pop(0)
    while words and _is_filler_word(words[-1]):
        words.pop()
    return " ".join(words)


def _split_segments(kw: str) -> tuple[str, list[str]]:
    """Split a champion chip into the text outside parentheses + each
    parenthetical's contents (nesting-aware).

        "Material Design (a) (długie wyjaśnienie)"
            → ("Material Design", ["a", "długie wyjaśnienie"])
    """
    outside: list[str] = []
    parens: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in kw:
        if ch == "(":
            if depth == 0:
                outside.append(" ")
                buf = []
            else:
                buf.append(ch)
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                parens.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        elif depth == 0:
            outside.append(ch)
        else:
            buf.append(ch)
    return "".join(outside).strip(), parens


_NON_SUBTERM_HEADS = {"np", "tj", "eg", "itp", "itd", "czyli", "zwłaszcza", "w"}


def _paren_is_subterm(content: str) -> bool:
    """True iff a parenthetical lists real sub-skills ("heurystyki, best
    practices UX", "iOS/Android", "RWD, multi-device") rather than a prose
    explanation ("projektowanie estetycznych interfejsów zgodnie z…").

    Champion chips in NEXUS read ``Koncept (pod-terminy) (długie wyjaśnienie)``.
    A short comma-list is a sub-term group worth bolding; a multi-word sentence
    is an explanation and must be dropped so its prose never bolds the CV.
    """
    c = content.strip()
    if not c:
        return False
    if _is_alias_like(c):  # "K8s", ".NET", "RWD"
        return True
    words = c.split()
    if len(words) > 5:
        return False
    first = re.sub(rf"[^{_WORD_CHARS}]", "", words[0].lower())
    return first not in _NON_SUBTERM_HEADS


# Conjunctions / separators that split a chip into independent bold-terms, so
# "Material Design oraz Human Interface Guidelines" bolds BOTH halves and a
# comma-list of sub-skills bolds each item.
_TERM_SEPARATORS = re.compile(r"[;,]|\b(?:i|oraz|lub|and|or)\b", re.IGNORECASE)


def _extract_keyword_terms(keyword: str) -> list[str]:
    """Expand a champion chip into every bold-worthy term.

    Strips prose-explanation parentheticals, keeps short sub-term groups, and
    splits on conjunctions so each real concept is matched on its own:

        "User-Centered Design (projektowanie w oparciu o…)"
            → ["User-Centered Design"]
        "Material Design oraz Human Interface Guidelines (znajomość…)"
            → ["Material Design", "Human Interface Guidelines"]
        "Zasady Gestalt (hierarchia, percepcja, grupowanie) (umiejętność…)"
            → ["Zasady Gestalt", "hierarchia", "percepcja", "grupowanie"]
        "Kubernetes (K8s)" → ["Kubernetes", "K8s"]
    """
    kw = (keyword or "").strip()
    if not kw:
        return []
    outside, parens = _split_segments(kw)
    raw: list[str] = []
    if outside:
        raw.append(outside)
    raw.extend(p for p in parens if _paren_is_subterm(p))

    terms: list[str] = []
    for chunk in raw:
        for part in _TERM_SEPARATORS.split(chunk):
            t = (part or "").strip()
            if t:
                terms.append(t)
    return terms


# Short tokens whose SHAPE trips the hard-tech heuristic (all-caps acronym or
# an embedded digit) but which are never technologies: language-proficiency
# levels ("English B2", "C1"), design/QA/business acronyms and role shorthands.
# Only the heuristic is gated — the skill taxonomy stays authoritative, so if a
# token is a real taxonomy technology it still bolds.
_NEVER_TECH_TOKENS = frozenset(
    {
        "a1",
        "a2",
        "b1",
        "b2",
        "c1",
        "c2",  # CEFR language levels
        "b2b",
        "b2c",
        "ux",
        "ui",
        "qa",
        "hr",
        "pm",
        "po",
        "cv",
        "kpi",
        "roi",
        "sla",
        "nda",
        "eu",
        "usa",
    }
)


def _is_strong_tech_token(token: str) -> bool:
    """True iff a single token is unmistakably a technology on its own.

    Used to pull the real tech out of a verbose champion requirement
    ("Doświadczenie z bazami danych SQL" → "SQL") WITHOUT also bolding the
    generic Polish prose around it ("bazami", "danych"). Only a HARD tech
    signal qualifies:

        special chars      C++, C#, .NET, Node.js, CI/CD
        digits             S3, OAuth2
        all-caps acronym   SQL, API, AWS, REST
        internal/camel cap PostgreSQL, GraphQL, GitLab

    A plain Capitalized word (Projektowanie, Aplikacji, Server) is ambiguous —
    it could be English tech or just a Polish common noun — so it NEVER
    qualifies. That asymmetry is what keeps requirement prose from bolding.
    """
    if _is_filler_word(token):
        return False
    # Probe with terminal sentence punctuation stripped. Without this, the
    # special-char test below fires on EVERY sentence-final Polish word
    # ("kandydata.", "dalej.", "projektami.") because of the trailing period,
    # which is how requirement prose ended up bolded in delivered CVs. Internal
    # separators are untouched — "Node.js", "CI/CD", "C++", "2.1/2.2" all keep
    # their special char because it is not terminal.
    probe = token.rstrip(".,:;!?…")
    if probe.lower() in _NEVER_TECH_TOKENS:
        return False
    if any(ch in probe for ch in "+#/."):
        return True
    # `probe`, not `token`, for all branches below the strip. Behaviourally a
    # no-op (the stripped characters carry neither digits nor letters) — kept
    # uniform so a future edit to the strip set stays correct everywhere.
    if any(ch.isdigit() for ch in probe):
        return True
    letters = [ch for ch in probe if ch.isalpha()]
    if len(letters) < 2:
        return False
    if all(ch.isupper() for ch in letters):
        return True
    # Internal camelCase hump — an uppercase letter directly after a lowercase
    # one ("PostgreSQL", "GraphQL", "GitLab", "iOS"). A capital after a hyphen
    # or space ("User-Centered", "Human Interface") is just Title Case, NOT a
    # tech signal, so it must not qualify.
    return any(
        token[i].isupper() and token[i - 1].islower() for i in range(1, len(token))
    )


# Concrete technologies — tools, languages, frameworks, libraries, platforms.
# The ONLY terms that bold without a hard-tech signal in the token itself: a
# plain Capitalized word like "Python" / "Figma" / "Docker" / "React" carries
# no signal (no caps drift, digit or special char), so it can only be matched
# against this curated, lowercase, whitespace/hyphen-normalised set
# (see :func:`_norm_tech`). Design methodologies / concepts ("User-Centered
# Design", "Material Design", "Zasady Gestalt") are deliberately ABSENT — they
# must never bold (recruiter directive: bold only technologies).
_KNOWN_TECH: frozenset[str] = frozenset(
    {
        # Languages
        "python",
        "java",
        "javascript",
        "typescript",
        "kotlin",
        "swift",
        "php",
        "ruby",
        "scala",
        "rust",
        "dart",
        "elixir",
        "clojure",
        "haskell",
        "lua",
        "perl",
        "groovy",
        "objective-c",
        "node.js",
        "node",
        "deno",
        "bun",
        # Frontend
        "react",
        "react native",
        "angular",
        "vue",
        "vue.js",
        "svelte",
        "next.js",
        "nextjs",
        "nuxt",
        "remix",
        "redux",
        "mobx",
        "jquery",
        "tailwind",
        "tailwind css",
        "bootstrap",
        "sass",
        "scss",
        "less",
        "webpack",
        "vite",
        "rollup",
        "babel",
        "styled-components",
        "astro",
        # Backend / frameworks
        "django",
        "flask",
        "fastapi",
        "spring",
        "spring boot",
        "express",
        "express.js",
        "nestjs",
        "laravel",
        "symfony",
        "rails",
        "ruby on rails",
        "asp.net",
        ".net",
        "dotnet",
        "ktor",
        "quarkus",
        "micronaut",
        # Data / databases
        "sql",
        "postgresql",
        "postgres",
        "mysql",
        "mariadb",
        "mongodb",
        "redis",
        "sqlite",
        "oracle",
        "sql server",
        "mssql",
        "cassandra",
        "dynamodb",
        "elasticsearch",
        "opensearch",
        "neo4j",
        "clickhouse",
        "snowflake",
        "bigquery",
        "redshift",
        "databricks",
        "spark",
        "hadoop",
        "kafka",
        "rabbitmq",
        "airflow",
        "dbt",
        # Cloud / devops
        "aws",
        "gcp",
        "azure",
        "docker",
        "kubernetes",
        "k8s",
        "terraform",
        "ansible",
        "jenkins",
        "gitlab",
        "github",
        "github actions",
        "circleci",
        "ci/cd",
        "helm",
        "prometheus",
        "grafana",
        "datadog",
        "nginx",
        "apache",
        "openshift",
        "argocd",
        "git",
        "svn",
        # Observability / security
        "splunk",
        "qradar",
        "sentry",
        "kibana",
        "logstash",
        "vault",
        "consul",
        # Mobile
        "android",
        "ios",
        "flutter",
        "swiftui",
        "jetpack compose",
        "xamarin",
        "ionic",
        "cordova",
        # Design tools
        "figma",
        "sketch",
        "adobe xd",
        "invision",
        "zeplin",
        "framer",
        "photoshop",
        "illustrator",
        "after effects",
        "indesign",
        "miro",
        "webflow",
        "axure",
        "protopie",
        # APIs / protocols / standards
        "rest",
        "restful",
        "graphql",
        "grpc",
        "soap",
        "websocket",
        "websockets",
        "oauth",
        "oauth2",
        "openapi",
        "swagger",
        "jwt",
        "saml",
        "json",
        "xml",
        "yaml",
        "html",
        "html5",
        "css",
        "css3",
        "wcag",
        "rwd",
        "wai-aria",
        "aria",
        "xpath",
        # Data science / ML
        "pytorch",
        "tensorflow",
        "keras",
        "scikit-learn",
        "sklearn",
        "pandas",
        "numpy",
        "matplotlib",
        "jupyter",
        "langchain",
        "opencv",
        "spacy",
        "xgboost",
        "power bi",
        "tableau",
        "looker",
        # Misc tools / platforms
        "jira",
        "confluence",
        "postman",
        "maven",
        "gradle",
        "npm",
        "yarn",
        "pnpm",
        "unity",
        "unreal engine",
        "wordpress",
        "drupal",
        "magento",
        "shopify",
        "salesforce",
        "sap",
        # Microsoft endpoint management / identity / MDM. Multi-word brand
        # names carry no per-token hard-tech signal ("Microsoft"/"Endpoint"/
        # "Manager" are plain words), so without the allowlist they bold only
        # partially or not at all — single-word brands ("Intune", "AirWatch")
        # already bold via the proper-noun fallback. Recruiter directive: a key
        # technology must bold at EVERY occurrence across the whole CV, and a
        # curated entry also bolds the phrase WHOLE (no stray "AD"/"ONE" runs).
        # Keys are stored normalised (hyphens → spaces) to match _norm_tech.
        "microsoft intune",
        "microsoft endpoint manager",
        "endpoint manager",
        "configuration manager",
        "windows autopilot",
        "azure ad",
        "azure active directory",
        "active directory",
        "microsoft entra",
        "microsoft entra id",
        "entra id",
        "conditional access",
        "group policy",
        "windows server",
        "hyper v",
        # Microsoft 365 / productivity / data
        "microsoft 365",
        "office 365",
        "microsoft office",
        "exchange online",
        "microsoft exchange",
        "sharepoint online",
        "microsoft teams",
        "power automate",
        "power apps",
        "power platform",
        "power query",
        "microsoft defender",
        "microsoft sentinel",
        "microsoft graph",
        "dynamics 365",
        # Azure / Microsoft dev stack (multi-word). Only phrases whose tokens
        # carry NO independent tech signal — a phrase like "Microsoft SQL
        # Server" / ".NET Core" is deliberately ABSENT: its sub-token ("SQL",
        # ".NET") is itself a technology that the buried-token logic already
        # bolds, and a curated whole-phrase entry would SUPPRESS that.
        "azure functions",
        "visual studio",
        "visual studio code",
        "vs code",
        "entity framework",
        "spring security",
        "spring data",
        "spring cloud",
        "spring mvc",
        # MDM / EMM platforms (peers of Intune)
        "workspace one",
        "vmware workspace one",
        "jamf pro",
        # Cloud platforms (multi-word)
        "google cloud",
        "google cloud platform",
        "google workspace",
        "amazon web services",
        "elastic stack",
    }
)


def _norm_tech(text: str) -> str:
    """Lowercase + collapse whitespace/hyphens for ``_KNOWN_TECH`` lookup.

    Keeps tech punctuation (``.`` ``/`` ``+`` ``#``) so ".net", "ci/cd" and
    "c++" stay distinct, but folds hyphen↔space drift ("react-native" ↔
    "react native") onto one key.
    """
    return re.sub(r"[\s\-]+", " ", text.strip().lower())


def _is_tech_word(token: str) -> bool:
    """True iff a single token is a recognised technology — the NEXUS skill
    taxonomy (canonical or alias in a tech category), a hard-tech signal
    (:func:`_is_strong_tech_token`), or the curated ``_KNOWN_TECH`` allowlist."""
    return (
        is_taxonomy_technology(token)
        or _is_strong_tech_token(token)
        or _norm_tech(token) in _KNOWN_TECH
    )


def _is_technology(term: str) -> bool:
    """True iff `term` is a concrete technology worth bolding on its own.

    Recruiters asked the generator to bold ONLY technologies — tools,
    languages, frameworks, libraries, platforms and technical acronyms /
    standards — and to STOP bolding design methodologies, concepts and
    requirement prose ("User-Centered Design", "Material Design", "Zasady
    Gestalt", "visual design", "tworzenie i rozwój design systemów").

    Qualifies when the term is a NEXUS skill-taxonomy technology (canonical or
    alias in a tech category — "Kubernetes", "K8s", "PostgreSQL"); the curated
    ``_KNOWN_TECH`` allowlist verbatim ("Spring Boot", "SQL Server"); a SINGLE
    token with a hard-tech signal ("SQL", "C++", "K8s"); or a multi-word phrase
    whose EVERY word is itself a tech token ("Selenium WebDriver", "GitLab
    CI/CD"). A phrase with any plain word ("visual design", "User-Centered
    Design") fails here — only a hard-tech token buried inside it (handled by
    the caller) may still bold.

    The old "any capitalised non-Polish word is a product name" fallback
    (``_is_tech_token_name``) was removed: it was the main source of false
    positives (Agile, Leadership, English, "Analiza"). Niche brands the
    allowlist misses are now covered by the taxonomy instead.
    """
    t = term.strip()
    if not t:
        return False
    if is_taxonomy_technology(t):
        return True
    if _norm_tech(t) in _KNOWN_TECH:
        return True
    tokens = [tok for tok in t.split() if tok]
    if not tokens:
        return False
    if len(tokens) == 1:
        return _is_tech_word(t)
    return all(_is_tech_word(tok) for tok in tokens)


def compile_keyword_patterns(keywords: list[str] | None) -> list[re.Pattern[str]]:
    """Compile whole-phrase, word-boundary regexes for champion TECHNOLOGIES.

    Every champion chip is expanded (:func:`_extract_keyword_terms`) into its
    candidate terms — explanation parentheticals stripped, conjunctions split.
    A term bolds WHOLE wherever it overlaps the CV (every section, including
    EXPERIENCE) ONLY when it is a concrete technology (:func:`_is_technology`):
    a tool, language, framework, library, platform or technical acronym /
    standard. Multi-word phrases match across flexible whitespace; matching is
    case-insensitive.

    Recruiter directive (supersedes the earlier "bold every requirement"
    behaviour): design methodologies / concepts / requirement prose
    ("User-Centered Design", "Material Design", "Zasady Gestalt", "visual
    design", "tworzenie i rozwój") must NOT bold. When such a phrase still
    hides a hard-tech token ("Zasady WCAG 2.1/2.2" → "WCAG", "bazami danych
    SQL" → "SQL"), only that token bolds — never the surrounding concept.
    """
    patterns: list[re.Pattern[str]] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        key = term.lower()
        if key in seen:
            return
        single_letter = len(term) == 1
        stopword_hit = key in _STOP_WORDS
        confirmed_tech = _is_tech_word(term)
        # Single-letter and stopword-colliding terms bold ONLY when they are a
        # confirmed technology, and then case-sensitively: the language "C"/"R"
        # and the QA tool "Jest" bold, but a stray lowercase "c"/"r" and the
        # Polish word "jest" never do. (Both were previously unbold-able — "C"
        # via the min-length-2 guard, "Jest" via the stop-word guard.)
        if single_letter and not (confirmed_tech and is_taxonomy_technology(term)):
            return
        if not single_letter and len(term) < 2:
            return
        if stopword_hit and not confirmed_tech:
            return
        seen.add(key)
        display = term
        case_sensitive = False
        if single_letter:
            display, case_sensitive = term.upper(), True
        elif stopword_hit:
            display, case_sensitive = term[:1].upper() + term[1:], True
        # Build from tokens so "auto-layout" also matches "auto layout"
        # (hyphen ↔ space spelling drift between champion list and CV).
        parts = [p for p in re.split(r"[\s\-]+", display) if p]
        escaped = r"[\s\-]+".join(re.escape(p) for p in parts)
        # "CI/CD" should also match "CI / CD" — slash with optional spaces.
        escaped = escaped.replace("/", r"\s*/\s*")
        if not escaped:
            return
        # Tolerate Polish declension on a plain single-word tech stem so
        # "Python"/"Docker" also bold "Pythona"/"Pythonie"/"Dockerem". Only for
        # all-letter single words (never acronyms / versioned / multi-word,
        # which don't inflect); the group is optional so the bare form matches.
        if len(parts) == 1 and display.isalpha() and len(display) >= 4:
            escaped = escaped + r"(?:a|u|em|ie|owi|ów|om|ach|ami|y)?"
        patterns.append(
            re.compile(
                rf"(?<![{_WORD_CHARS}]){escaped}(?![{_WORD_CHARS}])",
                0 if case_sensitive else re.IGNORECASE,
            )
        )

    def _add_technology(t: str) -> None:
        # Bold the whole technology, plus its taxonomy canonical/aliases so a
        # chip "ReactJS"/"K8s"/"Postgres"/"Microsoft Azure" also bolds
        # "React"/"Kubernetes"/"PostgreSQL"/"Azure" (and vice-versa).
        _add(t)
        for form in tech_alias_forms(t):
            _add(form)
        # Recover a buried brand token ONLY when a multi-word compound is ONE
        # real tech plus version junk ("Java 17+" → "Java"). A genuine
        # multi-word product ("Apache Airflow", "Selenium WebDriver") whose
        # words are EACH tech has ≥2 alpha-tech tokens → stays whole, so a
        # shared vendor prefix never leaks onto OTHER products ("Apache NiFi").
        tokens = t.split()
        if len(tokens) > 1 and _norm_tech(t) not in _KNOWN_TECH:
            alpha_tech = [
                tok
                for tok in tokens
                if _is_tech_word(tok) and any(ch.isalpha() for ch in tok)
            ]
            if len(alpha_tech) == 1:
                _add(alpha_tech[0])

    for kw in keywords or []:
        for term in _extract_keyword_terms(kw):
            raw = term.strip()
            # If the chip is itself a concrete technology, bold it directly.
            # This carries single-letter languages ("C"/"R") and the tool
            # "Jest" — which the length / stop-word / generic guards below (and
            # _core_keyword, which strips "Jest" to "") would otherwise drop.
            if raw and _is_technology(raw):
                _add_technology(raw)
                continue
            # Otherwise trim filler ("Znajomość Java" → "Java", "Zaawansowany
            # visual design" → "visual design"); a fully generic entry drops.
            v = _core_keyword(term).strip()
            if len(v) < 2 or v.lower() in _STOP_WORDS:
                continue
            if _is_generic_phrase(v):
                continue
            if _is_technology(v):
                _add_technology(v)
            else:
                # Not a technology in itself ("visual design", "User-Centered
                # Design", "bazami danych SQL") — never bold the concept/prose;
                # only surface a hard-tech token buried inside it ("SQL",
                # "WCAG") so it still bolds under inflection drift. Require a
                # letter so a bare version ("2.1/2.2") never bolds.
                for w in v.split():
                    if _is_strong_tech_token(w) and any(ch.isalpha() for ch in w):
                        _add(w)
    return patterns


def _unambiguous_tech_occurrence(text: str, match: re.Match[str]) -> bool:
    """Currently scoped to Jest; other ambiguous names need separate evidence/tests."""
    if match.group().casefold() != "jest":
        return True
    # "Jest" is also the Polish verb "is", including at sentence start.
    # Accept standalone/list mentions or a preceding testing/tool context.
    tail = text[match.end() :].lstrip()
    if not tail or tail[0] in ",;/()":
        return True
    prefix = re.split(r"[.!?;\n]", text[: match.start()])[-1][-80:]
    return bool(
        re.search(
            r"\b(?:test\w*|framework\w*|bibliotek\w*|narzędz\w*|using|with)\b",
            prefix,
            re.IGNORECASE,
        )
    )


def highlight_spans(
    text: str, patterns: list[re.Pattern[str]]
) -> list[tuple[int, int]]:
    """Merged (start, end) spans of all keyword matches inside `text`."""
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            if _unambiguous_tech_occurrence(text, m):
                spans.append((m.start(), m.end()))
    if not spans:
        return []
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def should_highlight(word: str, keywords: list[str] | None) -> bool:
    """True iff `word` (a single term) matches a champion keyword."""
    if not keywords or not word:
        return False
    return bool(highlight_spans(word, compile_keyword_patterns(keywords)))


def add_text_with_highlights(
    para: Any,
    text: str,
    keywords: list[str] | None,
    base_font_size: Pt = Pt(10),
    patterns: list[re.Pattern[str]] | None = None,
) -> None:
    """Add `text` to `para`, bolding phrases that match champion `keywords`."""

    def _add_run(fragment: str, bold: bool) -> None:
        if not fragment:
            return
        run = para.add_run(fragment)
        run.font.name = "Montserrat"
        run.font.color.rgb = COLOR_TEXT
        run.font.size = base_font_size
        if bold:
            run.font.bold = True

    if patterns is None:
        patterns = compile_keyword_patterns(keywords)
    if not patterns or not text:
        _add_run(text, bold=False)
        return

    spans = highlight_spans(text, patterns)
    cursor = 0
    for start, end in spans:
        _add_run(text[cursor:start], bold=False)
        _add_run(text[start:end], bold=True)
        cursor = end
    _add_run(text[cursor:], bold=False)


TRANSLATIONS = {
    "pl": {
        "why": "DLACZEGO NASZ KANDYDAT?",
        "education": "EDUKACJA",
        "dates": "Daty",
        "education_header": "Nazwa uczelni/kierunek",
        "skills": "UMIEJĘTNOŚCI",
        "certifications": "CERTYFIKATY",
        "languages": "JĘZYKI",
        "experience": "DOŚWIADCZENIE",
        "company_name": "Nazwa firmy:",
        "position": "Stanowisko:",
        "considered_for": "Rozważany na stanowisko:",
        "responsibilities": "Zakres zadań:",
        "technologies": "Technologie:",
        "consent_heading": "Zgoda kandydata na przetwarzanie danych przez Klienta",
        "rodo": (
            "Wyrażam zgodę na przetwarzanie moich danych osobowych zawartych w przekazanych "
            "przeze mnie dokumentach przez B2B.net S.A. w celach związanych z moim udziałem "
            "w niniejszym procesie rekrutacyjnym. Ponadto przyjmuję do wiadomości i oświadczam, "
            "że zrozumiałem/am, iż administratorem moich danych osobowych zebranych na podstawie "
            "niniejszej zgody jest B2B.net S.A. z siedzibą w Warszawie, Al. Jerozolimskie 180, "
            "02-486 Warszawa. Dane będą przetwarzane zgodnie z przepisami Rozporządzenia Parlamentu "
            "Europejskiego i Rady (UE) 2016/679 z dnia 27 kwietnia 2016 r. w sprawie ochrony osób "
            "fizycznych w związku z przetwarzaniem danych osobowych i w sprawie swobodnego przepływu "
            'takich danych (dalej „RODO"). Dane przekazałem/am dobrowolnie, przy czym przysługuje mi '
            "prawo do cofnięcia zgody na przetwarzanie danych w dowolnym momencie poprzez wysłanie "
            "żądania na adres: rekrutacja@b2bnetwork.pl. Podanie danych jest niezbędne do realizacji "
            "ww. celu, dlatego żądanie ich usunięcia jest równoznaczne z rezygnacją z dalszego udziału "
            "w procesie rekrutacyjnym. Przysługuje mi również prawo dostępu do treści moich danych oraz "
            "ich poprawiania w każdym czasie. Jestem również świadomy/świadoma, że odbiorcami moich danych "
            "osobowych mogą być wyłącznie podmioty upoważnione na podstawie przepisów prawa, a także "
            "upoważnione na podstawie umów zawartych przez B2B.net S.A., w szczególności z klientami."
        ),
    },
    "en": {
        "why": "WHY OUR CANDIDATE?",
        "education": "EDUCATION",
        "dates": "Dates",
        "education_header": "Names of University/degrees",
        "skills": "SKILLS",
        "certifications": "CERTIFICATIONS",
        "languages": "LANGUAGES",
        "experience": "EXPERIENCE",
        "company_name": "Company:",
        "position": "Position:",
        "considered_for": "Considered for:",
        "responsibilities": "Tasks:",
        "technologies": "Technologies:",
        "consent_heading": "Candidate's consent to data processing by the Client",
        "rodo": (
            "I hereby consent to the processing of my personal data contained in the documents "
            "submitted by me by B2B.net S.A. for purposes related to my participation in this "
            "recruitment process. Furthermore, I acknowledge and declare that I have understood "
            "that the administrator of my personal data collected on the basis of this consent is "
            "B2B.net S.A. with its registered office in Warsaw, Al. Jerozolimskie 180, 02-486 Warsaw. "
            "The data will be processed in accordance with the provisions of Regulation (EU) 2016/679 "
            "of the European Parliament and of the Council of 27 April 2016 on the protection of natural "
            "persons with regard to the processing of personal data and on the free movement of such data "
            '(hereinafter "GDPR"). I have provided the data voluntarily, and I have the right to withdraw '
            "my consent to data processing at any time by sending a request to: rekrutacja@b2bnetwork.pl. "
            "The provision of data is necessary for the realization of the above purpose, therefore requesting "
            "their deletion is tantamount to resignation from further participation in the recruitment process. "
            "I also have the right to access the content of my data and to correct them at any time. I am also "
            "aware that the recipients of my personal data may only be entities authorized under the law, as well "
            "as authorized under contracts concluded by B2B.net S.A., in particular with customers."
        ),
    },
}


def add_horizontal_line(doc: Any) -> Any:
    """Add the B2B branded red horizontal divider."""
    para = doc.add_paragraph()

    hr_xml = """
    <w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
         xmlns:v="urn:schemas-microsoft-com:vml"
         xmlns:o="urn:schemas-microsoft-com:office:office">
        <w:rPr><w:noProof/></w:rPr>
        <w:pict>
            <v:rect style="width:448.6pt;height:2pt" fillcolor="#e14f4f" stroked="f"
                    o:hr="t" o:hrstd="t" o:hrnoshade="t" o:hrpct="989" o:hralign="center"/>
        </w:pict>
    </w:r>
    """

    hr_element = parse_xml(hr_xml)
    para._element.append(hr_element)
    para.paragraph_format.space_before = Pt(4)
    para.paragraph_format.space_after = Pt(6)
    return para


# Maksymalna szerokość obrazu zgody w calach — szerokość kolumny tekstu przy
# marginesach szablonu. Obraz szerszy jest skalowany proporcjonalnie w dół;
# węższy zostaje w swoim rozmiarze, bo zrzut maila rozciągnięty na siłę robi
# się nieczytelny.
_CONSENT_MAX_WIDTH_IN = 6.3
# Sufit wysokości — użyteczna wysokość A4 przy marginesach szablonu, minus
# zapas na nagłówek sekcji. Bez niego wąski, długi zrzut z telefonu (np. 300×900)
# zostaje w swojej szerokości i wychodzi na 12 cali wysokości, czyli poza stronę:
# Word przycina go w połowie, a dowód zgody staje się nieczytelny. Ten sufit
# wychodzi na jaw dopiero, gdy przestaniemy rozciągać obrazy do szerokości
# kolumny — samo skalowanie w dół po szerokości go nie łapie.
_CONSENT_MAX_HEIGHT_IN = 8.5


def add_consent_screenshot(doc: Any, image_bytes: bytes, heading: str) -> bool:
    """Dołącz na końcu CV zrzut ekranu ze zgodą kandydata. Zwraca, czy się udało.

    Wymóg PKO BP: pod treścią CV ma być widoczny zrzut maila, w którym kandydat
    zgadza się na przetwarzanie danych przez bank. Do 09.2026 generator tylko
    OSTRZEGAŁ rekrutera, żeby wkleił go ręcznie przed wysyłką — bo nie miał
    skąd wziąć obrazu.

    Wstawiane w NORMALNYM przepływie, a nie jako pływak: klauzula RODO niżej
    jest kotwiczona do dolnej krawędzi ostatniej strony z oblewaniem
    „góra i dół", więc treść płynąca pod nią przechodzi na kolejną stronę
    zamiast się z nią nakładać. Obraz wstawiony jako drugi pływak nie miałby
    tej gwarancji i mógłby przykryć klauzulę.

    Zwraca `False` zamiast rzucać, gdy obraz jest nieczytelny dla python-docx:
    CV bez zrzutu to dokument do ręcznego uzupełnienia (stan sprzed tej zmiany),
    a wyjątek tutaj wywróciłby CAŁĄ generację — łącznie z wywołaniem modelu,
    które właśnie za nią zapłaciliśmy.
    """
    if not image_bytes:
        return False

    try:
        doc.add_page_break()
        head = doc.add_paragraph()
        run = head.add_run(heading)
        run.bold = True
        run.font.size = Pt(11)
        head.paragraph_format.space_after = Pt(6)

        stream = io.BytesIO(image_bytes)
        picture_para = doc.add_paragraph()
        picture_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        picture = picture_para.add_run().add_picture(stream)

        # Skalujemy WYŁĄCZNIE w dół. Podanie `width=` od razu przy wstawianiu
        # rozciągałoby też obrazy węższe niż kolumna tekstu — a zrzut z telefonu
        # rozdmuchany do 6,3" robi się rozmyty i nieczytelny, czyli dokładnie
        # bezużyteczny w roli dowodu zgody.
        max_width = Inches(_CONSENT_MAX_WIDTH_IN)
        max_height = Inches(_CONSENT_MAX_HEIGHT_IN)
        # Jeden współczynnik dla obu wymiarów — skalowanie osobno po szerokości
        # i wysokości zniekształciłoby proporcje zrzutu.
        ratio = min(
            max_width / picture.width if picture.width > max_width else 1.0,
            max_height / picture.height if picture.height > max_height else 1.0,
        )
        if ratio < 1.0:
            picture.width = int(picture.width * ratio)
            picture.height = int(picture.height * ratio)
        return True
    except Exception:  # noqa: BLE001 — patrz docstring: brak zrzutu > brak CV
        logger.warning(
            "consent screenshot: nie udało się wstawić obrazu", exc_info=True
        )
        return False


def add_bottom_pinned_rodo(doc: Any, rodo_text: str) -> Any:
    """Pin the RODO consent clause to the bottom of the last page.

    The clause lives inside a floating text box anchored to the bottom page
    margin, so — no matter where the CV body ends — it always lands at the foot
    of the final page (once, just above the footer) instead of dangling in the
    middle of a half-filled page. The text is justified, with no divider above
    it (the earlier thin red top rule was removed on request).

    The box wraps ``topAndBottom``, so it *reserves* its band at the foot of the
    page and body text is pushed above it — never through it. The earlier
    ``wrapNone`` reserved no in-flow space, so a body that filled the page ran
    straight under the pinned box and the last line(s) overlapped the clause
    (the reported "tekst nachodzi na siebie"). With top-and-bottom wrapping a
    body that would reach the reserved band spills its overflow — and the
    clause with it — onto the next page instead of colliding: the clause stays
    at the foot of the (new) last page, still once, and never overlaps. It is
    anchored in a trailing paragraph whose mark is shrunk to ~2pt to keep that
    anchor line negligible.
    """
    section = doc.sections[-1]
    content_w_emu = int(section.page_width - section.left_margin - section.right_margin)
    # ~4 lines of 5pt text; spAutoFit lets Word recompute the reserved band while
    # the bottom edge stays pinned to the margin, so an over/under-estimate is
    # self-correcting.
    box_h_emu = 320040

    anchor_para = doc.add_paragraph()
    anchor_para.paragraph_format.space_before = Pt(0)
    anchor_para.paragraph_format.space_after = Pt(0)
    # Shrink the otherwise-empty anchor line so it barely adds vertical space.
    rpr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "4")
    rpr.append(sz)
    anchor_para._element.get_or_add_pPr().append(rpr)

    # Built as a single line (no inter-tag whitespace) so no stray text nodes
    # slip into element-only content models.
    drawing_xml = "".join(
        [
            '<w:drawing xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
            ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
            ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
            ' xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">',
            '<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0"'
            ' relativeHeight="251659264" behindDoc="0" locked="0"'
            ' layoutInCell="1" allowOverlap="1">',
            '<wp:simplePos x="0" y="0"/>',
            '<wp:positionH relativeFrom="margin"><wp:align>left</wp:align></wp:positionH>',
            '<wp:positionV relativeFrom="margin"><wp:align>bottom</wp:align></wp:positionV>',
            f'<wp:extent cx="{content_w_emu}" cy="{box_h_emu}"/>',
            '<wp:effectExtent l="0" t="0" r="0" b="0"/>',
            "<wp:wrapTopAndBottom/>",
            '<wp:docPr id="101" name="RodoClause"/>',
            "<wp:cNvGraphicFramePr/>",
            "<a:graphic><a:graphicData"
            ' uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">',
            '<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr>',
            f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{content_w_emu}" cy="{box_h_emu}"/></a:xfrm>',
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln>',
            "</wps:spPr><wps:txbx><w:txbxContent><w:p><w:pPr>",
            '<w:spacing w:before="40" w:after="0"/><w:jc w:val="both"/></w:pPr>',
            '<w:r><w:rPr><w:rFonts w:ascii="Montserrat" w:hAnsi="Montserrat"/>',
            '<w:color w:val="373535"/><w:sz w:val="10"/><w:szCs w:val="10"/></w:rPr>',
            f'<w:t xml:space="preserve">{escape(rodo_text)}</w:t>',
            "</w:r></w:p></w:txbxContent></wps:txbx>",
            '<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="0" tIns="0"'
            ' rIns="0" bIns="0" anchor="b" anchorCtr="0"><a:spAutoFit/></wps:bodyPr>',
            "</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing>",
        ]
    )

    run = anchor_para.add_run()
    run._element.append(parse_xml(drawing_xml))
    return anchor_para


def add_section_header(doc: Any, text: str) -> Any:
    """Add a section header with divider above and Montserrat SemiBold title.

    Paragraphs carry no ``keep_with_next`` / ``keep_together`` cohesion: the
    document flows line-by-line under Word's default widow/orphan handling so a
    recruiter hand-tuning page breaks moves content one line per Enter, instead
    of a glued block jumping a whole section across the page boundary.
    """
    add_horizontal_line(doc)

    para = doc.add_paragraph()
    run = para.add_run(text)
    run.font.name = "Montserrat SemiBold"
    run.font.color.rgb = COLOR_HEADER
    run.font.bold = False
    run.font.size = Pt(14)
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(3)
    return para


def add_bullet_point(
    doc: Any,
    text: str,
    punctuation: str = "",
    highlight_keywords: list[str] | None = None,
    patterns: list[re.Pattern[str]] | None = None,
) -> Any:
    """Add a Word numbered bullet point with optional keyword bolding."""
    text = text.rstrip(".,;")
    text = text + punctuation

    para = doc.add_paragraph()

    add_text_with_highlights(para, text, highlight_keywords, Pt(10), patterns=patterns)

    pPr = para._element.get_or_add_pPr()
    numPr = etree.Element(f"{{{NS_W}}}numPr")

    ilvl = etree.SubElement(numPr, f"{{{NS_W}}}ilvl")
    ilvl.set(f"{{{NS_W}}}val", "0")

    numId = etree.SubElement(numPr, f"{{{NS_W}}}numId")
    numId.set(f"{{{NS_W}}}val", "1")

    pPr.insert(0, numPr)

    para.paragraph_format.space_before = Pt(1)
    para.paragraph_format.space_after = Pt(1)
    para.paragraph_format.line_spacing = 1.5
    return para


def add_bullet_list(
    doc: Any,
    items: list[str],
    highlight_keywords: list[str] | None = None,
    patterns: list[re.Pattern[str]] | None = None,
) -> None:
    """Add a bullet list with commas between items and a period at the end."""
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        punctuation = "." if is_last else ","
        add_bullet_point(doc, item, punctuation, highlight_keywords, patterns=patterns)


def normalize_letterhead_layout(doc: Any) -> None:
    """Reserve space for full-width background artwork on every page.

    The inherited template puts a 4.42 cm image behind text but also enables
    tight wrapping with a 3.25 cm body margin. On continuation pages that can
    send part of a word into the sliver beside the artwork. Keep the same page
    coordinates and image bytes; remove wrapping and reserve the image band.
    Preserve page anchoring: negative column offsets can suppress repeated
    headers in office renderers. Browser preview corrects its own origin.
    """
    ns = {
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    }
    inherited_headers: dict[str, Any] = {}
    for section in doc.sections:
        for ref in section._sectPr.findall(qn("w:headerReference")):
            inherited_headers[ref.get(qn("w:type")) or "default"] = (
                doc.part.related_parts[ref.get(qn("r:id"))]
            )
        page_width = int(section.page_width or 0)
        if page_width <= 0:
            continue  # No reliable frame for classifying full-page artwork.
        reserved_top = int(section.top_margin or 0)
        for part in inherited_headers.values():
            for anchor in part.element.findall(".//wp:anchor", ns):
                extent = anchor.find("wp:extent", ns)
                horizontal = anchor.find("wp:positionH", ns)
                vertical = anchor.find("wp:positionV", ns)
                if extent is None or horizontal is None or vertical is None:
                    continue
                # Only full-width background letterhead, never a foreground logo,
                # inline signature, consent image or another positioned object.
                if (
                    anchor.get("behindDoc") != "1"
                    or int(extent.get("cx", "0")) < page_width * 0.8
                ):
                    continue
                x = horizontal.find("wp:posOffset", ns)
                y = vertical.find("wp:posOffset", ns)
                if x is None or y is None:
                    continue
                vertical_frame = vertical.get("relativeFrom")
                if vertical_frame == "paragraph":
                    image_top = int(section.header_distance or 0) + int(y.text or "0")
                elif vertical_frame == "page":
                    image_top = int(y.text or "0")
                else:
                    continue
                if horizontal.get("relativeFrom") not in {"page", "column"}:
                    continue
                for child in list(anchor):
                    if etree.QName(child).localname.startswith("wrap"):
                        anchor.remove(child)
                # Schema order: wrap element precedes docPr/cNvGraphicFramePr.
                wrap = etree.Element(f"{{{ns['wp']}}}wrapNone")
                doc_pr = anchor.find("wp:docPr", ns)
                anchor.insert(
                    list(anchor).index(doc_pr) if doc_pr is not None else 0, wrap
                )
                reserved_top = max(
                    reserved_top, image_top + int(extent.get("cy", "0")) + int(Pt(6))
                )
        section.top_margin = reserved_top


def render_cv_to_bytes(
    candidate_data: dict[str, Any],
    template_path: str,
) -> bytes:
    """Render the candidate dict into a DOCX and return its bytes.

    Args:
        candidate_data: Dict from Claude extraction. Required keys:
            ``name``, ``position``, ``why_points``, ``skills``, ``languages``,
            ``experience``. Optional: ``education``, ``certifications``,
            ``language`` ('pl' default), ``blind_cv`` (False default),
            ``highlight_keywords`` (champion MUST-HAVE + NICE-TO-HAVE
            technologies).
        template_path: Path to ``szablon_firmowy.docx``.

    Returns:
        bytes — the rendered DOCX file content.
    """
    language = candidate_data.get("language", "pl")
    blind_cv = candidate_data.get("blind_cv", False)
    t = TRANSLATIONS.get(language, TRANSLATIONS["pl"])

    if blind_cv:
        if language == "en":
            candidate_data["name"] = "Candidate"
            candidate_data["first_name"] = "Candidate"
        else:
            candidate_data["name"] = "Kandydat"
            candidate_data["first_name"] = "Kandydat"

        for job in candidate_data.get("experience", []):
            industry = str(job.get("industry") or "").strip()
            if language == "en":
                job["company"] = (
                    f"Company from {industry} industry" if industry else "Company"
                )
            else:
                job["company"] = f"Firma z branży {industry}" if industry else "Firma"

    logger.info(
        "[cv_generator_b2b] Rendering CV name=%s lang=%s blind=%s",
        candidate_data.get("name"),
        language,
        blind_cv,
    )

    doc = Document(template_path)
    normalize_letterhead_layout(doc)

    for element in list(doc.element.body):
        if not element.tag.endswith("}sectPr"):
            doc.element.body.remove(element)

    # === NAGŁÓWEK GŁÓWNY ===
    header_para = doc.add_paragraph()
    if blind_cv:
        header_text = candidate_data["position"]
    else:
        header_text = f"{candidate_data['position']} – {candidate_data['name']}"
    header_run = header_para.add_run(header_text)
    header_run.font.name = "Montserrat SemiBold"
    header_run.font.color.rgb = COLOR_HEADER
    header_run.font.bold = False
    header_run.font.size = Pt(24)
    header_para.paragraph_format.space_after = Pt(6)
    header_para.paragraph_format.space_before = Pt(2)

    # The vacancy the candidate is being put forward for. Kept OUT of the main
    # header on purpose: the header states the candidate's actual position, so
    # the document never asserts a job title the source CV does not support.
    considered_for = str(candidate_data.get("considered_for") or "").strip()
    if considered_for:
        sub_para = doc.add_paragraph()
        label_run = sub_para.add_run(t["considered_for"] + " ")
        label_run.font.name = "Montserrat SemiBold"
        label_run.font.color.rgb = COLOR_HEADER
        label_run.font.bold = False
        label_run.font.size = Pt(10)
        value_run = sub_para.add_run(considered_for)
        value_run.font.name = "Montserrat"
        value_run.font.size = Pt(10)
        sub_para.paragraph_format.space_before = Pt(0)
        sub_para.paragraph_format.space_after = Pt(4)

    add_horizontal_line(doc)

    # === DLACZEGO [IMIĘ] / WHY [NAME] / PODSUMOWANIE ===
    para = doc.add_paragraph()
    if blind_cv:
        why_title = "Summary" if language == "en" else "Podsumowanie"
    else:
        why_title = t["why"]
    run = para.add_run(why_title)
    run.font.name = "Montserrat SemiBold"
    run.font.color.rgb = COLOR_HEADER
    run.font.bold = False
    run.font.size = Pt(14)
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after = Pt(3)

    highlight_keywords = candidate_data.get("highlight_keywords", [])
    # Compile once per render — every bullet/skill/technology reuses the set.
    patterns = compile_keyword_patterns(highlight_keywords)

    add_bullet_list(
        doc, candidate_data.get("why_points", []), highlight_keywords, patterns=patterns
    )

    # === EDUKACJA / EDUCATION ===
    if candidate_data.get("education"):
        add_section_header(doc, t["education"])

        table = doc.add_table(rows=len(candidate_data["education"]) + 1, cols=2)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.columns[0].width = Inches(1.8)
        table.columns[1].width = Inches(5.0)

        tbl = table._tbl
        tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement("w:tblPr")

        tblBorders = OxmlElement("w:tblBorders")
        for border_name in ["top", "left", "bottom", "right", "insideH", "insideV"]:
            border = OxmlElement(f"w:{border_name}")
            border.set(qn("w:val"), "single")
            border.set(qn("w:sz"), "4")
            border.set(qn("w:color"), "CCCCCC")
            tblBorders.append(border)
        tblPr.append(tblBorders)

        tblCellMar = OxmlElement("w:tblCellMar")
        for margin_name in ["top", "bottom"]:
            margin = OxmlElement(f"w:{margin_name}")
            margin.set(qn("w:w"), "80")
            margin.set(qn("w:type"), "dxa")
            tblCellMar.append(margin)
        for margin_name in ["left", "right"]:
            margin = OxmlElement(f"w:{margin_name}")
            margin.set(qn("w:w"), "120")
            margin.set(qn("w:type"), "dxa")
            tblCellMar.append(margin)
        tblPr.append(tblCellMar)

        header_cells = table.rows[0].cells
        header_cells[0].text = t["dates"]
        header_cells[1].text = t["education_header"]

        for cell in header_cells:
            shading_elm = OxmlElement("w:shd")
            shading_elm.set(qn("w:fill"), "E8E8E8")
            shading_elm.set(qn("w:val"), "clear")
            cell._element.get_or_add_tcPr().append(shading_elm)

            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(4)
                paragraph.paragraph_format.space_after = Pt(4)
                for run in paragraph.runs:
                    run.font.name = "Montserrat"
                    run.font.bold = True
                    run.font.color.rgb = COLOR_TEXT
                    run.font.size = Pt(10)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        for i, edu in enumerate(candidate_data["education"], start=1):
            row_cells = table.rows[i].cells

            row_cells[0].text = edu["dates"]

            row_cells[1].text = ""
            para = row_cells[1].paragraphs[0]

            run_institution = para.add_run(edu["institution"])
            run_institution.font.name = "Montserrat"
            run_institution.font.bold = True
            run_institution.font.color.rgb = COLOR_TEXT
            run_institution.font.size = Pt(9)

            para.add_run("\n")

            run_degree = para.add_run(edu["degree"])
            run_degree.font.name = "Montserrat"
            run_degree.font.bold = False
            run_degree.font.color.rgb = COLOR_TEXT
            run_degree.font.size = Pt(9)

            if i % 2 == 0:
                for cell in row_cells:
                    shading_elm = OxmlElement("w:shd")
                    shading_elm.set(qn("w:fill"), "F8F8F8")
                    shading_elm.set(qn("w:val"), "clear")
                    cell._element.get_or_add_tcPr().append(shading_elm)

            for cell in row_cells:
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.space_before = Pt(6)
                    paragraph.paragraph_format.space_after = Pt(6)
                    paragraph.paragraph_format.line_spacing = 1.5
                    for run in paragraph.runs:
                        run.font.name = "Montserrat"
                        run.font.color.rgb = COLOR_TEXT
                        run.font.size = Pt(9)

            for para in row_cells[0].paragraphs:
                for run in para.runs:
                    run.font.name = "Montserrat"
                    run.font.color.rgb = COLOR_TEXT
                    run.font.size = Pt(9)

        doc.add_paragraph()

    # === UMIEJĘTNOŚCI / SKILLS ===
    if candidate_data.get("skills"):
        add_section_header(doc, t["skills"])

    skill_categories = candidate_data.get("skills", [])
    for cat_idx, skill_category in enumerate(skill_categories):
        para = doc.add_paragraph()

        pPr = para._element.get_or_add_pPr()
        numPr = etree.Element(f"{{{NS_W}}}numPr")
        ilvl = etree.SubElement(numPr, f"{{{NS_W}}}ilvl")
        ilvl.set(f"{{{NS_W}}}val", "0")
        numId = etree.SubElement(numPr, f"{{{NS_W}}}numId")
        numId.set(f"{{{NS_W}}}val", "1")
        pPr.insert(0, numPr)

        run1 = para.add_run(skill_category["label"] + " ")
        run1.font.name = "Montserrat"
        run1.font.bold = True
        run1.font.color.rgb = COLOR_TEXT
        run1.font.size = Pt(10)

        # Skill categories form one comma-separated list across bullets:
        # every bullet ends with a comma, only the last closes with a period.
        content = skill_category["content"].rstrip(" ,.")
        is_last_category = cat_idx == len(skill_categories) - 1
        content = content + ("." if is_last_category else ",")
        add_text_with_highlights(
            para, content, highlight_keywords, Pt(10), patterns=patterns
        )

        para.paragraph_format.space_before = Pt(1)
        para.paragraph_format.space_after = Pt(1)
        para.paragraph_format.line_spacing = 1.5

    # === CERTYFIKATY / CERTIFICATIONS ===
    if candidate_data.get("certifications"):
        add_section_header(doc, t["certifications"])
        add_bullet_list(
            doc,
            candidate_data.get("certifications", []),
            highlight_keywords,
            patterns=patterns,
        )

    # === JĘZYKI / LANGUAGES ===
    if candidate_data.get("languages"):
        add_section_header(doc, t["languages"])
        add_bullet_list(
            doc,
            candidate_data.get("languages", []),
            highlight_keywords,
            patterns=patterns,
        )

    # === DOŚWIADCZENIE / EXPERIENCE ===
    if candidate_data.get("experience"):
        add_section_header(doc, t["experience"])

    for i, job in enumerate(candidate_data.get("experience", [])):
        if i > 0:
            add_horizontal_line(doc)

        # Role header (dates → company → position → "Zakres zadań:") flows
        # naturally without keep_with_next cohesion, so manual page-break edits
        # in Word move one line at a time instead of jumping the whole block.
        para = doc.add_paragraph()
        run = para.add_run(job["dates"])
        run.font.name = "Montserrat"
        run.font.color.rgb = COLOR_TEXT
        run.font.size = Pt(10)
        run.font.bold = True
        para.paragraph_format.space_before = Pt(1)
        para.paragraph_format.space_after = Pt(0)

        para = doc.add_paragraph()
        run1 = para.add_run(t["company_name"] + " ")
        run1.font.name = "Montserrat"
        run1.font.color.rgb = COLOR_TEXT
        run1.font.size = Pt(10)
        run2 = para.add_run(job["company"])
        run2.font.name = "Montserrat"
        run2.font.color.rgb = COLOR_TEXT
        run2.font.size = Pt(10)
        run2.font.bold = True
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)

        para = doc.add_paragraph()
        run1 = para.add_run(t["position"] + " ")
        run1.font.name = "Montserrat"
        run1.font.color.rgb = COLOR_TEXT
        run1.font.size = Pt(10)
        run2 = para.add_run(job["position"])
        run2.font.name = "Montserrat"
        run2.font.color.rgb = COLOR_TEXT
        run2.font.size = Pt(10)
        run2.font.bold = True
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)

        para = doc.add_paragraph()
        run = para.add_run(t["responsibilities"])
        run.font.name = "Montserrat"
        run.font.color.rgb = COLOR_TEXT
        run.font.size = Pt(10)
        run.font.bold = False
        run.font.underline = True
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(1)

        add_bullet_list(
            doc, job.get("responsibilities", []), highlight_keywords, patterns=patterns
        )

        if job.get("technologies"):
            para = doc.add_paragraph()
            run1 = para.add_run(t["technologies"] + " ")
            run1.font.name = "Montserrat"
            run1.font.color.rgb = COLOR_TEXT
            run1.font.size = Pt(10)
            run1.font.bold = True
            add_text_with_highlights(
                para,
                ", ".join(job["technologies"]),
                highlight_keywords,
                Pt(10),
                patterns=patterns,
            )
            para.paragraph_format.space_before = Pt(4)
            para.paragraph_format.space_after = Pt(2)

    # === KLAUZULA RODO / GDPR ===
    # The consent clause is always justified and always pinned to the foot of the
    # last page via a bottom-anchored float that wraps top-and-bottom. Anchored to
    # the bottom page margin, the clause reads as a footer at the bottom of the
    # last page no matter how full the CV is; the top-and-bottom wrap reserves its
    # band so body text is pushed above it and can never run underneath it.
    #
    # The earlier float used wrapNone (reserved no in-flow space). On a body that
    # filled the page the last line(s) ran straight under the pinned box and
    # overlapped the clause — the reported "tekst nachodzi na siebie". With
    # top-and-bottom wrapping a body that would reach the reserved band spills its
    # overflow (and the clause) onto the next page instead, so the clause lands at
    # the foot of the last page, once, and never overlaps. (An even earlier hybrid
    # dropped the clause into the normal flow near-full pages, which dangled it at
    # the TOP of the last page — "RODO na górze strony"; that is gone too.)
    #
    # Trade-off: the in-app docx-preview ("Podgląd") cannot position a bottom-
    # anchored floating box, so the clause shows only in the downloaded DOCX/PDF
    # (the file sent to the client), not in that preview. A page footer would be
    # visible in both but would repeat the clause on every page of a multi-page
    # CV, so the float — which lands once, on the last page only — is preferred.
    # === ZRZUT ZGODY KANDYDATA (wymóg PKO BP) ===
    # Bajty wstrzykuje WOŁAJĄCY pod `consent_screenshot._bytes` — renderer
    # zostaje czystą funkcją i nie sięga do magazynu obiektów, dzięki czemu
    # testy i ponowny render z zapisanego payloadu działają bez sieci.
    # W samym `render_payload` zapisany jest wyłącznie klucz w magazynie:
    # zrzut maila waży setki kilobajtów i w JSONB puchłby przy każdym pobraniu.
    _consent = candidate_data.get("consent_screenshot")
    if isinstance(_consent, dict) and _consent.get("_bytes"):
        add_consent_screenshot(doc, _consent["_bytes"], t["consent_heading"])

    add_bottom_pinned_rodo(doc, t["rodo"])

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
