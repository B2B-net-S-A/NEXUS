"""Propozycje do słownika — reguły bez bazy: nazwy, rodziny, bezpieczniki, lustro 0658.

Trasy, nocny bieg i zatwierdzanie na żywej bazie: ``test_skill_proposals_api.py``.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models.ai_feature import FEATURE_DATA_SENT, FEATURE_LABELS, AIFeatureKey
from app.models.skill_proposal import SkillProposal
from app.services import skill_proposals as sp
from app.services.ai_models import fallbacks_for, model_for
from app.services.care.skills import SkillDictionary

BACKEND = Path(__file__).resolve().parents[1]


def _dictionary() -> SkillDictionary:
    names = {
        1: "Microservices",
        2: "PostgreSQL",
        3: "MySQL",
        4: "Team Lead",
        5: "Excel Sheets",
    }
    categories = {
        1: "backend",
        2: "database",
        3: "database",
        4: "role_management",
        5: None,
    }
    by_key = {name.lower(): sid for sid, name in names.items()}
    by_key["mikroserwisy-pl"] = 1
    return SkillDictionary(by_key=by_key, names=names, categories=categories)


def test_clean_name_drops_sentences_and_noise() -> None:
    assert sp.clean_name("  Excel.  ") == "Excel"
    assert sp.clean_name("x") is None
    assert sp.clean_name(None) is None
    assert (
        sp.clean_name("umiejętność pracy w zespole pod presją czasu i stresu") is None
    )


def test_cv_content_splits_on_comma_outside_parentheses() -> None:
    assert sp.split_cv_content("Java 17+, Spring (Boot, Data); SQL") == [
        "Java 17+",
        " Spring (Boot, Data)",
        " SQL",
    ]
    assert sp.split_cv_content(None) == []


def test_job_row_variants_are_separate_names() -> None:
    assert sp.split_job_name("C# lub .NET") == ["C#", ".NET"]
    assert sp.split_job_name("Kafka / RabbitMQ") == ["Kafka", "RabbitMQ"]
    assert sp.split_job_name("CI/CD") == ["CI/CD"]


def test_family_drops_parentheses_and_vendor_prefixes() -> None:
    assert (
        sp.family_key("MS Excel")
        == sp.family_key("Microsoft Excel")
        == sp.family_key("excel")
    )
    assert sp.family_key("Apache Kafka") == "kafka"
    assert sp.family_key("Excel (zaawansowany)") == "excel"


def test_rule_alias_needs_every_name_on_the_same_entry() -> None:
    index = sp.loose_index(_dictionary())
    assert sp.rule_alias({"micro-services", "Micro Services"}, index) == 1
    assert sp.rule_alias({"micro-services", "zorblax"}, index) is None


def test_guard_alias_to_role_is_manual_only() -> None:
    d = _dictionary()
    fields = sp.apply_guards(
        {"decision": "alias", "canonical": "Team Lead", "confidence": "high"},
        d,
        sp.loose_index(d),
    )
    assert fields["target_skill_id"] == 4
    assert fields["confidence"] == "low"
    assert (
        fields["review_note"]
        == "Wskazuje rolę „Team Lead”, nie umiejętność: tylko ręcznie"
    )


def test_guard_alias_to_missing_entry_is_low() -> None:
    d = _dictionary()
    fields = sp.apply_guards(
        {"decision": "alias", "canonical": "Kubernetes", "confidence": "high"},
        d,
        sp.loose_index(d),
    )
    assert fields["target_skill_id"] is None
    assert fields["confidence"] == "low"


def test_guard_new_equal_to_existing_entry_becomes_alias() -> None:
    d = _dictionary()
    fields = sp.apply_guards(
        {
            "decision": "new",
            "canonical": "Micro-Services",
            "category": "backend",
            "confidence": "high",
        },
        d,
        sp.loose_index(d),
    )
    assert fields["decision"] == "alias"
    assert fields["target_skill_id"] == 1
    assert fields["canonical"] == "Microservices"
    assert fields["confidence"] == "high"


def test_guard_category_outside_list_is_dropped() -> None:
    d = _dictionary()
    index = sp.loose_index(d)
    role = sp.apply_guards(
        {
            "decision": "new",
            "canonical": "Zorblax",
            "category": "role_management",
            "confidence": "high",
        },
        d,
        index,
    )
    assert (role["category"], role["confidence"]) == (None, "low")
    practice = sp.apply_guards(
        {
            "decision": "new",
            "canonical": "Zorblax",
            "category": "practice",
            "confidence": "high",
        },
        d,
        index,
    )
    assert (practice["category"], practice["confidence"]) == ("practice", "high")


def test_guard_generic_keeps_only_dictionary_replacements() -> None:
    d = _dictionary()
    fields = sp.apply_guards(
        {
            "decision": "generic",
            "replacements": ["postgresql", "MySQL", "Zorblax DB"],
            "confidence": "high",
        },
        d,
        sp.loose_index(d),
    )
    assert fields["replacements"] == ["PostgreSQL", "MySQL"]
    assert fields["canonical"] is None and fields["category"] is None


def test_unknown_decision_and_confidence_fall_back_safely() -> None:
    d = _dictionary()
    fields = sp.apply_guards(
        {"decision": "maybe", "confidence": "sure"}, d, sp.loose_index(d)
    )
    assert (fields["decision"], fields["confidence"]) == ("noise", "low")


def test_group_unknown_counts_usage_and_reuses_merged_rows() -> None:
    d = _dictionary()
    stats = {
        "microservices": sp.NameStat(raw="Microservices", cand=10),
        "office 365": sp.NameStat(raw="Office 365", cand=3),
        "microsoft 365": sp.NameStat(raw="Microsoft 365", cand=5, jobs=1),
    }
    merged = SkillProposal(
        family_key="365",
        names=[{"name": "office 365"}, {"name": "microsoft 365"}],
        status="open",
    )
    groups, usage = sp.group_unknown(stats, d, [merged])
    assert usage == {1: 10}
    assert len(groups) == 1 and groups[0].row is merged
    assert groups[0].names == {"office 365", "microsoft 365"}


def test_merge_same_canonical_keeps_heaviest_row() -> None:
    profiles_only = SkillProposal(
        family_key="a",
        decision="new",
        canonical="Microsoft 365",
        confidence="high",
        names=[{"name": "microsoft 365", "count": 9}],
        cand_count=9,
        cv_count=0,
        job_count=0,
        weight=9,
    )
    with_job = SkillProposal(
        family_key="b",
        decision="new",
        canonical="microsoft 365",
        confidence="low",
        names=[{"name": "office 365", "count": 4}],
        cand_count=4,
        cv_count=0,
        job_count=1,
        weight=24,
    )
    dropped = sp._merge_same_canonical([profiles_only, with_job])
    assert dropped == [profiles_only], (
        "zostaje wiersz o większej wadze (wymaganie = 20)"
    )
    assert {n["name"] for n in with_job.names} == {"microsoft 365", "office 365"}
    assert with_job.weight == 13 + 20
    assert with_job.confidence == "low"


def test_only_high_new_or_alias_without_note_with_category_is_sure() -> None:
    base = dict(status="open", confidence="high", review_note=None, category="practice")
    assert sp.is_sure(SkillProposal(decision="new", canonical="Zorblax", **base))
    assert sp.is_sure(SkillProposal(decision="alias", target_skill_id=1, **base))
    assert not sp.is_sure(SkillProposal(decision="generic", **base))
    assert not sp.is_sure(
        SkillProposal(decision="new", canonical="Z", **{**base, "category": None})
    )
    assert not sp.is_sure(
        SkillProposal(decision="new", canonical="Z", **{**base, "review_note": "x"})
    )
    assert not sp.is_sure(
        SkillProposal(decision="new", canonical="Z", **{**base, "confidence": "low"})
    )


def test_parse_reply_reads_items_by_id() -> None:
    raw = 'tekst {"items": [{"id": 0, "decision": "new"}, {"id": "x"}, "zły"]} koniec'
    assert sp.parse_reply(raw) == {0: {"id": 0, "decision": "new"}}


def test_feature_is_registered_on_sol_with_sonnet_fallback() -> None:
    key = AIFeatureKey.skill_dictionary_proposals
    assert model_for(key) == "gpt-6.1-sol"
    assert fallbacks_for(key) == ("claude-sonnet-5-5",)
    assert "spoza słownika" in FEATURE_LABELS[key] or "Słownik" in FEATURE_LABELS[key]
    assert any("bez danych osób" in line for line in FEATURE_DATA_SENT[key])


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_migration_is_mirrored_in_entrypoint() -> None:
    path = BACKEND / "alembic" / "versions" / "0658_skill_proposals.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.down_revision == "0657_job_p0_overdue"
    entry = _squash(re.sub(r'"\s+"', "", (BACKEND / "entrypoint.sh").read_text()))
    assert "skill_proposals_schema as _skill_proposals_schema" in entry
    assert "*_SKILL_PROPOSALS_TABLE_DDL," in entry
    assert "ADD VALUE IF NOT EXISTS 'skill_dictionary_proposals'" in entry
    assert "SELECT 'skill_dictionary_proposals', TRUE, 0, now(), now()" in entry


def test_model_matches_ddl_columns() -> None:
    from app.services.skill_proposals_schema import TABLE_DDL

    ddl = TABLE_DDL[0]
    for column in SkillProposal.__table__.columns.keys():
        assert f"{column} " in ddl, column


def test_only_top_families_get_rows(monkeypatch) -> None:
    """Bieg na stagingu 06.11 zapisał 65 956 rodzin spoza top 400 — wiersze tylko dla top."""
    monkeypatch.setattr(sp, "TOP_FAMILIES", 2)
    stats = {
        "a": sp.NameStat(raw="a", cand=1),
        "b": sp.NameStat(raw="b", jobs=1),
        "c": sp.NameStat(raw="c", cand=5),
    }
    groups = [sp.Group(key=k, names={k}) for k in stats]
    assert [g.key for g in sp.select_top(groups, stats)] == ["b", "c"]


def test_names_with_parentheses_do_not_become_aliases() -> None:
    row = SkillProposal(
        names=[
            {"name": "excel", "count": 9},
            {"name": "excel (advanced)", "count": 3},
            {"name": "ms excel", "count": 2},
        ]
    )
    assert sp.alias_names(row) == ["excel", "ms excel"]
