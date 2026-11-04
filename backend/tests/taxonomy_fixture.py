"""Wczytany fragment słownika umiejętności dla testów bez bazy.

W testach ``ALIAS_MAP`` i taksonomia są puste, więc reguły czytające kategorie
(bramka must, umiejętności krytyczne) działają jak offline. Ten pomocnik
wczytuje mały słownik o kategoriach z produkcji (30.09.2026) i przywraca stan.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app.services import must_gate_terms, skill_normalize
from app.services.scoring_service import ALIAS_MAP, set_alias_map

# kanon -> (kategoria, aliasy) — kategorie jak w tabeli `skills` na produkcji.
PROD_LIKE_SKILLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Java": ("language", ()),
    "Python": ("language", ()),
    "C#": ("language", ("csharp",)),
    "TypeScript": ("language", ("ts",)),
    "Angular": ("frontend", ("angular.js", "angularjs")),
    "React": ("frontend", ("react.js", "reactjs")),
    "Spring Boot": ("backend", ()),
    "Docker": ("devops", ()),
    "Kubernetes": ("devops", ("k8s",)),
    "PostgreSQL": ("database", ("postgres",)),
    "Oracle DB": ("database", ("oracle",)),
    "Kafka": ("messaging", ("apache kafka",)),
    "Pega": ("tools", ()),
    "Jira": ("tools", ()),
    "Jenkins": ("devops", ()),
    "Bitbucket": ("tools", ()),
    "UML": ("standards", ()),
    "BPMN": ("standards", ()),
    "LLM": ("ai", ()),
    "Selenium": ("qa", ()),
    "Scrum": ("methodology", ()),
    "CI/CD": ("methodology", ()),
    "Agile": ("methodology", ()),
    "QA": ("role_qa", ("quality assurance",)),
    "Software developer": ("role_dev", ("backend developer",)),
    "IT analysis": ("role_analysis", ()),
    "Release manager": ("role_management", ()),
}


@contextmanager
def hydrated_taxonomy(
    skills: dict[str, tuple[str, tuple[str, ...]]] = PROD_LIKE_SKILLS,
) -> Iterator[None]:
    saved_alias = dict(ALIAS_MAP)
    saved = (
        set(skill_normalize.TECH_CANONICALS),
        dict(skill_normalize.ALIAS_TO_CANONICAL),
        {k: list(v) for k, v in skill_normalize.CANONICAL_TO_ALIASES.items()},
        dict(skill_normalize.CANONICAL_CATEGORY),
    )
    mapping: dict[str, str] = {}
    for canon, (_cat, aliases) in skills.items():
        mapping[canon.lower()] = canon.lower()
        for alias in aliases:
            mapping[alias.lower()] = canon.lower()
    set_alias_map(mapping)
    skill_normalize.set_tech_taxonomy(
        tech_canonicals={
            c
            for c, (cat, _a) in skills.items()
            if cat in skill_normalize.TECH_CATEGORIES
        },
        alias_to_canonical=mapping,
        canonical_to_aliases={
            c.lower(): [a.lower() for a in aliases]
            for c, (_cat, aliases) in skills.items()
        },
        categories={c: cat for c, (cat, _a) in skills.items()},
    )
    must_gate_terms.clear_cache()
    try:
        yield
    finally:
        set_alias_map(saved_alias)
        skill_normalize.set_tech_taxonomy(
            tech_canonicals=saved[0],
            alias_to_canonical=saved[1],
            canonical_to_aliases=saved[2],
            categories=saved[3],
        )
        must_gate_terms.clear_cache()
