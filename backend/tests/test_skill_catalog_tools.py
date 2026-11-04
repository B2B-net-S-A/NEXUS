"""Narzędzia w słowniku umiejętności (0397, 28.09.2026).

Pomiar na produkcji: wiersz wymagań „Jira” nie był technologią, więc „Szukaj
ręcznie” traktowało go jako „Mile widziane” zamiast wymagania. Pozycje
z ``app/data/skill_catalog_tools.json`` mają to zmienić, nie ruszając
generatora CV, przeglądu DZ ani „Podobnych rekrutacji”.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services import keyword_suggest, skill_catalog_tools as tools
from app.services.keyword_terms import parse_keyword
from app.services.skill_normalize import TECH_CATEGORIES

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _seed_0012():
    spec = importlib.util.spec_from_file_location(
        "m0012", _VERSIONS / "0012_skill_taxonomy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SEED


def test_categories_stay_outside_tech_taxonomy():
    # Generator CV (pogrubienia), przegląd DZ i „Podobne rekrutacje” czytają
    # tylko kategorie technologii — te pozycje nie mogą ich zmienić.
    assert {c for _, c, _ in tools.entries()} <= tools.CATEGORIES
    assert not tools.CATEGORIES & TECH_CATEGORIES


def test_names_and_aliases_are_unique_and_searchable():
    seen: set[str] = set()
    for name, _category, aliases in tools.entries():
        for word in (name, *aliases):
            key = keyword_suggest.fold(word)
            assert key not in seen, f"powtórzona pozycja: {word}"
            seen.add(key)
            assert parse_keyword(word) is not None
            # Aliasy 1–2-znakowe łapią szum w CV (R, Go, „ml” w „html”).
            assert len(key) >= 3, word


def test_no_collision_with_the_bootstrap_seed():
    bootstrap = set()
    for canonical, _cat, aliases in _seed_0012():
        bootstrap.add(keyword_suggest.fold(canonical))
        bootstrap.update(keyword_suggest.fold(a) for a in aliases)
    for name, _category, aliases in tools.entries():
        for word in (name, *aliases):
            assert keyword_suggest.fold(word) not in bootstrap, word


@pytest.fixture
def tools_catalog():
    saved = keyword_suggest._catalog
    skills = [(-(i + 1), name, cat) for i, (name, cat, _) in enumerate(tools.entries())]
    aliases = [
        (-(i + 1), alias)
        for i, (_, _, own) in enumerate(tools.entries())
        for alias in own
    ]
    skills.append((1, "Java", "language"))
    keyword_suggest.load_catalog(skills, aliases)
    yield
    keyword_suggest._catalog = saved


@pytest.mark.parametrize(
    "row", ["Jira", "Confluence", "jira confluence", "Git", "UML", "db2"]
)
def test_tool_rows_count_as_technology(tools_catalog, row):
    assert keyword_suggest.classify_skills(row).all_skills


@pytest.mark.parametrize(
    "row", ["bankowość", "wzorce projektowe", "stakeholder management"]
)
def test_prose_rows_stay_preferred(tools_catalog, row):
    assert not keyword_suggest.classify_skills(row).all_skills


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_never_steals_existing_names(monkeypatch):
    from app.core.database import engine

    nonce = "zt" + uuid.uuid4().hex[:10]
    owner, owned_alias = f"{nonce}owner", f"{nonce}taken"
    fresh, fresh_alias = f"{nonce}Tool", f"{nonce}alias"
    async with engine.begin() as conn:
        owner_id = (
            await conn.execute(
                text(
                    "INSERT INTO skills (canonical_name, category) "
                    "VALUES (:n, 'language') RETURNING id"
                ),
                {"n": owner},
            )
        ).scalar_one()
        await conn.execute(
            text("INSERT INTO skill_aliases (skill_id, alias) VALUES (:s, :a)"),
            {"s": owner_id, "a": owned_alias},
        )
    monkeypatch.setattr(
        tools,
        "entries",
        lambda: (
            (fresh, "tools", (fresh_alias.lower(), owned_alias)),
            # Nazwa zajęta jako alias innej umiejętności — nie powstaje.
            (owned_alias.upper(), "tools", ()),
        ),
    )
    try:
        for _ in range(2):
            async with engine.begin() as conn:
                await conn.run_sync(tools.seed)
        async with engine.connect() as conn:
            skills = (
                await conn.execute(
                    text(
                        "SELECT canonical_name, category FROM skills "
                        "WHERE lower(canonical_name) LIKE :p ORDER BY 1"
                    ),
                    {"p": f"{nonce}%"},
                )
            ).all()
            aliases = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT a.alias, s.canonical_name FROM skill_aliases a "
                            "JOIN skills s ON s.id = a.skill_id WHERE a.alias LIKE :p"
                        ),
                        {"p": f"{nonce}%"},
                    )
                ).all()
            )
        assert set(skills) == {(owner, "language"), (fresh, "tools")}
        assert aliases == {owned_alias: owner, fresh_alias.lower(): fresh}
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM skills WHERE lower(canonical_name) LIKE :p"),
                {"p": f"{nonce}%"},
            )


@pytest.mark.asyncio
async def test_migration_seeded_the_catalog():
    from app.core.database import engine

    async with engine.connect() as conn:
        names = set(
            (
                await conn.execute(
                    text("SELECT canonical_name FROM skills WHERE category = ANY(:c)"),
                    {"c": sorted(tools.CATEGORIES)},
                )
            ).scalars()
        )
    assert {"Jira", "Confluence", "Git", "UML", "SailPoint IdentityIQ"} <= names


# ── SailPoint IdentityIQ (zgłoszenie z 28.10.2026, rekrutacja 789171) ───────
#
# Krytyczne „SailPoint IIQ” ze słowem wiersza „IIQ” ukryło w nocnym przeglądzie
# 111 osób z SailPointem w CV — żadna nie miała słowa „IIQ”, piszą
# „SailPoint IdentityIQ”. Frazy niżej to dosłowne fragmenty CV ukrytych osób.


@pytest.fixture
def catalog_aliases():
    from app.services import must_text_evidence, scoring_service

    saved = dict(scoring_service.ALIAS_MAP)
    mapping: dict[str, str] = {}
    for name, _category, aliases in tools.entries():
        mapping[name] = name
        mapping.update({alias: name for alias in aliases})
    scoring_service.set_alias_map(mapping)
    must_text_evidence._patterns.cache_clear()
    yield
    scoring_service.set_alias_map(saved)
    must_text_evidence._patterns.cache_clear()


def _sailpoint_iiq():
    from app.services.must_gate_terms import requirement_with_options

    return requirement_with_options("sailpoint iiq", {"sailpoint iiq": ("IIQ",)})


@pytest.mark.parametrize(
    "cv",
    [
        "Onboarding applications to Sailpoint IdentityIQ",
        "Maintenance of Sailpoint IAM application IdentityIQ",
        "Making use of SCCM, Active Directory and SailPoint IdentityIQ",
        "SailPoint IIQ (IAM), Sentinel One (EDR)",
        "Identity IQ workflows and rules",
    ],
)
def test_identityiq_meets_sailpoint_iiq(catalog_aliases, cv):
    from app.services.must_text_evidence import mentions

    assert mentions(_sailpoint_iiq(), cv)


@pytest.mark.parametrize(
    "cv",
    [
        # Inny produkt SailPointa — o to rekruter pyta w rozmowie.
        "Streamlined user access processes in SailPoint IdentityNow",
        "expertise in CyberArk, Omada, SailPoint, and Delinea",
    ],
)
def test_other_sailpoint_products_do_not_meet_iiq(catalog_aliases, cv):
    from app.services.must_text_evidence import mentions

    assert not mentions(_sailpoint_iiq(), cv)
