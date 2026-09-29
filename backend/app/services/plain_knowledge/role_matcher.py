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
    r"(?<![\w-])(senior|junior|mid|regular|starszy|starsza|starsi|młodszy|młodsza|"
    r"sr|jr|ekspert|expert)(?![\w-])\.?",
    re.IGNORECASE,
)
_REF = re.compile(
    r"\b[A-Z]{2,}[-_/]?\d{2,}\b|\(\s*[^)]*\)|\d{3,}|\b\d+\s*x\b", re.IGNORECASE
)


def clean_role_name(title: str) -> str:
    """Tytuł bez numerów zapytań, nawiasów, liczby osób i poziomu stanowiska."""
    text = _REF.sub(" ", title or "")
    text = _SENIORITY.sub(" ", text)
    # „Nordea: PM for …” — przed dwukropkiem zwykle stoi klient, nie rola.
    head, sep, tail = text.partition(":")
    if sep and tail.strip() and len(head.split()) <= 2:
        text = tail
    text = re.split(r"[|·–—:]| - ", text)[0]
    text = re.sub(r"\s+", " ", text).strip(" ,.-/")[:120]
    return text[:1].upper() + text[1:]


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
    job: Any, category: Optional[str]
) -> tuple[str, dict[str, Any], list[str]]:
    """Nazwa i reguły nowej roli z rekrutacji, która nie pasuje do żadnej istniejącej."""
    from app.services import champion_view
    from app.services.job_similarity import title_tokens

    role_name = champion_view.basics(getattr(job, "champion_profile", None)).get(
        "role_name"
    )
    raw = role_name if isinstance(role_name, str) and role_name.strip() else None
    name = clean_role_name(
        raw or getattr(job, "working_title", None) or getattr(job, "title", None) or ""
    )
    title, skills = job_signals(job)
    words = sorted(title_tokens(name) or title)[:6]
    skill_list = sorted(skills)[:8]
    return (
        name[:200] or "Nowa rola",
        {"title_words": words, "skills": skill_list, "category": category},
        skill_list,
    )
