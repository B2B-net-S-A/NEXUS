"""„Kto już to robił” — funkcje czyste bez bazy (rozbicie, cytaty, ocena, kolejność).

Reguła: docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md
"""

import ast
from pathlib import Path

from app.services import duty_search_schema
from app.services.duty_search import (
    CvText,
    GoalPlan,
    capabilities_block,
    fused_order,
    parse_assessment,
    parse_plan,
)

BACKEND = Path(__file__).resolve().parent.parent

# Fragment prawdziwego układu z odczytu PDF: data wstawiona w środek zdania.
CV_WITH_DATE_INSIDE = (
    "Analysing business processes, and determining ways to optimize/\n"
    "01-2021 – Present\n"
    "improve JIRA and Confluence building and configuring complex scripts and\n"
    "workflows, screen, field, security, and notification schemes.\n"
    "Przeprowadziłem migrację 40 aplikacji z serwerowni do AWS."
)


class TestQuotes:
    def test_exact_quote_after_normalisation(self):
        cv = CvText(CV_WITH_DATE_INSIDE)
        assert cv.contains("przeprowadzilem MIGRACJE 40 aplikacji z serwerowni do AWS")

    def test_quote_glued_over_pdf_date_passes(self):
        cv = CvText(CV_WITH_DATE_INSIDE)
        quote = (
            "determining ways to optimize/ improve JIRA and Confluence building and "
            "configuring complex scripts and workflows"
        )
        assert cv.contains(quote)

    def test_fabricated_quote_is_rejected(self):
        cv = CvText(CV_WITH_DATE_INSIDE)
        assert not cv.contains("Led the migration of 200 Oracle databases to Azure SQL")

    def test_short_quote_must_be_exact(self):
        cv = CvText(CV_WITH_DATE_INSIDE)
        assert not cv.contains("JIRA")
        assert not cv.contains("optimize improve JIRA")


class TestPlan:
    def test_sanitises_model_output(self):
        raw = {
            "cel_jednym_zdaniem": "Migracja systemów z serwerowni do AWS",
            "zdolnosci": [
                {"nazwa": "Migracja do chmury", "waga": 7, "po_czym_poznac": "x"},
                {"nazwa": "migracja do chmury", "waga": 2},
                {"nazwa": "Sieć w AWS", "waga": "zła"},
                "nie słownik",
            ]
            + [{"nazwa": f"Z{i}", "waga": 1} for i in range(10)],
            "sygnaly_posrednie": [
                {"sygnal": "AWS DMS", "dlaczego": "narzędzie migracji"}
            ],
            "wzorce_regex": ["migra[^.]{0,60}aws", "(?=aws)", "x", "dms\\1"],
            "anty_sygnaly": ["tylko S3"],
            "fragmenty_cv": [
                "za krótki",
                "Przeniosłem 40 aplikacji z VMware do AWS, w tym bazy danych.",
            ],
        }
        plan = parse_plan(raw, fallback_summary="cel")
        assert plan.summary == "Migracja systemów z serwerowni do AWS"
        assert [c.name for c in plan.capabilities][:2] == [
            "Migracja do chmury",
            "Sieć w AWS",
        ]
        assert plan.capabilities[0].weight == 3
        assert plan.capabilities[1].weight == 1
        assert len(plan.capabilities) == 6
        assert plan.patterns == ("migra[^.]{0,60}aws",)
        assert len(plan.fragments) == 1

    def test_empty_answer_falls_back_to_goal(self):
        plan = parse_plan({}, fallback_summary="Wdrożenie Jira")
        assert plan == GoalPlan(summary="Wdrożenie Jira")
        assert "brak rozbicia" in capabilities_block(plan)


class TestAssessment:
    def test_level_needs_verified_quote(self):
        cv = CvText(CV_WITH_DATE_INSIDE)
        raw = {
            "poziom": "zrobil_to",
            "pewnosc": 140,
            "dowody": [
                {"cytat": "Led the migration of 200 Oracle databases", "wniosek": "x"}
            ],
        }
        a = parse_assessment(raw, cv, ["Migracja do chmury"])
        assert a.tier == "brak"
        assert a.rejected_quotes == 1
        assert a.confidence == 100

    def test_keeps_known_capabilities_and_quotes(self):
        cv = CvText(CV_WITH_DATE_INSIDE)
        raw = {
            "poziom": "bardzo_blisko",
            "pewnosc": "85",
            "zdolnosci": {
                "migracja do chmury": "tak",
                "Nieznana": "tak",
                "Sieć w AWS": "może",
            },
            "dowody": [
                {
                    "cytat": "Przeprowadziłem migrację 40 aplikacji z serwerowni do AWS.",
                    "gdzie": "Firma X / 2021",
                    "wniosek": "Migrował do AWS.",
                }
            ],
            "luka": "Brak landing zone.",
            "pytanie": "Jak wyglądała sieć?",
        }
        a = parse_assessment(raw, cv, ["Migracja do chmury", "Sieć w AWS"])
        assert a.tier == "bardzo_blisko"
        assert a.capabilities == {"Migracja do chmury": "tak"}
        assert a.evidence[0]["where"] == "Firma X / 2021"
        assert a.confidence == 85

    def test_unknown_tier_is_brak(self):
        a = parse_assessment({"poziom": "super"}, CvText("x"), [])
        assert a.tier == "brak"


class TestOrder:
    def test_strong_first_rest_keeps_both_lists(self):
        canonical = [1, 2, 3, 4]
        goal = [5, 3, 6]
        tiers = {
            1: "ma_klocki",
            2: "brak",
            3: "zrobil_to",
            4: "ma_klocki",
            5: "bardzo_blisko",
            6: "brak",
        }
        order = fused_order(canonical, goal, tiers)
        assert set(order) == {1, 2, 3, 4, 5, 6}
        assert order[:2] == [3, 5]  # 3 jest w obu listach, więc wyżej
        assert order[2] == 1  # „Ma klocki” zostaje, w kolejności RRF

    def test_judgement_does_not_reorder_inside_group(self):
        order = fused_order([10, 11], [], {10: "bardzo_blisko", 11: "zrobil_to"})
        assert order == [10, 11]


def test_migration_and_entrypoint_share_one_ddl_source():
    migration = (BACKEND / "alembic/versions/0678_duty_search.py").read_text()
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert "from app.services import duty_search_schema as schema" in migration
    assert (
        "from app.services import duty_search_schema as _duty_search_schema"
        in entrypoint
    )
    assert "*_DUTY_SEARCH_DDL," in entrypoint
    assert any("duty_search_results" in stmt for stmt in duty_search_schema.TABLE_DDL)
    # Wyniki niosą cytaty z CV — twarde usunięcie osoby musi je zabrać.
    results = next(
        s
        for s in duty_search_schema.TABLE_DDL
        if "CREATE TABLE IF NOT EXISTS duty_search_results" in s
    )
    assert "REFERENCES candidates(id) ON DELETE CASCADE" in results


def test_api_module_has_no_future_annotations():
    # AST, nie tekst: docstring modułu ostrzega przed tym importem (slowapi #579).
    tree = ast.parse((BACKEND / "app/api/duty_search.py").read_text())
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for node in tree.body
    )
