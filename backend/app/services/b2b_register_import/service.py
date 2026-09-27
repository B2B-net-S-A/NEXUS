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

import asyncio
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
from app.services.client_portfolio_import import loose_client_name
from app.services.b2b_register_import.parser import (
    ContractRow,
    NoBusinessRow,
    ParsedRegister,
    name_tokens,
    norm,
    parse_register,
)

logger = logging.getLogger(__name__)

RECEIPT_PREFIX = "0363_b2b_register_import_"
DETAILS_PREFIX = "repair_details_0363_b2b_register_import_"
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


#: Kolumny wiersza, które zmienia skutek podpisanego dokumentu pochodnego
#: (``services/b2b_documents/effects.py``): aneks daty startu przestawia datę
#: rozpoczęcia, aneks danych firmy stempluje zdjęcie z kolejki „Aneks
#: uzupełnienia danych”. Plik działu tego nie wie — import i „Cofnij”
#: nadpisywały podpisaną zmianę (runda 6 audytu, XLS-1).
_DOCUMENT_OWNED_COLUMNS: dict[str, tuple[str, ...]] = {
    "annex_start_date": ("start_date", "start_date_mode"),
    "annex_party_data": ("business_data_annex_done_at",),
}


async def _document_owned_columns(
    db: AsyncSession, row_ids: list[int], *, since: Optional[datetime] = None
) -> dict[int, set[str]]:
    """Kolumny wierszy rejestru, które zmienił podpisany dokument pochodny.

    ``since`` — tylko dokumenty podpisane po tej chwili (cofnięcie przebiegu:
    zmiana sprzed importu była w migawce „przed”, więc wolno ją przywrócić)."""
    if not row_ids:
        return {}
    stmt = select(
        B2BContractDocument.parent_generated_contract_id,
        B2BContractDocument.document_type,
    ).where(
        B2BContractDocument.parent_generated_contract_id.in_(row_ids),
        B2BContractDocument.document_type.in_(tuple(_DOCUMENT_OWNED_COLUMNS)),
        B2BContractDocument.effect_applied_at.isnot(None),
    )
    if since is not None:
        stmt = stmt.where(B2BContractDocument.effect_applied_at >= since)
    owned: dict[int, set[str]] = {}
    for parent_id, document_type in (await db.execute(stmt)).all():
        owned.setdefault(parent_id, set()).update(
            _DOCUMENT_OWNED_COLUMNS.get(document_type, ())
        )
    return owned


async def _missing_foreign_keys(db: AsyncSession, snapshot: dict[str, Any]) -> set[str]:
    """Kolumny migawki wskazujące rekord, którego już nie ma.

    Kandydat bywa scalony, a klient usunięty po imporcie — przywrócenie jego id
    przy „Cofnij” kończyło się 500 na kluczu obcym, więc taka kolumna zostaje
    przy bieżącej wartości (runda 6 audytu, XLS-1)."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.user import User

    missing: set[str] = set()
    for column, model in (
        ("candidate_id", Candidate),
        ("client_id", Client),
        ("recruiter_user_id", User),
    ):
        value = snapshot.get(column)
        if value is None:
            continue
        found = await db.scalar(select(model.id).where(model.id == value))
        if found is None:
            missing.add(column)
    return missing


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


def _client_identity(raw: Optional[str], match: Match) -> str:
    """Klient w kluczu wiersza: rozpoznany klient po id, inaczej nazwa bez
    formy prawnej — „Klient Testowy” i „Klient Testowy SA” to ten sam klient."""
    if match.kind == "matched":
        return f"id:{match.id}"
    if match.kind == "internal":
        return "internal"
    words = [w for w in loose_client_name(raw).split() if w not in _LEGAL_SUFFIXES]
    return " ".join(words) or norm(raw)


#: Skróty form prawnych pisane bez kropek („SA”, „Sp z oo”).
_LEGAL_SUFFIXES = frozenset({"sa", "zoo", "o", "spzoo", "sk", "sj"})


def _row_digest(
    tokens: frozenset[str], client_identity: str, kind: Optional[str], number_raw: Any
) -> str:
    """Klucz wiersza bez numeru: osoba + klient + rodzaj umowy. Bez dat —
    dział uzupełnia datę podpisania/startu później, a zmieniony klucz
    zakładałby drugi wiersz (a stary dostawałby „brak w pliku” razem ze
    statusem i dokumentami pochodnymi). Tekst w kolumnie numeru bez cyfr
    („bez numeru”, „zlecenie”) nie wchodzi do klucza — jego poprawka nie jest
    nową umową (runda 7, N3-2)."""
    folded_number = norm(number_raw)
    material = json.dumps(
        [
            sorted(tokens),
            client_identity,
            kind,
            folded_number if re.search(r"\d", folded_number) else "",
        ],
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:40]


def _row_hash(row: ContractRow, client_match: Match) -> str:
    return _row_digest(
        row.tokens,
        _client_identity(row.client_raw, client_match),
        row.kind,
        row.number_raw,
    )


def _stored_digest(row: B2BGeneratedContract, clients: ClientResolver) -> str:
    """Ten sam klucz policzony z danych zapisanych przez poprzedni import —
    niezależny od ``source_key`` (zapisanego starszą regułą i numerem
    wystąpienia w pliku)."""
    excel = (row.legacy_data or {}).get("excel") or {}
    name = excel.get("name")
    tokens = name_tokens(name) if name else name_tokens(row.partner_name)
    client_raw = excel.get("client")
    return _row_digest(
        tokens,
        _client_identity(client_raw, clients.resolve(client_raw)),
        row.contract_kind,
        excel.get("number", row.raw_contract_number),
    )


def assign_row_keys(
    plans: list[dict[str, Any]],
    existing: list[tuple[str, B2BGeneratedContract]],
    taken_keys: set[str],
) -> None:
    """Klucze wierszy bez numeru (``plan["digest"]``) — parowane z wierszami
    zapisanymi wcześniej po TREŚCI, nie po kolejności w pliku.

    Do rundy 7 (N3-2) druga umowa tej samej osoby u tego samego klienta
    dostawała sufiks ``:1`` według kolejności wystąpienia, więc posortowanie
    arkusza zamieniało klucze: rekord umowy z 2023 dostawał daty umowy
    z 2025, a przy nim zostawał status ustawiony ręcznie i dokumenty
    pochodne. Parowanie w grupie tego samego klucza treści: najpierw ta sama
    data podpisania i startu, potem sama data podpisania, sama data startu,
    na końcu reszta w kolejności (wiersz, któremu dział dopisał datę)."""
    by_digest: dict[str, list[dict[str, Any]]] = {}
    for plan in plans:
        if plan.get("key") is None:
            by_digest.setdefault(plan["digest"], []).append(plan)
    stored: dict[str, list[B2BGeneratedContract]] = {}
    for digest, row in existing:
        stored.setdefault(digest, []).append(row)

    def signing(row: B2BGeneratedContract) -> Optional[date]:
        return row.signing_date

    def start(row: B2BGeneratedContract) -> Optional[date]:
        return row.start_date

    passes = (
        lambda p, r: (
            (p.signing_date, p.start_date) == (signing(r), start(r))
            and (p.signing_date is not None or p.start_date is not None)
        ),
        lambda p, r: p.signing_date is not None and p.signing_date == signing(r),
        lambda p, r: p.start_date is not None and p.start_date == start(r),
        lambda p, r: True,
    )
    used = set(taken_keys)
    for digest, group in by_digest.items():
        rows = sorted(stored.get(digest, []), key=lambda r: r.id or 0)
        free = list(rows)
        for same in passes:
            for plan in group:
                if plan.get("key") is not None:
                    continue
                for row in free:
                    if same(plan["row"], row):
                        plan["key"] = row.source_key
                        used.add(row.source_key)
                        free.remove(row)
                        break
        occurrence = 0
        for plan in group:
            if plan.get("key") is not None:
                continue
            while True:
                key = f"h:{digest}" + (f":{occurrence}" if occurrence else "")
                occurrence += 1
                if key not in used:
                    break
            plan["key"] = key
            used.add(key)


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
    text_number = re.sub(r"[\u2010-\u2015\u2212]", "-", row.number_raw or "")
    return "n:" + re.sub(r"\s+", "", text_number.casefold())[:60]


def _legacy_number_key(row: ContractRow) -> Optional[str]:
    """Klucz numeru sprzed rundy 7 — wiersz zapisany nim wcześniej („1517/2026”,
    „1519 – A”) jest dalej tym samym wierszem, a nie brakiem w pliku."""
    raw = row.number_raw
    if row.number_int is not None and raw and re.fullmatch(r"\d+", raw):
        return f"n:{row.number_int}"
    folded = norm(raw)
    if not folded or not re.search(r"\d", folded):
        return None
    return "n:" + re.sub(r"\s+", "", (raw or "").casefold())[:60]


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
                "annex_cleared",
                "generator_annex_flagged",
                "signing_dates_unparsed",
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
        self.unparsed_dates: list[dict[str, Any]] = []

    def note_client(self, raw: Optional[str], match: Match) -> None:
        if match.kind == "matched":
            self.counters["clients_matched"] += 1
        elif match.kind == "internal":
            self.counters["clients_internal"] += 1
        else:
            self.counters["clients_unknown_rows"] += 1
            text = raw or "(pusta komórka)"
            key = (text, match.kind)
            entry = self.unknown_clients.setdefault(
                key, {"text": text, "reason": match.kind, "rows": 0}
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
            "unparsed_dates": self.unparsed_dates,
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


async def _import_owned_annex_flags(db: AsyncSession, ids: list[int]) -> set[int]:
    """Umowy z NEXUSA, którym flagę aneksu postawił (i nie zdjął) import.

    Ostatni wpis zastosowanego przebiegu z migawką flagi rozstrzyga: migawka
    ``False`` = import ją postawił, ``True`` = import ją zdjął. Filtr migawki
    w Pythonie — brak migawki to JSON ``null`` (jak w ``rollback_run``).
    """

    if not ids:
        return set()
    rows = (
        await db.execute(
            select(
                B2BRegisterImportRow.generated_contract_id,
                B2BRegisterImportRow.snapshot_before,
            )
            .join(
                B2BRegisterImportRun,
                B2BRegisterImportRun.id == B2BRegisterImportRow.run_id,
            )
            .where(
                B2BRegisterImportRow.generated_contract_id.in_(ids),
                B2BRegisterImportRow.decision.in_(
                    ("generator_match", "generator_conflict")
                ),
                B2BRegisterImportRun.mode == "applied",
            )
            .order_by(B2BRegisterImportRow.id)
        )
    ).all()
    set_by_import: dict[int, bool] = {}
    for generated_id, snapshot in rows:
        if isinstance(snapshot, dict) and "needs_business_data_annex" in snapshot:
            set_by_import[generated_id] = not snapshot["needs_business_data_annex"]
    return {generated_id for generated_id, owned in set_by_import.items() if owned}


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
    # zipfile + openpyxl to sekundy CPU przy dużym arkuszu — w wątku, nie na
    # pętli zdarzeń jedynego procesu API (runda 6 audytu).
    parsed = await asyncio.to_thread(parse_register, payload)
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

    # FOR UPDATE: PATCH statusu w trakcie przebiegu czeka na jego koniec,
    # zamiast zostać nadpisany stanem przeczytanym przed nim (runda 7, N3-10).
    existing = list(
        (await db.execute(select(B2BGeneratedContract).with_for_update()))
        .scalars()
        .all()
    )
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

    document_owned = await _document_owned_columns(
        db, [row.id for row in excel_by_key.values()]
    )
    annex_flag_owned = await _import_owned_annex_flags(
        db,
        [
            row.id
            for row in generator_by_number.values()
            if row.needs_business_data_annex
        ],
    )

    # ── Pierwsze przejście: klucze, kolizje, dopasowania ────────────────────
    plans: list[dict[str, Any]] = []
    seen_numbers: dict[str, int] = {}
    claimed_legacy: set[str] = set()
    ambiguous_by_client: dict[int, set[int]] = {}
    for row in parsed.contracts:
        flags = list(row.flags)
        key = _number_key(row)
        collision = None
        if "signing_date_unparsed" in flags:
            report.counters["signing_dates_unparsed"] += 1
            report.unparsed_dates.append(
                {"row": row.row_number, "number": _display_number(row)}
            )
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
                legacy_key = _legacy_number_key(row)
                # Runda 8 (R8-V1-7): numer umowy z NEXUSA idzie gałęzią
                # generatora, więc klucza legacy nie przejmuje — zapisany
                # przed rundą 7 duplikat z Excela („1517/2026” obok umowy
                # 1517) dostaje wtedy „brak w pliku” zamiast wisieć na zawsze.
                if (
                    row.number_int not in generator_by_number
                    and key not in excel_by_key
                    and legacy_key is not None
                    and legacy_key in excel_by_key
                    and legacy_key not in claimed_legacy
                ):
                    claimed_legacy.add(legacy_key)
                    key = legacy_key

        client_match = clients.resolve(row.client_raw)
        report.note_client(row.client_raw, client_match)
        recruiter_match = recruiters.resolve(row.recruiter_raw)
        report.note_recruiter(row.recruiter_raw, recruiter_match)
        candidate_ids = candidates.candidates_for(row.tokens)
        plan = {
            "row": row,
            "key": key,
            "digest": _row_hash(row, client_match) if key is None else None,
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

    assign_row_keys(
        plans,
        [
            (_stored_digest(row, clients), row)
            for key, row in excel_by_key.items()
            if key.startswith("h:")
        ],
        # Klucze wszystkich zapisanych wierszy: nowa umowa nie może dostać
        # klucza wiersza, którego nie sparowano (inna osoba, stara reguła).
        taken_keys={p["key"] for p in plans if p["key"] is not None}
        | set(excel_by_key),
    )

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
    # Osoba z arkusza, której wiersza nie da się jednoznacznie sparować, nadal
    # jest w arkuszu — jej flagi nie zdejmujemy jako „zniknęła z pliku”.
    annex_tokens = {nb.tokens for nb in parsed.no_business if nb.tokens}
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
            # Arkusz „Bez działalności” to jedyne, co import zmienia na umowie
            # wydanej w NEXUSIE: flaga kolejki „Aneks uzupełnienia danych do
            # zrobienia” (decyzja Artura 26.09.2026, runda 7 N3-1). Aneks
            # zrobiony według Excela flagi nie stawia — daty zrobienia na
            # wierszu z NEXUSA import nie wpisuje, więc wiersz stałby w kolejce.
            annex_snapshot: Optional[dict[str, Any]] = None
            annex = annex_by_plan.get(index)
            if (
                annex is not None
                and not annex.done
                and not generator.needs_business_data_annex
            ):
                annex_snapshot = {"needs_business_data_annex": False}
                generator.needs_business_data_annex = True
                report.counters["generator_annex_flagged"] += 1
            elif (
                generator.needs_business_data_annex
                and generator.id in annex_flag_owned
                and generator.business_data_annex_done_at is None
                and (
                    (annex is not None and annex.done)
                    or (
                        annex is None
                        and parsed.no_business_sheet_found
                        and row.tokens not in annex_tokens
                    )
                )
            ):
                # Runda 8 (R8-V1-2): flagę postawioną przez import zdejmuje
                # też import — gdy dział oznaczył aneks jako zrobiony (umowy
                # podpisujemy offline) albo osoby nie ma już w arkuszu. Bez
                # tego umowa z NEXUSA wisiała w kolejce aneksów na zawsze;
                # wiersze z Excela mają tę regułę od rundy 7 (N3-7).
                annex_snapshot = {"needs_business_data_annex": True}
                generator.needs_business_data_annex = False
                report.counters["annex_cleared"] += 1
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
                        snapshot_before=annex_snapshot,
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
            # Zmiana z podpisanego dokumentu wygrywa z plikiem, jak ręczny status.
            for column in document_owned.get(existing_row.id, ()):
                target[column] = getattr(existing_row, column)
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
                # Aneks zrobiony według działu, tylko bez daty — nie jest „do
                # zrobienia”. Daty nie zmyślamy; wiersz wychodzi z kolejki,
                # a status „zrobiony” zostaje w `legacy_data` (runda 7, N3-7).
                target["needs_business_data_annex"] = False
                flags.append("business_annex_done_undated")
            legacy["business_annex"] = {
                "status": "done" if annex.done else "todo",
                **({"note": annex.annex_raw} if annex.annex_raw else {}),
                **({"annex_notes": annex.annex_notes} if annex.annex_notes else {}),
            }
        elif previous_annex is not None:
            legacy["business_annex"] = previous_annex
            if (
                parsed.no_business_sheet_found
                and previous_annex.get("status") == "todo"
                and not previous_annex.get("removed_from_file")
            ):
                # Osoby nie ma już w arkuszu „Bez działalności” — flaga
                # postawiona przez import schodzi razem z nią (N3-7).
                legacy["business_annex"] = {**previous_annex, "removed_from_file": True}
                if target["needs_business_data_annex"]:
                    target["needs_business_data_annex"] = False
                    report.counters["annex_cleared"] += 1
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
    # Flaga aneksu postawiona przez ten przebieg na umowie z NEXUSA (N3-1).
    # Filtr w Pythonie: kolumna JSON zapisuje brak migawki jako JSON `null`,
    # którego `IS NOT NULL` nie odsiewa.
    generator_flags = [
        r
        for r in (
            await db.execute(
                select(B2BRegisterImportRow).where(
                    B2BRegisterImportRow.run_id == run.id,
                    B2BRegisterImportRow.decision.in_(
                        ("generator_match", "generator_conflict")
                    ),
                )
            )
        )
        .scalars()
        .all()
        if isinstance(r.snapshot_before, dict)
        and "needs_business_data_annex" in r.snapshot_before
    ]
    # Ręczna zmiana statusu w NEXUSIE po imporcie (PATCH, skutek podpisanego
    # dokumentu) zostawia wpis w dzienniku statusów — import go nie pisze.
    # Taki status wygrywa z cofnięciem, jak wygrywa z plikiem.
    touched_ids = {r.generated_contract_id for r in rows if r.generated_contract_id}
    # Blokada wierszy przed odczytem dziennika statusów: PATCH w trakcie
    # cofnięcia czeka na jego koniec, zamiast zostać nadpisany (runda 7, N3-10).
    locked_ids = touched_ids | {
        r.generated_contract_id for r in generator_flags if r.generated_contract_id
    }
    if locked_ids:
        await db.execute(
            select(B2BGeneratedContract.id)
            .where(B2BGeneratedContract.id.in_(locked_ids))
            .with_for_update()
        )
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
    # Zmiany z podpisanych po imporcie dokumentów zostają (runda 6 audytu, XLS-1).
    document_owned = await _document_owned_columns(
        db, list(touched_ids), since=run.created_at
    )
    for import_row in rows:
        if import_row.decision != "updated" or not import_row.snapshot_before:
            continue
        target = await db.get(B2BGeneratedContract, import_row.generated_contract_id)
        if target is None or target.source != "excel":
            continue
        manual_status = target.id in changed_by_hand
        keep = document_owned.get(target.id, set()) | await _missing_foreign_keys(
            db, import_row.snapshot_before
        )
        for column, value in import_row.snapshot_before.items():
            if manual_status and column in _STATUS_COLUMNS:
                continue
            if column in keep:
                continue
            setattr(target, column, _from_json(column, value))
        restored += 1
    for import_row in generator_flags:
        target = await db.get(B2BGeneratedContract, import_row.generated_contract_id)
        if target is None or target.source == "excel":
            continue
        target.needs_business_data_annex = bool(
            import_row.snapshot_before["needs_business_data_annex"]
        )
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
