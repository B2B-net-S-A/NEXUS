"""Masowa wysyłka nowej umowy B2B (E5b): plan, paczka, wiersze Generatora, wysyłka.

* ``collect`` — aktywne kontrakty B2B (jedna pozycja na osobę), dane umowy
  i ocena każdej osoby (``readiness.assess``). Tylko odczyt; czyta to podgląd,
  próba bez wysyłki i założenie paczki.
* ``create_batch`` — paczka z pozycjami: gotowe ``pending``, reszta
  ``needs_review`` / ``skipped`` z powodem. Wymaga podpiętego nowego wzoru.
* ``process_item`` — pętla w workerze: wiersz Generatora tą samą drogą co
  „Pobierz DOCX” (``issue_standalone_contract``: numer, plik, wiersz), potem
  wysyłka do podpisu drogą „Wyślij do podpisu” (``open_signing_request``
  i mail ze skrzynki osoby, która zaczęła paczkę). Przełącznik „nowy wzór
  podpięty” sprawdza się jeszcze raz przed każdym krokiem.

Kto może: ten, kto mógłby wysłać obecną umowę tej osoby do podpisu
(``b2b_esign._assert_row_sender`` na jej wierszu Generatora), z włączonym
podpisem w NEXUSIE. Paczka nie otwiera stawek cudzych umów: nowy wiersz ma
autora = osobę, która zaczęła paczkę, więc bez tej bramki wystarczyłoby
zacząć paczkę, żeby zostać autorem 600 umów ze stawkami.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from fastapi import HTTPException
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.b2b_contract_document import B2BContractDocument
from app.models.b2b_contract_role import B2BContractRole
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_mass_send import B2BMassSendBatch, B2BMassSendItem
from app.models.b2b_signing_request import OPEN_STATUSES, B2BSigningRequest
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_partner_read import ContractPartnerRead
from app.models.user import User
from app.services.b2b_mass_send import readiness
from app.services.b2b_mass_send import settings as mass_settings
from app.services.b2b_mass_send.readiness import Assessment, Person, Source
from app.services.b2b_mass_send.schema_sql import ITEM_STATUSES, LIVE_ITEM_STATUSES

logger = logging.getLogger(__name__)

#: Ile pozycji przechodzi jeden bieg pętli (mail ze skrzynki osoby — limity M365).
CHUNK = 50
#: Wzór, na którym powstają umowy, dopóki nowy nie jest w kodzie.
TEMPLATE_LABEL = "Umowa B2B, obecny wzór Generatora"
#: Ile razy ponawiamy numer zajęty w międzyczasie przez kogoś w Generatorze.
MAX_NUMBER_ATTEMPTS = 3

MSG_TEMPLATE_NOT_READY = (
    "Nowy wzór umowy nie jest jeszcze podpięty, więc do kontraktorów nic nie "
    "wychodzi. Podgląd i próba bez wysyłki działają. Wysyłkę odblokuje admin, "
    "gdy nowy wzór będzie gotowy."
)
MSG_WORKER_OFF = (
    "Wysyłka w tle jest wyłączona na serwerze, więc paczka by nie ruszyła. "
    "Poproś admina o włączenie."
)
MSG_RUNNING = "Poprzednia masowa wysyłka jeszcze trwa. Poczekaj na jej koniec."
MSG_NOTHING_READY = "Nie ma nikogo gotowego do wysyłki."
MSG_NO_MAILBOX = (
    "Skrzynka Microsoft 365 osoby, która zaczęła wysyłkę, nie jest połączona "
    "z NEXUSEM, więc mail z linkiem by nie wyszedł."
)
MSG_STARTER_GONE = "Konto osoby, która zaczęła wysyłkę, nie jest już aktywne."
MSG_NOT_AVAILABLE = (
    "Osoba nie ma już aktywnego kontraktu B2B albo osoba, która zaczęła "
    "wysyłkę, nie może już wysłać jej umowy."
)
MSG_ROW_GONE = "Wiersz umowy w rejestrze usunięto przed wysyłką."
MSG_BAD_EMAIL = "Adres e-mail kontraktora jest nieprawidłowy."
MSG_CANCELLED = "Wysyłkę zatrzymano."
MSG_MAIL_FAILED = "Mail z linkiem nie wyszedł, wysyłkę tej osoby wycofano."
MSG_PREPARE_FAILED = "Nie udało się przygotować umowy. Spróbuj z Generatora."

_EMAIL = TypeAdapter(EmailStr)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Zbieranie osób ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Planned:
    person: Person
    source: Optional[Source]
    assessment: Assessment
    source_created_by: Optional[int] = None


def _mass_send_rows():
    """Wiersz Generatora założony przez masową wysyłkę (nie jest „starą umową”)."""
    return exists().where(
        B2BMassSendItem.generated_contract_id == B2BGeneratedContract.id
    )


async def _people(
    db: AsyncSession, candidate_ids: Optional[Sequence[int]]
) -> dict[int, list[tuple[Contract, str, Optional[str], str]]]:
    """Aktywne kontrakty B2B po osobie: (kontrakt, imię i nazwisko, e-mail, klient)."""
    query = (
        select(
            Contract,
            Candidate.name,
            Candidate.lastname,
            Candidate.email,
            Client.name,
            Client.display_name,
        )
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .join(Client, Client.id == Contract.client_id)
        .where(
            Contract.status == ContractStatus.active,
            Contract.contract_type == ContractType.b2b,
            Contract.candidate_id.is_not(None),
        )
        .order_by(
            Contract.candidate_id,
            Contract.start_date.desc().nulls_last(),
            Contract.id.desc(),
        )
    )
    if candidate_ids is not None:
        query = query.where(Contract.candidate_id.in_(list(candidate_ids)))
    out: dict[int, list[tuple[Contract, str, Optional[str], str]]] = defaultdict(list)
    for contract, first, last, email, client, display in (
        await db.execute(query)
    ).all():
        name = " ".join(p for p in (first, last) if p).strip() or "—"
        out[contract.candidate_id].append(
            (contract, name, email, (display or "").strip() or client)
        )
    return out


async def _sources(
    db: AsyncSession, contract_ids: list[int], candidate_ids: list[int]
) -> list[B2BGeneratedContract]:
    """Podpisane wiersze Generatora tych osób albo kontraktów, od najnowszego."""
    generated = B2BGeneratedContract
    return list(
        (
            await db.scalars(
                select(generated)
                .where(
                    generated.render_payload.is_not(None),
                    generated.source == "generator",
                    or_(
                        generated.contract_kind.is_(None),
                        generated.contract_kind != "mandate",
                    ),
                    generated.signature_status == "signed_both",
                    generated.contract_status != "cancelled",
                    or_(
                        generated.contract_id.in_(contract_ids),
                        generated.candidate_id.in_(candidate_ids),
                    ),
                    ~_mass_send_rows(),
                )
                .order_by(generated.created_at.desc(), generated.id.desc())
            )
        ).all()
    )


async def _pending_drafts(db: AsyncSession, candidate_ids: list[int]) -> set[int]:
    generated = B2BGeneratedContract
    return set(
        (
            await db.scalars(
                select(generated.candidate_id).where(
                    generated.candidate_id.in_(candidate_ids),
                    generated.contract_status == "in_progress",
                    generated.signature_status != "signed_both",
                    ~_mass_send_rows(),
                )
            )
        ).all()
    )


async def _open_requests(db: AsyncSession, candidate_ids: list[int]) -> set[int]:
    return set(
        (
            await db.scalars(
                select(B2BGeneratedContract.candidate_id)
                .join(
                    B2BSigningRequest,
                    B2BSigningRequest.generated_contract_id == B2BGeneratedContract.id,
                )
                .where(
                    B2BGeneratedContract.candidate_id.in_(candidate_ids),
                    B2BSigningRequest.status.in_(OPEN_STATUSES),
                )
            )
        ).all()
    )


async def _live_items(
    db: AsyncSession, candidate_ids: list[int], exclude_item_id: Optional[int]
) -> dict[int, int]:
    query = select(B2BMassSendItem.candidate_id, B2BMassSendItem.batch_id).where(
        B2BMassSendItem.candidate_id.in_(candidate_ids),
        B2BMassSendItem.status.in_(LIVE_ITEM_STATUSES),
    )
    if exclude_item_id is not None:
        query = query.where(B2BMassSendItem.id != exclude_item_id)
    return {cid: bid for cid, bid in (await db.execute(query)).all()}


async def _confirmed(db: AsyncSession, contract_ids: list[int]) -> dict[int, dict]:
    rows = await db.execute(
        select(ContractPartnerRead.contract_id, ContractPartnerRead.confirmed)
        .where(
            ContractPartnerRead.contract_id.in_(contract_ids),
            ContractPartnerRead.decision == "applied",
            ContractPartnerRead.confirmed.is_not(None),
        )
        .order_by(ContractPartnerRead.decided_at.desc(), ContractPartnerRead.id.desc())
    )
    out: dict[int, dict] = {}
    for contract_id, confirmed in rows.all():
        out.setdefault(contract_id, confirmed)
    return out


async def _with_annex(db: AsyncSession, source_ids: list[int]) -> set[int]:
    if not source_ids:
        return set()
    return set(
        (
            await db.scalars(
                select(B2BContractDocument.parent_generated_contract_id).where(
                    B2BContractDocument.parent_generated_contract_id.in_(source_ids),
                    B2BContractDocument.document_type.like("annex%"),
                    B2BContractDocument.status != "cancelled",
                )
            )
        ).all()
    )


async def _scheduled_rates(
    db: AsyncSession, contract_ids: list[int], today: date
) -> dict[int, Decimal]:
    """Stawka z harmonogramu kontraktu, która obowiązuje dziś."""
    rows = await db.execute(
        select(ContractCandidateRate.contract_id, ContractCandidateRate.rate)
        .where(
            ContractCandidateRate.contract_id.in_(contract_ids),
            ContractCandidateRate.effective_from <= today,
            or_(
                ContractCandidateRate.effective_to.is_(None),
                ContractCandidateRate.effective_to >= today,
            ),
        )
        .order_by(ContractCandidateRate.effective_from.desc())
    )
    out: dict[int, Decimal] = {}
    for contract_id, rate in rows.all():
        out.setdefault(contract_id, rate)
    return out


def _person(
    contract: Contract,
    name: str,
    email: Optional[str],
    client_name: str,
    *,
    rate: Optional[Decimal],
    contracts: int,
) -> Person:
    unit = contract.rate_unit.value if contract.rate_unit is not None else None
    return Person(
        contract_id=contract.id,
        candidate_id=contract.candidate_id,
        candidate_name=name,
        client_id=contract.client_id,
        client_name=client_name,
        job_id=contract.job_id,
        start_date=contract.start_date,
        end_date=contract.end_date,
        agreement_last_day=contract.agreement_last_day,
        rate=rate if rate is not None else contract.rate_candidate,
        rate_unit=unit,
        currency=contract.rate_candidate_currency or contract.currency,
        is_replacement=contract.is_replacement,
        replaced_contract_id=contract.replaced_contract_id,
        fte=contract.fte,
        is_client_referral=contract.is_client_referral,
        candidate_email=email,
        active_b2b_contracts=contracts,
    )


async def may_send_for(
    db: AsyncSession,
    user: User,
    person: Person,
    source_row: Optional[B2BGeneratedContract],
) -> bool:
    """Ta sama reguła co „Wyślij do podpisu” (``_assert_row_sender``) na obecnej
    umowie tej osoby; bez wiersza Generatora — na wierszu o kliencie
    i rekrutacji kontraktu, bez autora (nikt nie jest autorem)."""
    from app.api.b2b_esign import _may_send  # noqa: PLC0415 — router importuje serwis

    probe = source_row
    if probe is None:
        probe = B2BGeneratedContract(
            client_id=person.client_id,
            job_id=person.job_id,
            created_by=None,
            contract_status="in_progress",
            signature_status="unsigned",
        )
    return await _may_send(db, user, probe)


async def collect(
    db: AsyncSession,
    user: User,
    *,
    today: date,
    skip_ending: bool,
    candidate_ids: Optional[Sequence[int]] = None,
    exclude_item_id: Optional[int] = None,
) -> list[Planned]:
    """Każda osoba z aktywnym kontraktem B2B, którą ``user`` mógłby wysłać,
    z oceną. Bez zapisów."""
    people = await _people(db, candidate_ids)
    if not people:
        return []
    cand_ids = list(people)
    contract_ids = [c.id for group in people.values() for c, *_ in group]
    sources = await _sources(db, contract_ids, cand_ids)
    by_contract: dict[int, B2BGeneratedContract] = {}
    by_candidate: dict[int, B2BGeneratedContract] = {}
    for row in sources:
        if row.contract_id is not None:
            by_contract.setdefault(row.contract_id, row)
        if row.candidate_id is not None:
            by_candidate.setdefault(row.candidate_id, row)
    drafts = await _pending_drafts(db, cand_ids)
    open_requests = await _open_requests(db, cand_ids)
    live = await _live_items(db, cand_ids, exclude_item_id)
    confirmed = await _confirmed(db, contract_ids)
    rates = await _scheduled_rates(db, contract_ids, today)
    role_ids = frozenset((await db.scalars(select(B2BContractRole.id))).all())

    picked: list[tuple[Person, Optional[B2BGeneratedContract], Optional[dict]]] = []
    for candidate_id, group in people.items():
        # Kontrakt z ostatnią podpisaną umową wygrywa; inaczej najnowszy start.
        candidates = [by_contract[c.id] for c, *_ in group if c.id in by_contract]
        if candidate_id in by_candidate:
            candidates.append(by_candidate[candidate_id])
        source_row = max(candidates, key=lambda r: (r.created_at, r.id), default=None)
        contract, name, email, client_name = next(
            (
                entry
                for entry in group
                if source_row is not None and entry[0].id == source_row.contract_id
            ),
            group[0],
        )
        person = _person(
            contract,
            name,
            email,
            client_name,
            rate=rates.get(contract.id),
            contracts=len(group),
        )
        person_confirmed = confirmed.get(contract.id) or next(
            (confirmed[c.id] for c, *_ in group if c.id in confirmed), None
        )
        picked.append((person, source_row, person_confirmed))

    source_ids = [row.id for _, row, _ in picked if row is not None]
    annexed = await _with_annex(db, source_ids)
    out: list[Planned] = []
    for person, source_row, person_confirmed in picked:
        if not await may_send_for(db, user, person, source_row):
            continue
        source = (
            Source(
                id=source_row.id,
                payload=source_row.render_payload or {},
                client_id=source_row.client_id,
                job_id=source_row.job_id,
                created_by=source_row.created_by,
                needs_business_data_annex=bool(source_row.needs_business_data_annex),
                has_annex=source_row.id in annexed,
            )
            if source_row is not None
            else None
        )
        assessment = readiness.assess(
            person,
            today=today,
            skip_ending=skip_ending,
            source=source,
            confirmed=person_confirmed,
            open_request=person.candidate_id in open_requests,
            live_batch_id=live.get(person.candidate_id),
            pending_draft=person.candidate_id in drafts,
            known_role_ids=role_ids,
        )
        out.append(Planned(person=person, source=source, assessment=assessment))
    out.sort(
        key=lambda p: (p.person.client_name.lower(), p.person.candidate_name.lower())
    )
    return out


def counts(planned: Sequence[Planned], today: date) -> dict[str, Any]:
    by_reason: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    clients: dict[Optional[int], dict[str, Any]] = {}
    for item in planned:
        by_status[item.assessment.status] += 1
        if item.assessment.reason:
            by_reason[item.assessment.reason] += 1
        entry = clients.setdefault(
            item.person.client_id,
            {
                "client_id": item.person.client_id,
                "client_name": item.person.client_name,
                "total": 0,
                "ready": 0,
            },
        )
        entry["total"] += 1
        entry["ready"] += int(item.assessment.status == "ready")
    return {
        "total": len(planned),
        "ready": by_status["ready"],
        "needs_review": by_status["needs_review"],
        "skipped": by_status["skipped"],
        "by_reason": dict(by_reason),
        # Liczba do pola „Pomiń osoby, którym umowa kończy się w ciągu 30 dni”
        # — także wtedy, gdy pole jest odznaczone.
        "ending_soon": sum(1 for p in planned if readiness.ends_soon(p.person, today)),
        "by_client": sorted(
            clients.values(), key=lambda c: (-c["total"], c["client_name"].lower())
        ),
    }


async def generator_problem(
    db: AsyncSession, user: User, payload_values: dict[str, Any]
) -> Optional[str]:
    """Bramki Generatora bez zapisu i bez numeru: formularz, para (kandydat,
    rekrutacja), dostęp do klienta i „Szczegóły administracyjne”. ``None`` =
    „Pobierz DOCX” by przeszło (poza samym renderem pliku)."""
    from app.api.b2b_contract_generator import (  # noqa: PLC0415
        prepare_standalone_render,
    )
    from app.schemas.b2b_contract_generator import B2BRenderRequest  # noqa: PLC0415
    from app.services.b2b_contract_generator import admin_details  # noqa: PLC0415

    try:
        payload = B2BRenderRequest(**payload_values)
    except ValidationError as exc:
        return _form_problem(exc)
    try:
        await prepare_standalone_render(db, payload, user)
        await admin_details.apply_admin_details(
            db,
            B2BGeneratedContract(),
            is_replacement=payload.is_replacement,
            replaced_contract_id=payload.replaced_contract_id,
            fte=payload.fte,
            candidate_id=payload.candidate_id,
            linked=payload.job_id is not None,
            is_client_referral=payload.is_client_referral,
        )
    except HTTPException as exc:
        return _detail_text(exc)
    return None


def _form_problem(exc: ValidationError) -> str:
    return "Dane umowy nie przechodzą formularza Generatora: " + "; ".join(
        str(error.get("msg", "")) for error in exc.errors()[:3]
    )


async def dry_run(
    db: AsyncSession, user: User, *, skip_ending: bool
) -> tuple[list[Planned], dict[int, str]]:
    """Plan i bramki Generatora dla każdej gotowej osoby, bez zapisu.

    Zwraca plan i problemy (kandydat → komunikat) osób, które plan uznał za
    gotowe, a Generator by odrzucił."""
    planned = await collect(db, user, today=business_today(), skip_ending=skip_ending)
    problems: dict[int, str] = {}
    for item in planned:
        if item.assessment.status != "ready":
            continue
        problem = await generator_problem(db, user, item.assessment.payload or {})
        if problem:
            problems[item.person.candidate_id] = problem
    return planned, problems


# ── Paczka ───────────────────────────────────────────────────────────────────


async def running_batch(db: AsyncSession) -> Optional[B2BMassSendBatch]:
    return await db.scalar(
        select(B2BMassSendBatch)
        .where(B2BMassSendBatch.status == "running")
        .order_by(B2BMassSendBatch.id.desc())
        .limit(1)
    )


_ITEM_STATUS = {
    "ready": "pending",
    "needs_review": "needs_review",
    "skipped": "skipped",
}


async def create_batch(
    db: AsyncSession,
    user: User,
    *,
    skip_ending: bool,
    company_signer_id: int,
    days: int,
) -> B2BMassSendBatch:
    """Paczka z pozycjami (bez commita). Wołający sprawdził wzór, przełącznik
    i reprezentanta. Jedna paczka naraz (blokada doradcza w transakcji)."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('b2b_mass_send'))"))
    if await running_batch(db) is not None:
        raise HTTPException(status_code=409, detail=MSG_RUNNING)
    today = business_today()
    planned = await collect(db, user, today=today, skip_ending=skip_ending)
    summary = counts(planned, today)
    if not summary["ready"]:
        raise HTTPException(status_code=409, detail=MSG_NOTHING_READY)
    batch = B2BMassSendBatch(
        status="running",
        started_by=user.id,
        company_signer_id=company_signer_id,
        link_days=days,
        skip_ending=skip_ending,
        template_label=TEMPLATE_LABEL,
        planned={k: summary[k] for k in ("total", "ready", "needs_review", "skipped")},
    )
    db.add(batch)
    await db.flush()
    for item in planned:
        assessment = item.assessment
        db.add(
            B2BMassSendItem(
                batch_id=batch.id,
                contract_id=item.person.contract_id,
                candidate_id=item.person.candidate_id,
                client_id=item.person.client_id,
                source_generated_contract_id=assessment.source_id,
                status=_ITEM_STATUS[assessment.status],
                reason=assessment.reason,
                missing=list(assessment.missing),
                error=readiness.describe(assessment.missing, assessment.issues) or None,
            )
        )
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=MSG_RUNNING) from exc
    return batch


async def cancel_batch(
    db: AsyncSession, batch: B2BMassSendBatch, *, actor_id: int, now: datetime
) -> int:
    """Zatrzymaj paczkę: pozycje bez wysyłki → ``skipped``. Wysłanych linków
    nie wycofuje — każdy da się wycofać w rejestrze jak pojedynczą wysyłkę."""
    items = (
        await db.scalars(
            select(B2BMassSendItem)
            .where(
                B2BMassSendItem.batch_id == batch.id,
                B2BMassSendItem.status.in_(("pending", "created")),
            )
            .with_for_update()
        )
    ).all()
    for item in items:
        item.status = "skipped"
        item.reason = "cancelled"
        item.error = MSG_CANCELLED
    batch.status = "cancelled"
    batch.cancelled_at = now
    batch.cancelled_by = actor_id
    batch.finished_at = now
    return len(items)


async def progress(db: AsyncSession, batch_id: int) -> dict[str, int]:
    """Postęp: stany pozycji i — przy wysłanych — stany wniosków o podpis."""
    item_rows = await db.execute(
        select(B2BMassSendItem.status, func.count())
        .where(B2BMassSendItem.batch_id == batch_id)
        .group_by(B2BMassSendItem.status)
    )
    out: dict[str, int] = {status: 0 for status in ITEM_STATUSES}
    for status, n in item_rows.all():
        out[status] = int(n)
    request_rows = await db.execute(
        select(B2BSigningRequest.status, func.count())
        .join(
            B2BMassSendItem,
            B2BMassSendItem.signing_request_id == B2BSigningRequest.id,
        )
        .where(B2BMassSendItem.batch_id == batch_id)
        .group_by(B2BSigningRequest.status)
    )
    requests = {status: int(n) for status, n in request_rows.all()}
    out["waiting_contractor"] = requests.get("sent", 0)
    out["waiting_company"] = requests.get("contractor_signed", 0)
    out["signed"] = requests.get("completed", 0)
    out["closed"] = requests.get("withdrawn", 0) + requests.get("expired", 0)
    return out


# ── Pętla: wiersz Generatora i wysyłka jednej pozycji ────────────────────────


def _detail_text(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("detail") or ""
    return str(detail or "")[:1000]


async def _lock_item(db: AsyncSession, item_id: int) -> Optional[B2BMassSendItem]:
    return await db.scalar(
        select(B2BMassSendItem)
        .where(B2BMassSendItem.id == item_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


async def _finish_item(
    db: AsyncSession,
    item_id: int,
    *,
    status: str,
    error: Optional[str] = None,
    reason: Optional[str] = None,
    missing: Optional[Sequence[str]] = None,
    bump_attempts: bool = False,
) -> None:
    """Zapis stanu pozycji w osobnej transakcji (po rollbacku kroku)."""
    item = await db.get(B2BMassSendItem, item_id, populate_existing=True)
    if item is None:
        return
    item.status = status
    item.error = error
    if reason is not None:
        item.reason = reason
    if missing is not None:
        item.missing = list(missing)
    if bump_attempts:
        item.attempts = (item.attempts or 0) + 1
    await db.commit()


async def _template_ready(db: AsyncSession) -> bool:
    return (await mass_settings.load(db)).template_ready


async def _create_row(
    db: AsyncSession, item: B2BMassSendItem, batch: B2BMassSendBatch, starter: User
) -> None:
    """``pending`` → ``created`` (wiersz Generatora) albo powód, czemu nie."""
    from app.api.b2b_contract_generator import (  # noqa: PLC0415
        issue_standalone_contract,
    )
    from app.schemas.b2b_contract_generator import B2BRenderRequest  # noqa: PLC0415

    item_id = item.id
    # Dane sprawdzamy jeszcze raz: od planu ktoś mógł poprawić umowę, wysłać ją
    # sam albo zakończyć kontrakt.
    planned = await collect(
        db,
        starter,
        today=business_today(),
        skip_ending=batch.skip_ending,
        candidate_ids=[item.candidate_id] if item.candidate_id else [],
        exclude_item_id=item_id,
    )
    current = planned[0] if planned else None
    if current is None:
        await db.rollback()
        await _finish_item(
            db,
            item_id,
            status="skipped",
            reason="not_available",
            error=MSG_NOT_AVAILABLE,
        )
        return
    assessment = current.assessment
    if assessment.status != "ready":
        await db.rollback()
        await _finish_item(
            db,
            item_id,
            status=_ITEM_STATUS[assessment.status],
            reason=assessment.reason,
            missing=assessment.missing,
            error=readiness.describe(assessment.missing, assessment.issues)
            or readiness.reason_label(assessment.reason),
        )
        return
    contract = await db.get(Contract, current.person.contract_id)
    try:
        payload = B2BRenderRequest(**(current.assessment.payload or {}))
    except ValidationError as exc:
        await db.rollback()
        await _finish_item(
            db,
            item_id,
            status="needs_review",
            reason=readiness.REASON_MISSING,
            error=_form_problem(exc),
        )
        return
    source_id = current.assessment.source_id

    async def _link(row: B2BGeneratedContract) -> None:
        # Kontrakt jak przy umowie po powrocie z przerwy
        # (``contract_termination_sync._create_follow_up_agreement``), nie przez
        # ``apply_contract_link``: tamto stempluje numer i datę podpisu w
        # szczegółach B2B kontraktu, a ta umowa nie jest jeszcze podpisana.
        # Stempel zrobi podpis („Oznacz jako podpisaną” albo podpis w NEXUSIE).
        row.contract_id = contract.id
        row.candidate_id = contract.candidate_id
        row.client_id = contract.client_id
        row.previous_generated_contract_id = source_id
        locked = await db.get(B2BMassSendItem, item_id)
        locked.generated_contract_id = row.id
        locked.source_generated_contract_id = source_id
        locked.status = "created"
        locked.error = None
        await db.flush()

    try:
        await issue_standalone_contract(
            db, payload, starter, notify_owner=False, on_created=_link
        )
    except HTTPException as exc:
        await db.rollback()
        message = _detail_text(exc)
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get("code") == "contract_number_taken":
            fresh = await db.get(B2BMassSendItem, item_id, populate_existing=True)
            attempts = (fresh.attempts or 0) + 1 if fresh else MAX_NUMBER_ATTEMPTS
            await _finish_item(
                db,
                item_id,
                status="pending" if attempts < MAX_NUMBER_ATTEMPTS else "failed",
                error=message,
                bump_attempts=True,
            )
        elif exc.status_code in (404, 409, 422):
            await _finish_item(
                db,
                item_id,
                status="needs_review",
                reason=readiness.REASON_MISSING,
                error=message,
            )
        else:
            await _finish_item(db, item_id, status="failed", error=message)
        return
    except Exception:  # noqa: BLE001 — jedna osoba nie zatrzymuje paczki
        await db.rollback()
        logger.exception("b2b_mass_send: wiersz Generatora item=%s", item_id)
        await _finish_item(db, item_id, status="failed", error=MSG_PREPARE_FAILED)


def _contractor_email(row: B2BGeneratedContract, candidate: Optional[Candidate]) -> str:
    """Jak w oknie „Wyślij do podpisu”: e-mail z umowy, potem z profilu."""
    email = (row.render_payload or {}).get("partner_email")
    if not (isinstance(email, str) and email.strip()) and candidate is not None:
        email = candidate.email
    return email.strip() if isinstance(email, str) else ""


async def _send_row(
    db: AsyncSession, item: B2BMassSendItem, batch: B2BMassSendBatch, starter: User
) -> None:
    """``created`` → ``sent`` drogą „Wyślij do podpisu”, mail ze skrzynki
    osoby, która zaczęła paczkę."""
    from app.api import b2b_esign as esign_api  # noqa: PLC0415
    from app.services.b2b_esign import mail as esign_mail  # noqa: PLC0415
    from app.services.b2b_esign import service as esign_service  # noqa: PLC0415
    from app.services.b2b_esign import settings as esign_settings  # noqa: PLC0415

    item_id = item.id
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.id == item.generated_contract_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        await db.rollback()
        await _finish_item(db, item_id, status="failed", error=MSG_ROW_GONE)
        return
    esign = await esign_settings.load(db)
    problem: Optional[str] = None
    if not esign.can_send(starter):
        problem = esign_api.MSG_OFF
    elif batch.company_signer_id not in esign.company_signer_ids:
        problem = esign_api.MSG_SIGNER
    elif not await esign_mail.mailbox_connected(db, starter.id):
        problem = MSG_NO_MAILBOX
    if problem is None:
        try:
            await esign_api._assert_row_sender(db, starter, row)
            esign_service.assert_sendable(row)
        except HTTPException as exc:
            problem = _detail_text(exc)
    candidate = await db.get(Candidate, row.candidate_id) if row.candidate_id else None
    email = _contractor_email(row, candidate)
    if problem is None:
        try:
            _EMAIL.validate_python(email)
        except ValidationError:
            problem = MSG_BAD_EMAIL
    if problem is not None:
        await db.rollback()
        await _finish_item(db, item_id, status="failed", error=problem)
        return
    # Ostatnie sprawdzenie tuż przed wysyłką: admin mógł cofnąć „nowy wzór
    # podpięty” w trakcie biegu.
    if not await _template_ready(db):
        await db.rollback()
        return
    try:
        request, token = await esign_api.open_signing_request(
            db,
            row,
            actor_id=starter.id,
            contractor_email=email,
            company_signer_id=batch.company_signer_id,
            days=batch.link_days,
        )
        locked = await db.get(B2BMassSendItem, item_id)
        locked.signing_request_id = request.id
        locked.status = "sent"
        locked.error = None
        await db.commit()
    except HTTPException as exc:
        await db.rollback()
        await _finish_item(db, item_id, status="failed", error=_detail_text(exc))
        return
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("b2b_mass_send: wysyłka item=%s", item_id)
        await _finish_item(db, item_id, status="failed", error=MSG_PREPARE_FAILED)
        return
    request_id = request.id
    out = await esign_api._out(db, request)
    mail_sent, mail_problem = await esign_api._mail_link(
        db,
        sender_id=starter.id,
        request=out,
        row=row,
        url=esign_api._sign_url(token),
    )
    if mail_sent:
        return
    # Linku nie zna nikt poza mailem, który nie wyszedł — wniosek w toku
    # blokowałby wiersz bez pożytku. Wycofanie zostawia „Wyślij do podpisu”.
    await esign_service.withdraw(
        db,
        request_id=request_id,
        actor_id=starter.id,
        reason=MSG_MAIL_FAILED,
        now=_now(),
    )
    await db.commit()
    await _finish_item(
        db,
        item_id,
        status="failed",
        error=f"{MSG_MAIL_FAILED} {mail_problem or ''}".strip(),
    )


async def process_item(db: AsyncSession, item_id: int) -> Optional[str]:
    """Jedna pozycja: wiersz Generatora i wysyłka. Zwraca stan po kroku albo
    ``None`` (pozycja zajęta, paczka nie biegnie albo wysyłka zablokowana)."""
    item = await _lock_item(db, item_id)
    if item is None or item.status not in ("pending", "created"):
        await db.rollback()
        return None
    batch = await db.get(B2BMassSendBatch, item.batch_id)
    if batch is None or batch.status != "running" or not await _template_ready(db):
        await db.rollback()
        return None
    starter = await db.get(User, batch.started_by) if batch.started_by else None
    if starter is None or not starter.is_active:
        await db.rollback()
        await _finish_item(db, item_id, status="failed", error=MSG_STARTER_GONE)
        return "failed"
    if item.status == "pending":
        await _create_row(db, item, batch, starter)
        item = await _lock_item(db, item_id)
        if item is None or item.status != "created":
            await db.rollback()
            fresh = await db.get(B2BMassSendItem, item_id, populate_existing=True)
            return fresh.status if fresh else None
    await _send_row(db, item, batch, starter)
    fresh = await db.get(B2BMassSendItem, item_id, populate_existing=True)
    return fresh.status if fresh else None


async def next_item_ids(db: AsyncSession, batch_id: int, limit: int) -> list[int]:
    return list(
        (
            await db.scalars(
                select(B2BMassSendItem.id)
                .where(
                    B2BMassSendItem.batch_id == batch_id,
                    B2BMassSendItem.status.in_(("pending", "created")),
                )
                .order_by(B2BMassSendItem.id)
                .limit(limit)
            )
        ).all()
    )


async def finish_if_done(db: AsyncSession, batch_id: int) -> bool:
    batch = await db.get(B2BMassSendBatch, batch_id, with_for_update=True)
    if batch is None or batch.status != "running":
        return False
    if await next_item_ids(db, batch_id, 1):
        return False
    batch.status = "finished"
    batch.finished_at = _now()
    await db.commit()
    return True
