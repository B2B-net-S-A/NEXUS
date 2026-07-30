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

from sqlalchemy import cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
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
FUZZY_BLOCK_THRESHOLD = 0.88
SYSTEM_CLIENT_NAMES = {"__traffit_orphans"}

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
            f"2026-07-30 cutover manifest must contain exactly "
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
        await db.execute(select(ClientAlias.client_id, ClientAlias.alias))
    ).all():
        aliases_by_client[int(client_id)].append(alias)
    return [
        client for client in clients if _is_business_client(client)
    ], aliases_by_client


def _duplicate_candidates(
    clients: list[Client], aliases_by_client: dict[int, list[str]]
) -> list[dict[str, Any]]:
    """Return report-only likely duplicates; never used to merge."""

    results: dict[tuple[int, int], dict[str, Any]] = {}
    loose_groups: dict[str, list[Client]] = defaultdict(list)
    labels: dict[int, str] = {}
    for client in clients:
        preferred = client.display_name or client.legal_name or client.name
        labels[client.id] = preferred
        key = loose_client_name(preferred)
        if len(key) >= 3:
            loose_groups[key].append(client)
    for key, group in loose_groups.items():
        if len(group) < 2:
            continue
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                pair = tuple(sorted((left.id, right.id)))
                results[pair] = {
                    "client_ids": list(pair),
                    "names": [labels[pair[0]], labels[pair[1]]],
                    "reason": "same_normalized_legal_name",
                    "score": 1.0,
                }

    # Small portfolio: O(n²) suggestion pass is deterministic and cheap.
    for index, left in enumerate(clients):
        left_label = loose_client_name(labels[left.id])
        if len(left_label) < 4:
            continue
        for right in clients[index + 1 :]:
            right_label = loose_client_name(labels[right.id])
            if len(right_label) < 4:
                continue
            score = SequenceMatcher(None, left_label, right_label).ratio()
            if score < 0.9:
                continue
            pair = tuple(sorted((left.id, right.id)))
            results.setdefault(
                pair,
                {
                    "client_ids": list(pair),
                    "names": [labels[pair[0]], labels[pair[1]]],
                    "reason": "fuzzy_name_similarity",
                    "score": round(score, 4),
                },
            )
    return sorted(results.values(), key=lambda item: item["client_ids"])


async def _direct_client_fk_counts(
    db: AsyncSession, source_client_id: int
) -> list[dict[str, Any]]:
    """Inventory every direct FK to clients using the Postgres catalog."""

    if db.get_bind().dialect.name != "postgresql":
        return []
    rows = (
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
    impact: list[dict[str, Any]] = []
    for table_name, column_name in rows:
        if table_name == "clients":
            continue
        if not _SAFE_IDENTIFIER.fullmatch(table_name) or not _SAFE_IDENTIFIER.fullmatch(
            column_name
        ):
            raise ClientPortfolioImportError("Unsafe FK identifier from catalog")
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
                }
            )
    return impact


async def _candidate_excluded_client_count(db: AsyncSession, client_id: int) -> int:
    """Count non-FK JSON references used by candidate exclusion preferences."""

    if db.get_bind().dialect.name == "postgresql":
        numeric_payload = json.dumps({"excluded_clients": [client_id]})
        string_payload = json.dumps({"excluded_clients": [str(client_id)]})
        return int(
            (
                await db.scalar(
                    select(func.count())
                    .select_from(Candidate)
                    .where(
                        Candidate.preferences.is_not(None),
                        or_(
                            Candidate.preferences.op("@>")(
                                cast(numeric_payload, JSONB)
                            ),
                            Candidate.preferences.op("@>")(cast(string_payload, JSONB)),
                        ),
                    )
                )
            )
            or 0
        )

    # Unit tests use SQLite, whose JSON implementation has no PostgreSQL @>
    # operator. Keep the small compatibility fallback out of production.
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
        # Match precedence is intentional. A reviewed ClientAlias is the
        # strongest local assertion and must not be diluted by a colliding
        # historical source/display name. NIP/REGON are optional in the
        # manifest, but supported before exact normalized names.
        candidate_ids: set[int] = {
            client_id for label in labels for client_id in alias_map.get(label, set())
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
                if "kir" in _client_labels(client, aliases_by_client.get(client.id, []))
            }
            if len(kir_ids) == 1:
                candidate_ids = kir_ids
                match_method = "approved_kir_survivor"

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
        if "kir" in _client_labels(client, aliases_by_client.get(client.id, []))
    ]
    kir_losers = [
        client
        for client in clients
        if client not in kir_targets
        and (
            normalize_client_name(client.name).startswith("krajowa izba rozlicz")
            or normalize_client_name(client.display_name).startswith(
                "krajowa izba rozlicz"
            )
        )
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
        if fk_impact or jsonb_candidates:
            blockers.append(
                {
                    "code": "kir_dependencies_require_row_level_rollback",
                    "source": _public_client(source),
                    "target": _public_client(target),
                    "fk_impact": fk_impact,
                    "jsonb_candidates": jsonb_candidates,
                }
            )
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
    for candidate in duplicate_report:
        candidate_clients = [
            client_by_id[client_id] for client_id in candidate["client_ids"]
        ]
        candidate["clients"] = [_public_client(client) for client in candidate_clients]
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
    source_key: str | None = None,
) -> None:
    normalized = normalize_client_name(alias)
    if not normalized:
        return
    existing = await db.scalar(
        select(ClientAlias).where(
            ClientAlias.client_id == client_id,
            ClientAlias.normalized_alias == normalized,
        )
    )
    if existing is None:
        db.add(
            ClientAlias(
                client_id=client_id,
                alias=alias.strip(),
                normalized_alias=normalized,
                source_system=SOURCE_SYSTEM,
                source_key=source_key,
            )
        )


async def _replace_candidate_excluded_client(
    db: AsyncSession, *, source_id: int, target_id: int
) -> int:
    candidates = (
        (await db.execute(select(Candidate).where(Candidate.preferences.is_not(None))))
        .scalars()
        .all()
    )
    changed = 0
    for candidate in candidates:
        preferences = dict(candidate.preferences or {})
        raw = preferences.get("excluded_clients")
        if not isinstance(raw, list):
            continue
        replacement: list[Any] = []
        touched = False
        for value in raw:
            comparable = str(value)
            if comparable == str(source_id):
                replacement.append(target_id)
                touched = True
            else:
                replacement.append(value)
        if touched:
            preferences["excluded_clients"] = list(dict.fromkeys(replacement))
            candidate.preferences = preferences
            changed += 1
    return changed


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


async def _merge_kir(
    db: AsyncSession,
    *,
    source_id: int,
    target_id: int,
    expected_source_updated_at: str | None,
    expected_target_updated_at: str | None,
    archived_by: int | None,
) -> dict[str, Any]:
    """Repoint direct FKs, preserve aliases and archive the loser.

    Any uniqueness collision raises and rolls back the enclosing savepoint.
    No child rows or client rows are deleted.
    """

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
    if source_id not in by_id or target_id not in by_id:
        raise ClientPortfolioImportError("KIR source/target disappeared")
    source, target = by_id[source_id], by_id[target_id]
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
    if source.merged_into_client_id == target_id and source.hidden:
        return {
            "already_merged": True,
            "moved_references": [],
            "jsonb_candidates": 0,
        }
    if target.merged_into_client_id is not None:
        raise ClientPortfolioImportError(
            "KIR merge target is itself merged; resolve the chain first"
        )
    if source.merged_into_client_id is not None:
        raise ClientPortfolioImportError(
            "KIR duplicate is already merged into a different client"
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
    if db.get_bind().dialect.name == "postgresql":
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
        for table_name, column_name in fk_rows:
            if table_name == "clients":
                continue
            if not _SAFE_IDENTIFIER.fullmatch(
                table_name
            ) or not _SAFE_IDENTIFIER.fullmatch(column_name):
                raise ClientPortfolioImportError("Unsafe FK identifier from catalog")
            result = await db.execute(
                text(
                    f'UPDATE "{table_name}" SET "{column_name}" = :target_id '
                    f'WHERE "{column_name}" = :source_id'
                ),
                {"source_id": source_id, "target_id": target_id},
            )
            if result.rowcount:
                moved.append(
                    {
                        "table": table_name,
                        "column": column_name,
                        "rows": int(result.rowcount),
                    }
                )

    jsonb_candidates = await _replace_candidate_excluded_client(
        db, source_id=source_id, target_id=target_id
    )
    if source.external_id and not target.external_id:
        target.external_source = source.external_source
        target.external_id = source.external_id
        source.external_source = "merged"
        source.external_id = None
    target.display_name = "Krajowa Izba Rozliczeń"
    await _upsert_alias(db, client_id=target.id, alias="KIR", source_key="kir")
    await _upsert_alias(
        db,
        client_id=target.id,
        alias=source.display_name or source.name,
        source_key="kir-duplicate-name",
    )
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
        "jsonb_candidates": jsonb_candidates,
        "job_ids_reindexed": job_ids,
        "source_before": source_before,
        "source_after": _client_state(source),
        "target_before": target_before,
        "target_after": _client_state(target),
    }


async def _find_existing_scope(
    db: AsyncSession, source_key: str
) -> ClientPortfolioScope | None:
    return await db.scalar(
        select(ClientPortfolioScope).where(
            ClientPortfolioScope.source_system == SOURCE_SYSTEM,
            ClientPortfolioScope.source_key == source_key,
            ClientPortfolioScope.archived_at.is_(None),
        )
    )


async def _find_existing_msa(
    db: AsyncSession, source_key: str
) -> ClientFrameworkContract | None:
    return await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.source_system == SOURCE_SYSTEM,
            ClientFrameworkContract.source_key == source_key,
        )
    )


async def apply_client_portfolio_manifest(
    db: AsyncSession,
    *,
    actor_id: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail-closed, idempotent apply in one savepoint under an advisory lock."""

    manifest = manifest or load_client_portfolio_manifest()
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": ADVISORY_LOCK_KEY},
        )

    existing_run = await db.scalar(
        select(ClientImportRun).where(
            ClientImportRun.source_system == SOURCE_SYSTEM,
            ClientImportRun.source_sha256 == manifest["source"]["sha256"],
            ClientImportRun.status == ClientImportRunStatus.applied,
        )
    )
    if existing_run is not None:
        return {
            "status": "already_applied",
            "run_id": existing_run.id,
            "summary": existing_run.summary,
        }

    plan = await build_client_portfolio_plan(db, manifest=manifest)
    run = ClientImportRun(
        source_system=SOURCE_SYSTEM,
        source_filename=manifest["source"]["filename"],
        source_sha256=manifest["source"]["sha256"],
        status=ClientImportRunStatus.applying,
        summary={
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
                )

            groups_by_key = {group["client_key"]: group for group in plan["groups"]}
            clients_by_key: dict[str, Client] = {}
            created_client_ids: list[int] = []
            changed_client_ids: set[int] = set()
            created_msa_ids: list[int] = []
            scope_ids: list[int] = []
            client_audit_by_key: dict[str, dict[str, Any]] = {}

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
                    if expected != actual:
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
                        await _upsert_alias(
                            db,
                            client_id=client.id,
                            alias=alias,
                            source_key=f"{row['source_key']}:{alias_index}",
                        )

            snapshot = date.fromisoformat(manifest["snapshot_date"])
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
                            status=_msa_status(start, end, snapshot),
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
                        msa.status = _msa_status(start, end, snapshot)
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
                source_key = f"nexus-only:{client.id}:{manifest['snapshot_date']}"
                scope = await _find_existing_scope(db, source_key)
                before_scope: dict[str, Any] | None = None
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
                    before_scope = _scope_state(scope)
                    scope.category = PortfolioCategory.inactive
                    scope.archived_at = None
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
                "rows_applied": len(manifest["rows"]),
                "nexus_only_applied": len(plan["nexus_only"]),
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
    equal its recorded ``after`` snapshot.  A later edit therefore blocks the
    whole rollback instead of being overwritten.  Rows created by the import
    are archived/superseded, never deleted.
    """

    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": ADVISORY_LOCK_KEY},
        )

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

    # A generic FK merge can only be reversed safely with a row-level FK
    # ledger.  The production KIR duplicate is expected to be empty; if that
    # assumption was false, fail before touching any scope/MSA/client.
    merge = (run.summary or {}).get("merge")
    if merge and not merge.get("already_merged"):
        moved_count = sum(
            int(item.get("rows") or 0) for item in merge.get("moved_references") or []
        )
        jsonb_count = int(merge.get("jsonb_candidates") or 0)
        if moved_count or jsonb_count:
            conflicts.append(
                {
                    "reason": "kir_merge_requires_row_level_rollback",
                    "moved_reference_rows": moved_count,
                    "jsonb_candidates": jsonb_count,
                }
            )
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

    client_audits: dict[int, dict[str, Any]] = {}
    scope_audits: dict[int, dict[str, Any]] = {}
    msa_audits: dict[int, dict[str, Any]] = {}

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

    clients: dict[int, Client] = {}
    scopes: dict[int, ClientPortfolioScope] = {}
    msas: dict[int, ClientFrameworkContract] = {}
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

    if conflicts:
        return {
            "status": "blocked",
            "run_id": run.id,
            "conflicts": conflicts,
        }

    now = datetime.now(timezone.utc)
    try:
        async with db.begin_nested():
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

            run.status = ClientImportRunStatus.rolled_back
            run.summary = {
                **(run.summary or {}),
                "rollback_at": now.isoformat(),
                "rollback_conflicts": [],
                "rollback_actor_id": actor_id,
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
