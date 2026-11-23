"""Dane firm z umów (E5a, 0755): wybór pliku, odczyt, decyzja, sprawdzenie w rejestrze.

* ``scan`` / ``read_document_row`` — aktywne kontrakty B2B bez danych firmy
  Partnera w Generatorze i główny plik umowy każdego z nich (pętla w workerze).
* ``apply_read`` — „Zastosuj”: dane potwierdzone przez człowieka (z poprawkami)
  trafiają do ``confirmed``, a do profilu kandydata tylko w puste kolumny;
  wpisaną wartość zmienia wyłącznie jawne ``overwrite``.
* ``dismiss_read`` — „Odrzuć”: odczyt nie bierze udziału w niczym dalej.
* ``verify_read`` — „Sprawdź w rejestrze”: CEIDG albo KRS na żądanie człowieka.
  Rejestry mają limity (biznes.gov.pl tylko dla pojedynczych zapytań, biała
  lista MF 100 dziennie na całą firmę), więc pętla ich nie woła.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import PurePath
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_partner_read import ContractPartnerRead
from app.models.user import User
from app.services import storage_service
from app.services.contract_document_folders import (
    ContractNumber,
    parse_contract_number,
)
from app.services.contract_partner_reads import reader

logger = logging.getLogger(__name__)

#: Pole odczytu → kolumna kandydata, z której Generator wypełnia formularz.
CANDIDATE_COLUMNS: dict[str, str] = {
    "partner_legal_name": "legal_name",
    "partner_nip": "nip",
    "partner_regon": "regon",
    "partner_business_address": "business_address",
    "partner_email": "email",
    "partner_phone": "phone",
}
#: Kontakt trafia tylko w puste pole, także przy „Nadpisz”: e-mail to klucz
#: tożsamości osoby („ta sama osoba = ten sam e-mail”), a e-mail i telefon
#: synchronizuje Traffit. Inny kontakt z umowy zostaje w ``confirmed``.
FILL_ONLY_COLUMNS: frozenset[str] = frozenset({"email", "phone"})
_NUMBER_COLUMNS: frozenset[str] = frozenset({"nip", "regon"})
#: Ponowne „Sprawdź w rejestrze” w tym czasie oddaje zapisany wynik.
VERIFY_REUSE = timedelta(minutes=10)
STATES: tuple[str, ...] = ("open", "failed", "applied", "dismissed")

_REGISTRY_FIELDS: tuple[tuple[str, str], ...] = (
    ("partner_legal_name", "name"),
    ("partner_name", "person"),
    ("partner_nip", "nip"),
    ("partner_regon", "regon"),
    ("partner_krs", "krs"),
    ("partner_business_address", "address"),
    ("partner_entity_type", "entity_type"),
)


class PartnerReadError(Exception):
    """Odmowa z komunikatem dla człowieka (trasa zamienia ją na 409/422)."""

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DocumentRow:
    id: int
    contract_id: int
    filename: str
    file_path: str
    content_type: Optional[str]
    content_sha256: Optional[str]


@dataclass(frozen=True)
class Scan:
    """Stan teczek: pliki do odczytu i kontrakty, w których nie ma czego czytać."""

    pending: list[DocumentRow] = field(default_factory=list)
    eligible: int = 0
    without_file: int = 0


# ── Wybór pliku ──────────────────────────────────────────────────────────────


_READABLE_SUFFIXES = frozenset({".pdf", ".jpg", ".jpeg", ".png"})


def _readable(doc: DocumentRow) -> bool:
    """PDF albo zdjęcie. Rozszerzenie wygrywa z typem z wgrania („.docx” jako PDF)."""

    suffix = PurePath(doc.filename or "").suffix.lower()
    if suffix and suffix not in _READABLE_SUFFIXES:
        return False
    return reader.mime_for(doc.filename, doc.content_type) is not None


def pick_main_document(
    docs: Sequence[DocumentRow], current: Optional[ContractNumber]
) -> Optional[DocumentRow]:
    """Główny plik umowy z sekcji „Aktualna umowa” (bez folderu).

    Plik z numerem bieżącej umowy (dane umowy B2B albo Generatora) wygrywa;
    bez niego najnowszy numer z nazwy pliku. PDF przed zdjęciem (zdjęcie bywa
    jedną stroną), potem nowszy plik. DOCX pomijamy — to wersja robocza
    z Generatora, bez podpisu.
    """

    readable = [d for d in docs if _readable(d)]
    if current is not None:
        matching = [d for d in readable if parse_contract_number(d.filename) == current]
        readable = matching or readable

    def rank(doc: DocumentRow) -> tuple[int, int, int, int]:
        number = parse_contract_number(doc.filename) or (0, 0)
        is_pdf = reader.mime_for(doc.filename, doc.content_type) == "application/pdf"
        return number[1], number[0], int(is_pdf), doc.id

    return max(readable, key=rank, default=None)


def _has_generator_partner_data():
    """Wiersz Generatora z danymi firmy Partnera dla kontraktu albo jego osoby."""

    generated = B2BGeneratedContract
    return exists().where(
        generated.render_payload.is_not(None),
        func.coalesce(generated.render_payload["partner_nip"].as_string(), "") != "",
        or_(
            generated.contract_id == Contract.id,
            and_(
                Contract.candidate_id.is_not(None),
                generated.candidate_id == Contract.candidate_id,
            ),
        ),
    )


def eligible_contracts(client_ids: Optional[frozenset[int]] = None):
    """Aktywne kontrakty B2B z osobą, bez danych firmy w Generatorze."""

    query = select(Contract.id).where(
        Contract.status == ContractStatus.active,
        Contract.contract_type == ContractType.b2b,
        Contract.candidate_id.is_not(None),
        ~_has_generator_partner_data(),
    )
    if client_ids is not None:
        query = query.where(Contract.client_id.in_(list(client_ids)))
    return query


async def _current_numbers(
    db: AsyncSession, contract_ids: Sequence[int]
) -> dict[int, ContractNumber]:
    """Numer bieżącej umowy na raz dla wszystkich kontraktów.

    Ta sama kolejność co ``contract_document_folders._current_contract_number``:
    dane umowy B2B, a bez nich najnowszy wiersz Generatora.
    """

    if not contract_ids:
        return {}
    out: dict[int, ContractNumber] = {}
    generated = (
        await db.execute(
            select(
                B2BGeneratedContract.contract_id, B2BGeneratedContract.contract_number
            )
            .where(B2BGeneratedContract.contract_id.in_(list(contract_ids)))
            .order_by(B2BGeneratedContract.created_at)
        )
    ).all()
    for contract_id, number in generated:
        parsed = parse_contract_number(number)
        if parsed:
            out[contract_id] = parsed
    details = (
        await db.execute(
            select(
                B2BContractDetail.contract_id, B2BContractDetail.contract_number
            ).where(B2BContractDetail.contract_id.in_(list(contract_ids)))
        )
    ).all()
    for contract_id, number in details:
        parsed = parse_contract_number(number)
        if parsed:
            out[contract_id] = parsed
    return out


async def scan(db: AsyncSession, client_ids: Optional[frozenset[int]] = None) -> Scan:
    """Pliki do odczytu bieżącą wersją czytnika, od najnowszego pliku.

    Plik z odczytem tą wersją albo z decyzją człowieka (dowolną wersją) jest
    gotowy. Nowy plik umowy w kontrakcie wygrywa wybór i czeka na odczyt.
    """

    contract_ids = list((await db.execute(eligible_contracts(client_ids))).scalars())
    if not contract_ids:
        return Scan()
    read = ContractPartnerRead
    done = exists().where(
        read.contract_document_id == ContractDocument.id,
        or_(read.reader_version == reader.READER_VERSION, read.decision.is_not(None)),
    )
    rows = (
        await db.execute(
            select(
                ContractDocument.id,
                ContractDocument.contract_id,
                ContractDocument.filename,
                ContractDocument.file_path,
                ContractDocument.content_type,
                ContractDocument.content_sha256,
                done,
            ).where(
                ContractDocument.contract_id.in_(eligible_contracts(client_ids)),
                ContractDocument.doc_type == ContractDocumentType.contract,
                ContractDocument.folder_id.is_(None),
            )
        )
    ).all()
    by_contract: dict[int, list[DocumentRow]] = {}
    finished: set[int] = set()
    for *values, is_done in rows:
        doc = DocumentRow(*values)
        by_contract.setdefault(doc.contract_id, []).append(doc)
        if is_done:
            finished.add(doc.id)
    numbers = await _current_numbers(db, list(by_contract))
    pending: list[DocumentRow] = []
    without_file = 0
    for contract_id in contract_ids:
        main = pick_main_document(
            by_contract.get(contract_id, []), numbers.get(contract_id)
        )
        if main is None:
            without_file += 1
        elif main.id not in finished:
            pending.append(main)
    pending.sort(key=lambda d: d.id, reverse=True)
    return Scan(pending=pending, eligible=len(contract_ids), without_file=without_file)


# ── Odczyt ───────────────────────────────────────────────────────────────────


async def read_document_row(db: AsyncSession, doc: DocumentRow) -> ContractPartnerRead:
    """Odczyt jednego pliku i zapis wiersza (bez commita)."""

    from app.services.ai_quota import ai_feature  # noqa: PLC0415 — cykl importów

    mime = reader.mime_for(doc.filename, doc.content_type)
    result = reader.ReadResult("skipped")
    sha = doc.content_sha256
    if mime is not None:
        try:
            content = storage_service.get_contract_document_path(
                doc.file_path
            ).read_bytes()
        except (FileNotFoundError, OSError):
            content = None
        if content is not None:
            sha = sha or hashlib.sha256(content).hexdigest()
            async with ai_feature(db, AIFeatureKey.contract_partner_read):
                await db.commit()  # połączenie wraca do puli na czas modelu
                result = await reader.read_document(content, mime, doc.filename)
    row = ContractPartnerRead(
        contract_document_id=doc.id,
        contract_id=doc.contract_id,
        content_sha256=sha,
        reader_version=reader.READER_VERSION,
        status=result.status,
        result=result.as_json(),
    )
    db.add(row)
    await db.flush()
    return row


# ── Decyzja człowieka ────────────────────────────────────────────────────────


def _filled(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _comparable(column: str, value: Any) -> str:
    text = "" if value is None else str(value)
    if column in _NUMBER_COLUMNS:
        digits = "".join(ch for ch in text if ch.isdigit())
        # 14-cyfrowy REGON z „00000” na końcu to ten sam 9-cyfrowy.
        return digits[:9] if len(digits) == 14 and digits.endswith("00000") else digits
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def plan_candidate_changes(
    current: Mapping[str, Any],
    confirmed: Mapping[str, Any],
    *,
    overwrite: bool,
) -> dict[str, dict[str, Any]]:
    """Co zrobić z każdą kolumną kandydata (czysta funkcja, bez bazy).

    ``written`` — zapis; ``same`` — profil ma już tę wartość; ``kept`` — profil
    ma inną wartość i zostaje (bez ``overwrite`` albo kolumna kontaktu);
    ``no_value`` — w potwierdzonych danych nie ma tego pola.
    """

    plan: dict[str, dict[str, Any]] = {}
    for name, column in CANDIDATE_COLUMNS.items():
        new, old = confirmed.get(name), current.get(column)
        if new is None:
            plan[column] = {"action": "no_value"}
        elif _filled(old) and _comparable(column, old) == _comparable(column, new):
            plan[column] = {"action": "same"}
        elif not _filled(old):
            plan[column] = {"action": "written", "value": new}
        elif overwrite and column not in FILL_ONLY_COLUMNS:
            plan[column] = {"action": "written", "value": new, "previous": old}
        else:
            plan[column] = {"action": "kept"}
    return plan


def confirmed_values(
    result: Mapping[str, Any], corrections: Optional[Mapping[str, Any]]
) -> tuple[dict[str, Optional[str]], list[str]]:
    """Wartości z odczytu z poprawkami człowieka i lista poprawionych pól.

    Poprawka przechodzi te same reguły co odczyt (``reader.clean_value``);
    zła wartość to odmowa z nazwą pola, nie cichy zapis.
    """

    fields = result.get("fields") or {}
    values: dict[str, Optional[str]] = {
        name: (fields.get(name) or {}).get("value") for name in reader.FIELDS
    }
    corrected: list[str] = []
    for name, raw in (corrections or {}).items():
        if name not in reader.FIELDS:
            raise PartnerReadError(f"Nieznane pole „{name}”.", status_code=422)
        value, issue = reader.clean_value(name, raw)
        if issue:
            raise PartnerReadError(f"{reader.LABELS[name]}: {issue}", status_code=422)
        if value != values.get(name):
            corrected.append(name)
        values[name] = value
    return values, sorted(corrected)


async def _locked_row(
    db: AsyncSession, read_id: int, client_ids: Optional[frozenset[int]]
) -> tuple[ContractPartnerRead, Contract]:
    row = await db.get(
        ContractPartnerRead, read_id, with_for_update=True, populate_existing=True
    )
    contract = await db.get(Contract, row.contract_id) if row else None
    if (
        row is None
        or contract is None
        or (client_ids is not None and contract.client_id not in client_ids)
    ):
        raise PartnerReadError("Nie ma takiego odczytu umowy.", status_code=404)
    return row, contract


async def apply_read(
    db: AsyncSession,
    read_id: int,
    *,
    user: User,
    overwrite: bool = False,
    corrections: Optional[Mapping[str, Any]] = None,
    client_ids: Optional[frozenset[int]] = None,
) -> ContractPartnerRead:
    """„Zastosuj”: zapis potwierdzenia i pustych kolumn kandydata (bez commita)."""

    from app.services.candidate_identity_ownership import (  # noqa: PLC0415
        lock_changed_traffit_synced_fields,
    )
    from app.services.dedup_service import find_candidate_by_email  # noqa: PLC0415

    row, contract = await _locked_row(db, read_id, client_ids)
    if row.decision is not None:
        raise PartnerReadError("Ten odczyt jest już rozstrzygnięty.")
    if row.status != "read":
        raise PartnerReadError(
            "Odczyt tej umowy się nie udał — wpisz dane firmy w profilu kandydata."
        )
    if contract.candidate_id is None:
        raise PartnerReadError(
            "Kontrakt nie ma kandydata — nie ma gdzie zapisać danych."
        )
    values, corrected = confirmed_values(row.result or {}, corrections)
    candidate = (
        await db.execute(
            select(Candidate)
            .where(Candidate.id == contract.candidate_id)
            .with_for_update()
        )
    ).scalar_one()
    plan = plan_candidate_changes(
        {column: getattr(candidate, column) for column in CANDIDATE_COLUMNS.values()},
        values,
        overwrite=overwrite,
    )
    email = plan["email"]
    if email["action"] == "written" and await find_candidate_by_email(
        db, email["value"], exclude_candidate_id=candidate.id
    ):
        plan["email"] = {"action": "taken"}
    updates = {
        column: change["value"]
        for column, change in plan.items()
        if change["action"] == "written"
    }
    # Kontakt potwierdzony przez człowieka nie wraca przy nocnym syncu
    # Traffita — ta sama blokada co przy ręcznej edycji profilu.
    lock_changed_traffit_synced_fields(candidate, updates, user_id=user.id)
    for column, value in updates.items():
        setattr(candidate, column, value)
    entity_type = values.get("partner_entity_type")
    row.decision = "applied"
    row.confirmed = {
        "fields": values,
        "contract_variant": {"company": "company", "sole_trader": "jdg"}.get(
            entity_type or ""
        ),
        "corrected": corrected,
        "overwrite": overwrite,
    }
    row.candidate_changes = plan
    row.decided_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="partner_data_from_contract",
            user_id=user.id,
            details={
                "contract_id": contract.id,
                "document_id": row.contract_document_id,
                "read_id": row.id,
                "fields": sorted(updates),
                "corrected": corrected,
            },
        )
    )
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        if "email" in str(exc.orig):
            raise PartnerReadError(
                "Kandydat z tym adresem e-mail już istnieje."
            ) from exc
        raise
    return row


async def dismiss_read(
    db: AsyncSession,
    read_id: int,
    *,
    user: User,
    client_ids: Optional[frozenset[int]] = None,
) -> ContractPartnerRead:
    row, _ = await _locked_row(db, read_id, client_ids)
    if row.decision == "applied":
        raise PartnerReadError(
            "Dane z tej umowy są już zastosowane — zmień je w profilu kandydata."
        )
    row.decision = "dismissed"
    row.decided_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    await db.flush()
    return row


# ── Rejestr na żądanie ───────────────────────────────────────────────────────


def _registry_comparable(name: str, value: Any) -> str:
    column = CANDIDATE_COLUMNS.get(name, "")
    if name == "partner_krs":
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return digits.lstrip("0")
    return _comparable(column, value)


def compare_with_registry(
    values: Mapping[str, Any], company: Optional[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Pole z umowy obok pola z rejestru — tylko tam, gdzie rejestr coś podał."""

    out: list[dict[str, Any]] = []
    for name, key in _REGISTRY_FIELDS:
        registry_value = (company or {}).get(key)
        if not _filled(registry_value):
            continue
        read_value = values.get(name)
        out.append(
            {
                "field": name,
                "read": read_value,
                "registry": registry_value,
                "same": _filled(read_value)
                and _registry_comparable(name, read_value)
                == _registry_comparable(name, registry_value),
            }
        )
    return out


async def verify_read(
    db: AsyncSession,
    read_id: int,
    *,
    client_ids: Optional[frozenset[int]] = None,
    corrections: Optional[Mapping[str, Any]] = None,
) -> ContractPartnerRead:
    """„Sprawdź w rejestrze” po NIP-ie albo KRS z odczytu (z poprawkami człowieka)."""

    from app.services.b2b_contract_generator.registry_verification import (  # noqa: PLC0415
        verify_company,
    )

    row, _ = await _locked_row(db, read_id, client_ids)
    if row.status != "read":
        raise PartnerReadError(
            "Odczyt tej umowy się nie udał — nie ma czego sprawdzić."
        )
    values, _corrected = confirmed_values(row.result or {}, corrections)
    nip, krs = values.get("partner_nip"), values.get("partner_krs")
    if not nip and not krs:
        raise PartnerReadError(
            "W odczycie nie ma poprawnego NIP-u ani KRS — wpisz NIP i sprawdź ponownie.",
            status_code=422,
        )
    now = datetime.now(timezone.utc)
    previous = row.verification or {}
    if (
        row.verified_at is not None
        and now - row.verified_at < VERIFY_REUSE
        and previous.get("query") == {"nip": nip, "krs": krs}
    ):
        return row
    await db.commit()  # bez blokady wiersza na czas zapytań do rejestru (do 30 s)
    result = await verify_company(nip=nip, krs=krs)
    row, _ = await _locked_row(db, read_id, client_ids)
    row.verification = {
        **result,
        "query": {"nip": nip, "krs": krs},
        "comparison": compare_with_registry(values, result.get("company")),
    }
    row.verified_at = now
    await db.flush()
    return row


# ── Lista ────────────────────────────────────────────────────────────────────


def _state_clause(state: str):
    read = ContractPartnerRead
    current = read.reader_version == reader.READER_VERSION
    if state == "open":
        return and_(current, read.status == "read", read.decision.is_(None))
    if state == "failed":
        return and_(current, read.status != "read", read.decision.is_(None))
    return read.decision == state


async def _views(db: AsyncSession, query) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            query.add_columns(
                Contract, Candidate, Client.name, ContractDocument.filename
            )
            .join(Contract, Contract.id == ContractPartnerRead.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .outerjoin(
                ContractDocument,
                ContractDocument.id == ContractPartnerRead.contract_document_id,
            )
        )
    ).all()
    return [
        view(
            row,
            contract=contract,
            candidate=candidate,
            client_name=client,
            filename=filename,
        )
        for row, contract, candidate, client, filename in rows
    ]


async def read_view(db: AsyncSession, read_id: int) -> dict[str, Any]:
    """Jeden odczyt w kształcie listy (odpowiedź po decyzji)."""

    [item] = await _views(
        db, select(ContractPartnerRead).where(ContractPartnerRead.id == read_id)
    )
    return item


async def list_reads(
    db: AsyncSession,
    *,
    state: str,
    client_ids: Optional[frozenset[int]] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Odczyty w stanie ``state`` z kontraktem, osobą, klientem i plikiem."""

    base = (
        select(ContractPartnerRead.id)
        .join(Contract, Contract.id == ContractPartnerRead.contract_id)
        .where(_state_clause(state))
    )
    if state in ("open", "failed"):
        base = base.where(Contract.status == ContractStatus.active)
    if client_ids is not None:
        base = base.where(Contract.client_id.in_(list(client_ids)))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = await _views(
        db,
        select(ContractPartnerRead)
        .where(ContractPartnerRead.id.in_(base))
        .order_by(ContractPartnerRead.id.desc())
        .limit(limit)
        .offset(offset),
    )
    return items, int(total)


async def counts(
    db: AsyncSession, client_ids: Optional[frozenset[int]] = None
) -> dict[str, int]:
    """Liczniki zakładek i stan teczek (do odczytu, bez pliku umowy)."""

    out: dict[str, int] = {}
    for state in STATES:
        query = (
            select(func.count(ContractPartnerRead.id))
            .join(Contract, Contract.id == ContractPartnerRead.contract_id)
            .where(_state_clause(state))
        )
        if state in ("open", "failed"):
            query = query.where(Contract.status == ContractStatus.active)
        if client_ids is not None:
            query = query.where(Contract.client_id.in_(list(client_ids)))
        out[state] = int(await db.scalar(query) or 0)
    folders = await scan(db, client_ids)
    out["to_read"] = len(folders.pending)
    out["without_file"] = folders.without_file
    out["eligible"] = folders.eligible
    return out


def _candidate_name(candidate: Optional[Candidate]) -> Optional[str]:
    if candidate is None:
        return None
    return " ".join(p for p in (candidate.name, candidate.lastname) if p) or None


def view(
    row: ContractPartnerRead,
    *,
    contract: Optional[Contract] = None,
    candidate: Optional[Candidate] = None,
    client_name: Optional[str] = None,
    filename: Optional[str] = None,
) -> dict[str, Any]:
    """Odczyt dla ekranu: pola z cytatami obok bieżącej wartości w profilu."""

    result = row.result or {}
    fields = result.get("fields") or {}
    columns = CANDIDATE_COLUMNS
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "document_id": row.contract_document_id,
        "filename": filename,
        "status": row.status,
        "mode": result.get("mode"),
        "read_at": row.created_at.isoformat() if row.created_at else None,
        "document_kind": result.get("document_kind"),
        "agreement_number": result.get("agreement_number"),
        "document_date": result.get("document_date"),
        "contract_variant": result.get("contract_variant"),
        "client_name": client_name,
        "contract_status": getattr(getattr(contract, "status", None), "value", None),
        "candidate_id": contract.candidate_id if contract else None,
        "candidate_name": _candidate_name(candidate),
        "fields": [
            {
                "name": name,
                "value": (fields.get(name) or {}).get("value"),
                "quote": (fields.get(name) or {}).get("quote"),
                "quote_found": (fields.get(name) or {}).get("quote_found"),
                "column": columns.get(name),
                "current": getattr(candidate, columns[name], None)
                if candidate is not None and name in columns
                else None,
            }
            for name in reader.FIELDS
        ],
        "issues": result.get("issues") or [],
        "decision": row.decision,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "confirmed": row.confirmed,
        "candidate_changes": row.candidate_changes,
        "verification": row.verification,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
    }
