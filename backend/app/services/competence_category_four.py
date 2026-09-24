"""Cztery kategorie kompetencji zamiast pięciu (decyzja Artura 24.09.2026).

Zespół pracuje w podziale z dawnego InfraReportera: „Infra & Operations &
Security / Data & AI”, „Development”, „QA”, „Management & Delivery (PM & BA)”.
NEXUS miał pięć kategorii (osobno „Dane i AI”, a security razem z QA), więc
przydział ludzi do requestów nie dał się zapisać tak, jak zespół naprawdę
pracuje.

Identyfikatory i slugi zostają — zmieniają się nazwy, opisy i słowa kluczowe:

* ``infrastructure_operations`` → Infra & Operations & Security / Data & AI
  (przejmuje ``data_ai`` i security),
* ``software_development`` → Development,
* ``security_quality`` → QA (słowa kluczowe wyłącznie testowe),
* ``management_delivery`` → Management & Delivery (PM & BA),
* ``data_ai`` → ``is_active = false``; każdy klucz obcy przepięty na infra.

Stały slug to świadomy wybór: slug siedzi w starym polu tekstowym kandydatów,
w tekście embeddingu i w regułach klasyfikacji. Nowy slug oznaczałby ponowne
liczenie wektorów całej bazy bez żadnego zysku dla użytkownika.

``data_ai`` NIE jest kasowana: dwa klucze obce (rekrutacje, kandydaci) blokują
kasowanie, cztery tabele kasowałyby wiersze kaskadą, a seed w ``entrypoint.sh``
(``ON CONFLICT (slug) DO NOTHING``) i tak wstawiłby ją z powrotem przy
następnym starcie.

SQL ma jedno źródło — ten moduł. Czyta go migracja
``0371_request_allocation`` i blok w ``entrypoint.sh`` (alembic na produkcji
bywa osierocony). Blokada doradcza + znacznik w ``app_settings`` → drugi
przebieg kończy się od razu. Paragon niesie wyłącznie liczby.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MARKER = "competence_categories_four_2026_09"

INFRA = "infrastructure_operations"
DEVELOPMENT = "software_development"
QA = "security_quality"
MANAGEMENT = "management_delivery"
RETIRED = "data_ai"

# Kolejność = kolejność na ekranach (display_order).
CATEGORIES: tuple[dict[str, Any], ...] = (
    {
        "slug": INFRA,
        "name_pl": "Infra & Operations & Security / Data & AI",
        "name_en": "Infra & Operations & Security / Data & AI",
        "description": (
            "Infrastruktura, cloud, DevOps, SRE, sieć, administracja, "
            "cyberbezpieczeństwo (SOC, pentesting, IAM) oraz dane i AI "
            "(inżynieria danych, BI, data science, machine learning)."
        ),
        "keywords": [
            "devops",
            "sre",
            "kubernetes",
            "docker",
            "terraform",
            "ansible",
            "aws",
            "azure",
            "gcp",
            "cloud",
            "linux",
            "sysadmin",
            "networking",
            "ci/cd",
            "observability",
            "infrastructure",
            "security",
            "soc",
            "siem",
            "pentester",
            "appsec",
            "cybersecurity",
            "iam",
            "data engineer",
            "data scientist",
            "machine learning",
            "ai",
            "llm",
            "spark",
            "databricks",
            "power bi",
            "etl",
            "bi",
        ],
        "display_order": 1,
    },
    {
        "slug": DEVELOPMENT,
        "name_pl": "Development",
        "name_en": "Development",
        "description": (
            "Rozwój oprogramowania: backend, frontend, mobile, embedded, "
            "low-code i ERP."
        ),
        "keywords": [
            "frontend",
            "backend",
            "fullstack",
            "react",
            "angular",
            "vue",
            "typescript",
            "javascript",
            "java",
            "spring",
            "python",
            "node",
            "go",
            ".net",
            "c#",
            "php",
            "kotlin",
            "swift",
            "android",
            "ios",
            "mobile",
            "embedded",
            "sap",
            "salesforce",
        ],
        "display_order": 2,
    },
    {
        "slug": QA,
        "name_pl": "QA",
        "name_en": "QA",
        "description": (
            "Zapewnienie jakości: testy manualne i automatyczne, testy "
            "wydajnościowe, test management."
        ),
        "keywords": [
            "qa",
            "quality assurance",
            "tester",
            "test automation",
            "selenium",
            "cypress",
            "playwright",
            "junit",
            "pytest",
            "performance testing",
            "test manager",
            "istqb",
        ],
        "display_order": 3,
    },
    {
        "slug": MANAGEMENT,
        "name_pl": "Management & Delivery (PM & BA)",
        "name_en": "Management & Delivery (PM & BA)",
        "description": (
            "Zarządzanie projektami i produktem, analiza biznesowa i "
            "systemowa, Scrum, delivery."
        ),
        "keywords": [
            "project manager",
            "product owner",
            "product manager",
            "business analyst",
            "system analyst",
            "scrum master",
            "agile coach",
            "delivery manager",
            "pmo",
            "tech lead",
        ],
        "display_order": 4,
    },
)

# Tytuł rekrutacji z dzisiejszą kategorią QA, który opisuje security, a nie
# testy — przechodzi do grupy Infra. Test ma pierwszeństwo: „Security Tester”
# zostaje w QA (jak w regułach klasyfikatora).
SECURITY_TITLE_SQL = (
    r"(\msecurity\M|\msoc\M|siem|\miam\M|vulnerab|appsec|owasp|pentest|"
    r"penetration|bezpiecze|cyber|red team|blue team|malware|exploit|\mcsirt\M)"
)
QA_TITLE_SQL = r"((?<!pen)tester|\mqa\M|quality assurance|\mtest\M|testów|testowani)"

# (tabela, kolumna) z kluczem obcym bez unikalności po kategorii — proste
# przepięcie.
_PLAIN_FKS: tuple[tuple[str, str], ...] = (
    ("jobs", "competence_category_id"),
    ("candidates", "competence_category_id"),
    ("talent_pools", "competence_category_id"),
    ("interview_questions", "competence_category_id"),
    ("recruitment_priority_assignments", "competence_category_id"),
    ("cc_suggestion_overrides", "suggested_cc_id"),
    ("cc_suggestion_overrides", "final_cc_id"),
)


def _category_updates() -> list[tuple[str, dict[str, Any]]]:
    statements = []
    for category in CATEGORIES:
        statements.append(
            (
                """UPDATE competence_categories
                      SET name_pl = :name_pl, name_en = :name_en,
                          description = :description,
                          keywords = CAST(:keywords AS jsonb),
                          display_order = :display_order, is_active = true
                    WHERE slug = :slug""",
                {
                    **category,
                    "keywords": json.dumps(category["keywords"], ensure_ascii=False),
                },
            )
        )
    statements.append(
        (
            "UPDATE competence_categories SET is_active = false, "
            "display_order = 99 WHERE slug = :slug",
            {"slug": RETIRED},
        )
    )
    return statements


_OLD = "(SELECT id FROM competence_categories WHERE slug = 'data_ai')"
_NEW = "(SELECT id FROM competence_categories WHERE slug = 'infrastructure_operations')"
_QA = "(SELECT id FROM competence_categories WHERE slug = 'security_quality')"


def _remap_statements() -> list[str]:
    """Przepięcie ``data_ai → infra`` i security-rekrutacji z QA do infra.

    Tabele z unikalnością (osoba/kandydat/rekrutacja × kategoria) najpierw
    oddają „główność” wierszowi docelowemu, potem kasują duplikat, dopiero
    potem przepinają resztę — inaczej UPDATE wpadłby na UNIQUE.
    """
    statements = [
        f"UPDATE {table} SET {column} = {_NEW} WHERE {column} = {_OLD}"
        for table, column in _PLAIN_FKS
    ]
    # Kandydat × kategoria: jeśli kandydat ma obie, główność przechodzi na
    # infra, wiersz data_ai znika.
    statements += [
        f"""UPDATE candidate_competence_categories AS keep
               SET is_primary = true
             WHERE keep.competence_category_id = {_NEW}
               AND EXISTS (SELECT 1 FROM candidate_competence_categories AS old
                            WHERE old.candidate_id = keep.candidate_id
                              AND old.competence_category_id = {_OLD}
                              AND old.is_primary)""",
        f"""DELETE FROM candidate_competence_categories AS old
             WHERE old.competence_category_id = {_OLD}
               AND EXISTS (SELECT 1 FROM candidate_competence_categories AS keep
                            WHERE keep.candidate_id = old.candidate_id
                              AND keep.competence_category_id = {_NEW})""",
        f"""UPDATE candidate_competence_categories
               SET competence_category_id = {_NEW}
             WHERE competence_category_id = {_OLD}""",
    ]
    # Osoba × kategoria: priorytet 1 przechodzi na infra (jedna główna na
    # osobę pilnuje częściowy indeks — osoba ma ją najwyżej jedną, więc
    # przeniesienie jej z data_ai na infra niczego nie łamie).
    statements += [
        f"""DELETE FROM user_competence_categories AS keep
             WHERE keep.competence_category_id = {_NEW}
               AND keep.priority = 2
               AND EXISTS (SELECT 1 FROM user_competence_categories AS old
                            WHERE old.user_id = keep.user_id
                              AND old.competence_category_id = {_OLD}
                              AND old.priority = 1)""",
        f"""DELETE FROM user_competence_categories AS old
             WHERE old.competence_category_id = {_OLD}
               AND EXISTS (SELECT 1 FROM user_competence_categories AS keep
                            WHERE keep.user_id = old.user_id
                              AND keep.competence_category_id = {_NEW})""",
        f"""UPDATE user_competence_categories
               SET competence_category_id = {_NEW}
             WHERE competence_category_id = {_OLD}""",
    ]
    for table, owner in (
        ("job_secondary_cc", "job_id"),
        ("tac_linkedin_farming", "tac_user_id"),
    ):
        statements += [
            f"""DELETE FROM {table} AS old
                 WHERE old.competence_category_id = {_OLD}
                   AND EXISTS (SELECT 1 FROM {table} AS keep
                                WHERE keep.{owner} = old.{owner}
                                  AND keep.competence_category_id = {_NEW})""",
            f"""UPDATE {table} SET competence_category_id = {_NEW}
                 WHERE competence_category_id = {_OLD}""",
        ]
    # Rekrutacja z kategorią QA, której tytuł mówi o security, nie o testach.
    statements.append(
        f"""UPDATE jobs SET competence_category_id = {_NEW}
             WHERE competence_category_id = {_QA}
               AND title ~* '{SECURITY_TITLE_SQL}'
               AND title !~* '{QA_TITLE_SQL}'"""
    )
    # Kategoria poboczna równa głównej po przepięciu to szum.
    statements.append(
        """DELETE FROM job_secondary_cc AS secondary
             USING jobs
            WHERE jobs.id = secondary.job_id
              AND jobs.competence_category_id = secondary.competence_category_id"""
    )
    return statements


async def _count(db: AsyncSession, sql: str) -> int:
    return int((await db.execute(text(sql))).scalar() or 0)


async def run_competence_category_four(db: AsyncSession) -> Optional[dict[str, int]]:
    """Przełącz bazę na cztery kategorie. ``None`` = już zrobione.

    Wołający commituje. Bez kategorii w bazie (świeża instalacja przed
    seedem) nie ma czego przepinać — znacznik NIE jest stawiany, żeby
    przebieg po seedzie zrobił swoje.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": MARKER})
    done = await db.execute(
        text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": MARKER}
    )
    if done.scalar() is not None:
        return None
    if not await _count(db, "SELECT count(*) FROM competence_categories"):
        return None

    before = {
        "jobs_data_ai": await _count(
            db, f"SELECT count(*) FROM jobs WHERE competence_category_id = {_OLD}"
        ),
        "candidates_data_ai": await _count(
            db,
            "SELECT count(*) FROM candidate_competence_categories "
            f"WHERE competence_category_id = {_OLD}",
        ),
    }
    for sql, params in _category_updates():
        await db.execute(text(sql), params)
    for sql in _remap_statements():
        await db.execute(text(sql))
    receipt = {
        **before,
        "remaining_fk_data_ai": await _count(
            db,
            "SELECT (SELECT count(*) FROM jobs WHERE competence_category_id = "
            f"{_OLD}) + (SELECT count(*) FROM candidate_competence_categories "
            f"WHERE competence_category_id = {_OLD})",
        ),
    }
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value, updated_at) "
            "VALUES (:k, CAST(:v AS jsonb), now()) ON CONFLICT (key) DO NOTHING"
        ),
        {"k": MARKER, "v": json.dumps(receipt)},
    )
    return receipt


def sync_statements() -> list[tuple[str, dict[str, Any]]]:
    """Te same zmiany jako lista (SQL, parametry) dla migracji alembica."""
    return _category_updates() + [(sql, {}) for sql in _remap_statements()]
