"""Dopasowanie rekrutacji do roli z biblioteki — bez AI.

Reguły roli (``role_profiles.match_rules``): słowa tytułu, kluczowe
umiejętności (nazwy kanoniczne) i opcjonalnie slug kategorii kompetencji.
Wynik 0–1: 0,5 × pokrycie słów tytułu + 0,35 × pokrycie umiejętności
+ 0,15 × ta sama kategoria. Rola musi dostać trafienie w tytule albo co
najmniej połowę kluczowych umiejętności — sama kategoria to za mało.

Ręczny wybór (``jobs.role_profile_source='manual'``) nigdy nie jest
nadpisywany.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

MIN_SCORE = 0.45

# Poziom stanowiska nie jest częścią roli: „Starszy Programista Frontend” i
# „Programista Frontend” to ta sama pozycja w bibliotece. „Lead”/„Principal”
# zostają — „Tech Lead” to inna rola, nie wyższy poziom programisty.
_SENIORITY = re.compile(
    r"(?<![\w-])(senior|junior|mid|middle|regular|starszy|starsza|starsi|młodszy|młodsza|"
    r"sr|jr|ekspert|expert)(?![\w-])\.?",
    re.IGNORECASE,
)
_REF = re.compile(
    r"\b[A-Z]{2,}[-_/]?\d{2,}\b|\(\s*[^)]*\)|\[[^\]]*\]|\d{3,}|\b\d+\s*x\b|\bx\s*\d+\b",
    re.IGNORECASE,
)
# Oznaczenia z tytułów Traffita i zamówień klientów, które nie mówią nic o roli:
# wstrzymanie, moduł i część umowy, numer zapotrzebowania, identyfikator
# projektu, zastępstwo, kraj zespołu na początku tytułu.
_NOISE = re.compile(
    r"\bon\s*hold\b|\bonhold\b|\bmodu[łl]\s+[ivx]+\b|\bcz\.?\s*[ivx\d]+\b|"
    r"\bczi+\b|\bpep\s*id\b|\btp#|\bdemand\b|\breplacement\b|#",
    re.IGNORECASE,
)
_TAIL = re.compile(r"\b(zapotrzebowanie|zam[óo]wienie)\b.*$", re.IGNORECASE)
_LEAD_COUNTRY = re.compile(r"^\s*(pl|poland)\b[\s\-/,]*", re.IGNORECASE)
# „Developer for team X”, „Analityk dla …”, „Data Scientist w …” — dopisek
# o zespole albo projekcie nie jest częścią roli.
_CONTEXT = re.compile(r"\s(for|dla|do|in|w|to support)\s.*$", re.IGNORECASE)
# Rola musi mieć rzeczownik zawodu — inaczej to oznaczenie zespołu albo
# projektu („PL”, „BCCM RRP”, „AKADEMIA”) i z niego roli nie zakładamy.
ROLE_NOUNS = (
    "developer",
    "dev",
    "programist",
    "analityk",
    "analyst",
    "tester",
    "test",
    "qa",
    "engineer",
    "inżynier",
    "inzynier",
    "architect",
    "architekt",
    "manager",
    "menedżer",
    "kierownik",
    "lider",
    "leader",
    "lead",
    "specjalist",
    "specialist",
    "administrator",
    "admin",
    "designer",
    "projektant",
    "owner",
    "scrum",
    "consultant",
    "konsultant",
    "coordinator",
    "koordynator",
    "scientist",
    "devops",
    "pmo",
    "pm",
    "support",
    "officer",
    "coach",
    "sre",
    "dba",
    "helpdesk",
    "pentester",
    "delivery",
    "controller",
    "auditor",
    "audytor",
    "master",
)


def _has_role_noun(text: str) -> bool:
    return any(
        word.startswith(ROLE_NOUNS) for word in re.findall(r"[\w.+#]+", text.casefold())
    )


def _drop_words(text: str, drop: frozenset[str]) -> str:
    if not drop:
        return text
    return " ".join(w for w in text.split() if w.strip(",.;/-").casefold() not in drop)


def clean_role_name(title: str, drop_words: frozenset[str] = frozenset()) -> str:
    """Nazwa roli z tytułu: bez numerów, nawiasów, liczby osób, poziomu,
    oznaczeń zamówień, kraju zespołu, dopisku o projekcie i słów z
    ``drop_words`` (np. nazwy klienta). Pusty napis = tytuł nie niesie roli."""
    text = (title or "").replace("_", " ")
    text = _TAIL.sub(" ", text)
    text = _REF.sub(" ", text)
    text = _NOISE.sub(" ", text)
    text = _SENIORITY.sub(" ", text)
    segments = [s.strip() for s in re.split(r"[|·–—:]| - ", text) if s and s.strip()]
    chosen = ""
    for segment in segments:
        segment = _LEAD_COUNTRY.sub("", segment)
        segment = _CONTEXT.sub("", segment)
        segment = _drop_words(segment, drop_words)
        segment = re.sub(r"\s+", " ", segment).strip(" ,.-/+&")
        if segment and _has_role_noun(segment):
            chosen = segment
            break
    chosen = chosen[:80].strip(" ,.-/+&")
    return chosen[:1].upper() + chosen[1:]


def client_words(*names: Optional[str]) -> frozenset[str]:
    """Słowa nazwy klienta do usunięcia z nazwy roli (bez form prawnych)."""
    legal = {
        "s.a.",
        "sa",
        "sp.",
        "z",
        "o.o.",
        "spółka",
        "akcyjna",
        "oddział",
        "w",
        "polsce",
    }
    out: set[str] = set()
    for name in names:
        words = [
            w
            for w in re.findall(r"[\w.&-]+", (name or "").casefold())
            if w not in legal
        ]
        for word in words:
            if len(word) >= 2 and not _has_role_noun(word):
                out.add(word)
        # Skróty z nazwy: „PKO Bank Polski” → „pbp”, „bp” (tytuły piszą „PKO BP”).
        initials = "".join(w[0] for w in words if w[:1].isalpha())
        for start in range(len(initials) - 1):
            if len(initials) - start >= 2:
                out.add(initials[start:])
    return frozenset(out)


@dataclass(frozen=True)
class RoleRules:
    role_id: int
    title_words: frozenset[str]
    skills: frozenset[str]
    category: Optional[str]


def rules_of(role_id: int, raw: Any) -> RoleRules:
    data = raw if isinstance(raw, dict) else {}

    def words(value: Any) -> frozenset[str]:
        return frozenset(
            str(v).strip().casefold()
            for v in (value or [])
            if isinstance(v, str) and v.strip()
        )

    category = data.get("category")
    return RoleRules(
        role_id=role_id,
        title_words=words(data.get("title_words")),
        skills=words(data.get("skills")),
        category=category if isinstance(category, str) and category else None,
    )


def score(
    rules: RoleRules,
    title: frozenset[str],
    skills: frozenset[str],
    category: Optional[str],
) -> float:
    title_hit = (
        len(rules.title_words & title) / len(rules.title_words)
        if rules.title_words
        else 0.0
    )
    skill_hit = len(rules.skills & skills) / len(rules.skills) if rules.skills else 0.0
    if title_hit == 0.0 and skill_hit < 0.5:
        return 0.0
    same_cat = (
        1.0 if rules.category and category and rules.category == category else 0.0
    )
    return round(0.5 * title_hit + 0.35 * skill_hit + 0.15 * same_cat, 4)


def best_role(
    roles: Sequence[RoleRules],
    title: frozenset[str],
    skills: frozenset[str],
    category: Optional[str],
) -> Optional[int]:
    """Id najlepszej roli albo ``None``. Remis → niższe id (starsza rola)."""
    best: Optional[tuple[float, int]] = None
    for rules in roles:
        value = score(rules, title, skills, category)
        if value < MIN_SCORE:
            continue
        if (
            best is None
            or value > best[0]
            or (value == best[0] and rules.role_id < best[1])
        ):
            best = (value, rules.role_id)
    return best[1] if best else None


def job_signals(job: Any) -> tuple[frozenset[str], frozenset[str]]:
    """Słowa tytułu (tytuł klienta + tytuł roboczy + rola z profilu) i must-have."""
    from app.services import champion_view
    from app.services.job_similarity import skill_set, title_tokens

    role_name = champion_view.basics(getattr(job, "champion_profile", None)).get(
        "role_name"
    )
    title = (
        title_tokens(getattr(job, "title", None))
        | title_tokens(getattr(job, "working_title", None))
        | title_tokens(role_name if isinstance(role_name, str) else None)
    )
    skills = skill_set(
        getattr(job, "must_skills", None), getattr(job, "champion_profile", None)
    )
    return title, skills


def rules_for_new_role(
    job: Any, category: Optional[str], drop_words: frozenset[str] = frozenset()
) -> Optional[tuple[str, dict[str, Any], list[str]]]:
    """Nazwa i reguły nowej roli z rekrutacji, która nie pasuje do żadnej
    istniejącej. ``None``, gdy żaden tytuł nie niesie nazwy zawodu."""
    from app.services import champion_view
    from app.services.job_similarity import title_tokens

    role_name = champion_view.basics(getattr(job, "champion_profile", None)).get(
        "role_name"
    )
    name = ""
    for raw in (
        role_name if isinstance(role_name, str) else None,
        getattr(job, "working_title", None),
        getattr(job, "title", None),
    ):
        name = clean_role_name(raw or "", drop_words)
        if name:
            break
    if not name:
        return None
    title, skills = job_signals(job)
    words = sorted(title_tokens(name) or title)[:6]
    skill_list = sorted(skills)[:8]
    return (
        name[:200],
        {"title_words": words, "skills": skill_list, "category": category},
        skill_list,
    )
