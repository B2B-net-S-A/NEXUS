"""Powtarzalny import rejestru umów z Excela działu do ``b2b_generated_contracts``.

Excel „UMOWY I ZAMÓWIENIA” jest prowadzony RÓWNOLEGLE z NEXUSEM (decyzja
Artura 23.09.2026), więc ten sam albo nowszy plik jest wgrywany wielokrotnie:

* wiersz ``source='excel'`` jest aktualizowany po ``source_key`` (numer albo
  skrót wiersza dla „bez numeru”/„zlecenie”) — ponowny import tego samego
  pliku niczego nie zmienia;
* wiersz ``source='generator'`` (umowa wydana w NEXUSIE) NIGDY nie jest
  zmieniany — rozbieżność (inny Partner, inny klient pod tym samym numerem)
  trafia do raportu;
* wiersz, którego nie ma w nowym pliku, dostaje ``excel_missing_since`` —
  nie kasujemy;
* status zmieniony ręcznie w NEXUSIE wygrywa z plikiem: import nadpisuje
  status wyłącznie wtedy, gdy wiersz nadal ma status ustawiony przez
  poprzedni import (``legacy_data.import_status``).

``dry_run`` biegnie tą samą ścieżką i kończy się rollbackiem (w bazie zostaje
tylko wiersz przebiegu z licznikami — odblokowuje „Zastosuj”). Logi niosą
wyłącznie liczby; nazwiska są tylko w odpowiedzi dla admina i w szczegółach
paragonu (klucz ``repair_details_…``, którego publiczny workflow nie drukuje).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.b2b_contract_document import B2BContractDocument
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_generated_contract_status_event import (
    B2BGeneratedContractStatusEvent,
)
from app.models.b2b_register_import import B2BRegisterImportRow, B2BRegisterImportRun
from app.services.b2b_register_import.matching import (
    CandidateIndex,
    ClientResolver,
    Match,
    RecruiterResolver,
    candidates_linked_to_client,
)
from app.services.b2b_register_import.parser import (
    ContractRow,
    NoBusinessRow,
    ParsedRegister,
    name_tokens,
    norm,
    parse_register,
)

logger = logging.getLogger(__name__)

RECEIPT_PREFIX = "0358_b2b_register_import_"
DETAILS_PREFIX = "repair_details_0358_b2b_register_import_"
#: „Zastosuj” wymaga podglądu tego samego pliku nie starszego niż to.
DRY_RUN_VALIDITY = timedelta(hours=24)
_LOCK_KEY = 356_0023_2026

CLOSED_REASON_OTHER = "Import z Excela — zakończona"

#: Kolumny, które import ustawia na wierszu `excel` (i porównuje przy
#: ponownym imporcie). Kolejność = kolejność w migawce do „Cofnij”.
MANAGED_COLUMNS: tuple[str, ...] = (
    "contract_number",
    "year",
    "seq",
    "raw_contract_number",
    "partner_name",
    "client_name",
    "client_id",
    "candidate_id",
    "position",
    "contract_kind",
    "signing_date",
    "start_date",
    "start_date_mode",
    "recruiter_user_id",
    "legacy_data",
    "signature_status",
    "contract_status",
    "closure_reason",
    "closure_reason_other",
    "closure_date",
    "needs_business_data_annex",
    "business_data_annex_done_at",
    "excel_missing_since",
)
_STATUS_COLUMNS = frozenset(
    {
        "contract_status",
        "closure_reason",
        "closure_reason_other",
        "closure_date",
    }
)
_DATE_COLUMNS = {
    "signing_date",
    "start_date",
    "closure_date",
    "business_data_annex_done_at",
}
_STATUS_COLUMNS = (
    "contract_status",
    "closure_reason",
    "closure_reason_other",
    "closure_date",
)


class RegisterImportConflict(Exception):
    """Operacja niemożliwa w bieżącym stanie (409) — komunikat po polsku."""


def payload_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def _json_value(column: str, value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _from_json(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in _DATE_COLUMNS:
        return date.fromisoformat(value)
    if column == "excel_missing_since":
        return datetime.fromisoformat(value)
    return value


def _snapshot(row: B2BGeneratedContract) -> dict[str, Any]:
    return {
        column: _json_value(column, getattr(row, column)) for column in MANAGED_COLUMNS
    }


def _display_number(row: ContractRow) -> str:
    return row.number_raw or "—"


def _row_hash(row: ContractRow) -> str:
    """Klucz wiersza bez numeru: osoba + klient + rodzaj umowy. Bez dat —
    dział uzupełnia datę podpisania/startu później, a zmieniony klucz
    zakładałby drugi wiersz (a stary dostawałby „brak w pliku” razem ze
    statusem i dokumentami pochodnymi). Ta sama osoba kilka razy u klienta
    rozróżnia się numerem wystąpienia w pliku (`:<n>`)."""
    material = json.dumps(
        [
            sorted(row.tokens),
            norm(row.client_raw),
            row.kind,
            norm(row.number_raw),
        ],
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:40]


def _number_key(row: ContractRow) -> Optional[str]:
    """„n:1517”, „n:264a” — numer ciągły między latami, więc klucz nie
    zawiera roku (poprawiona w Excelu data podpisania nie tworzy nowego
    wiersza)."""
    if row.number_int is not None:
        return f"n:{row.number_int}"
    folded = norm(row.number_raw)
    # „bez numeru”, „zlecenie” itp. — to nie są numery.
    if not folded or not re.search(r"\d", folded):
        return None
    return "n:" + re.sub(r"\s+", "", (row.number_raw or "").casefold())[:60]


def _legacy_payload(row: ContractRow) -> dict[str, Any]:
    excel = {
        "name": row.name_raw,
        "number": row.number_raw,
        "client": row.client_raw,
        "kind": row.kind_raw,
        "signing": row.signing_raw,
        "start": row.start_raw,
        "end": row.end_raw,
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "loyalty": row.loyalty_raw,
        "recruiter": row.recruiter_raw,
        "settlement_info": row.settlement_raw,
        "welcome_mail": row.welcome_raw,
        "notes": row.notes,
        "changes": row.changes,
    }
    return {
        "excel": {k: v for k, v in excel.items() if v is not None},
        "colors": {
            k: v
            for k, v in {"name_cell": row.name_fill, "row": row.row_fill}.items()
            if v
        },
    }


def _derived_status(row: ContractRow) -> dict[str, Any]:
    if row.cancelled:
        return {
            "contract_status": "cancelled",
            "closure_reason": None,
            "closure_reason_other": None,
            "closure_date": None,
        }
    if row.red and row.closure_date is not None:
        return {
            "contract_status": "closed",
            "closure_reason": "other",
            "closure_reason_other": CLOSED_REASON_OTHER,
            "closure_date": row.closure_date,
        }
    return {
        "contract_status": "active" if row.signing_date else "in_progress",
        "closure_reason": None,
        "closure_reason_other": None,
        "closure_date": None,
    }


def _created_at(row: ContractRow) -> datetime:
    # Okno rejestru jest po `created_at` — wiersz z Excela staje w historii
    # w dniu podpisania, a nie masowo „dziś” (inaczej 1170 wierszy przykryłoby
    # umowy wydane w NEXUSIE przed importem).
    anchor = row.signing_date or row.start_date or date(2000, 1, 1)
    return datetime.combine(anchor, time(12, 0), tzinfo=timezone.utc)


# ── Import ───────────────────────────────────────────────────────────────────


class _Report:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {
            key: 0
            for key in (
                "rows_total",
                "contract_rows",
                "created",
                "updated",
                "unchanged",
                "skipped",
                "cancelled",
                "closed",
                "likely_ended",
                "generator_matches",
                "generator_discrepancies",
                "number_collisions",
                "missing_marked",
                "status_kept",
                "candidates_matched",
                "candidates_unmatched",
                "candidates_ambiguous",
                "clients_matched",
                "clients_internal",
                "clients_unknown_rows",
                "recruiters_matched",
                "recruiters_unknown_rows",
                "annex_rows",
                "annex_matched",
                "annex_unmatched",
                "annex_done",
            )
        }
        self.unmatched_candidates: list[dict[str, Any]] = []
        self.ambiguous_candidates: list[dict[str, Any]] = []
        self.unknown_clients: dict[tuple[str, str], dict[str, Any]] = {}
        self.unknown_recruiters: dict[tuple[str, str], dict[str, Any]] = {}
        self.generator_discrepancies: list[dict[str, Any]] = []
        self.number_collisions: list[dict[str, Any]] = []
        self.status_kept: list[dict[str, Any]] = []
        self.annex_matched: list[dict[str, Any]] = []
        self.annex_unmatched: list[dict[str, Any]] = []
        self.skipped_rows: list[dict[str, Any]] = []

    def note_client(self, raw: Optional[str], match: Match) -> None:
        if match.kind == "matched":
            self.counters["clients_matched"] += 1
        elif match.kind == "internal":
            self.counters["clients_internal"] += 1
        else:
            self.counters["clients_unknown_rows"] += 1
            key = (raw or "", match.kind)
            entry = self.unknown_clients.setdefault(
                key, {"text": raw or "", "reason": match.kind, "rows": 0}
            )
            entry["rows"] += 1

    def note_recruiter(self, raw: Optional[str], match: Match) -> None:
        if not raw:
            return
        if match.kind == "matched":
            self.counters["recruiters_matched"] += 1
            return
        self.counters["recruiters_unknown_rows"] += 1
        key = (raw, match.kind)
        entry = self.unknown_recruiters.setdefault(
            key, {"text": raw, "reason": match.kind, "rows": 0}
        )
        entry["rows"] += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "unmatched_candidates": self.unmatched_candidates,
            "ambiguous_candidates": self.ambiguous_candidates,
            "unknown_clients": sorted(
                self.unknown_clients.values(), key=lambda e: -e["rows"]
            ),
            "unknown_recruiters": sorted(
                self.unknown_recruiters.values(), key=lambda e: -e["rows"]
            ),
            "generator_discrepancies": self.generator_discrepancies,
            "number_collisions": self.number_collisions,
            "status_kept": self.status_kept,
            "annex": {"matched": self.annex_matched, "unmatched": self.annex_unmatched},
            "skipped_rows": self.skipped_rows,
        }


async def _deleted_numbers(db: AsyncSession) -> set[int]:
    rows = await db.execute(
        select(Activity.details["contract_number"].astext).where(
            Activity.entity_type == "b2b_generated_contract",
            Activity.action == "deleted",
        )
    )
    numbers: set[int] = set()
    for (value,) in rows.all():
        match = re.match(r"^\s*(\d+)\s*/\s*\d{4}\s*$", value or "")
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def _generator_number(contract_number: Optional[str]) -> Optional[int]:
    match = re.match(r"^\s*(\d+)\s*/\s*\d{4}\s*$", contract_number or "")
    return int(match.group(1)) if match else None


async def run_import(
    db: AsyncSession,
    *,
    payload: bytes,
    filename: str,
    user_id: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Import (albo podgląd) jednego pliku. Wołający commituje/rollbackuje
    zgodnie z ``dry_run`` — patrz ``api/b2b_register_import.py``."""
    sha = payload_sha256(payload)
    parsed = parse_register(payload)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})

    if not dry_run:
        since = datetime.now(timezone.utc) - DRY_RUN_VALIDITY
        previewed = await db.scalar(
            select(func.count(B2BRegisterImportRun.id)).where(
                B2BRegisterImportRun.source_sha256 == sha,
                B2BRegisterImportRun.mode == "dry_run",
                B2BRegisterImportRun.created_at >= since,
            )
        )
        if not previewed:
            raise RegisterImportConflict(
                "Najpierw uruchom podgląd tego samego pliku — „Zastosuj” zapisuje "
                "dokładnie to, co pokazał podgląd."
            )

    run = B2BRegisterImportRun(
        source_filename=filename[:255],
        source_sha256=sha,
        mode="dry_run" if dry_run else "applied",
        created_by=user_id,
    )
    db.add(run)
    await db.flush()

    report = await _apply(db, parsed, run=run)
    run.counters = dict(report.counters)
    result = {
        "run_id": run.id,
        "mode": run.mode,
        "filename": run.source_filename,
        "sha256": sha,
        "no_business_sheet_found": parsed.no_business_sheet_found,
        **report.as_dict(),
    }
    if not dry_run:
        await _write_receipt(db, run, result, user_id)
    logger.info(
        "b2b register import %s run=%s counters=%s",
        run.mode,
        run.id,
        json.dumps(report.counters, sort_keys=True),
    )
    return result


async def record_dry_run(
    db: AsyncSession, *, sha: str, filename: str, user_id: int, counters: dict[str, int]
) -> int:
    """Po rollbacku podglądu — trwały ślad „ten plik obejrzano” (same liczby)."""
    run = B2BRegisterImportRun(
        source_filename=filename[:255],
        source_sha256=sha,
        mode="dry_run",
        created_by=user_id,
        counters=counters,
    )
    db.add(run)
    await db.flush()
    return run.id


async def _apply(
    db: AsyncSession, parsed: ParsedRegister, *, run: B2BRegisterImportRun
) -> _Report:
    report = _Report()
    report.counters["contract_rows"] = len(parsed.contracts)
    report.counters["annex_rows"] = len(parsed.no_business)
    report.counters["rows_total"] = (
        len(parsed.contracts) + len(parsed.no_business) + len(parsed.skipped)
    )
    report.counters["skipped"] = len(parsed.skipped)
    report.skipped_rows = list(parsed.skipped)
    persist_rows = run.mode == "applied"

    candidates = await CandidateIndex.build(db)
    clients = await ClientResolver.build(db)
    recruiters = await RecruiterResolver.build(db)
    deleted_numbers = await _deleted_numbers(db)

    existing = list((await db.execute(select(B2BGeneratedContract))).scalars().all())
    generator_by_number: dict[int, B2BGeneratedContract] = {}
    excel_by_key: dict[str, B2BGeneratedContract] = {}
    taken_pairs: dict[tuple[int, int], int] = {}
    for row in existing:
        if row.seq is not None and row.year is not None:
            taken_pairs[(row.year, row.seq)] = row.id
        if row.source == "excel":
            if row.source_key:
                excel_by_key[row.source_key] = row
        elif (number := _generator_number(row.contract_number)) is not None:
            generator_by_number.setdefault(number, row)

    # ── Pierwsze przejście: klucze, kolizje, dopasowania ────────────────────
    plans: list[dict[str, Any]] = []
    seen_numbers: dict[str, int] = {}
    seen_hashes: dict[str, int] = {}
    ambiguous_by_client: dict[int, set[int]] = {}
    for row in parsed.contracts:
        flags = list(row.flags)
        key = _number_key(row)
        collision = None
        if key is not None:
            if key in seen_numbers:
                collision = "duplicate_in_file"
                report.number_collisions.append(
                    {
                        "number": _display_number(row),
                        "rows": [seen_numbers[key], row.row_number],
                        "reason": collision,
                    }
                )
                flags.append("number_collision")
                key = None
            else:
                seen_numbers[key] = row.row_number
        if key is None:
            digest = _row_hash(row)
            occurrence = seen_hashes.get(digest, 0)
            seen_hashes[digest] = occurrence + 1
            key = f"h:{digest}" + (f":{occurrence}" if occurrence else "")

        client_match = clients.resolve(row.client_raw)
        report.note_client(row.client_raw, client_match)
        recruiter_match = recruiters.resolve(row.recruiter_raw)
        report.note_recruiter(row.recruiter_raw, recruiter_match)
        candidate_ids = candidates.candidates_for(row.tokens)
        plan = {
            "row": row,
            "key": key,
            "flags": flags,
            "collision": collision,
            "client": client_match,
            "recruiter": recruiter_match,
            "candidate_ids": candidate_ids,
            "candidate_id": candidate_ids[0] if len(candidate_ids) == 1 else None,
        }
        if len(candidate_ids) > 1 and client_match.kind == "matched":
            ambiguous_by_client.setdefault(client_match.id, set()).update(candidate_ids)
        plans.append(plan)

    linked: dict[int, set[int]] = {}
    for client_id, ids in ambiguous_by_client.items():
        linked[client_id] = await candidates_linked_to_client(db, ids, client_id)

    for plan in plans:
        row: ContractRow = plan["row"]
        ids: list[int] = plan["candidate_ids"]
        if len(ids) > 1 and plan["client"].kind == "matched":
            narrowed = [
                cid for cid in ids if cid in linked.get(plan["client"].id, set())
            ]
            if len(narrowed) == 1:
                plan["candidate_id"] = narrowed[0]
        entry = {
            "row": row.row_number,
            "number": _display_number(row),
            "name": row.name_raw,
        }
        if plan["candidate_id"] is not None:
            report.counters["candidates_matched"] += 1
        elif ids:
            report.counters["candidates_ambiguous"] += 1
            report.ambiguous_candidates.append({**entry, "candidate_count": len(ids)})
            plan["flags"].append("candidate_ambiguous")
        else:
            report.counters["candidates_unmatched"] += 1
            report.unmatched_candidates.append(entry)

    # ── Arkusz „Bez działalności” → flagi aneksu ────────────────────────────
    annex_by_plan: dict[int, NoBusinessRow] = {}
    for nb in parsed.no_business:
        matches = [
            i for i, p in enumerate(plans) if p["row"].tokens == nb.tokens and nb.tokens
        ]
        if len(matches) > 1 and nb.client_raw:
            nb_client = clients.resolve(nb.client_raw)
            narrowed = [
                i
                for i in matches
                if norm(plans[i]["row"].client_raw) == norm(nb.client_raw)
                or (
                    nb_client.kind == "matched"
                    and plans[i]["client"].kind == "matched"
                    and plans[i]["client"].id == nb_client.id
                )
            ]
            matches = narrowed or matches
        if len(matches) > 1 and nb.start_date:
            narrowed = [
                i for i in matches if plans[i]["row"].start_date == nb.start_date
            ]
            matches = narrowed or matches
        entry = {"row": nb.row_number, "name": nb.name_raw}
        if len(matches) == 1:
            annex_by_plan[matches[0]] = nb
            report.counters["annex_matched"] += 1
            if nb.done:
                report.counters["annex_done"] += 1
            report.annex_matched.append(
                {
                    **entry,
                    "number": _display_number(plans[matches[0]]["row"]),
                    "done": nb.done,
                }
            )
        else:
            report.counters["annex_unmatched"] += 1
            report.annex_unmatched.append(
                {**entry, "reason": "ambiguous" if matches else "not_found"}
            )
        if persist_rows:
            db.add(
                B2BRegisterImportRow(
                    run_id=run.id,
                    sheet="bez_dzialalnosci",
                    row_number=nb.row_number,
                    raw=nb.raw,
                    parsed={
                        "done": nb.done,
                        "done_date": nb.done_date.isoformat() if nb.done_date else None,
                    },
                    matches={"contract_row": plans[matches[0]]["row"].row_number}
                    if len(matches) == 1
                    else {"count": len(matches)},
                    decision="annex_flag" if len(matches) == 1 else "annex_unmatched",
                )
            )

    # ── Drugie przejście: zapis ─────────────────────────────────────────────
    present_keys: set[str] = set()
    now = datetime.now(timezone.utc)
    for index, plan in enumerate(plans):
        row: ContractRow = plan["row"]
        flags: list[str] = plan["flags"]
        key: str = plan["key"]
        decision: str
        snapshot: Optional[dict[str, Any]] = None
        target_row: Optional[B2BGeneratedContract] = None

        generator = (
            generator_by_number.get(row.number_int)
            if row.number_int is not None
            else None
        )
        if generator is not None:
            present_keys.add(key)
            differences = _generator_differences(row, plan["client"], generator)
            if differences:
                report.counters["generator_discrepancies"] += 1
                report.generator_discrepancies.append(
                    {
                        "row": row.row_number,
                        "number": generator.contract_number,
                        "excel_partner": row.partner_name,
                        "nexus_partner": generator.partner_name,
                        "excel_client": row.client_raw,
                        "nexus_client": generator.client_name,
                        "differences": differences,
                    }
                )
            else:
                report.counters["generator_matches"] += 1
            decision = "generator_conflict" if differences else "generator_match"
            if persist_rows:
                db.add(
                    B2BRegisterImportRow(
                        run_id=run.id,
                        sheet="umowy_b2b",
                        row_number=row.row_number,
                        raw=row.raw,
                        decision=decision,
                        generated_contract_id=generator.id,
                        matches={"differences": differences},
                    )
                )
            continue

        if row.number_int is not None and row.number_int in deleted_numbers:
            report.number_collisions.append(
                {
                    "number": _display_number(row),
                    "rows": [row.row_number],
                    "reason": "deleted_in_nexus",
                }
            )
            report.counters["number_collisions"] += 1
            flags.append("deleted_number_reused")
        if plan["collision"]:
            report.counters["number_collisions"] += 1

        # Numer kanoniczny tylko dla liczby + znanego roku i gdy para
        # (rok, numer) nie jest zajęta przez inny wiersz.
        existing_row = excel_by_key.get(key)
        year = row.signing_date.year if row.signing_date else None
        seq = (
            row.number_int
            if (
                row.number_int is not None
                and year is not None
                and not plan["collision"]
            )
            else None
        )
        if seq is not None:
            owner = taken_pairs.get((year, seq))
            if owner is not None and (existing_row is None or owner != existing_row.id):
                report.number_collisions.append(
                    {
                        "number": f"{seq}/{year}",
                        "rows": [row.row_number],
                        "reason": "number_taken",
                    }
                )
                report.counters["number_collisions"] += 1
                flags.append("number_collision")
                seq = None
        contract_number = (
            f"{seq}/{year}" if seq is not None else (row.number_raw or "bez numeru")
        )

        annex = annex_by_plan.get(index)
        legacy = _legacy_payload(row)
        derived = _derived_status(row)
        if row.cancelled:
            report.counters["cancelled"] += 1
        elif derived["contract_status"] == "closed":
            report.counters["closed"] += 1
        if "likely_ended" in flags:
            report.counters["likely_ended"] += 1

        client_match: Match = plan["client"]
        recruiter_match: Match = plan["recruiter"]
        target: dict[str, Any] = {
            "contract_number": contract_number[:64],
            "year": year,
            "seq": seq,
            "raw_contract_number": (row.number_raw or None) and row.number_raw[:64],
            "partner_name": row.partner_name[:255] or None,
            "client_name": (row.client_raw or None) and row.client_raw[:255],
            "client_id": client_match.id if client_match.kind == "matched" else None,
            "candidate_id": plan["candidate_id"],
            "position": (row.position or None) and row.position[:255],
            "contract_kind": row.kind,
            "signing_date": row.signing_date,
            "start_date": row.start_date,
            "start_date_mode": row.start_date_mode if row.start_date else None,
            "recruiter_user_id": recruiter_match.id
            if recruiter_match.kind == "matched"
            else None,
            "signature_status": "signed_both"
            if (row.signing_date and not row.cancelled)
            else "unsigned",
            "excel_missing_since": None,
            **derived,
        }
        # Brak dopasowania w tym pliku nie kasuje powiązania ustalonego wcześniej.
        if existing_row is not None:
            for column in ("client_id", "candidate_id", "recruiter_user_id"):
                if target[column] is None:
                    target[column] = getattr(existing_row, column)
            previous_legacy = existing_row.legacy_data or {}
            previous_status = previous_legacy.get("import_status")
            current_status = {
                "contract_status": existing_row.contract_status,
                "closure_reason": existing_row.closure_reason,
                "closure_reason_other": existing_row.closure_reason_other,
                "closure_date": _json_value("closure_date", existing_row.closure_date),
            }
            if previous_status is not None and previous_status != current_status:
                # Status zmieniony ręcznie w NEXUSIE — plik go nie nadpisuje.
                for column in _STATUS_COLUMNS:
                    target[column] = getattr(existing_row, column)
                if {
                    k: _json_value(k, derived[k]) for k in _STATUS_COLUMNS
                } != current_status:
                    report.counters["status_kept"] += 1
                    report.status_kept.append(
                        {"row": row.row_number, "number": contract_number}
                    )
                import_status = previous_status
            else:
                import_status = {k: _json_value(k, derived[k]) for k in _STATUS_COLUMNS}
            target["needs_business_data_annex"] = existing_row.needs_business_data_annex
            target["business_data_annex_done_at"] = (
                existing_row.business_data_annex_done_at
            )
            previous_annex = previous_legacy.get("business_annex")
        else:
            import_status = {k: _json_value(k, derived[k]) for k in _STATUS_COLUMNS}
            target["needs_business_data_annex"] = False
            target["business_data_annex_done_at"] = None
            previous_annex = None
        if annex is not None:
            target["needs_business_data_annex"] = True
            if annex.done_date and target["business_data_annex_done_at"] is None:
                target["business_data_annex_done_at"] = annex.done_date
            if (
                annex.done
                and not annex.done_date
                and target["business_data_annex_done_at"] is None
            ):
                flags.append("business_annex_done_undated")
            legacy["business_annex"] = {
                "status": "done" if annex.done else "todo",
                **({"note": annex.annex_raw} if annex.annex_raw else {}),
                **({"annex_notes": annex.annex_notes} if annex.annex_notes else {}),
            }
        elif previous_annex is not None:
            legacy["business_annex"] = previous_annex
        legacy["flags"] = sorted(set(flags))
        legacy["import_status"] = import_status
        target["legacy_data"] = legacy
        present_keys.add(key)

        if existing_row is None:
            target_row = B2BGeneratedContract(
                source="excel",
                source_key=key,
                language="pl",
                import_run_id=run.id,
                created_at=_created_at(row),
                **target,
            )
            db.add(target_row)
            await db.flush()
            if seq is not None:
                taken_pairs[(year, seq)] = target_row.id
            decision = "created"
            report.counters["created"] += 1
        else:
            before = _snapshot(existing_row)
            after = {
                column: _json_value(column, target[column])
                for column in MANAGED_COLUMNS
            }
            if before == after:
                decision = "unchanged"
                report.counters["unchanged"] += 1
            else:
                snapshot = before
                old_pair = (existing_row.year, existing_row.seq)
                for column, value in target.items():
                    setattr(existing_row, column, value)
                existing_row.import_run_id = run.id
                if old_pair in taken_pairs and old_pair != (year, seq):
                    taken_pairs.pop(old_pair, None)
                if seq is not None:
                    taken_pairs[(year, seq)] = existing_row.id
                await db.flush()
                decision = "updated"
                report.counters["updated"] += 1
            target_row = existing_row

        if persist_rows:
            db.add(
                B2BRegisterImportRow(
                    run_id=run.id,
                    sheet="umowy_b2b",
                    row_number=row.row_number,
                    raw=row.raw,
                    parsed={
                        "key": key,
                        "status": target["contract_status"],
                        "flags": legacy["flags"],
                    },
                    matches={
                        "candidate": plan["candidate_id"],
                        "candidate_count": len(plan["candidate_ids"]),
                        "client": client_match.kind,
                        "recruiter": recruiter_match.kind,
                    },
                    decision=decision,
                    generated_contract_id=target_row.id if target_row else None,
                    snapshot_before=snapshot,
                )
            )

    # ── Wiersze z Excela, których nie ma w pliku ────────────────────────────
    missing_ids = [
        row.id
        for key, row in excel_by_key.items()
        if key not in present_keys and row.excel_missing_since is None
    ]
    if missing_ids:
        await db.execute(
            update(B2BGeneratedContract)
            .where(B2BGeneratedContract.id.in_(missing_ids))
            .values(excel_missing_since=now)
        )
    run.missing_marked_ids = missing_ids
    report.counters["missing_marked"] = len(missing_ids)
    await db.flush()
    return report


def _generator_differences(
    row: ContractRow, client_match: Match, generator: B2BGeneratedContract
) -> list[str]:
    differences: list[str] = []
    nexus_tokens = name_tokens(generator.partner_name)
    if (
        row.tokens
        and nexus_tokens
        and not (row.tokens <= nexus_tokens or nexus_tokens <= row.tokens)
    ):
        differences.append("partner")
    same_client = (
        client_match.kind == "matched"
        and generator.client_id is not None
        and client_match.id == generator.client_id
    ) or norm(row.client_raw) == norm(generator.client_name)
    if row.client_raw and generator.client_name and not same_client:
        differences.append("client")
    return differences


async def _write_receipt(
    db: AsyncSession, run: B2BRegisterImportRun, result: dict[str, Any], user_id: int
) -> None:
    sha12 = run.source_sha256[:12]
    created_ids = (
        (
            await db.execute(
                select(B2BRegisterImportRow.generated_contract_id).where(
                    B2BRegisterImportRow.run_id == run.id,
                    B2BRegisterImportRow.decision == "created",
                )
            )
        )
        .scalars()
        .all()
    )
    updated_ids = (
        (
            await db.execute(
                select(B2BRegisterImportRow.generated_contract_id).where(
                    B2BRegisterImportRow.run_id == run.id,
                    B2BRegisterImportRow.decision == "updated",
                )
            )
        )
        .scalars()
        .all()
    )
    # Paragon: SAME liczby i ID (workflow `migration-receipts` drukuje klucze
    # `NNNN_…` w publicznym logu).
    receipt = {
        "run_id": run.id,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "counters": result["counters"],
        "created_ids": sorted(i for i in created_ids if i is not None),
        "updated_ids": sorted(i for i in updated_ids if i is not None),
        "missing_marked_ids": list(run.missing_marked_ids or []),
    }
    details = {
        "run_id": run.id,
        "filename": run.source_filename,
        **{
            k: v
            for k, v in result.items()
            if k not in ("counters", "run_id", "filename")
        },
    }
    for key, value in (
        (f"{RECEIPT_PREFIX}{sha12}", receipt),
        (f"{DETAILS_PREFIX}{sha12}", details),
    ):
        row = await db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value, updated_by=user_id))
        else:
            if key.startswith(RECEIPT_PREFIX):
                value = {
                    **value,
                    "first_applied_at": row.value.get("first_applied_at")
                    or row.value.get("applied_at"),
                }
            row.value = value
            row.updated_by = user_id
    await db.flush()


# ── Cofnięcie przebiegu ──────────────────────────────────────────────────────


async def rollback_run(
    db: AsyncSession, *, run_id: int, user_id: int
) -> dict[str, int]:
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
    run = await db.get(B2BRegisterImportRun, run_id, with_for_update=True)
    if run is None:
        raise LookupError("run")
    if run.mode != "applied":
        raise RegisterImportConflict("Cofnąć można tylko zastosowany przebieg.")
    latest = await db.scalar(
        select(func.max(B2BRegisterImportRun.id)).where(
            B2BRegisterImportRun.mode == "applied"
        )
    )
    if latest != run.id:
        raise RegisterImportConflict(
            "Cofnąć można tylko ostatni zastosowany przebieg — nowszy import "
            "zapisał stan na podstawie tego."
        )
    rows = (
        (
            await db.execute(
                select(B2BRegisterImportRow).where(
                    B2BRegisterImportRow.run_id == run.id,
                    B2BRegisterImportRow.decision.in_(("created", "updated")),
                )
            )
        )
        .scalars()
        .all()
    )
    # Ręczna zmiana statusu w NEXUSIE po imporcie (PATCH, skutek podpisanego
    # dokumentu) zostawia wpis w dzienniku statusów — import go nie pisze.
    # Taki status wygrywa z cofnięciem, jak wygrywa z plikiem.
    touched_ids = {r.generated_contract_id for r in rows if r.generated_contract_id}
    changed_by_hand: set[int] = set()
    if touched_ids:
        changed_by_hand = set(
            (
                await db.execute(
                    select(B2BGeneratedContractStatusEvent.generated_contract_id).where(
                        B2BGeneratedContractStatusEvent.generated_contract_id.in_(
                            touched_ids
                        ),
                        B2BGeneratedContractStatusEvent.created_at >= run.created_at,
                    )
                )
            )
            .scalars()
            .all()
        )
    created_ids = [
        r.generated_contract_id
        for r in rows
        if r.decision == "created"
        and r.generated_contract_id
        and r.generated_contract_id not in changed_by_hand
    ]
    kept_created = sum(
        1
        for r in rows
        if r.decision == "created" and r.generated_contract_id in changed_by_hand
    )
    if created_ids:
        with_documents = await db.scalar(
            select(
                func.count(
                    func.distinct(B2BContractDocument.parent_generated_contract_id)
                )
            ).where(B2BContractDocument.parent_generated_contract_id.in_(created_ids))
        )
        if with_documents:
            raise RegisterImportConflict(
                f"{with_documents} umów z tego przebiegu ma już dokumenty pochodne "
                "(aneksy, rozwiązania) — cofnięcie skasowałoby je. Nic nie zmieniono."
            )
        await db.execute(
            B2BGeneratedContract.__table__.delete().where(
                B2BGeneratedContract.id.in_(created_ids),
                B2BGeneratedContract.source == "excel",
            )
        )
    restored = 0
    for import_row in rows:
        if import_row.decision != "updated" or not import_row.snapshot_before:
            continue
        target = await db.get(B2BGeneratedContract, import_row.generated_contract_id)
        if target is None or target.source != "excel":
            continue
        manual_status = target.id in changed_by_hand
        for column, value in import_row.snapshot_before.items():
            if manual_status and column in _STATUS_COLUMNS:
                continue
            setattr(target, column, _from_json(column, value))
        restored += 1
    missing_ids = list(run.missing_marked_ids or [])
    if missing_ids:
        await db.execute(
            update(B2BGeneratedContract)
            .where(
                B2BGeneratedContract.id.in_(missing_ids),
                B2BGeneratedContract.source == "excel",
            )
            .values(excel_missing_since=None)
        )
    run.mode = "rolled_back"
    run.rolled_back_at = datetime.now(timezone.utc)
    run.rolled_back_by = user_id
    receipt_key = f"{RECEIPT_PREFIX}{run.source_sha256[:12]}"
    receipt = await db.get(AppSetting, receipt_key)
    if receipt is not None:
        receipt.value = {
            **receipt.value,
            "rolled_back_at": run.rolled_back_at.isoformat(),
            "rolled_back_run_id": run.id,
        }
    await db.flush()
    result = {
        "deleted": len(created_ids),
        "restored": restored,
        "missing_cleared": len(missing_ids),
        # Wiersze, których status zmieniono w NEXUSIE po imporcie — zostają
        # (utworzone) albo zachowują status (zaktualizowane).
        "kept_manual_status": len(changed_by_hand),
        "kept_created": kept_created,
    }
    logger.info("b2b register import rollback run=%s %s", run.id, json.dumps(result))
    return result
