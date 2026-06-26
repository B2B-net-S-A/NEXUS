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

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

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
    if any(ch in token for ch in "+#/."):
        return True
    if any(ch.isdigit() for ch in token):
        return True
    letters = [ch for ch in token if ch.isalpha()]
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
    """True iff a single token is a recognised technology — a hard-tech signal
    (:func:`_is_strong_tech_token`) or a curated allowlist hit."""
    return _is_strong_tech_token(token) or _norm_tech(token) in _KNOWN_TECH


_POLISH_DIACRITICS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
# Inflectional endings of Polish concept / soft-skill nouns a recruiter types
# as a bare requirement ("Komunikatywność", "Projektowanie", "Negocjacje").
_POLISH_SUFFIXES = (
    "ość",
    "ości",
    "ością",
    "ościach",
    "anie",
    "ania",
    "aniu",
    "aniem",
    "enie",
    "enia",
    "eniu",
    "eniem",
    "owanie",
    "owania",
    "ywanie",
    "ywania",
    "cja",
    "cji",
    "cją",
    "cje",
    "cjach",
    "sja",
    "zja",
    "alność",
    "ywność",
)


def _looks_polish_word(token: str) -> bool:
    """Heuristic: a Polish concept/soft-skill word, not a tech brand name.

    Catches the frequent cases ("Komunikatywność", "Projektowanie",
    "Negocjacje") via diacritics or inflectional suffixes so they are not
    mistaken for an unlisted technology. Not exhaustive — it only needs to
    suppress the common Polish nouns a recruiter types as a bare skill.
    """
    if any(ch in _POLISH_DIACRITICS for ch in token):
        return True
    low = token.lower()
    return any(low.endswith(suf) for suf in _POLISH_SUFFIXES)


def _is_tech_token_name(token: str) -> bool:
    """Fallback for technologies absent from ``_KNOWN_TECH`` — niche tools
    (Splunk, QRadar) the allowlist will never fully cover.

    A single brand-like token qualifies when it carries an uppercase letter (a
    proper-noun/brand signal — recruiters capitalise tool names) and is neither
    a generic/stop word nor Polish-looking. That keeps lowercase concept
    sub-terms ("komponenty", "tokeny") and Polish nouns ("Projektowanie",
    "Komunikatywność") out, while letting "Splunk"/"QRadar"/"Figma" through.
    """
    if _is_filler_word(token) or token.lower() in _STOP_WORDS:
        return False
    if not any(ch.isupper() for ch in token):
        return False
    if _looks_polish_word(token):
        return False
    return sum(1 for ch in token if ch.isalpha()) >= 2


def _is_technology(term: str) -> bool:
    """True iff `term` is a concrete technology worth bolding on its own.

    Recruiters asked the generator to bold ONLY technologies — tools,
    languages, frameworks, libraries, platforms and technical acronyms /
    standards — and to STOP bolding design methodologies, concepts and
    requirement prose ("User-Centered Design", "Material Design", "Zasady
    Gestalt", "visual design", "tworzenie i rozwój design systemów").

    Qualifies when the term is the curated allowlist verbatim ("Spring Boot",
    "SQL Server", "Adobe XD"); a SINGLE brand-like token (hard-tech signal,
    allowlist, or proper-noun fallback — "SQL", "Figma", "Splunk", "QRadar");
    or a multi-word phrase whose EVERY word is itself a tech token ("GitLab
    CI/CD", "C++ STL"). A phrase with any plain word ("visual design",
    "User-Centered Design") fails here — only a hard-tech token buried inside
    it (handled by the caller) may still bold.
    """
    t = term.strip()
    if not t:
        return False
    if _norm_tech(t) in _KNOWN_TECH:
        return True
    tokens = [tok for tok in t.split() if tok]
    if not tokens:
        return False
    if len(tokens) == 1:
        return _is_tech_word(t) or _is_tech_token_name(t)
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
        if len(term) < 2 or key in _STOP_WORDS or key in seen:
            return
        seen.add(key)
        # Build from tokens so "auto-layout" also matches "auto layout"
        # (hyphen ↔ space spelling drift between champion list and CV).
        parts = [p for p in re.split(r"[\s\-]+", term) if p]
        escaped = r"[\s\-]+".join(re.escape(p) for p in parts)
        # "CI/CD" should also match "CI / CD" — slash with optional spaces.
        escaped = escaped.replace("/", r"\s*/\s*")
        if not escaped:
            return
        patterns.append(
            re.compile(
                rf"(?<![{_WORD_CHARS}]){escaped}(?![{_WORD_CHARS}])",
                re.IGNORECASE,
            )
        )

    for kw in keywords or []:
        for term in _extract_keyword_terms(kw):
            # Trim filler ("Znajomość Java" → "Java", "Zaawansowany visual
            # design" → "visual design"); a fully generic entry drops out.
            v = _core_keyword(term).strip()
            if len(v) < 2 or v.lower() in _STOP_WORDS:
                continue
            if _is_generic_phrase(v):
                continue
            if _is_technology(v):
                # A real technology bolds whole ("Figma", "Spring Boot",
                # "GitLab CI/CD", "C++").
                _add(v)
                # A NON-curated compound qualifies only because EVERY token is
                # itself a technology ("Java 17+", "Java 17", "REST API",
                # "GitLab CI/CD") — so also bold each brand token on its own.
                # Without this a champion skill carrying a version ("Java 17+")
                # matched only verbatim, so plain "Java" in the CV never bolded
                # (recruiter directive: bold ALL must-have + nice-to-have
                # technologies). Curated multi-word techs ("Spring Boot", "SQL
                # Server", "React Native") stay whole — their bare common part
                # ("Boot", "Native") must never bold.
                tokens = v.split()
                if len(tokens) > 1 and _norm_tech(v) not in _KNOWN_TECH:
                    for tok in tokens:
                        if _is_tech_word(tok) and any(ch.isalpha() for ch in tok):
                            _add(tok)
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


def highlight_spans(
    text: str, patterns: list[re.Pattern[str]]
) -> list[tuple[int, int]]:
    """Merged (start, end) spans of all keyword matches inside `text`."""
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        for m in pattern.finditer(text):
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
        "responsibilities": "Zakres zadań:",
        "technologies": "Technologie:",
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
        "responsibilities": "Tasks:",
        "technologies": "Technologies:",
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
            industry = job.get("industry", "IT")
            if language == "en":
                job["company"] = f"Company from {industry} industry"
            else:
                job["company"] = f"Firma z branży {industry}"

    logger.info(
        "[cv_generator_b2b] Rendering CV name=%s lang=%s blind=%s",
        candidate_data.get("name"),
        language,
        blind_cv,
    )

    doc = Document(template_path)

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
    # A red divider closes the document body — the last EXPERIENCE role, or
    # whatever the final section is — so the consent clause reads as a separate
    # footer block instead of notes tacked onto that role's description. The
    # clause sits just below the divider; on a content-filled CV that lands it
    # near the foot of the page, set off from the experience above. The divider
    # is kept tight (the clause is a 5pt block) so it takes less vertical room
    # than the blank-line spacer it replaces and never pushes a one-page CV onto
    # a second page just for the clause.
    closing_divider = add_horizontal_line(doc)
    closing_divider.paragraph_format.space_before = Pt(2)
    closing_divider.paragraph_format.space_after = Pt(5)

    rodo_para = doc.add_paragraph()
    rodo_text = t["rodo"]

    run = rodo_para.add_run(rodo_text)
    run.font.name = "Montserrat"
    run.font.size = Pt(5)
    run.font.color.rgb = COLOR_TEXT

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
