"""Raport `compare_metadata` w `/api/health/deep`: kształt i ochrona sondy."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, String, Table

from app.services import schema_compare


def _table() -> Table:
    return Table(
        "candidates", MetaData(), Column("id", Integer), Column("name", String)
    )


def test_clean_schema() -> None:
    assert schema_compare.summarize([])["status"] == "clean"


def test_breaking_columns_lead_the_sample() -> None:
    table = _table()
    index = Index("ix_name", table.c.name)
    report = schema_compare.summarize(
        [
            ("remove_index", index),
            ("add_column", None, "candidates", table.c.name),
            ("remove_table", Table("stara", MetaData(), Column("id", Integer))),
        ]
    )
    assert report["status"] == "breaking"
    assert report["counts"] == {"add_column": 1, "remove_index": 1, "remove_table": 1}
    assert report["sample"][0] == {"kind": "add_column", "object": "candidates.name"}


def test_modify_diff_comes_as_list() -> None:
    report = schema_compare.summarize(
        [[("modify_nullable", None, "candidates", "name", {}, True, False)]]
    )
    assert report["status"] == "drift"
    assert report["sample"] == [
        {"kind": "modify_nullable", "object": "candidates.name"}
    ]


def test_sample_is_capped() -> None:
    table = _table()
    diffs = [("add_column", None, f"t{i}", table.c.name) for i in range(80)]
    report = schema_compare.summarize(diffs)
    assert report["total"] == 80 and len(report["sample"]) == 50


def test_alembic_version_is_ignored() -> None:
    assert not schema_compare._include_object(None, "alembic_version", "table")
    assert schema_compare._include_object(None, "candidates", "table")


@pytest.fixture
def clean_state(monkeypatch):
    monkeypatch.setattr(schema_compare, "_result", None)
    monkeypatch.setattr(schema_compare, "_expires_at", 0.0)
    monkeypatch.setattr(schema_compare, "_running", None)


def test_first_call_is_pending_and_runs_once(monkeypatch, clean_state) -> None:
    calls = []

    def fake() -> dict:
        calls.append(1)
        return {"status": "clean"}

    monkeypatch.setattr(schema_compare, "_compare_sync", fake)

    async def scenario() -> list[dict]:
        first = schema_compare.schema_compare_report()
        second = schema_compare.schema_compare_report()
        await schema_compare._running
        return [first, second, schema_compare.schema_compare_report()]

    first, second, third = asyncio.run(scenario())
    assert first == second == {"status": "pending"}
    assert third == {"status": "clean"}
    assert len(calls) == 1, "publiczna sonda nie może mnożyć biegów"


def test_failure_is_reported_without_details(monkeypatch, clean_state) -> None:
    def fake() -> dict:
        raise RuntimeError("password=sekret")

    monkeypatch.setattr(schema_compare, "_compare_sync", fake)

    async def scenario() -> dict:
        schema_compare.schema_compare_report()
        await schema_compare._running
        return schema_compare.schema_compare_report()

    assert asyncio.run(scenario()) == {"status": "unavailable", "error": "RuntimeError"}
