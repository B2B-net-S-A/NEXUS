from __future__ import annotations

import json
from datetime import date

import pytest

from app.models.client_framework_contract import FrameworkContractStatus
from app.services.client_portfolio_import import (
    ClientPortfolioImportError,
    _derived_manifest_warnings,
    _msa_status,
    load_client_portfolio_manifest,
    loose_client_name,
    normalize_client_name,
)


def test_checked_in_manifest_is_complete_and_preserves_scope_identity() -> None:
    manifest = load_client_portfolio_manifest()

    assert manifest["source"]["sha256"] == (
        "1d3957d0907036d19976f887b0167d80061f5ea4bc9cd8f8f8c265dc423a6658"
    )
    assert manifest["snapshot_date"] == "2026-07-30"
    assert len(manifest["rows"]) == 34
    assert {
        category: sum(row["category"] == category for row in manifest["rows"])
        for category in ("active", "relationship", "inactive")
    } == {"active": 30, "relationship": 3, "inactive": 1}

    nordea = [
        row
        for row in manifest["rows"]
        if row["client_key"] == "nordea-bank-abp"
    ]
    assert len(nordea) == 2
    assert {row["category"] for row in nordea} == {"active", "relationship"}
    assert next(row for row in nordea if row["category"] == "relationship")[
        "scope_label"
    ] == "Pentesty"


def test_manifest_captures_open_ended_missing_and_expired_active_cases() -> None:
    rows = load_client_portfolio_manifest()["rows"]

    bik = next(row for row in rows if row["display_name"] == "BIK")
    assert bik["effective_date"] == "2018-02-27"
    assert bik["expiry_date"] is None
    assert bik["expiry_is_open_ended"] is True

    cezz = next(row for row in rows if row["display_name"] == "Centrum e-Zdrowia")
    assert cezz["effective_date"] is None
    assert cezz["expiry_date"] is None
    assert cezz["expiry_is_open_ended"] is False

    ey = next(row for row in rows if row["display_name"] == "EY")
    assert ey["category"] == "active"
    assert ey["expiry_date"] == "2026-03-29"
    assert ey["workbook_status"] == "nieaktywny"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 7, 31), None, FrameworkContractStatus.draft),
        (date(2026, 7, 30), None, FrameworkContractStatus.active),
        (
            date(2024, 1, 1),
            date(2026, 7, 29),
            FrameworkContractStatus.expired,
        ),
    ],
)
def test_msa_status_is_derived_at_manifest_snapshot(
    start: date,
    end: date | None,
    expected: FrameworkContractStatus,
) -> None:
    assert _msa_status(start, end, date(2026, 7, 30)) == expected


def test_name_normalization_handles_legal_suffixes_and_polish_characters() -> None:
    assert normalize_client_name("Krajowa Izba Rozliczeń S.A.") == (
        "krajowa izba rozliczen s a"
    )
    assert loose_client_name("Krajowa Izba Rozliczeń S.A.") == (
        "krajowa izba rozliczen"
    )


def test_manifest_rejects_invalid_date_order(tmp_path) -> None:
    manifest = load_client_portfolio_manifest()
    manifest["rows"][0]["effective_date"] = "2028-01-02"
    manifest["rows"][0]["expiry_date"] = "2028-01-01"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ClientPortfolioImportError, match="ends before it starts"):
        load_client_portfolio_manifest(invalid)


def test_manifest_rejects_duplicate_source_key(tmp_path) -> None:
    manifest = load_client_portfolio_manifest()
    manifest["rows"][1]["source_key"] = manifest["rows"][0]["source_key"]
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ClientPortfolioImportError, match="duplicate source_key"):
        load_client_portfolio_manifest(invalid)


def test_manifest_rejects_wrong_sheet_and_open_ended_marker(tmp_path) -> None:
    manifest = load_client_portfolio_manifest()
    manifest["rows"][0]["sheet"] = "Relacyjni klienci"
    invalid_sheet = tmp_path / "invalid-sheet.json"
    invalid_sheet.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ClientPortfolioImportError, match="wrong sheet"):
        load_client_portfolio_manifest(invalid_sheet)

    manifest = load_client_portfolio_manifest()
    manifest["rows"][0]["expiry_is_open_ended"] = True
    invalid_marker = tmp_path / "invalid-marker.json"
    invalid_marker.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ClientPortfolioImportError, match="open-ended marker"):
        load_client_portfolio_manifest(invalid_marker)


def test_manifest_discrepancies_are_reported_but_sheet_category_wins() -> None:
    manifest = load_client_portfolio_manifest()
    warnings = _derived_manifest_warnings(manifest)

    ey_codes = {
        warning["code"]
        for warning in warnings
        if warning["source_key"] == "active:ey"
    }
    assert {
        "sheet_category_workbook_status_mismatch",
        "active_sheet_expired_msa",
    }.issubset(ey_codes)
    assert any(
        warning["code"] == "relationship_sheet_workbook_status_observed"
        and warning["source_key"] == "relationship:nordea-bank-abp:pentesty"
        for warning in warnings
    )
