from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.client import Client, ClientStatus
from app.models.client_framework_contract import FrameworkContractStatus
from app.services.client_portfolio_import import (
    ClientPortfolioImportError,
    _derived_manifest_warnings,
    _msa_status,
    build_client_portfolio_plan,
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

    nordea = [row for row in manifest["rows"] if row["client_key"] == "nordea-bank-abp"]
    assert len(nordea) == 2
    assert {row["category"] for row in nordea} == {"active", "relationship"}
    assert (
        next(row for row in nordea if row["category"] == "relationship")["scope_label"]
        == "Pentesty"
    )

    pko = next(
        row
        for row in manifest["rows"]
        if row["client_key"]
        == "powszechna-kasa-oszczednosci-bank-polski-spolka-akcyjna"
    )
    assert "PKO" in pko["aliases"]

    pekao = next(
        row
        for row in manifest["rows"]
        if row["client_key"] == "bank-polska-kasa-opieki-spolka-akcyjna"
    )
    assert {"Bank Pekao SA", "PEKAO S.A."}.issubset(pekao["aliases"])

    approved_matches = {
        row["client_key"]: row.get("approved_match_alias")
        for row in manifest["rows"]
        if row.get("approved_match_alias")
    }
    assert approved_matches == {
        "mleasing-spolka-z-ograniczona-odpowiedzialnoscia": "mLeasing",
        "ms-enter-prise-spolka-z-ograniczona-odpowiedzialnoscia": "MS Enter Price",
        "polska-agencja-zeglugi-powietrznej": (
            "PANSA - Polska Agencja Żeglugli Powietrznej"
        ),
    }


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


def test_manifest_rejects_untracked_approved_match_alias(tmp_path) -> None:
    manifest = load_client_portfolio_manifest()
    manifest["rows"][0]["approved_match_alias"] = "Untracked production name"
    invalid = tmp_path / "invalid-approved-match.json"
    invalid.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ClientPortfolioImportError, match="approved_match_alias"):
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
        warning["code"] for warning in warnings if warning["source_key"] == "active:ey"
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


@pytest.mark.asyncio
async def test_fresh_database_creates_kir_without_requiring_merge(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.client_portfolio_import._load_directory_clients",
        AsyncMock(return_value=([], {})),
    )

    plan = await build_client_portfolio_plan(
        SimpleNamespace(),
        manifest=load_client_portfolio_manifest(),
    )

    kir_group = next(
        group
        for group in plan["groups"]
        if group["client_key"] == "krajowa-izba-rozliczeniowa-spolka-akcyjna"
    )
    assert kir_group["action"] == "create"
    assert plan["blockers"] == []
    assert {"code": "kir_records_not_present_create_from_manifest"} in plan["warnings"]


@pytest.mark.asyncio
async def test_confirmed_manifest_aliases_resolve_exact_production_variants(
    monkeypatch,
) -> None:
    clients = [
        Client(
            id=23,
            name="mLeasing",
            status=ClientStatus.active,
            external_source="traffit",
            external_id="14",
        ),
        Client(
            id=61,
            name="MS Enter Price",
            status=ClientStatus.active,
            external_source="traffit",
            external_id="61",
        ),
        Client(
            id=153,
            name="PANSA - Polska Agencja Żeglugli Powietrznej",
            status=ClientStatus.active,
            external_source="traffit",
            external_id="160",
        ),
    ]
    monkeypatch.setattr(
        "app.services.client_portfolio_import._load_directory_clients",
        AsyncMock(return_value=(clients, {})),
    )

    plan = await build_client_portfolio_plan(
        SimpleNamespace(),
        manifest=load_client_portfolio_manifest(),
    )
    groups = {group["client_key"]: group for group in plan["groups"]}

    assert plan["blockers"] == []
    assert {
        key: (
            groups[key]["match_method"],
            groups[key]["target_client"]["id"],
        )
        for key in (
            "mleasing-spolka-z-ograniczona-odpowiedzialnoscia",
            "ms-enter-prise-spolka-z-ograniczona-odpowiedzialnoscia",
            "polska-agencja-zeglugi-powietrznej",
        )
    } == {
        "mleasing-spolka-z-ograniczona-odpowiedzialnoscia": (
            "approved_manifest_alias",
            23,
        ),
        "ms-enter-prise-spolka-z-ograniczona-odpowiedzialnoscia": (
            "approved_manifest_alias",
            61,
        ),
        "polska-agencja-zeglugi-powietrznej": (
            "approved_manifest_alias",
            153,
        ),
    }
