"""Scalenie rekrutacji-duplikatów po migracji z Traffita — reguły bez bazy.

Która para w ogóle jest parą, kiedy ją pomijamy i co idzie za osobą. Zapis
sprawdza ``test_job_twin_merge.py`` na Postgresie.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest
from fastapi import HTTPException

from app.api.admin_traffit import _merge_scope
from app.services import job_twin_merge as merge


def _copy(**over: Any) -> merge.JobFacts:
    facts: dict[str, Any] = {
        "job_id": 1,
        "external_source": "traffit",
        "managed_in_nexus": True,
        "status": "published",
        "client_id": 7,
    }
    return merge.JobFacts(**{**facts, **over})


def _nexus(**over: Any) -> merge.JobFacts:
    facts: dict[str, Any] = {
        "job_id": 2,
        "external_source": "manual",
        "managed_in_nexus": False,
        "status": "published",
        "client_id": 7,
    }
    return merge.JobFacts(**{**facts, **over})


def _reason(
    source: Optional[merge.JobFacts],
    target: Optional[merge.JobFacts],
    *,
    shared: bool = False,
    merged: bool = False,
) -> Optional[str]:
    return merge.skip_reason(source, target, shared=shared, merged=merged)


def test_open_copy_and_open_nexus_recruitment_can_be_merged() -> None:
    assert _reason(_copy(), _nexus()) is None


def test_copy_closed_by_a_person_still_gives_its_people_away() -> None:
    assert _reason(_copy(status="closed"), _nexus()) is None


def test_merged_pair_is_not_merged_twice() -> None:
    assert _reason(_copy(), _nexus(), merged=True) == merge.SKIP_MERGED


def test_copy_returned_to_traffit_is_left_alone() -> None:
    # Bez „Prowadzona w NEXUSIE” import odtworzyłby w kopii przeniesione pary.
    assert _reason(_copy(managed_in_nexus=False), _nexus()) == merge.SKIP_SOURCE
    assert _reason(_copy(external_source="manual"), _nexus()) == merge.SKIP_SOURCE
    assert _reason(None, _nexus()) == merge.SKIP_SOURCE


def test_target_must_be_a_recruitment_created_in_nexus() -> None:
    assert _reason(_copy(), None) == merge.SKIP_TARGET
    assert _reason(_copy(), _nexus(external_source="traffit")) == merge.SKIP_TARGET


def test_two_copies_of_one_recruitment_wait_for_a_person() -> None:
    assert _reason(_copy(), _nexus(), shared=True) == merge.SKIP_SHARED


def test_other_client_is_not_the_same_request() -> None:
    assert _reason(_copy(), _nexus(client_id=8)) == merge.SKIP_CLIENT


def test_closed_nexus_recruitment_does_not_receive_people() -> None:
    # Przepięcie do zamkniętej rekrutacji schowałoby ludzi z Tablicy.
    assert _reason(_copy(), _nexus(status="closed")) == merge.SKIP_TARGET_CLOSED


def test_only_exact_twins_from_the_transfer_receipt_are_pairs() -> None:
    rows = [
        (10, "20", "true"),
        (11, "21", "false"),  # podobny tytuł, inny numer requestu
        (12, "22", None),  # paragon sprzed pola `twin_exact`
        (13, None, "true"),
        (14, "nie-id", "true"),
        (15, "15", "true"),  # rekrutacja nie jest własnym bliźniakiem
    ]
    assert merge.parse_pairs(rows) == [merge.Pair(10, 20)]


def test_scope_key_does_not_depend_on_the_order_of_ids() -> None:
    assert merge.Scope((3, 1, 2)).key() == merge.Scope((1, 2, 3)).key()
    assert merge.Scope().key() != merge.Scope((1,)).key()


def test_route_scope_reads_a_list_and_refuses_an_empty_one() -> None:
    assert _merge_scope(None) == merge.Scope()
    assert _merge_scope(" 5, 3,5 ") == merge.Scope((3, 5))
    for bad in ("", " , ", "3;4", "abc"):
        with pytest.raises(HTTPException) as caught:
            _merge_scope(bad)
        assert caught.value.status_code == 422


def test_pair_tables_follow_by_job_and_candidate() -> None:
    keys = [follow.key for follow in merge.FOLLOW]
    assert len(keys) == len(set(keys))
    for follow in merge.FOLLOW:
        update, count = follow.update_sql(), follow.count_sql()
        assert update.startswith(f"UPDATE {follow.table} SET {follow.column} = :target")
        assert ":source" in update and ":ids" in update
        assert count.startswith(f"SELECT count(*) FROM {follow.table} WHERE ")
        # Wiersze etapów i procesy przepina wyłącznie warstwa komend.
        assert follow.table not in {"candidate_stages", "recruitment_processes"}


def test_unique_pair_tables_keep_the_row_of_the_nexus_recruitment() -> None:
    by_key = {follow.key: follow for follow in merge.FOLLOW}
    for key in (
        "recommendation_cards",
        "screening_forms",
        "slot_requests",
        "placement_exclusions",
    ):
        assert "NOT EXISTS" in by_key[key].where
        assert "x.job_id = :target" in by_key[key].where


def test_pair_readers_named_by_the_review_are_followed() -> None:
    # Bramka debriefu, checklista ruchu, prepy i wysyłka maila odmowy czytają
    # parę po (kandydat, rekrutacja) — bez przepięcia zgubiłyby osobę.
    tables = {follow.table for follow in merge.FOLLOW}
    assert {
        "calendar_events",
        "client_interview_slot_requests",
        "interview_feedback",
        "prep_meetings",
        "prep_transcripts",
        "prep_reviews",
        "interview_question_ratings",
        "scheduled_rejection_emails",
        "placement_exclusions",
        "application_submissions",
        "application_screenings",
    } <= tables


def test_follow_tables_and_columns_exist_in_the_models() -> None:
    # Surowy SQL nie przechodzi przez ORM — literówka w nazwie wyszłaby dopiero
    # na produkcji, w połowie pary.
    import re

    import app.models  # noqa: F401 — rejestruje wszystkie tabele
    from app.models.base import Base

    for follow in merge.FOLLOW:
        table = Base.metadata.tables[follow.table]
        assert follow.column in table.c, follow
        own_where = follow.where.split("NOT EXISTS")[0]
        for column in re.findall(r"\b([a-z_]+) = ", own_where):
            assert column in table.c, (follow.table, column)


def test_merged_copy_is_never_a_transfer_wave_candidate() -> None:
    from app.services import traffit_transfer as transfer

    for scope in (transfer.Scope(job_ids=(1,)), transfer.Scope(client_id=1)):
        sql = transfer._jobs_sql(scope)  # noqa: SLF001
        assert f"merged.action = '{merge.MERGE_ACTION}'" in sql


def test_totals_add_up_pairs_and_columns() -> None:
    totals = merge._totals(  # noqa: SLF001
        [
            {"status": "merged", "people": 5, "moved": 4, "in_both": 1, "notes": 3}
            | {"columns": {"new": 3, "screening": 1}},
            {"status": "merged", "people": 2, "moved": 2, "columns": {"new": 2}},
            {"status": "skipped", "skip_reason": merge.SKIP_TARGET_CLOSED},
        ]
    )
    assert totals["pairs"] == 3
    assert totals["by_status"] == {"merged": 2, "skipped": 1}
    assert (totals["people"], totals["moved"], totals["in_both"]) == (7, 6, 1)
    assert totals["notes"] == 3
    assert totals["columns"] == {"new": 5, "screening": 1}
