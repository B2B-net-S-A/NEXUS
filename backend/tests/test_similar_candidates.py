"""Zakładka „Podobni” (22.10.2026) — reguły bez bazy.

Qdrant i zapytania SQL są podmienione. Sprawdzamy: stopnie podobieństwa,
wspólne umiejętności, filtry zakładki, sprawdzenie krytycznych pod rekrutację
i to, że dodanie bez krytycznej wymaga zdania (decyzja Artura).
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.candidate import AvailabilityStatus
from app.services import similar_candidates
from app.services.similar_candidates import (
    CriticalItem,
    SimilarFilters,
    critical_items,
    missing_labels,
    note_for_missing,
    passes_filters,
    similarity_level,
    skill_overlap,
)


def _person(**kw):
    base = dict(
        id=1,
        name="Jan",
        lastname="Testowy",
        skills=None,
        verified_tech=None,
        tags=None,
        experience=None,
        cv_extracted_data=None,
        raw_cv_text="",
        skills_manually_curated=False,
        availability_status=AvailabilityStatus.actively_looking,
        expected_rate_hourly=None,
        expected_rate_currency=None,
        rate_from_computed_at=None,
        city=None,
        location=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── Stopień i wspólne umiejętności ────────────────────────────────────────


def test_level_bands_follow_thresholds() -> None:
    assert similarity_level(similar_candidates.VERY_SIMILAR_MIN) == "very"
    assert similarity_level(0.99) == "very"
    assert similarity_level(similar_candidates.SIMILAR_MIN) == "similar"
    assert similarity_level(similar_candidates.SIMILAR_MIN - 0.0001) == "partial"


def test_overlap_keeps_source_order_and_caps_the_rest() -> None:
    source = ["active directory", "windows server", "microsoft 365", "vmware"]
    other = ["vmware", "intune", "active directory"]
    overlap = skill_overlap(source, other)
    assert overlap.shared == ("active directory", "vmware")
    assert overlap.only_source == ("windows server", "microsoft 365")
    assert overlap.only_other == ("intune",)

    many = [f"s{i}" for i in range(30)]
    assert (
        len(skill_overlap(many, []).only_source) == similar_candidates.ONLY_SKILLS_CAP
    )


# ── Filtry zakładki ───────────────────────────────────────────────────────


def test_not_looking_hidden_by_default_and_shown_on_request() -> None:
    person = _person(availability_status=AvailabilityStatus.not_looking)
    assert not passes_filters(person, SimilarFilters(), 0)
    assert passes_filters(person, SimilarFilters(hide_not_looking=False), 0)
    # „Nie wiemy” to nie „Nie szuka”.
    assert passes_filters(
        _person(availability_status=AvailabilityStatus.unknown), SimilarFilters(), 0
    )


def test_without_process_drops_people_in_progress() -> None:
    filters = SimilarFilters(without_process=True)
    assert passes_filters(_person(), filters, 0)
    assert not passes_filters(_person(), filters, 2)


def test_rate_max_keeps_people_without_rate_and_foreign_currency() -> None:
    filters = SimilarFilters(rate_max=Decimal("70"))
    assert passes_filters(_person(expected_rate_hourly=Decimal("70")), filters, 0)
    assert not passes_filters(_person(expected_rate_hourly=Decimal("85")), filters, 0)
    assert passes_filters(_person(), filters, 0)
    assert passes_filters(
        _person(expected_rate_hourly=Decimal("90"), expected_rate_currency="EUR"),
        filters,
        0,
    )


def test_city_matches_city_or_location_case_insensitive() -> None:
    filters = SimilarFilters(city="kraków")
    assert passes_filters(_person(city="Kraków"), filters, 0)
    assert passes_filters(_person(location="Kraków, małopolskie"), filters, 0)
    assert not passes_filters(_person(city="Łódź"), filters, 0)


# ── Wyszukanie: Qdrant podmieniony ────────────────────────────────────────


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _query):
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_find_similar_reports_engine_down_and_missing_vector(monkeypatch) -> None:
    async def down(_cid, *, limit):
        return None

    monkeypatch.setattr(similar_candidates, "nearest_candidates", down)
    result = await similar_candidates.find_similar(_Db([]), _person(), SimilarFilters())
    assert (result.status, result.total) == ("unavailable", 0)

    async def no_vector(_cid, *, limit):
        return (False, [])

    monkeypatch.setattr(similar_candidates, "nearest_candidates", no_vector)
    result = await similar_candidates.find_similar(_Db([]), _person(), SimilarFilters())
    assert result.status == "no_vector"


@pytest.mark.asyncio
async def test_find_similar_keeps_qdrant_order_filters_and_pages(monkeypatch) -> None:
    async def hits(_cid, *, limit):
        assert limit == similar_candidates.POOL_SIZE
        return (True, [(3, 0.91), (2, 0.85), (4, 0.72), (5, 0.6)])

    async def counts(_db, ids):
        return {4: 1}

    monkeypatch.setattr(similar_candidates, "nearest_candidates", hits)
    monkeypatch.setattr(similar_candidates, "active_process_counts", counts)
    # Osoba 5 nie wróciła z bazy (np. czarna lista odcięta w zapytaniu).
    rows = [
        _person(id=2),
        _person(id=3),
        _person(id=4),
    ]
    result = await similar_candidates.find_similar(
        _Db(rows), _person(id=1), SimilarFilters(without_process=True), limit=1
    )
    assert result.status == "ok"
    assert result.total == 2  # 4 odpada filtrem „bez procesu”
    assert [r.candidate.id for r in result.rows] == [3]
    assert result.rows[0].level == "very"

    page_two = await similar_candidates.find_similar(
        _Db(rows),
        _person(id=1),
        SimilarFilters(without_process=True),
        offset=1,
        limit=1,
    )
    assert [r.candidate.id for r in page_two.rows] == [2]


# ── Sprawdzenie krytycznych ───────────────────────────────────────────────


def test_critical_items_met_missing_and_unknown() -> None:
    person = _person(raw_cv_text="Administracja Active Directory i Windows Server.")
    items = critical_items(
        person,
        ["Active Directory", "Microsoft 365", "doświadczenie w bankowości projektów"],
        options=None,
    )
    by_label = {item.label: item for item in items}
    assert by_label["Active Directory"].status == "met"
    assert "cv" in by_label["Active Directory"].sources
    assert by_label["Microsoft 365"].status == "missing"
    assert missing_labels(items) == ["Microsoft 365"]


def test_critical_items_reads_notes_as_evidence() -> None:
    person = _person(raw_cv_text="Windows Server")
    items = critical_items(
        person,
        ["Microsoft 365"],
        options=None,
        note_texts=["Pracował z Microsoft 365 u klienta."],
    )
    assert items[0].status == "met"
    assert items[0].sources == ("note",)


def test_note_for_missing_names_skills_and_reason() -> None:
    assert (
        note_for_missing(["Microsoft 365"], "  dopytam w rozmowie ")
        == "Do sprawdzenia: Microsoft 365 — dopytam w rozmowie"
    )


# ── Dodanie: zdanie przy braku krytycznej ─────────────────────────────────


def test_similar_source_is_registered_for_telemetry() -> None:
    from app.api.proposals_bulk import BulkAddSource
    from app.services.match_telemetry_service import PIPELINE_ADD_SOURCES

    assert "similar_candidates" in get_args(BulkAddSource)
    assert "similar_candidates" in PIPELINE_ADD_SOURCES


def test_reasons_are_trimmed_and_bounded() -> None:
    from app.api.proposals_bulk import BulkProposalsRequest

    body = BulkProposalsRequest(
        candidate_ids=[1, 2], reasons={"1": "  dopytam  ", "2": "   "}
    )
    assert body.reasons == {1: "dopytam"}
    with pytest.raises(ValidationError):
        BulkProposalsRequest(candidate_ids=[1], reasons={"1": "x" * 1001})


@pytest.mark.asyncio
async def test_missing_critical_without_reason_is_refused(monkeypatch) -> None:
    from app.api import proposals_bulk

    people = [_person(id=7, name="Paweł", lastname="Zieliński"), _person(id=8)]

    async def check(_db, _job, candidates):
        return {
            7: [CriticalItem("Microsoft 365", "missing", ())],
            8: [CriticalItem("Microsoft 365", "met", ("cv",))],
        }

    monkeypatch.setattr(similar_candidates, "critical_check", check)
    with pytest.raises(HTTPException) as refused:
        await proposals_bulk._similar_reason_notes(
            _Db(people), job=SimpleNamespace(id=5), candidate_ids=[7, 8], reasons={}
        )
    assert refused.value.status_code == 422
    assert refused.value.detail["code"] == "critical_reason_required"
    assert "Paweł Zieliński" in refused.value.detail["message"]

    notes = await proposals_bulk._similar_reason_notes(
        _Db(people),
        job=SimpleNamespace(id=5),
        candidate_ids=[7, 8],
        reasons={7: "Exchange Online u klienta, dopytam"},
    )
    assert notes == {
        7: "Do sprawdzenia: Microsoft 365 — Exchange Online u klienta, dopytam"
    }
