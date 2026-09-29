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

from dataclasses import dataclass
from typing import Any, Optional, Sequence

MIN_SCORE = 0.45


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
    name = (
        role_name.strip() if isinstance(role_name, str) and role_name.strip() else None
    )
    if not name:
        name = (
            (getattr(job, "working_title", None) or getattr(job, "title", None) or "")
            .split("·")[0]
            .strip()
        )
    title, skills = job_signals(job)
    words = sorted(title_tokens(name) or title)[:6]
    skill_list = sorted(skills)[:8]
    return (
        name[:200] or "Nowa rola",
        {"title_words": words, "skills": skill_list, "category": category},
        skill_list,
    )
