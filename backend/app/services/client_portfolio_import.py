"""Plan, validate and apply the local NEXUS client-portfolio manifest.

This module intentionally has no dependency on the Traffit client/importer.
Source-owned ``Client.name``/``Client.status`` stay untouched for existing
clients; the directory uses local display names, scopes and framework
contracts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.client_directory import (
    ClientAlias,
    ClientImportRow,
    ClientImportRowStatus,
    ClientImportRun,
    ClientImportRunStatus,
    ClientPortfolioScope,
    PortfolioCategory,
)
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractSignedVia,
    FrameworkContractStatus,
)
from app.models.job import Job

logger = logging.getLogger(__name__)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "client_portfolio_2026_07_30.json"
)
SOURCE_SYSTEM = "client_excel"
ADVISORY_LOCK_KEY = 0x434C49454E5453  # ASCII-ish "CLIENTS", stable across deploys
POSTGRES_LOCK_TIMEOUT = "15s"
FUZZY_BLOCK_THRESHOLD = 0.88
SYSTEM_CLIENT_NAMES = {"__traffit_orphans"}
KIR_SURVIVOR_NAME_KEY = "kir"
KIR_DUPLICATE_NAME_KEY = "krajowa izba rozliczen s a"

# One-shot cutover contract for the reviewed 2026-07-30 workbook snapshot.
# Re-cutting the source requires updating these constants and the checked-in
# manifest together so an accidental row/category drift fails before planning.
_EXPECTED_CUTOVER_ROWS = 34
_EXPECTED_CUTOVER_CATEGORY_COUNTS = {
    "active": 30,
    "relationship": 3,
    "inactive": 1,
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_LEGAL_TOKENS = {
    "spolka",
    "akcyjna",
    "sp",
    "s",
    "a",
    "z",
    "ograniczona",
    "odpowiedzialnoscia",
    "oddzial",
    "w",
    "polsce",
}


class ClientPortfolioImportError(RuntimeError):
    """Raised for an invalid manifest or a blocked apply."""


def _database_dialect_name(db: AsyncSession) -> str | None:
    """Resolve the dialect through AsyncSession's supported bind API."""

    get_bind = getattr(db, "get_bind", None)
    bind = get_bind() if callable(get_bind) else getattr(db, "bind", None)
    dialect = getattr(bind, "dialect", None)
    return getattr(dialect, "name", None)


async def _acquire_import_advisory_lock(db: AsyncSession) -> bool:
    """Acquire the transaction lock with a bounded PostgreSQL wait.

    ``lock_timeout`` applies to both the advisory lock and every later table/
    row lock in this transaction. A stuck production writer therefore makes
    startup fail red and retry instead of leaving a deploy pending forever.
    """

    if _database_dialect_name(db) != "postgresql":
        return False
    await db.execute(
        text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": POSTGRES_LOCK_TIMEOUT},
    )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": ADVISORY_LOCK_KEY},
    )
    return True


async def _lock_import_write_surface(
    db: AsyncSession,
    *,
    kir_client_ids: tuple[int, ...] = (),
    include_candidates: bool = False,
) -> None:
    """Freeze complete matching inputs, plus KIR-only surfaces when needed.

    The planner classifies every visible client (including NEXUS-only rows), so
    ``clients`` and ``client_aliases`` need short table locks to prevent an
    insert from changing that complete population. Scope/MSA writes use unique
    source keys and row locks and therefore do not require global table locks.
    Candidate JSONB is unrelated unless the reviewed KIR merge is present.
    """

    tables = ["clients", "client_aliases"]
    if include_candidates:
        tables.append("candidates")
    await db.execute(
        text(
            f"LOCK TABLE {', '.join(tables)} "  # noqa: S608 - fixed identifiers
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    if kir_client_ids:
        # A foreign-key insert takes a KEY SHARE row lock on its referenced
        # client. Locking only the reviewed source/target closes that race
        # without taking FOR UPDATE on the complete client directory.
        await db.execute(
            select(Client.id)
            .where(Client.id.in_(kir_client_ids))
            .order_by(Client.id)
            .with_for_update()
        )


def normalize_client_name(value: str | None) -> str:
    """Case/diacritic/punctuation-insensitive exact-match key."""

    if not value:
        return ""
    value = value.replace("Ł", "L").replace("ł", "l")
    ascii_value = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return _NON_ALNUM.sub(" ", ascii_value.casefold()).strip()


def loose_client_name(value: str | None) -> str:
    """Suggestion-only key with common legal suffix words removed."""

    return " ".join(
        token
        for token in normalize_client_name(value).split()
        if token not in _LEGAL_TOKENS
    )


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def _append_plan_blocker(
    plan: dict[str, Any], blocker: dict[str, Any]
) -> dict[str, Any]:
    """Return a self-consistent plan after a post-plan concurrency blocker."""

    plan_core = {
        key: plan[key]
        for key in (
            "manifest_sha256",
            "snapshot_date",
            "groups",
            "nexus_only",
            "kir_merge",
            "duplicate_candidates",
            "blockers",
            "warnings",
        )
    }
    plan_core["blockers"] = [*plan_core["blockers"], blocker]
    return {
        **plan_core,
        "plan_sha256": _stable_hash(plan_core),
        "summary": {
            **plan["summary"],
            "blockers": len(plan_core["blockers"]),
        },
    }


def _normalized_manifest_sha256(manifest: dict[str, Any]) -> str:
    """Digest the reviewed JSON, independently from the source XLSX hash."""

    return _stable_hash(manifest)


def load_client_portfolio_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Load and strictly validate the checked-in normalized manifest."""

    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ClientPortfolioImportError("Unsupported client manifest schema")
    source = manifest.get("source") or {}
    source_sha = source.get("sha256")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise ClientPortfolioImportError("Manifest source.sha256 must be SHA-256")

    rows = manifest.get("rows")
    if not isinstance(rows, list) or len(rows) != _EXPECTED_CUTOVER_ROWS:
        raise ClientPortfolioImportError(
            "2026-07-30 cutover manifest must contain exactly "
            f"{_EXPECTED_CUTOVER_ROWS} rows"
        )
    expected_counts = _EXPECTED_CUTOVER_CATEGORY_COUNTS
    expected_sheets = {
        "active": "Aktywni Klienci",
        "relationship": "Relacyjni klienci",
        "inactive": "Niekatywni klienci",
    }
    try:
        date.fromisoformat(manifest["snapshot_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ClientPortfolioImportError(
            "Manifest snapshot_date must be an ISO date"
        ) from exc
    if source.get("sheets") != expected_sheets:
        raise ClientPortfolioImportError("Manifest sheet/category map is invalid")

    counts: dict[str, int] = defaultdict(int)
    source_keys: set[str] = set()
    source_rows: set[tuple[str, int]] = set()
    for row in rows:
        category = row.get("category")
        if category not in expected_counts:
            raise ClientPortfolioImportError(f"Unknown category: {category!r}")
        counts[category] += 1
        source_key = row.get("source_key")
        if not source_key or source_key in source_keys:
            raise ClientPortfolioImportError(
                f"Missing/duplicate source_key: {source_key!r}"
            )
        source_keys.add(source_key)
        if (
            not row.get("client_key")
            or not row.get("legal_name")
            or not row.get("display_name")
        ):
            raise ClientPortfolioImportError(
                f"Row {source_key} has no client_key/display_name/legal_name"
            )
        sheet_name = row.get("sheet")
        row_number = row.get("row_number")
        if sheet_name != expected_sheets[category]:
            raise ClientPortfolioImportError(
                f"Row {source_key} is assigned to the wrong sheet"
            )
        if not isinstance(row_number, int) or row_number < 2:
            raise ClientPortfolioImportError(f"Row {source_key} has invalid row_number")
        row_identity = (sheet_name, row_number)
        if row_identity in source_rows:
            raise ClientPortfolioImportError(
                f"Duplicate workbook row identity: {row_identity!r}"
            )
        source_rows.add(row_identity)
        aliases = row.get("aliases")
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            raise ClientPortfolioImportError(f"Row {source_key} has invalid aliases")
        approved_match_alias = row.get("approved_match_alias")
        if approved_match_alias is not None and (
            not isinstance(approved_match_alias, str)
            or not approved_match_alias.strip()
            or approved_match_alias not in aliases
        ):
            raise ClientPortfolioImportError(
                f"Row {source_key} has invalid approved_match_alias"
            )
        start = _parse_iso_date(row.get("effective_date"))
        end = _parse_iso_date(row.get("expiry_date"))
        if end is not None and start is None:
            raise ClientPortfolioImportError(
                f"Row {source_key} has end date without start date"
            )
        if start is not None and end is not None and end < start:
            raise ClientPortfolioImportError(f"Row {source_key} ends before it starts")
        expected_open_ended = start is not None and end is None
        if bool(row.get("expiry_is_open_ended")) != expected_open_ended:
            raise ClientPortfolioImportError(
                f"Row {source_key} has inconsistent open-ended marker"
            )
    if dict(counts) != expected_counts:
        raise ClientPortfolioImportError(
            f"Unexpected category counts: {dict(counts)!r}"
        )
    return manifest


async def get_client_portfolio_import_health(
    db: AsyncSession,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a count-only readiness view for the checked-in manifest.

    The deep-health endpoint deliberately exposes no client names or row
    payloads.  The applied run is selected by the exact source hash, while the
    counters make a partial/corrupt audit trail visible instead of reporting a
    misleading ``applied`` state.
    """

    manifest = manifest or load_client_portfolio_manifest()
    expected_source_sha256 = manifest["source"]["sha256"]
    expected_manifest_sha256 = _normalized_manifest_sha256(manifest)
    expected_category_rows = {
        category.value: sum(
            row["category"] == category.value for row in manifest["rows"]
        )
        for category in PortfolioCategory
    }
    expected_manifest_rows = len(manifest["rows"])
    expected_framework_contracts = sum(
        row.get("effective_date") is not None for row in manifest["rows"]
    )
    empty_counts = {
        "expected_manifest_rows": expected_manifest_rows,
        "expected_framework_contracts": expected_framework_contracts,
        "imported_manifest_rows": 0,
        "nexus_only_rows": 0,
        "audit_rows": 0,
        "unique_clients": 0,
        "portfolio_scopes": 0,
        "framework_contracts": 0,
        "live_portfolio_scopes": 0,
        "live_framework_contracts": 0,
        "category_rows": {category.value: 0 for category in PortfolioCategory},
    }

    run = await db.scalar(
        select(ClientImportRun)
        .where(
            ClientImportRun.source_system == SOURCE_SYSTEM,
            ClientImportRun.source_sha256 == expected_source_sha256,
            ClientImportRun.status == ClientImportRunStatus.applied,
        )
        .order_by(ClientImportRun.id.desc())
        .limit(1)
    )
    if run is None:
        return {
            "expected_source_sha256": expected_source_sha256,
            "expected_manifest_sha256": expected_manifest_sha256,
            "status": "not_applied",
            "run_id": None,
            "applied_at": None,
            "counts": empty_counts,
        }

    count_row = (
        await db.execute(
            select(
                func.count(ClientImportRow.id).label("audit_rows"),
                func.count(ClientImportRow.id)
                .filter(ClientImportRow.sheet_name != "NEXUS-only")
                .label("imported_manifest_rows"),
                func.count(ClientImportRow.id)
                .filter(ClientImportRow.sheet_name == "NEXUS-only")
                .label("nexus_only_rows"),
                func.count(func.distinct(ClientImportRow.matched_client_id)).label(
                    "unique_clients"
                ),
                func.count(func.distinct(ClientImportRow.portfolio_scope_id)).label(
                    "portfolio_scopes"
                ),
                func.count(func.distinct(ClientImportRow.framework_contract_id)).label(
                    "framework_contracts"
                ),
                *(
                    func.count(ClientImportRow.id)
                    .filter(
                        ClientImportRow.sheet_name != "NEXUS-only",
                        ClientImportRow.category == category,
                    )
                    .label(f"{category.value}_rows")
                    for category in PortfolioCategory
                ),
            ).where(ClientImportRow.import_run_id == run.id)
        )
    ).one()
    live_scope_rows = int(
        (
            await db.execute(
                select(func.count(ClientImportRow.id))
                .select_from(ClientImportRow)
                .join(
                    ClientPortfolioScope,
                    ClientPortfolioScope.id == ClientImportRow.portfolio_scope_id,
                )
                .where(
                    ClientImportRow.import_run_id == run.id,
                    ClientPortfolioScope.archived_at.is_(None),
                    ClientPortfolioScope.client_id == ClientImportRow.matched_client_id,
                    ClientPortfolioScope.category == ClientImportRow.category,
                    ClientPortfolioScope.source_system == SOURCE_SYSTEM,
                    ClientPortfolioScope.source_key == ClientImportRow.source_key,
                    ClientPortfolioScope.framework_contract_id.is_not_distinct_from(
                        ClientImportRow.framework_contract_id
                    ),
                )
            )
        ).scalar_one()
    )
    live_framework_contracts = int(
        (
            await db.execute(
                select(func.count(ClientImportRow.id))
                .select_from(ClientImportRow)
                .join(
                    ClientFrameworkContract,
                    ClientFrameworkContract.id == ClientImportRow.framework_contract_id,
                )
                .where(
                    ClientImportRow.import_run_id == run.id,
                    ClientImportRow.sheet_name != "NEXUS-only",
                    ClientFrameworkContract.client_id
                    == ClientImportRow.matched_client_id,
                    ClientFrameworkContract.source_system == SOURCE_SYSTEM,
                    ClientFrameworkContract.source_key == ClientImportRow.source_key,
                    ClientFrameworkContract.import_run_id == run.id,
                    ClientFrameworkContract.effective_date.is_not_distinct_from(
                        ClientImportRow.start_date
                    ),
                    ClientFrameworkContract.expiry_date.is_not_distinct_from(
                        ClientImportRow.end_date
                    ),
                )
            )
        ).scalar_one()
    )
    counts = {
        "expected_manifest_rows": expected_manifest_rows,
        "expected_framework_contracts": expected_framework_contracts,
        "imported_manifest_rows": int(count_row.imported_manifest_rows),
        "nexus_only_rows": int(count_row.nexus_only_rows),
        "audit_rows": int(count_row.audit_rows),
        "unique_clients": int(count_row.unique_clients),
        "portfolio_scopes": int(count_row.portfolio_scopes),
        "framework_contracts": int(count_row.framework_contracts),
        "live_portfolio_scopes": live_scope_rows,
        "live_framework_contracts": live_framework_contracts,
        "category_rows": {
            category.value: int(getattr(count_row, f"{category.value}_rows"))
            for category in PortfolioCategory
        },
    }
    applied_manifest_sha256 = (run.summary or {}).get("normalized_manifest_sha256")
    is_consistent = (
        run.applied_at is not None
        and applied_manifest_sha256 == expected_manifest_sha256
        and counts["imported_manifest_rows"] == expected_manifest_rows
        and counts["category_rows"] == expected_category_rows
        and counts["portfolio_scopes"] == counts["audit_rows"]
        and counts["live_portfolio_scopes"] == counts["audit_rows"]
        and counts["framework_contracts"] == expected_framework_contracts
        and counts["live_framework_contracts"] == expected_framework_contracts
    )
    return {
        "expected_source_sha256": expected_source_sha256,
        "expected_manifest_sha256": expected_manifest_sha256,
        "status": "applied" if is_consistent else "inconsistent",
        "run_id": run.id,
        "applied_at": _iso_datetime(run.applied_at),
        "counts": counts,
    }


def _derived_manifest_warnings(
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Report category/status/date discrepancies without changing precedence."""

    snapshot = date.fromisoformat(manifest["snapshot_date"])
    warnings: list[dict[str, Any]] = []
    for row in manifest["rows"]:
        workbook_status = normalize_client_name(row.get("workbook_status"))
        category = row["category"]
        expected_workbook_status = {
            "active": "aktywny",
            "inactive": "nieaktywny",
        }.get(category)
        if expected_workbook_status and workbook_status != expected_workbook_status:
            warnings.append(
                {
                    "code": "sheet_category_workbook_status_mismatch",
                    "source_key": row["source_key"],
                    "category": category,
                    "workbook_status": row.get("workbook_status"),
                    "resolution": "sheet_category_wins",
                }
            )
        elif category == "relationship" and workbook_status:
            warnings.append(
                {
                    "code": "relationship_sheet_workbook_status_observed",
                    "source_key": row["source_key"],
                    "category": category,
                    "workbook_status": row.get("workbook_status"),
                    "resolution": "sheet_category_wins",
                }
            )

        start = _parse_iso_date(row.get("effective_date"))
        end = _parse_iso_date(row.get("expiry_date"))
        if start is None:
            continue
        derived_status = _msa_status(start, end, snapshot).value
        if category == "active" and derived_status == "expired":
            warnings.append(
                {
                    "code": "active_sheet_expired_msa",
                    "source_key": row["source_key"],
                    "derived_msa_status": derived_status,
                    "resolution": "sheet_category_wins",
                }
            )
        if workbook_status == "aktywny" and derived_status == "expired":
            warnings.append(
                {
                    "code": "workbook_status_expired_msa_mismatch",
                    "source_key": row["source_key"],
                    "workbook_status": row.get("workbook_status"),
                    "derived_msa_status": derived_status,
                }
            )
    return warnings


def _parse_iso_date(value: str | None) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ClientPortfolioImportError(f"Invalid ISO date: {value!r}") from exc


def _client_labels(client: Client, aliases: Iterable[str] = ()) -> set[str]:
    return {
        normalized
        for normalized in (
            normalize_client_name(client.name),
            normalize_client_name(client.display_name),
            normalize_client_name(client.legal_name),
            *(normalize_client_name(alias) for alias in aliases),
        )
        if normalized
    }


def _manifest_group_labels(rows: list[dict[str, Any]]) -> set[str]:
    labels: set[str] = set()
    for row in rows:
        for value in (
            row.get("legal_name"),
            row.get("display_name"),
            *(row.get("aliases") or []),
        ):
            normalized = normalize_client_name(value)
            if normalized:
                labels.add(normalized)
    return labels


def _public_client(client: Client) -> dict[str, Any]:
    return {
        "id": client.id,
        "name": client.name,
        "display_name": client.display_name,
        "legal_name": client.legal_name,
        "nip": client.nip,
        "regon": client.regon,
        "external_source": client.external_source,
        "external_id": client.external_id,
        "updated_at": client.updated_at.isoformat() if client.updated_at else None,
    }


def _is_business_client(client: Client) -> bool:
    return (
        not client.hidden
        and client.archived_at is None
        and client.merged_into_client_id is None
        and normalize_client_name(client.name)
        not in {normalize_client_name(name) for name in SYSTEM_CLIENT_NAMES}
    )


async def _load_directory_clients(
    db: AsyncSession,
) -> tuple[list[Client], dict[int, list[str]]]:
    clients = (
        (
            await db.execute(
                select(Client).where(
                    Client.hidden.is_(False),
                    Client.archived_at.is_(None),
                    Client.merged_into_client_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    aliases_by_client: dict[int, list[str]] = defaultdict(list)
    for client_id, alias in (
        await db.execute(
            select(ClientAlias.client_id, ClientAlias.alias).where(
                ClientAlias.archived_at.is_(None)
            )
        )
    ).all():
        aliases_by_client[int(client_id)].append(alias)
    return [
        client for client in clients if _is_business_client(client)
    ], aliases_by_client


def _duplicate_candidates(
    clients: list[Client], aliases_by_client: dict[int, list[str]]
) -> list[dict[str, Any]]:
    """Return report-only likely duplicates; never use suggestions to merge.

    Identifier equality is stronger than a name/alias collision, which in turn
    is stronger than a fuzzy suggestion. ``setdefault`` preserves that
    deterministic precedence when one pair matches more than one signal.
    """

    results: dict[tuple[int, int], dict[str, Any]] = {}
    preferred_names = {
        client.id: client.display_name or client.legal_name or client.name
        for client in clients
    }

    def record_group(
        grouped_ids: dict[str, set[int]],
        *,
        reason: str,
        evidence_key: str,
    ) -> None:
        for evidence, client_ids in sorted(grouped_ids.items()):
            ordered_ids = sorted(client_ids)
            for index, left_id in enumerate(ordered_ids):
                for right_id in ordered_ids[index + 1 :]:
                    pair = (left_id, right_id)
                    results.setdefault(
                        pair,
                        {
                            "client_ids": list(pair),
                            "names": [
                                preferred_names[left_id],
                                preferred_names[right_id],
                            ],
                            "reason": reason,
                            "score": 1.0,
                            evidence_key: evidence,
                        },
                    )

    nip_groups: dict[str, set[int]] = defaultdict(set)
    regon_groups: dict[str, set[int]] = defaultdict(set)
    exact_label_groups: dict[str, set[int]] = defaultdict(set)
    loose_label_groups: dict[str, set[int]] = defaultdict(set)
    normalized_labels: dict[int, set[str]] = {}
    loose_labels: dict[int, set[str]] = {}
    for client in clients:
        nip = re.sub(r"\W+", "", str(getattr(client, "nip", None) or "")).casefold()
        regon = re.sub(r"\W+", "", str(getattr(client, "regon", None) or "")).casefold()
        if nip:
            nip_groups[nip].add(client.id)
        if regon:
            regon_groups[regon].add(client.id)

        normalized_labels[client.id] = _client_labels(
            client, aliases_by_client.get(client.id, [])
        )
        loose_labels[client.id] = {
            loose
            for label in normalized_labels[client.id]
            if len(loose := loose_client_name(label)) >= 3
        }
        for label in normalized_labels[client.id]:
            exact_label_groups[label].add(client.id)
        for label in loose_labels[client.id]:
            loose_label_groups[label].add(client.id)

    record_group(nip_groups, reason="same_nip", evidence_key="nip")
    record_group(regon_groups, reason="same_regon", evidence_key="regon")
    record_group(
        exact_label_groups,
        reason="same_normalized_name_or_alias",
        evidence_key="normalized_label",
    )
    record_group(
        loose_label_groups,
        reason="same_loose_legal_name_or_alias",
        evidence_key="normalized_label",
    )

    # Small portfolio: O(n²) suggestion pass is deterministic and cheap.
    ordered_clients = sorted(clients, key=lambda client: client.id)
    for index, left in enumerate(ordered_clients):
        if not loose_labels[left.id]:
            continue
        for right in ordered_clients[index + 1 :]:
            if not loose_labels[right.id]:
                continue
            score = max(
                SequenceMatcher(None, left_label, right_label).ratio()
                for left_label in loose_labels[left.id]
                for right_label in loose_labels[right.id]
            )
            if score < 0.9:
                continue
            pair = (left.id, right.id)
            results.setdefault(
                pair,
                {
                    "client_ids": list(pair),
                    "names": [
                        preferred_names[pair[0]],
                        preferred_names[pair[1]],
                    ],
                    "reason": "fuzzy_name_similarity",
                    "score": round(score, 4),
                },
            )
    return sorted(results.values(), key=lambda item: item["client_ids"])


def _validate_identifier(identifier: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(identifier):
        raise ClientPortfolioImportError("Unsafe identifier from database catalog")
    return identifier


async def _direct_client_fk_specs(db: AsyncSession) -> list[dict[str, Any]]:
    """Return direct client FK columns and their row-addressable primary keys."""

    if _database_dialect_name(db) != "postgresql":
        return []
    fk_rows = (
        await db.execute(
            text(
                """
                SELECT tc.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.constraint_schema = kcu.constraint_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.constraint_schema = tc.constraint_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND ccu.table_schema = current_schema()
                  AND ccu.table_name = 'clients'
                  AND ccu.column_name = 'id'
                  AND tc.table_schema = current_schema()
                ORDER BY tc.table_name, kcu.column_name
                """
            )
        )
    ).all()
    specs: list[dict[str, Any]] = []
    for raw_table_name, raw_column_name in fk_rows:
        table_name = _validate_identifier(str(raw_table_name))
        column_name = _validate_identifier(str(raw_column_name))
        primary_key_columns = [
            _validate_identifier(str(column_name))
            for column_name in (
                await db.execute(
                    text(
                        """
                        SELECT kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.constraint_schema = kcu.constraint_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema = current_schema()
                          AND tc.table_name = :table_name
                        ORDER BY kcu.ordinal_position
                        """
                    ),
                    {"table_name": table_name},
                )
            )
            .scalars()
            .all()
        ]
        specs.append(
            {
                "table": table_name,
                "column": column_name,
                "primary_key_columns": primary_key_columns,
            }
        )
    return specs


async def _direct_client_fk_counts(
    db: AsyncSession, source_client_id: int
) -> list[dict[str, Any]]:
    """Inventory every direct FK to clients using the Postgres catalog."""

    impact: list[dict[str, Any]] = []
    for spec in await _direct_client_fk_specs(db):
        table_name = spec["table"]
        column_name = spec["column"]
        count = await db.scalar(
            text(
                f'SELECT count(*) FROM "{table_name}" '
                f'WHERE "{column_name}" = :source_id'
            ),
            {"source_id": source_client_id},
        )
        if count:
            impact.append(
                {
                    "table": table_name,
                    "column": column_name,
                    "rows": int(count),
                    "primary_key_columns": spec["primary_key_columns"],
                    "rollback_supported": bool(spec["primary_key_columns"]),
                }
            )
    return impact


async def _candidate_excluded_client_count(db: AsyncSession, client_id: int) -> int:
    """Count non-FK JSON references used by candidate exclusion preferences."""

    dialect_name = _database_dialect_name(db)
    if dialect_name == "postgresql":
        count = await db.scalar(
            text(
                """
                SELECT count(*)
                FROM candidates
                WHERE preferences @> CAST(:numeric_payload AS jsonb)
                   OR preferences @> CAST(:string_payload AS jsonb)
                """
            ),
            {
                "numeric_payload": json.dumps({"excluded_clients": [client_id]}),
                "string_payload": json.dumps({"excluded_clients": [str(client_id)]}),
            },
        )
        return int(count or 0)
    if dialect_name != "sqlite":
        raise ClientPortfolioImportError(
            "Candidate JSON dependency inventory requires PostgreSQL"
        )

    # SQLite is used only by focused tests and has no PostgreSQL JSONB @>.
    count = 0
    rows = (
        await db.execute(
            select(Candidate.preferences).where(Candidate.preferences.is_not(None))
        )
    ).scalars()
    for preferences in rows:
        raw = (preferences or {}).get("excluded_clients")
        if isinstance(raw, list) and any(str(value) == str(client_id) for value in raw):
            count += 1
    return count


async def build_client_portfolio_plan(
    db: AsyncSession, *, manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a deterministic, read-only production plan."""

    manifest = manifest or load_client_portfolio_manifest()
    clients, aliases_by_client = await _load_directory_clients(db)
    client_by_id = {client.id: client for client in clients}
    alias_map: dict[str, set[int]] = defaultdict(set)
    exact_name_map: dict[str, set[int]] = defaultdict(set)
    nip_map: dict[str, set[int]] = defaultdict(set)
    regon_map: dict[str, set[int]] = defaultdict(set)
    for client in clients:
        for alias in aliases_by_client.get(client.id, []):
            normalized_alias = normalize_client_name(alias)
            if normalized_alias:
                alias_map[normalized_alias].add(client.id)
        for label in _client_labels(client):
            exact_name_map[label].add(client.id)
        if client.nip:
            nip_map[re.sub(r"\W+", "", client.nip).casefold()].add(client.id)
        if client.regon:
            regon_map[re.sub(r"\W+", "", client.regon).casefold()].add(client.id)

    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in manifest["rows"]:
        grouped_rows[row["client_key"]].append(row)

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = [
        *(dict(item) for item in manifest.get("known_anomalies") or []),
        *_derived_manifest_warnings(manifest),
    ]
    groups: list[dict[str, Any]] = []
    matched_client_ids: set[int] = set()

    for client_key, rows in grouped_rows.items():
        labels = _manifest_group_labels(rows)
        # Match precedence is intentional. A one-shot manifest alias records
        # an explicit business approval for this cutover and therefore wins
        # over every inferred signal. It must still resolve to exactly one
        # visible client or the whole apply remains blocked.
        approved_manifest_labels = {
            normalized
            for row in rows
            if (normalized := normalize_client_name(row.get("approved_match_alias")))
        }
        candidate_ids: set[int] = {
            client_id
            for label in approved_manifest_labels
            for client_id in exact_name_map.get(label, set())
        }
        match_method = "approved_manifest_alias" if candidate_ids else None
        if approved_manifest_labels and not candidate_ids:
            blockers.append(
                {
                    "code": "approved_manifest_alias_not_found",
                    "client_key": client_key,
                    "approved_aliases": sorted(approved_manifest_labels),
                }
            )
            groups.append(
                {
                    "client_key": client_key,
                    "action": "blocked",
                    "rows": rows,
                }
            )
            continue

        # A reviewed ClientAlias is the strongest persistent local assertion
        # and must not be diluted by a colliding historical source/display
        # name. NIP/REGON are optional in the manifest, but supported before
        # exact normalized names.
        if not candidate_ids:
            candidate_ids = {
                client_id
                for label in labels
                for client_id in alias_map.get(label, set())
            }
            match_method = "approved_alias" if candidate_ids else None
        if not candidate_ids:
            identifier_ids: set[int] = set()
            for row in rows:
                nip = re.sub(r"\W+", "", str(row.get("nip") or "")).casefold()
                regon = re.sub(r"\W+", "", str(row.get("regon") or "")).casefold()
                if nip:
                    identifier_ids.update(nip_map.get(nip, set()))
                if regon:
                    identifier_ids.update(regon_map.get(regon, set()))
            candidate_ids = identifier_ids
            match_method = "nip_regon" if candidate_ids else None
        if not candidate_ids:
            candidate_ids = {
                client_id
                for label in labels
                for client_id in exact_name_map.get(label, set())
            }
            match_method = "exact_normalized_name" if candidate_ids else None

        # Explicitly approved survivor for the known KIR duplicate.
        if any(row["display_name"] == "Krajowa Izba Rozliczeń" for row in rows):
            kir_ids = {
                client.id
                for client in clients
                if normalize_client_name(client.name) == KIR_SURVIVOR_NAME_KEY
            }
            candidate_ids = kir_ids
            if candidate_ids:
                match_method = "approved_kir_survivor"
            else:
                match_method = None

        if len(candidate_ids) == 1:
            target_id = next(iter(candidate_ids))
            matched_client_ids.add(target_id)
            groups.append(
                {
                    "client_key": client_key,
                    "action": "match",
                    "match_method": match_method,
                    "target_client": _public_client(client_by_id[target_id]),
                    "rows": rows,
                }
            )
            continue
        if len(candidate_ids) > 1:
            blockers.append(
                {
                    "code": "ambiguous_exact_match",
                    "client_key": client_key,
                    "match_method": match_method,
                    "candidate_clients": [
                        _public_client(client_by_id[cid])
                        for cid in sorted(candidate_ids)
                    ],
                }
            )
            groups.append(
                {
                    "client_key": client_key,
                    "action": "blocked",
                    "rows": rows,
                }
            )
            continue

        fuzzy: list[dict[str, Any]] = []
        for client in clients:
            score = max(
                (
                    SequenceMatcher(None, source, target).ratio()
                    for source in labels
                    for target in _client_labels(
                        client, aliases_by_client.get(client.id, [])
                    )
                ),
                default=0.0,
            )
            if score >= FUZZY_BLOCK_THRESHOLD:
                fuzzy.append(
                    {
                        **_public_client(client),
                        "score": round(score, 4),
                    }
                )
        if fuzzy:
            blockers.append(
                {
                    "code": "plausible_duplicate_requires_review",
                    "client_key": client_key,
                    "candidate_clients": sorted(
                        fuzzy, key=lambda item: (-item["score"], item["id"])
                    ),
                }
            )
            groups.append(
                {
                    "client_key": client_key,
                    "action": "blocked",
                    "rows": rows,
                }
            )
            continue
        groups.append(
            {
                "client_key": client_key,
                "action": "create",
                "rows": rows,
            }
        )

    # Known KIR merge preview. Other duplicate candidates remain report-only.
    kir_targets = [
        client
        for client in clients
        if normalize_client_name(client.name) == KIR_SURVIVOR_NAME_KEY
    ]
    kir_losers = [
        client
        for client in clients
        if normalize_client_name(client.name) == KIR_DUPLICATE_NAME_KEY
    ]
    kir_merge: dict[str, Any] | None = None
    if len(kir_targets) == 1 and len(kir_losers) == 1:
        target, source = kir_targets[0], kir_losers[0]
        source_identity = (source.external_source, source.external_id)
        target_identity = (target.external_source, target.external_id)
        if (
            source.external_id
            and target.external_id
            and source_identity != target_identity
        ):
            blockers.append(
                {
                    "code": "kir_external_identity_conflict",
                    "source": _public_client(source),
                    "target": _public_client(target),
                }
            )
        fk_impact = await _direct_client_fk_counts(db, source.id)
        jsonb_candidates = await _candidate_excluded_client_count(db, source.id)
        kir_merge = {
            "source": _public_client(source),
            "target": _public_client(target),
            "fk_impact": fk_impact,
            "jsonb_candidates": jsonb_candidates,
        }
        unsupported_impact = [
            item for item in fk_impact if not item.get("rollback_supported")
        ]
        if unsupported_impact:
            blockers.append(
                {
                    "code": "kir_dependency_not_reversible",
                    "source": _public_client(source),
                    "target": _public_client(target),
                    "fk_impact": unsupported_impact,
                }
            )
    elif not kir_targets and not kir_losers:
        # Fresh/DR databases legitimately have no pre-existing KIR records.
        # The manifest group will create the canonical client without a merge.
        warnings.append({"code": "kir_records_not_present_create_from_manifest"})
    elif len(kir_targets) != 1:
        blockers.append(
            {
                "code": "kir_survivor_not_unique",
                "candidate_clients": [_public_client(client) for client in kir_targets],
            }
        )
    elif len(kir_losers) > 1:
        blockers.append(
            {
                "code": "kir_duplicate_not_unique",
                "candidate_clients": [_public_client(client) for client in kir_losers],
            }
        )
    else:
        warnings.append({"code": "kir_duplicate_not_present"})

    nexus_only = [
        _public_client(client)
        for client in clients
        if client.id not in matched_client_ids
        and not (
            kir_merge
            and client.id in {kir_merge["source"]["id"], kir_merge["target"]["id"]}
        )
    ]

    duplicate_report = _duplicate_candidates(clients, aliases_by_client)
    if kir_merge:
        known_kir_pair = {
            kir_merge["source"]["id"],
            kir_merge["target"]["id"],
        }
        duplicate_report = [
            candidate
            for candidate in duplicate_report
            if set(candidate["client_ids"]) != known_kir_pair
        ]
    for candidate in duplicate_report:
        candidate_clients = [
            client_by_id[client_id] for client_id in candidate["client_ids"]
        ]
        candidate["clients"] = [
            {
                **_public_client(client),
                "aliases": sorted(aliases_by_client.get(client.id, [])),
            }
            for client in candidate_clients
        ]
        candidate["dependency_counts"] = {
            str(client.id): await _direct_client_fk_counts(db, client.id)
            for client in candidate_clients
        }
        candidate["jsonb_dependency_counts"] = {
            str(client.id): await _candidate_excluded_client_count(db, client.id)
            for client in candidate_clients
        }
    plan_core = {
        "manifest_sha256": manifest["source"]["sha256"],
        "snapshot_date": manifest["snapshot_date"],
        "groups": groups,
        "nexus_only": nexus_only,
        "kir_merge": kir_merge,
        "duplicate_candidates": duplicate_report,
        "blockers": blockers,
        "warnings": warnings,
    }
    return {
        **plan_core,
        "plan_sha256": _stable_hash(plan_core),
        "summary": {
            "manifest_rows": len(manifest["rows"]),
            "matched_groups": sum(group["action"] == "match" for group in groups),
            "created_groups": sum(group["action"] == "create" for group in groups),
            "blocked_groups": sum(group["action"] == "blocked" for group in groups),
            "nexus_only_clients": len(nexus_only),
            "duplicate_candidates": len(duplicate_report),
            "blockers": len(blockers),
            "warnings": len(warnings),
        },
    }


def _msa_status(
    start: date, end: date | None, snapshot: date
) -> FrameworkContractStatus:
    if end is not None and end < snapshot:
        return FrameworkContractStatus.expired
    if start > snapshot:
        return FrameworkContractStatus.draft
    return FrameworkContractStatus.active


def _application_date() -> date:
    """Single, UTC-based business date used for all statuses in one apply."""

    return datetime.now(timezone.utc).date()


def _msa_name(display_name: str, row: dict[str, Any]) -> str:
    start = row.get("effective_date") or "?"
    end = row.get("expiry_date") or "bezterminowa"
    scope = row.get("scope_label")
    prefix = f"{display_name} — {scope}" if scope else display_name
    return f"{prefix} — MSA {start}–{end}"[:255]


async def _upsert_alias(
    db: AsyncSession,
    *,
    client_id: int,
    alias: str,
    import_run_id: int,
    source_key: str | None = None,
) -> dict[str, Any] | None:
    """Create/revive one import-owned alias and return its rollback audit.

    An already-active alias is preserved verbatim, including manual
    provenance. Archived aliases may only be revived when they are owned by
    this importer; otherwise the uniqueness collision is a fail-closed review
    blocker rather than an implicit ownership transfer.
    """

    normalized = normalize_client_name(alias)
    if not normalized:
        return None
    existing = await db.scalar(
        select(ClientAlias)
        .where(
            ClientAlias.client_id == client_id,
            ClientAlias.normalized_alias == normalized,
        )
        .with_for_update()
    )
    if existing is None:
        created = ClientAlias(
            client_id=client_id,
            alias=alias.strip(),
            normalized_alias=normalized,
            source_system=SOURCE_SYSTEM,
            source_key=source_key,
            import_run_id=import_run_id,
        )
        db.add(created)
        await db.flush()
        return {
            "alias_id": created.id,
            "before": None,
            "after": _alias_state(created),
        }
    if existing.archived_at is None:
        return None
    if existing.source_system != SOURCE_SYSTEM:
        raise ClientPortfolioImportError(
            f"Archived alias belongs to another source: {existing.id}"
        )
    before = _alias_state(existing)
    existing.alias = alias.strip()
    existing.source_key = source_key
    existing.import_run_id = import_run_id
    existing.archived_at = None
    return {
        "alias_id": existing.id,
        "before": before,
        "after": _alias_state(existing),
    }


async def _replace_candidate_excluded_client(
    db: AsyncSession, *, source_id: int, target_id: int
) -> list[dict[str, Any]]:
    """Replace JSON client references and retain exact row-level rollback data."""

    dialect_name = _database_dialect_name(db)
    query = (
        select(Candidate)
        .where(Candidate.preferences.is_not(None))
        .order_by(Candidate.id)
        .with_for_update()
    )
    params: dict[str, Any] = {}
    if dialect_name == "postgresql":
        query = query.where(
            text(
                "(preferences @> CAST(:numeric_payload AS jsonb) "
                "OR preferences @> CAST(:string_payload AS jsonb))"
            )
        )
        params = {
            "numeric_payload": json.dumps({"excluded_clients": [source_id]}),
            "string_payload": json.dumps({"excluded_clients": [str(source_id)]}),
        }
    elif dialect_name != "sqlite":
        raise ClientPortfolioImportError(
            "Candidate JSON dependency merge requires PostgreSQL"
        )
    candidates = (await db.execute(query, params)).scalars().all()
    ledger: list[dict[str, Any]] = []
    for candidate in candidates:
        preferences = dict(candidate.preferences or {})
        raw = preferences.get("excluded_clients")
        if not isinstance(raw, list):
            continue
        replacement: list[Any] = []
        seen: set[str] = set()
        touched = False
        for value in raw:
            comparable = str(value)
            if comparable == str(source_id):
                replacement_value: Any = target_id
                touched = True
            else:
                replacement_value = value
            identity = json.dumps(
                replacement_value,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if identity not in seen:
                replacement.append(replacement_value)
                seen.add(identity)
        if touched:
            before = list(raw)
            preferences["excluded_clients"] = replacement
            candidate.preferences = preferences
            ledger.append(
                {
                    "candidate_id": candidate.id,
                    "before_excluded_clients": before,
                    "after_excluded_clients": list(preferences["excluded_clients"]),
                }
            )
    return ledger


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _client_state(client: Client) -> dict[str, Any]:
    """Serializable fields owned by the portfolio import/merge.

    ``updated_at`` is deliberately not part of the state.  SQLAlchemy/Postgres
    updates it as a side effect of restoring the business fields, so comparing
    it would make a successful rollback look like a concurrent edit.
    """

    return {
        "id": client.id,
        "name": client.name,
        "display_name": client.display_name,
        "legal_name": client.legal_name,
        "status": client.status.value,
        "hidden": client.hidden,
        "archived_at": _iso_datetime(client.archived_at),
        "archived_by": client.archived_by,
        "merged_into_client_id": client.merged_into_client_id,
        "external_source": client.external_source,
        "external_id": client.external_id,
    }


def _scope_state(scope: ClientPortfolioScope) -> dict[str, Any]:
    return {
        "id": scope.id,
        "client_id": scope.client_id,
        "framework_contract_id": scope.framework_contract_id,
        "category": scope.category.value,
        "label": scope.label,
        "source_system": scope.source_system,
        "source_key": scope.source_key,
        "archived_at": _iso_datetime(scope.archived_at),
    }


def _alias_state(alias: ClientAlias) -> dict[str, Any]:
    return {
        "id": alias.id,
        "client_id": alias.client_id,
        "alias": alias.alias,
        "normalized_alias": alias.normalized_alias,
        "source_system": alias.source_system,
        "source_key": alias.source_key,
        "import_run_id": alias.import_run_id,
        "archived_at": _iso_datetime(alias.archived_at),
    }


def _msa_state(msa: ClientFrameworkContract) -> dict[str, Any]:
    return {
        "id": msa.id,
        "client_id": msa.client_id,
        "name": msa.name,
        "status": msa.status.value,
        "effective_date": (
            msa.effective_date.isoformat() if msa.effective_date else None
        ),
        "expiry_date": msa.expiry_date.isoformat() if msa.expiry_date else None,
        "signed_via": msa.signed_via.value,
        "source_system": msa.source_system,
        "source_key": msa.source_key,
        "import_run_id": msa.import_run_id,
        "notes": msa.notes,
    }


def _parse_optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _restore_client_state(client: Client, state: dict[str, Any]) -> None:
    client.name = state["name"]
    client.display_name = state["display_name"]
    client.legal_name = state["legal_name"]
    client.status = ClientStatus(state["status"])
    client.hidden = bool(state["hidden"])
    client.archived_at = _parse_optional_datetime(state["archived_at"])
    client.archived_by = state["archived_by"]
    client.merged_into_client_id = state["merged_into_client_id"]
    client.external_source = state["external_source"]
    client.external_id = state["external_id"]


def _restore_scope_state(scope: ClientPortfolioScope, state: dict[str, Any]) -> None:
    scope.client_id = state["client_id"]
    scope.framework_contract_id = state["framework_contract_id"]
    scope.category = PortfolioCategory(state["category"])
    scope.label = state["label"]
    scope.source_system = state["source_system"]
    scope.source_key = state["source_key"]
    scope.archived_at = _parse_optional_datetime(state["archived_at"])


def _restore_alias_state(alias: ClientAlias, state: dict[str, Any]) -> None:
    alias.client_id = state["client_id"]
    alias.alias = state["alias"]
    alias.normalized_alias = state["normalized_alias"]
    alias.source_system = state["source_system"]
    alias.source_key = state["source_key"]
    alias.import_run_id = state["import_run_id"]
    alias.archived_at = _parse_optional_datetime(state["archived_at"])


def _restore_msa_state(msa: ClientFrameworkContract, state: dict[str, Any]) -> None:
    msa.client_id = state["client_id"]
    msa.name = state["name"]
    msa.status = FrameworkContractStatus(state["status"])
    msa.effective_date = _parse_iso_date(state["effective_date"])
    msa.expiry_date = _parse_iso_date(state["expiry_date"])
    msa.signed_via = FrameworkContractSignedVia(state["signed_via"])
    msa.source_system = state["source_system"]
    msa.source_key = state["source_key"]
    msa.import_run_id = state["import_run_id"]
    msa.notes = state["notes"]


def _json_ledger_value(value: Any) -> Any:
    """Convert a catalog-selected primary-key value to JSON-safe audit data."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def _merge_kir(
    db: AsyncSession,
    *,
    source_id: int,
    target_id: int,
    expected_source_updated_at: str | None,
    expected_target_updated_at: str | None,
    archived_by: int | None,
    import_run_id: int,
) -> dict[str, Any]:
    """Repoint direct FKs, preserve aliases and archive the loser.

    Any uniqueness collision raises and rolls back the enclosing savepoint.
    No child rows or client rows are deleted.
    """

    if _database_dialect_name(db) != "postgresql":
        raise ClientPortfolioImportError("KIR merge requires PostgreSQL")

    locked = (
        (
            await db.execute(
                select(Client)
                .where(Client.id.in_((source_id, target_id)))
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    by_id = {client.id: client for client in locked}
    if source_id == target_id:
        raise ClientPortfolioImportError("KIR source and survivor must be distinct")
    if source_id not in by_id or target_id not in by_id:
        raise ClientPortfolioImportError("KIR source/target disappeared")
    source, target = by_id[source_id], by_id[target_id]
    if target.merged_into_client_id is not None:
        raise ClientPortfolioImportError(
            "KIR merge target is itself merged; resolve the chain first"
        )
    if source.merged_into_client_id not in (None, target_id):
        raise ClientPortfolioImportError(
            "KIR duplicate is already merged into a different client"
        )
    if normalize_client_name(source.name) != KIR_DUPLICATE_NAME_KEY:
        raise ClientPortfolioImportError(
            "KIR merge source is not the approved duplicate record"
        )
    if normalize_client_name(target.name) != KIR_SURVIVOR_NAME_KEY:
        raise ClientPortfolioImportError(
            "KIR merge target is not the approved survivor record"
        )
    source_before = _client_state(source)
    target_before = _client_state(target)
    actual_source_updated_at = (
        source.updated_at.isoformat() if source.updated_at else None
    )
    actual_target_updated_at = (
        target.updated_at.isoformat() if target.updated_at else None
    )
    if actual_source_updated_at != expected_source_updated_at:
        raise ClientPortfolioImportError(
            f"KIR duplicate changed after plan: {source.id}"
        )
    if actual_target_updated_at != expected_target_updated_at:
        raise ClientPortfolioImportError(
            f"KIR survivor changed after plan: {target.id}"
        )
    target_is_live = (
        not target.hidden
        and target.archived_at is None
        and target.merged_into_client_id is None
    )
    if (
        source.merged_into_client_id == target_id
        and source.hidden
        and source.archived_at is not None
        and target_is_live
    ):
        return {
            "already_merged": True,
            "moved_references": [],
            "reference_ledger": [],
            "jsonb_candidates": 0,
            "candidate_preferences_ledger": [],
            "alias_audits": [],
        }
    if (
        source.hidden
        or source.archived_at is not None
        or source.merged_into_client_id is not None
        or not target_is_live
    ):
        raise ClientPortfolioImportError(
            "KIR source and survivor must both be live, unarchived records"
        )
    if (
        source.external_id
        and target.external_id
        and (
            source.external_source,
            source.external_id,
        )
        != (target.external_source, target.external_id)
    ):
        raise ClientPortfolioImportError("KIR external identities conflict")

    job_ids = list(
        (await db.execute(select(Job.id).where(Job.client_id == source_id))).scalars()
    )
    moved: list[dict[str, Any]] = []
    reference_ledger: list[dict[str, Any]] = []
    for spec in await _direct_client_fk_specs(db):
        table_name = spec["table"]
        column_name = spec["column"]
        primary_key_columns = spec["primary_key_columns"]
        if not primary_key_columns:
            count = await db.scalar(
                text(
                    f'SELECT count(*) FROM "{table_name}" '
                    f'WHERE "{column_name}" = :source_id'
                ),
                {"source_id": source_id},
            )
            if count:
                raise ClientPortfolioImportError(
                    "KIR dependency has no row-addressable primary key: "
                    f"{table_name}.{column_name}"
                )
            continue

        select_columns = ", ".join(
            f'"{primary_key_column}"' for primary_key_column in primary_key_columns
        )
        order_by = ", ".join(
            f'"{primary_key_column}"' for primary_key_column in primary_key_columns
        )
        reference_rows = (
            (
                await db.execute(
                    text(
                        f'SELECT {select_columns} FROM "{table_name}" '
                        f'WHERE "{column_name}" = :source_id '
                        f"ORDER BY {order_by} FOR UPDATE"
                    ),
                    {"source_id": source_id},
                )
            )
            .mappings()
            .all()
        )
        if not reference_rows:
            continue
        records = [
            {
                "primary_key": {
                    primary_key_column: _json_ledger_value(
                        reference_row[primary_key_column]
                    )
                    for primary_key_column in primary_key_columns
                },
                "before_client_id": source_id,
                "after_client_id": target_id,
            }
            for reference_row in reference_rows
        ]
        result = await db.execute(
            text(
                f'UPDATE "{table_name}" SET "{column_name}" = :target_id '
                f'WHERE "{column_name}" = :source_id'
            ),
            {"source_id": source_id, "target_id": target_id},
        )
        if result.rowcount != len(records):
            raise ClientPortfolioImportError(
                "KIR dependency set changed while applying merge: "
                f"{table_name}.{column_name}"
            )
        moved.append(
            {
                "table": table_name,
                "column": column_name,
                "rows": len(records),
            }
        )
        reference_ledger.append(
            {
                "table": table_name,
                "column": column_name,
                "primary_key_columns": primary_key_columns,
                "records": records,
            }
        )

    candidate_preferences_ledger = await _replace_candidate_excluded_client(
        db, source_id=source_id, target_id=target_id
    )
    if source.external_id and not target.external_id:
        target.external_source = source.external_source
        target.external_id = source.external_id
        source.external_source = "merged"
        source.external_id = None
    target.display_name = "Krajowa Izba Rozliczeń"
    alias_audits = [
        audit
        for audit in (
            await _upsert_alias(
                db,
                client_id=target.id,
                alias="KIR",
                source_key="kir",
                import_run_id=import_run_id,
            ),
            await _upsert_alias(
                db,
                client_id=target.id,
                alias=source.display_name or source.name,
                source_key="kir-duplicate-name",
                import_run_id=import_run_id,
            ),
        )
        if audit is not None
    ]
    source.hidden = True
    source.archived_at = datetime.now(timezone.utc)
    source.archived_by = archived_by
    source.merged_into_client_id = target.id

    if job_ids:
        from app.services.index_outbox_service import JOB, record_bulk_reindex

        await record_bulk_reindex(db, JOB, job_ids)
    return {
        "already_merged": False,
        "moved_references": moved,
        "reference_ledger": reference_ledger,
        "jsonb_candidates": len(candidate_preferences_ledger),
        "candidate_preferences_ledger": candidate_preferences_ledger,
        "job_ids_reindexed": job_ids,
        "alias_audits": alias_audits,
        "source_before": source_before,
        "source_after": _client_state(source),
        "target_before": target_before,
        "target_after": _client_state(target),
    }


async def _find_existing_scope(
    db: AsyncSession, source_key: str
) -> ClientPortfolioScope | None:
    return await db.scalar(
        select(ClientPortfolioScope)
        .where(
            ClientPortfolioScope.source_system == SOURCE_SYSTEM,
            ClientPortfolioScope.source_key == source_key,
        )
        .order_by(
            ClientPortfolioScope.archived_at.is_not(None),
            ClientPortfolioScope.id.desc(),
        )
        .limit(1)
        .with_for_update()
    )


async def _find_existing_msa(
    db: AsyncSession, source_key: str
) -> ClientFrameworkContract | None:
    return await db.scalar(
        select(ClientFrameworkContract)
        .where(
            ClientFrameworkContract.source_system == SOURCE_SYSTEM,
            ClientFrameworkContract.source_key == source_key,
        )
        .with_for_update()
    )


async def apply_client_portfolio_manifest(
    db: AsyncSession,
    *,
    actor_id: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail-closed, idempotent apply in one savepoint under an advisory lock."""

    manifest = manifest or load_client_portfolio_manifest()
    has_postgres_lock = await _acquire_import_advisory_lock(db)

    normalized_manifest_sha256 = _normalized_manifest_sha256(manifest)
    existing_run = await db.scalar(
        select(ClientImportRun).where(
            ClientImportRun.source_system == SOURCE_SYSTEM,
            ClientImportRun.source_sha256 == manifest["source"]["sha256"],
            ClientImportRun.status == ClientImportRunStatus.applied,
        )
    )
    if existing_run is not None:
        applied_manifest_sha256 = (existing_run.summary or {}).get(
            "normalized_manifest_sha256"
        )
        if applied_manifest_sha256 != normalized_manifest_sha256:
            return {
                "status": "blocked",
                "run_id": existing_run.id,
                "blockers": [
                    {
                        "code": "normalized_manifest_digest_mismatch",
                        "expected": normalized_manifest_sha256,
                        "applied": applied_manifest_sha256,
                    }
                ],
            }
        health = await get_client_portfolio_import_health(db, manifest=manifest)
        if health.get("status") != "applied":
            return {
                "status": "blocked",
                "run_id": existing_run.id,
                "blockers": [
                    {
                        "code": "applied_manifest_state_inconsistent",
                        "health_status": health.get("status"),
                        "counts": health.get("counts") or {},
                    }
                ],
            }
        return {
            "status": "already_applied",
            "run_id": existing_run.id,
            "summary": existing_run.summary,
        }

    plan = await build_client_portfolio_plan(db, manifest=manifest)
    if has_postgres_lock:
        # The advisory lock coordinates importer instances only. During a
        # zero-downtime deploy the previous API can still write. Freeze only
        # the complete matching population and any KIR-specific surface, then
        # rebuild under those locks. A changed plan blocks instead of silently
        # applying a different decision. Plain reads continue normally.
        kir_merge = plan.get("kir_merge")
        kir_client_ids = (
            tuple(
                sorted(
                    {
                        int(kir_merge["source"]["id"]),
                        int(kir_merge["target"]["id"]),
                    }
                )
            )
            if isinstance(kir_merge, dict)
            else ()
        )
        await _lock_import_write_surface(
            db,
            kir_client_ids=kir_client_ids,
            include_candidates=bool(kir_merge),
        )
        locked_plan = await build_client_portfolio_plan(db, manifest=manifest)
        if locked_plan["plan_sha256"] != plan["plan_sha256"]:
            plan = _append_plan_blocker(
                locked_plan,
                {
                    "code": "plan_changed_while_acquiring_write_locks",
                    "before_plan_sha256": plan["plan_sha256"],
                    "locked_plan_sha256": locked_plan["plan_sha256"],
                },
            )
        else:
            plan = locked_plan
    run = ClientImportRun(
        source_system=SOURCE_SYSTEM,
        source_filename=manifest["source"]["filename"],
        source_sha256=manifest["source"]["sha256"],
        status=ClientImportRunStatus.applying,
        summary={
            "normalized_manifest_sha256": normalized_manifest_sha256,
            "plan_sha256": plan["plan_sha256"],
            "plan_summary": plan["summary"],
            "warnings": plan["warnings"],
            "duplicate_candidates": plan["duplicate_candidates"],
        },
        created_by=actor_id,
        approved_by=actor_id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()

    if plan["blockers"]:
        run.status = ClientImportRunStatus.failed
        run.error_message = json.dumps(plan["blockers"], ensure_ascii=False)
        run.summary = {**run.summary, "blockers": plan["blockers"]}
        return {
            "status": "blocked",
            "run_id": run.id,
            "plan_sha256": plan["plan_sha256"],
            "blockers": plan["blockers"],
        }

    try:
        async with db.begin_nested():
            alias_audits_by_id: dict[int, dict[str, Any]] = {}

            def record_alias_audit(audit: dict[str, Any] | None) -> None:
                if audit is None:
                    return
                alias_id = int(audit["alias_id"])
                previous = alias_audits_by_id.setdefault(alias_id, audit)
                if previous != audit:
                    raise ClientPortfolioImportError(
                        f"Inconsistent alias audit during apply: {alias_id}"
                    )

            merge_result: dict[str, Any] | None = None
            if plan["kir_merge"]:
                merge_result = await _merge_kir(
                    db,
                    source_id=plan["kir_merge"]["source"]["id"],
                    target_id=plan["kir_merge"]["target"]["id"],
                    expected_source_updated_at=plan["kir_merge"]["source"][
                        "updated_at"
                    ],
                    expected_target_updated_at=plan["kir_merge"]["target"][
                        "updated_at"
                    ],
                    archived_by=actor_id,
                    import_run_id=run.id,
                )
                for alias_audit in merge_result.get("alias_audits") or []:
                    record_alias_audit(alias_audit)
                planned_reference_counts = {
                    (item["table"], item["column"]): int(item["rows"])
                    for item in plan["kir_merge"].get("fk_impact") or []
                }
                moved_reference_counts = {
                    (item["table"], item["column"]): int(item["rows"])
                    for item in merge_result.get("moved_references") or []
                }
                if planned_reference_counts != moved_reference_counts or int(
                    plan["kir_merge"].get("jsonb_candidates") or 0
                ) != int(merge_result.get("jsonb_candidates") or 0):
                    raise ClientPortfolioImportError(
                        "KIR dependencies changed after validation; "
                        "the merge was rolled back"
                    )

            groups_by_key = {group["client_key"]: group for group in plan["groups"]}
            clients_by_key: dict[str, Client] = {}
            created_client_ids: list[int] = []
            changed_client_ids: set[int] = set()
            created_msa_ids: list[int] = []
            scope_ids: list[int] = []
            client_audit_by_key: dict[str, dict[str, Any]] = {}
            superseded_nexus_only_scope_audits: list[dict[str, Any]] = []

            for client_key, group in groups_by_key.items():
                rows = group["rows"]
                primary = rows[0]
                if group["action"] == "match":
                    client = await db.scalar(
                        select(Client)
                        .where(Client.id == group["target_client"]["id"])
                        .with_for_update()
                    )
                    if client is None:
                        raise ClientPortfolioImportError(
                            f"Matched client disappeared: {client_key}"
                        )
                    expected = group["target_client"].get("updated_at")
                    actual = (
                        client.updated_at.isoformat() if client.updated_at else None
                    )
                    merge_target_id = (
                        plan["kir_merge"]["target"]["id"]
                        if plan["kir_merge"] and merge_result is not None
                        else None
                    )
                    # _merge_kir already locked and validated this exact
                    # survivor against the plan before making importer-owned
                    # changes that can advance updated_at.
                    if client.id != merge_target_id and expected != actual:
                        raise ClientPortfolioImportError(
                            f"Client changed after plan: {client.id}"
                        )
                    before_client: dict[str, Any] | None = _client_state(client)
                    client.legal_name = primary["legal_name"]
                    if primary.get("force_display_name") or not client.display_name:
                        client.display_name = primary["display_name"]
                    if before_client != _client_state(client):
                        changed_client_ids.add(client.id)
                elif group["action"] == "create":
                    categories = {row["category"] for row in rows}
                    status = (
                        ClientStatus.inactive
                        if categories == {"inactive"}
                        else ClientStatus.active
                    )
                    external_id = f"portfolio:{hashlib.sha256(client_key.encode()).hexdigest()[:32]}"
                    client = await db.scalar(
                        select(Client)
                        .where(
                            Client.external_source == SOURCE_SYSTEM,
                            Client.external_id == external_id,
                        )
                        .with_for_update()
                    )
                    if client is None:
                        before_client = None
                        client = Client(
                            name=primary["display_name"],
                            display_name=primary["display_name"],
                            legal_name=primary["legal_name"],
                            status=status,
                            external_source=SOURCE_SYSTEM,
                            external_id=external_id,
                        )
                        db.add(client)
                        await db.flush()
                        created_client_ids.append(client.id)
                    else:
                        # A rollback archives Excel-only clients instead of
                        # deleting them. Re-applying the same stable client key
                        # revives that exact record so history and identifiers
                        # are preserved and the external-id UNIQUE remains
                        # retry-safe.
                        if (
                            not client.hidden
                            or client.archived_at is None
                            or client.merged_into_client_id is not None
                        ):
                            raise ClientPortfolioImportError(
                                f"Imported client identity is already in use: {client_key}"
                            )
                        before_client = _client_state(client)
                        client.name = primary["display_name"]
                        client.display_name = primary["display_name"]
                        client.legal_name = primary["legal_name"]
                        client.status = status
                        client.hidden = False
                        client.archived_at = None
                        client.archived_by = None
                        changed_client_ids.add(client.id)
                else:
                    raise ClientPortfolioImportError(
                        f"Unexpected group action: {group['action']}"
                    )
                clients_by_key[client_key] = client
                client_audit_by_key[client_key] = {
                    "before": before_client,
                    "after": _client_state(client),
                }
                for row in rows:
                    for alias_index, alias in enumerate(row.get("aliases") or []):
                        record_alias_audit(
                            await _upsert_alias(
                                db,
                                client_id=client.id,
                                alias=alias,
                                source_key=f"{row['source_key']}:{alias_index}",
                                import_run_id=run.id,
                            )
                        )

            manifest_client_ids = {client.id for client in clients_by_key.values()}
            nexus_only_client_ids = {int(item["id"]) for item in plan["nexus_only"]}
            if manifest_client_ids & nexus_only_client_ids:
                raise ClientPortfolioImportError(
                    "Import plan classifies one client as both workbook and NEXUS-only"
                )
            for client_id in sorted(manifest_client_ids):
                nexus_only_scopes = (
                    (
                        await db.execute(
                            select(ClientPortfolioScope)
                            .where(
                                ClientPortfolioScope.client_id == client_id,
                                ClientPortfolioScope.source_system == SOURCE_SYSTEM,
                                ClientPortfolioScope.source_key.startswith(
                                    "nexus-only:"
                                ),
                                ClientPortfolioScope.archived_at.is_(None),
                            )
                            .order_by(ClientPortfolioScope.id)
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                for nexus_only_scope in nexus_only_scopes:
                    before_nexus_only_scope = _scope_state(nexus_only_scope)
                    nexus_only_scope.archived_at = datetime.now(timezone.utc)
                    superseded_nexus_only_scope_audits.append(
                        {
                            "scope_id": nexus_only_scope.id,
                            "before": before_nexus_only_scope,
                            "after": _scope_state(nexus_only_scope),
                        }
                    )

            apply_date = _application_date()
            for manifest_row in manifest["rows"]:
                client = clients_by_key[manifest_row["client_key"]]
                start = _parse_iso_date(manifest_row.get("effective_date"))
                end = _parse_iso_date(manifest_row.get("expiry_date"))
                msa: ClientFrameworkContract | None = None
                before_msa: dict[str, Any] | None = None
                after_msa: dict[str, Any] | None = None
                if start is not None:
                    msa = await _find_existing_msa(db, manifest_row["source_key"])
                    if msa is None:
                        msa = ClientFrameworkContract(
                            client_id=client.id,
                            name=_msa_name(
                                client.display_name or client.name, manifest_row
                            ),
                            status=_msa_status(start, end, apply_date),
                            effective_date=start,
                            expiry_date=end,
                            signed_via=FrameworkContractSignedVia.legacy_import,
                            source_system=SOURCE_SYSTEM,
                            source_key=manifest_row["source_key"],
                            import_run_id=run.id,
                            notes=(
                                f"Zaimportowano z {manifest_row['sheet']} "
                                f"wiersz {manifest_row['row_number']}; "
                                f"źródło SHA-256 {manifest['source']['sha256']}"
                            ),
                        )
                        db.add(msa)
                        await db.flush()
                        created_msa_ids.append(msa.id)
                    else:
                        before_msa = _msa_state(msa)
                        msa.client_id = client.id
                        msa.name = _msa_name(
                            client.display_name or client.name, manifest_row
                        )
                        msa.status = _msa_status(start, end, apply_date)
                        msa.effective_date = start
                        msa.expiry_date = end
                        msa.signed_via = FrameworkContractSignedVia.legacy_import
                        msa.import_run_id = run.id
                    after_msa = _msa_state(msa)

                scope = await _find_existing_scope(db, manifest_row["source_key"])
                before_scope: dict[str, Any] | None = None
                if scope is None:
                    scope = ClientPortfolioScope(
                        client_id=client.id,
                        framework_contract_id=msa.id if msa else None,
                        category=PortfolioCategory(manifest_row["category"]),
                        label=manifest_row.get("scope_label"),
                        source_system=SOURCE_SYSTEM,
                        source_key=manifest_row["source_key"],
                    )
                    db.add(scope)
                    await db.flush()
                else:
                    before_scope = _scope_state(scope)
                    scope.client_id = client.id
                    scope.framework_contract_id = msa.id if msa else None
                    scope.category = PortfolioCategory(manifest_row["category"])
                    scope.label = manifest_row.get("scope_label")
                    scope.archived_at = None
                scope_ids.append(scope.id)

                db.add(
                    ClientImportRow(
                        import_run_id=run.id,
                        sheet_name=manifest_row["sheet"],
                        row_number=manifest_row["row_number"],
                        source_key=manifest_row["source_key"],
                        source_name=manifest_row["legal_name"],
                        normalized_name=normalize_client_name(
                            manifest_row["legal_name"]
                        ),
                        proposed_display_name=manifest_row["display_name"],
                        proposed_legal_name=manifest_row["legal_name"],
                        category=PortfolioCategory(manifest_row["category"]),
                        start_date=start,
                        end_date=end,
                        status=ClientImportRowStatus.applied,
                        match_confidence=1,
                        raw_payload={
                            "manifest": manifest_row,
                            "client": client_audit_by_key[manifest_row["client_key"]],
                            "before_msa": before_msa,
                            "after_msa": after_msa,
                            "before_scope": before_scope,
                            "after_scope": _scope_state(scope),
                        },
                        matched_client_id=client.id,
                        portfolio_scope_id=scope.id,
                        framework_contract_id=msa.id if msa else None,
                        resolved_by=actor_id,
                        resolved_at=datetime.now(timezone.utc),
                    )
                )

            # Existing business clients absent from the authoritative workbook
            # get a local inactive scope only; their operational status is kept.
            for item in plan["nexus_only"]:
                client = await db.scalar(
                    select(Client).where(Client.id == item["id"]).with_for_update()
                )
                if client is None or not _is_business_client(client):
                    raise ClientPortfolioImportError(
                        f"NEXUS-only client changed after plan: {item['id']}"
                    )
                actual_updated_at = (
                    client.updated_at.isoformat() if client.updated_at else None
                )
                if actual_updated_at != item.get("updated_at"):
                    raise ClientPortfolioImportError(
                        f"NEXUS-only client changed after plan: {item['id']}"
                    )
                source_key = f"nexus-only:{client.id}"
                scope = await _find_existing_scope(db, source_key)
                before_scope: dict[str, Any] | None = None
                legacy_nexus_only_scopes = (
                    (
                        await db.execute(
                            select(ClientPortfolioScope)
                            .where(
                                ClientPortfolioScope.client_id == client.id,
                                ClientPortfolioScope.source_system == SOURCE_SYSTEM,
                                ClientPortfolioScope.source_key.startswith(
                                    "nexus-only:"
                                ),
                                ClientPortfolioScope.source_key != source_key,
                                ClientPortfolioScope.archived_at.is_(None),
                            )
                            .order_by(ClientPortfolioScope.id)
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                if scope is None and legacy_nexus_only_scopes:
                    scope = legacy_nexus_only_scopes.pop(0)
                    before_scope = _scope_state(scope)
                    scope.source_key = source_key
                if scope is None:
                    scope = ClientPortfolioScope(
                        client_id=client.id,
                        category=PortfolioCategory.inactive,
                        label=None,
                        source_system=SOURCE_SYSTEM,
                        source_key=source_key,
                    )
                    db.add(scope)
                    await db.flush()
                else:
                    if scope.client_id != client.id:
                        raise ClientPortfolioImportError(
                            "NEXUS-only scope identity does not match its client"
                        )
                    if before_scope is None:
                        before_scope = _scope_state(scope)
                    scope.category = PortfolioCategory.inactive
                    scope.archived_at = None
                for legacy_scope in legacy_nexus_only_scopes:
                    before_legacy_scope = _scope_state(legacy_scope)
                    legacy_scope.archived_at = datetime.now(timezone.utc)
                    superseded_nexus_only_scope_audits.append(
                        {
                            "scope_id": legacy_scope.id,
                            "before": before_legacy_scope,
                            "after": _scope_state(legacy_scope),
                        }
                    )
                db.add(
                    ClientImportRow(
                        import_run_id=run.id,
                        sheet_name="NEXUS-only",
                        row_number=client.id,
                        source_key=source_key,
                        source_name=client.display_name or client.name,
                        normalized_name=normalize_client_name(
                            client.display_name or client.name
                        ),
                        proposed_display_name=client.display_name or client.name,
                        proposed_legal_name=client.legal_name,
                        category=PortfolioCategory.inactive,
                        status=ClientImportRowStatus.applied,
                        match_confidence=1,
                        raw_payload={
                            "reason": "absent_from_authoritative_workbook",
                            "before_scope": before_scope,
                            "after_scope": _scope_state(scope),
                        },
                        matched_client_id=client.id,
                        portfolio_scope_id=scope.id,
                        resolved_by=actor_id,
                        resolved_at=datetime.now(timezone.utc),
                    )
                )
                scope_ids.append(scope.id)

            for client_id in sorted(changed_client_ids | set(created_client_ids)):
                db.add(
                    Activity(
                        entity_type="client",
                        entity_id=client_id,
                        action="client_portfolio_excel_imported",
                        user_id=actor_id,
                        details={
                            "import_run_id": run.id,
                            "source_sha256": manifest["source"]["sha256"],
                        },
                    )
                )

            run.status = ClientImportRunStatus.applied
            run.applied_at = datetime.now(timezone.utc)
            run.summary = {
                **run.summary,
                "merge": merge_result,
                "created_client_ids": created_client_ids,
                "changed_client_ids": sorted(changed_client_ids),
                "created_msa_ids": created_msa_ids,
                "scope_ids": scope_ids,
                "alias_audits": [
                    alias_audits_by_id[alias_id]
                    for alias_id in sorted(alias_audits_by_id)
                ],
                "rows_applied": len(manifest["rows"]),
                "nexus_only_applied": len(plan["nexus_only"]),
                "msa_status_as_of": apply_date.isoformat(),
                "superseded_nexus_only_scope_audits": (
                    superseded_nexus_only_scope_audits
                ),
            }
    except Exception as exc:
        run.status = ClientImportRunStatus.failed
        run.error_message = str(exc)
        run.summary = {**run.summary, "apply_error": str(exc)}
        logger.exception("Client portfolio import rolled back")
        return {
            "status": "failed",
            "run_id": run.id,
            "error": str(exc),
            "plan_sha256": plan["plan_sha256"],
        }

    return {
        "status": "applied",
        "run_id": run.id,
        "plan_sha256": plan["plan_sha256"],
        "summary": run.summary,
    }


async def rollback_client_portfolio_import(
    db: AsyncSession, *, run_id: int, actor_id: int | None = None
) -> dict[str, Any]:
    """Restore the audited before-state, or make no business-data changes.

    Rollback is intentionally optimistic: every import-owned field must still
    equal its recorded ``after`` snapshot. A later edit therefore blocks the
    whole rollback instead of being overwritten. Rows created by the import
    are archived/superseded, never deleted.

    Unlike apply, rollback does not freeze the complete matching population.
    It locks every audited ORM row and candidate plus every catalog-discovered
    KIR child row before comparing current state. The KIR client ``FOR UPDATE``
    locks also conflict with FK ``KEY SHARE`` inserts. Concurrent writers thus
    wait until commit and are re-evaluated on retry, without global table locks.
    """

    await _acquire_import_advisory_lock(db)

    run = await db.scalar(
        select(ClientImportRun).where(ClientImportRun.id == run_id).with_for_update()
    )
    if run is None:
        raise ClientPortfolioImportError("Import run not found")
    if run.status == ClientImportRunStatus.rolled_back:
        return {"status": "already_rolled_back", "run_id": run.id}
    if run.status != ClientImportRunStatus.applied:
        raise ClientPortfolioImportError("Only an applied run can be rolled back")

    rows = (
        (
            await db.execute(
                select(ClientImportRow)
                .where(ClientImportRow.import_run_id == run.id)
                .order_by(ClientImportRow.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    conflicts: list[dict[str, Any]] = []
    if not rows:
        conflicts.append({"reason": "missing_import_audit_rows"})

    # Every dependency moved by the KIR merge must have an exact row-level
    # ledger. Missing or inconsistent audit data blocks before any business
    # mutation.
    raw_merge = (run.summary or {}).get("merge")
    merge = raw_merge if isinstance(raw_merge, dict) else None
    if raw_merge is not None and merge is None:
        conflicts.append({"reason": "invalid_kir_merge_audit"})
    reference_ledger: list[dict[str, Any]] = []
    candidate_preferences_ledger: list[dict[str, Any]] = []
    if merge and not merge.get("already_merged"):
        for key in (
            "source_before",
            "source_after",
            "target_before",
            "target_after",
        ):
            snapshot = merge.get(key)
            if not isinstance(snapshot, dict) or not {
                "id",
                "name",
                "display_name",
                "legal_name",
                "status",
                "hidden",
                "archived_at",
                "archived_by",
                "merged_into_client_id",
                "external_source",
                "external_id",
            }.issubset(snapshot):
                conflicts.append(
                    {"reason": "missing_kir_rollback_audit", "snapshot": key}
                )

        source_before = merge.get("source_before")
        target_before = merge.get("target_before")
        source_id = source_before.get("id") if isinstance(source_before, dict) else None
        target_id = target_before.get("id") if isinstance(target_before, dict) else None
        if (
            not isinstance(source_id, int)
            or not isinstance(target_id, int)
            or source_id == target_id
        ):
            conflicts.append({"reason": "invalid_kir_merge_client_ids"})
        source_after = merge.get("source_after")
        target_after = merge.get("target_after")
        if (
            not isinstance(source_before, dict)
            or normalize_client_name(source_before.get("name"))
            != KIR_DUPLICATE_NAME_KEY
            or source_before.get("hidden") is not False
            or source_before.get("archived_at") is not None
            or source_before.get("merged_into_client_id") is not None
            or not isinstance(target_before, dict)
            or normalize_client_name(target_before.get("name")) != KIR_SURVIVOR_NAME_KEY
            or target_before.get("hidden") is not False
            or target_before.get("archived_at") is not None
            or target_before.get("merged_into_client_id") is not None
            or not isinstance(source_after, dict)
            or source_after.get("id") != source_id
            or source_after.get("hidden") is not True
            or source_after.get("archived_at") is None
            or source_after.get("merged_into_client_id") != target_id
            or not isinstance(target_after, dict)
            or target_after.get("id") != target_id
            or target_after.get("hidden") is not False
            or target_after.get("archived_at") is not None
            or target_after.get("merged_into_client_id") is not None
        ):
            conflicts.append({"reason": "invalid_kir_merge_lifecycle_audit"})

        expected_reference_counts: dict[tuple[str, str], int] = {}
        raw_moved_references = merge.get("moved_references")
        if not isinstance(raw_moved_references, list):
            conflicts.append({"reason": "invalid_kir_moved_reference_summary"})
            raw_moved_references = []
        for index, item in enumerate(raw_moved_references):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("table"), str)
                or not isinstance(item.get("column"), str)
                or not isinstance(item.get("rows"), int)
                or item["rows"] < 0
            ):
                conflicts.append(
                    {
                        "reason": "invalid_kir_moved_reference_summary",
                        "audit_index": index,
                    }
                )
                continue
            try:
                table_name = _validate_identifier(item["table"])
                column_name = _validate_identifier(item["column"])
            except ClientPortfolioImportError:
                conflicts.append(
                    {
                        "reason": "unsafe_kir_reference_ledger_identifier",
                        "audit_index": index,
                    }
                )
                continue
            key = (table_name, column_name)
            if key in expected_reference_counts:
                conflicts.append(
                    {
                        "reason": "duplicate_kir_moved_reference_summary",
                        "table": table_name,
                        "column": column_name,
                    }
                )
                continue
            expected_reference_counts[key] = item["rows"]

        raw_reference_ledger = merge.get("reference_ledger")
        expected_reference_total = sum(expected_reference_counts.values())
        if not isinstance(raw_reference_ledger, list):
            raw_reference_ledger = []
            if expected_reference_total:
                conflicts.append(
                    {
                        "reason": "kir_merge_requires_row_level_rollback",
                        "detail": "missing_reference_ledger",
                        "moved_reference_rows": expected_reference_total,
                    }
                )
        actual_reference_counts: dict[tuple[str, str], int] = {}
        seen_reference_rows: set[tuple[str, str, str]] = set()
        for index, item in enumerate(raw_reference_ledger):
            if not isinstance(item, dict):
                conflicts.append(
                    {
                        "reason": "invalid_kir_reference_ledger",
                        "audit_index": index,
                    }
                )
                continue
            try:
                table_name = _validate_identifier(str(item.get("table") or ""))
                column_name = _validate_identifier(str(item.get("column") or ""))
                primary_key_columns = [
                    _validate_identifier(str(primary_key_column))
                    for primary_key_column in item.get("primary_key_columns") or []
                ]
            except ClientPortfolioImportError:
                conflicts.append(
                    {
                        "reason": "unsafe_kir_reference_ledger_identifier",
                        "audit_index": index,
                    }
                )
                continue
            records = item.get("records")
            if (
                not primary_key_columns
                or len(primary_key_columns) != len(set(primary_key_columns))
                or not isinstance(records, list)
            ):
                conflicts.append(
                    {
                        "reason": "invalid_kir_reference_ledger",
                        "audit_index": index,
                    }
                )
                continue
            valid_records: list[dict[str, Any]] = []
            for record_index, record in enumerate(records):
                primary_key = (
                    record.get("primary_key") if isinstance(record, dict) else None
                )
                if (
                    not isinstance(primary_key, dict)
                    or set(primary_key) != set(primary_key_columns)
                    or record.get("before_client_id") != source_id
                    or record.get("after_client_id") != target_id
                ):
                    conflicts.append(
                        {
                            "reason": "invalid_kir_reference_ledger_record",
                            "audit_index": index,
                            "record_index": record_index,
                        }
                    )
                    continue
                row_identity = (
                    table_name,
                    column_name,
                    json.dumps(
                        primary_key,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                )
                if row_identity in seen_reference_rows:
                    conflicts.append(
                        {
                            "reason": "duplicate_kir_reference_ledger_record",
                            "table": table_name,
                            "column": column_name,
                            "primary_key": primary_key,
                        }
                    )
                    continue
                seen_reference_rows.add(row_identity)
                valid_records.append(record)
            ledger_item = {
                "table": table_name,
                "column": column_name,
                "primary_key_columns": primary_key_columns,
                "records": valid_records,
            }
            reference_ledger.append(ledger_item)
            key = (table_name, column_name)
            actual_reference_counts[key] = actual_reference_counts.get(key, 0) + len(
                valid_records
            )
        if actual_reference_counts != expected_reference_counts:
            conflicts.append(
                {
                    "reason": "kir_reference_ledger_count_mismatch",
                    "expected": {
                        f"{table}.{column}": count
                        for (table, column), count in expected_reference_counts.items()
                    },
                    "actual": {
                        f"{table}.{column}": count
                        for (table, column), count in actual_reference_counts.items()
                    },
                }
            )

        raw_jsonb_count = merge.get("jsonb_candidates")
        jsonb_count = raw_jsonb_count if isinstance(raw_jsonb_count, int) else None
        if jsonb_count is None or jsonb_count < 0:
            conflicts.append({"reason": "invalid_kir_jsonb_reference_summary"})
            jsonb_count = 0
        raw_candidate_ledger = merge.get("candidate_preferences_ledger")
        if not isinstance(raw_candidate_ledger, list):
            raw_candidate_ledger = []
            if jsonb_count:
                conflicts.append(
                    {
                        "reason": "kir_merge_requires_row_level_rollback",
                        "detail": "missing_candidate_preferences_ledger",
                        "jsonb_candidates": jsonb_count,
                    }
                )
        seen_candidate_ids: set[int] = set()
        for index, item in enumerate(raw_candidate_ledger):
            candidate_id = item.get("candidate_id") if isinstance(item, dict) else None
            before_values = (
                item.get("before_excluded_clients") if isinstance(item, dict) else None
            )
            after_values = (
                item.get("after_excluded_clients") if isinstance(item, dict) else None
            )
            if (
                not isinstance(candidate_id, int)
                or candidate_id in seen_candidate_ids
                or not isinstance(before_values, list)
                or not isinstance(after_values, list)
                or not any(str(value) == str(source_id) for value in before_values)
                or any(str(value) == str(source_id) for value in after_values)
                or not any(str(value) == str(target_id) for value in after_values)
            ):
                conflicts.append(
                    {
                        "reason": "invalid_kir_candidate_preferences_ledger",
                        "audit_index": index,
                    }
                )
                continue
            seen_candidate_ids.add(candidate_id)
            candidate_preferences_ledger.append(item)
        if len(candidate_preferences_ledger) != jsonb_count:
            conflicts.append(
                {
                    "reason": "kir_candidate_preferences_ledger_count_mismatch",
                    "expected": jsonb_count,
                    "actual": len(candidate_preferences_ledger),
                }
            )

    client_audits: dict[int, dict[str, Any]] = {}
    scope_audits: dict[int, dict[str, Any]] = {}
    msa_audits: dict[int, dict[str, Any]] = {}
    alias_audits: dict[int, dict[str, Any]] = {}

    required_client_fields = {
        "id",
        "name",
        "display_name",
        "legal_name",
        "status",
        "hidden",
        "archived_at",
        "archived_by",
        "merged_into_client_id",
        "external_source",
        "external_id",
    }
    required_scope_fields = {
        "id",
        "client_id",
        "framework_contract_id",
        "category",
        "label",
        "source_system",
        "source_key",
        "archived_at",
    }
    required_msa_fields = {
        "id",
        "client_id",
        "name",
        "status",
        "effective_date",
        "expiry_date",
        "signed_via",
        "source_system",
        "source_key",
        "import_run_id",
        "notes",
    }
    required_alias_fields = {
        "id",
        "client_id",
        "alias",
        "normalized_alias",
        "source_system",
        "source_key",
        "import_run_id",
        "archived_at",
    }

    def register_audit(
        *,
        entity: str,
        entity_id: int | None,
        before: Any,
        after: Any,
        required_fields: set[str],
        registry: dict[int, dict[str, Any]],
        row_id: int,
    ) -> None:
        if entity_id is None:
            conflicts.append(
                {
                    "reason": "missing_rollback_entity_id",
                    "entity": entity,
                    "row_id": row_id,
                }
            )
            return
        if not isinstance(after, dict) or not required_fields.issubset(after):
            conflicts.append(
                {
                    "reason": "missing_rollback_audit",
                    "entity": entity,
                    "entity_id": entity_id,
                    "row_id": row_id,
                }
            )
            return
        if before is not None and (
            not isinstance(before, dict) or not required_fields.issubset(before)
        ):
            conflicts.append(
                {
                    "reason": "incomplete_before_snapshot",
                    "entity": entity,
                    "entity_id": entity_id,
                    "row_id": row_id,
                }
            )
            return
        audit = {"before": before, "after": after}
        previous = registry.setdefault(entity_id, audit)
        if previous != audit:
            conflicts.append(
                {
                    "reason": "inconsistent_rollback_audit",
                    "entity": entity,
                    "entity_id": entity_id,
                }
            )

    raw_alias_audits = (run.summary or {}).get("alias_audits", [])
    if not isinstance(raw_alias_audits, list):
        conflicts.append({"reason": "invalid_alias_rollback_audit_collection"})
    else:
        for index, alias_audit in enumerate(raw_alias_audits):
            if not isinstance(alias_audit, dict) or not isinstance(
                alias_audit.get("alias_id"), int
            ):
                conflicts.append(
                    {
                        "reason": "invalid_alias_rollback_audit",
                        "audit_index": index,
                    }
                )
                continue
            register_audit(
                entity="alias",
                entity_id=alias_audit["alias_id"],
                before=alias_audit.get("before"),
                after=alias_audit.get("after"),
                required_fields=required_alias_fields,
                registry=alias_audits,
                row_id=-(index + 1),
            )

    raw_superseded_scope_audits = (run.summary or {}).get(
        "superseded_nexus_only_scope_audits", []
    )
    if not isinstance(raw_superseded_scope_audits, list):
        conflicts.append(
            {"reason": "invalid_superseded_nexus_only_scope_audit_collection"}
        )
    else:
        for index, scope_audit in enumerate(raw_superseded_scope_audits):
            if not isinstance(scope_audit, dict) or not isinstance(
                scope_audit.get("scope_id"), int
            ):
                conflicts.append(
                    {
                        "reason": "invalid_superseded_nexus_only_scope_audit",
                        "audit_index": index,
                    }
                )
                continue
            register_audit(
                entity="scope",
                entity_id=scope_audit["scope_id"],
                before=scope_audit.get("before"),
                after=scope_audit.get("after"),
                required_fields=required_scope_fields,
                registry=scope_audits,
                row_id=-(10_000 + index),
            )

    for row in rows:
        payload = row.raw_payload or {}
        client_audit = payload.get("client")
        if client_audit is not None:
            if not isinstance(client_audit, dict):
                conflicts.append(
                    {
                        "reason": "invalid_client_rollback_audit",
                        "row_id": row.id,
                    }
                )
            else:
                register_audit(
                    entity="client",
                    entity_id=row.matched_client_id,
                    before=client_audit.get("before"),
                    after=client_audit.get("after"),
                    required_fields=required_client_fields,
                    registry=client_audits,
                    row_id=row.id,
                )
        register_audit(
            entity="scope",
            entity_id=row.portfolio_scope_id,
            before=payload.get("before_scope"),
            after=payload.get("after_scope"),
            required_fields=required_scope_fields,
            registry=scope_audits,
            row_id=row.id,
        )
        if row.framework_contract_id is not None:
            register_audit(
                entity="msa",
                entity_id=row.framework_contract_id,
                before=payload.get("before_msa"),
                after=payload.get("after_msa"),
                required_fields=required_msa_fields,
                registry=msa_audits,
                row_id=row.id,
            )

    kir_client_ids: set[int] = set()
    if merge and not merge.get("already_merged"):
        for key in ("source_after", "target_after"):
            snapshot = merge.get(key)
            if isinstance(snapshot, dict) and isinstance(snapshot.get("id"), int):
                kir_client_ids.add(snapshot["id"])

    client_ids = set(client_audits) | kir_client_ids
    scope_ids = set(scope_audits)
    msa_ids = set(msa_audits)
    alias_ids = set(alias_audits)
    candidate_ids = {item["candidate_id"] for item in candidate_preferences_ledger}

    clients: dict[int, Client] = {}
    scopes: dict[int, ClientPortfolioScope] = {}
    msas: dict[int, ClientFrameworkContract] = {}
    aliases: dict[int, ClientAlias] = {}
    candidates: dict[int, Candidate] = {}
    # These locks stay held through both compare_current and the nested restore
    # savepoint, closing the read/restore window without blocking unrelated
    # client, scope, MSA, alias or candidate rows.
    if client_ids:
        loaded = (
            (
                await db.execute(
                    select(Client)
                    .where(Client.id.in_(client_ids))
                    .order_by(Client.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        clients = {client.id: client for client in loaded}
    if scope_ids:
        loaded = (
            (
                await db.execute(
                    select(ClientPortfolioScope)
                    .where(ClientPortfolioScope.id.in_(scope_ids))
                    .order_by(ClientPortfolioScope.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        scopes = {scope.id: scope for scope in loaded}
    if msa_ids:
        loaded = (
            (
                await db.execute(
                    select(ClientFrameworkContract)
                    .where(ClientFrameworkContract.id.in_(msa_ids))
                    .order_by(ClientFrameworkContract.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        msas = {msa.id: msa for msa in loaded}
    if alias_ids:
        loaded = (
            (
                await db.execute(
                    select(ClientAlias)
                    .where(ClientAlias.id.in_(alias_ids))
                    .order_by(ClientAlias.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        aliases = {alias.id: alias for alias in loaded}
    if candidate_ids:
        loaded = (
            (
                await db.execute(
                    select(Candidate)
                    .where(Candidate.id.in_(candidate_ids))
                    .order_by(Candidate.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        candidates = {candidate.id: candidate for candidate in loaded}

    def compare_current(
        *,
        entity: str,
        entity_id: int,
        current: dict[str, Any] | None,
        expected: dict[str, Any],
    ) -> None:
        if current is None:
            conflicts.append(
                {
                    "reason": "rollback_entity_missing",
                    "entity": entity,
                    "entity_id": entity_id,
                }
            )
            return
        changed_fields = sorted(
            key for key, value in expected.items() if current.get(key) != value
        )
        if changed_fields:
            conflicts.append(
                {
                    "reason": "changed_after_import",
                    "entity": entity,
                    "entity_id": entity_id,
                    "fields": changed_fields,
                }
            )

    for client_id, audit in client_audits.items():
        client = clients.get(client_id)
        compare_current(
            entity="client",
            entity_id=client_id,
            current=_client_state(client) if client else None,
            expected=audit["after"],
        )
    for scope_id, audit in scope_audits.items():
        scope = scopes.get(scope_id)
        compare_current(
            entity="scope",
            entity_id=scope_id,
            current=_scope_state(scope) if scope else None,
            expected=audit["after"],
        )
    for msa_id, audit in msa_audits.items():
        msa = msas.get(msa_id)
        compare_current(
            entity="msa",
            entity_id=msa_id,
            current=_msa_state(msa) if msa else None,
            expected=audit["after"],
        )
    for alias_id, audit in alias_audits.items():
        alias = aliases.get(alias_id)
        compare_current(
            entity="alias",
            entity_id=alias_id,
            current=_alias_state(alias) if alias else None,
            expected=audit["after"],
        )

    if merge and not merge.get("already_merged"):
        source_after = merge.get("source_after")
        target_after = merge.get("target_after")
        if isinstance(source_after, dict) and isinstance(source_after.get("id"), int):
            source = clients.get(source_after["id"])
            compare_current(
                entity="kir_source",
                entity_id=source_after["id"],
                current=_client_state(source) if source else None,
                expected=source_after,
            )
        if isinstance(target_after, dict) and isinstance(target_after.get("id"), int):
            target = clients.get(target_after["id"])
            if target is None:
                conflicts.append(
                    {
                        "reason": "rollback_entity_missing",
                        "entity": "kir_target",
                        "entity_id": target_after["id"],
                    }
                )
            else:
                # The normal manifest update runs after the merge and can
                # legitimately change the target's display/legal name.  Its
                # complete state is already checked through ``client_audits``;
                # here only verify the identity fields owned by the merge.
                changed_identity = [
                    key
                    for key in ("external_source", "external_id")
                    if _client_state(target).get(key) != target_after.get(key)
                ]
                if changed_identity:
                    conflicts.append(
                        {
                            "reason": "changed_after_import",
                            "entity": "kir_target",
                            "entity_id": target.id,
                            "fields": changed_identity,
                        }
                    )

    if reference_ledger:
        catalog_specs = {
            (item["table"], item["column"]): tuple(item["primary_key_columns"])
            for item in await _direct_client_fk_specs(db)
        }
        for item in reference_ledger:
            table_name = item["table"]
            column_name = item["column"]
            primary_key_columns = item["primary_key_columns"]
            if catalog_specs.get((table_name, column_name)) != tuple(
                primary_key_columns
            ):
                conflicts.append(
                    {
                        "reason": "kir_reference_schema_changed",
                        "table": table_name,
                        "column": column_name,
                    }
                )
                continue
            for record in item["records"]:
                primary_key = record["primary_key"]
                predicates: list[str] = []
                params: dict[str, Any] = {}
                for index, primary_key_column in enumerate(primary_key_columns):
                    parameter_name = f"pk_{index}"
                    predicates.append(f'"{primary_key_column}" = :{parameter_name}')
                    params[parameter_name] = primary_key[primary_key_column]
                current_rows = (
                    (
                        await db.execute(
                            text(
                                f'SELECT "{column_name}" AS current_client_id '
                                f'FROM "{table_name}" WHERE '
                                + " AND ".join(predicates)
                                + " FOR UPDATE"
                            ),
                            params,
                        )
                    )
                    .mappings()
                    .all()
                )
                if len(current_rows) != 1:
                    conflicts.append(
                        {
                            "reason": "kir_reference_row_missing",
                            "table": table_name,
                            "column": column_name,
                            "primary_key": primary_key,
                        }
                    )
                    continue
                current_client_id = current_rows[0]["current_client_id"]
                if current_client_id != record["after_client_id"]:
                    conflicts.append(
                        {
                            "reason": "kir_reference_changed_after_import",
                            "table": table_name,
                            "column": column_name,
                            "primary_key": primary_key,
                            "expected_client_id": record["after_client_id"],
                            "actual_client_id": current_client_id,
                        }
                    )

    for item in candidate_preferences_ledger:
        candidate_id = item["candidate_id"]
        candidate = candidates.get(candidate_id)
        if candidate is None:
            conflicts.append(
                {
                    "reason": "kir_candidate_missing",
                    "candidate_id": candidate_id,
                }
            )
            continue
        current_excluded_clients = (candidate.preferences or {}).get("excluded_clients")
        if current_excluded_clients != item["after_excluded_clients"]:
            conflicts.append(
                {
                    "reason": "kir_candidate_preferences_changed_after_import",
                    "candidate_id": candidate_id,
                }
            )

    if conflicts:
        return {
            "status": "blocked",
            "run_id": run.id,
            "conflicts": conflicts,
        }

    now = datetime.now(timezone.utc)
    try:
        async with db.begin_nested():
            for alias_id, audit in alias_audits.items():
                alias = aliases[alias_id]
                before = audit["before"]
                if before is None:
                    alias.archived_at = now
                else:
                    _restore_alias_state(alias, before)

            for scope_id, audit in scope_audits.items():
                scope = scopes[scope_id]
                before = audit["before"]
                if before is None:
                    scope.archived_at = now
                else:
                    _restore_scope_state(scope, before)

            for msa_id, audit in msa_audits.items():
                msa = msas[msa_id]
                before = audit["before"]
                if before is None:
                    msa.status = FrameworkContractStatus.superseded
                    msa.notes = (
                        (msa.notes or "") + f"\nRollback importu {run.id}."
                    ).strip()
                else:
                    _restore_msa_state(msa, before)

            for client_id, audit in client_audits.items():
                client = clients[client_id]
                before = audit["before"]
                if before is None:
                    client.hidden = True
                    client.archived_at = now
                    client.archived_by = actor_id
                else:
                    _restore_client_state(client, before)

            if merge and not merge.get("already_merged"):
                source_before = merge["source_before"]
                target_before = merge["target_before"]
                _restore_client_state(clients[target_before["id"]], target_before)
                # When the merge transferred an external identity to the
                # survivor, release it before restoring it on the duplicate.
                await db.flush()
                _restore_client_state(clients[source_before["id"]], source_before)

            # Flush ORM-owned reversals before restoring catalog-discovered FK
            # rows with audited primary keys.
            await db.flush()
            restored_job_ids: set[int] = set()
            for item in reference_ledger:
                table_name = item["table"]
                column_name = item["column"]
                primary_key_columns = item["primary_key_columns"]
                for record in item["records"]:
                    primary_key = record["primary_key"]
                    predicates: list[str] = []
                    params: dict[str, Any] = {
                        "source_id": record["before_client_id"],
                        "target_id": record["after_client_id"],
                    }
                    for index, primary_key_column in enumerate(primary_key_columns):
                        parameter_name = f"pk_{index}"
                        predicates.append(f'"{primary_key_column}" = :{parameter_name}')
                        params[parameter_name] = primary_key[primary_key_column]
                    result = await db.execute(
                        text(
                            f'UPDATE "{table_name}" '
                            f'SET "{column_name}" = :source_id WHERE '
                            + " AND ".join(predicates)
                            + f' AND "{column_name}" = :target_id'
                        ),
                        params,
                    )
                    if result.rowcount != 1:
                        raise ClientPortfolioImportError(
                            "KIR dependency changed during rollback: "
                            f"{table_name}.{column_name}"
                        )
                    if (
                        table_name == Job.__tablename__
                        and column_name == "client_id"
                        and primary_key_columns == ["id"]
                        and isinstance(primary_key["id"], int)
                    ):
                        restored_job_ids.add(primary_key["id"])

            for item in candidate_preferences_ledger:
                candidate = candidates[item["candidate_id"]]
                preferences = dict(candidate.preferences or {})
                preferences["excluded_clients"] = list(item["before_excluded_clients"])
                candidate.preferences = preferences

            if restored_job_ids:
                from app.services.index_outbox_service import JOB, record_bulk_reindex

                await record_bulk_reindex(db, JOB, sorted(restored_job_ids))

            run.status = ClientImportRunStatus.rolled_back
            run.summary = {
                **(run.summary or {}),
                "rollback_at": now.isoformat(),
                "rollback_conflicts": [],
                "rollback_actor_id": actor_id,
                "rollback_job_ids_reindexed": sorted(restored_job_ids),
            }
    except Exception as exc:
        logger.exception("Client portfolio rollback was rolled back")
        return {
            "status": "blocked",
            "run_id": run_id,
            "conflicts": [
                {
                    "reason": "rollback_apply_failed",
                    "error": str(exc),
                }
            ],
        }

    return {
        "status": "rolled_back",
        "run_id": run.id,
        "conflicts": [],
    }
