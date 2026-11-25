"""Sprawdzenie w tle: zlecenie, bieg, zapis ustaleń bez duplikatów, odczyt dla ekranu.

Kiedy biegnie:

* **po odczycie wgranej albo podmienionej umowy ramowej lub aneksu**
  (``framework_contract_index`` woła ``after_document_indexed``) — bieg
  pomija klienta, gdy odcisk źródeł (pliki umów i aneksów, wzór z klauzulami
  klienta) jest taki sam jak przy ostatnim udanym sprawdzeniu;
* **na żądanie** („Sprawdź ponownie”) — zawsze.

Jeden bieg naraz na klienta w procesie, a zlecenie w kolejce sprzed mniej niż
``REQUEUE_AFTER`` nie zakłada drugiego. Wiersz ``legal_client_fit_checks`` jest
jeden na klienta, ustalenie jedno na temat (``UNIQUE (client_id, topic)``):
nowe sprawdzenie nadpisuje ustalenia tematów, które znalazło, i usuwa te,
których już nie ma. Model nie odpowiedział → ustalenia zostają w bazie, ale
ekran i zadania ich nie pokazują (status ``unavailable`` / ``failed``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.tasks import spawn
from app.services import framework_contract_index
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.legal_client_fit import LegalClientFitCheck, LegalClientFitFinding
from app.services.legal.pseudonymize import Entity
from app.services.legal_client_fit import engine, sources
from app.services.legal_client_fit.schema import CLIENT_REF_MAX

logger = logging.getLogger(__name__)

#: Zlecenie „w kolejce” albo „trwa” starsze niż to uznajemy za urwane
#: (redeploy ubił proces) i zlecamy na nowo.
REQUEUE_AFTER = timedelta(minutes=15)
#: Statusy, przy których ekran i zadania pokazują ustalenia (ostatni bieg
#: się udał albo właśnie trwa ponowny — wtedy widać poprzedni wynik).
SHOWS_FINDINGS = frozenset({"done", "queued", "running"})
ACTIVE_CONTRACT_STATUSES = (ContractStatus.active, ContractStatus.ending)

MSG_NO_CONTRACT = (
    "Klient nie ma umowy ramowej ani aneksu z treścią do przeczytania — "
    "wgraj plik w karcie klienta → Umowy."
)
MSG_NO_CLIENT = "Klienta nie ma w NEXUSIE."

_inflight: dict[int, "asyncio.Task[None]"] = {}


# ── zlecenie ────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _check_row(db: AsyncSession, client_id: int) -> Optional[LegalClientFitCheck]:
    return await db.scalar(
        select(LegalClientFitCheck).where(LegalClientFitCheck.client_id == client_id)
    )


def _in_progress(row: Optional[LegalClientFitCheck], now: datetime) -> bool:
    if row is None or row.status not in ("queued", "running"):
        return False
    since = row.started_at or row.requested_at
    return since is not None and now - since < REQUEUE_AFTER


async def request_check(
    db: AsyncSession,
    client_id: int,
    *,
    trigger: str,
    user_id: Optional[int] = None,
) -> LegalClientFitCheck:
    """Zapisuje zlecenie (commit) i uruchamia bieg w tle; trwające zostawia."""
    now = _now()
    row = await _check_row(db, client_id)
    if _in_progress(row, now):
        return row  # type: ignore[return-value]
    if row is None:
        row = LegalClientFitCheck(client_id=client_id, status="queued", trigger=trigger)
        db.add(row)
    row.status = "queued"
    row.trigger = trigger
    row.requested_by_id = user_id
    row.requested_at = now
    row.started_at = None
    row.status_message = None
    await db.commit()
    await db.refresh(row)
    start(client_id)
    return row


def start(client_id: int) -> "asyncio.Task[None]":
    task = _inflight.get(client_id)
    if task is None or task.done():
        task = spawn(run_check(client_id), f"legal-client-fit:{client_id}")
        _inflight[client_id] = task

        def _done(finished: "asyncio.Task[None]") -> None:
            if _inflight.get(client_id) is finished:
                del _inflight[client_id]

        task.add_done_callback(_done)
    return task


async def after_document_indexed(kind: str, document_id: int) -> None:
    """Po odczycie pliku umowy ramowej albo aneksu — sprawdzenie klienta w tle."""
    try:
        async with AsyncSessionLocal() as db:
            if kind == sources.SOURCE_AMENDMENT:
                client_id = await db.scalar(
                    select(Client.id)
                    .join(
                        sources.ClientFrameworkContract,
                        sources.ClientFrameworkContract.client_id == Client.id,
                    )
                    .join(
                        ClientContractAmendment,
                        ClientContractAmendment.framework_contract_id
                        == sources.ClientFrameworkContract.id,
                    )
                    .where(ClientContractAmendment.id == document_id)
                )
            else:
                client_id = await db.scalar(
                    select(sources.ClientFrameworkContract.client_id).where(
                        sources.ClientFrameworkContract.id == document_id
                    )
                )
            if client_id is None:
                return
            await request_check(db, int(client_id), trigger="upload")
    except Exception as exc:  # noqa: BLE001 — sprawdzenie nie może zepsuć odczytu umowy
        logger.warning(
            "[legal_client_fit] zlecenie po odczycie %s %s nieudane: %s",
            kind,
            document_id,
            type(exc).__name__,
        )


# ── bieg ────────────────────────────────────────────────────────────────────


async def _finish(
    db: AsyncSession,
    row: LegalClientFitCheck,
    status: str,
    *,
    message: Optional[str] = None,
    fingerprint: Optional[str] = None,
    template_label: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    row.status = status
    row.status_message = message
    row.checked_at = _now()
    if fingerprint is not None:
        row.source_fingerprint = fingerprint
    if template_label is not None:
        row.template_label = template_label
    if model is not None:
        row.model = model
    await db.commit()


async def _entities(db: AsyncSession, client: Client) -> list[Entity]:
    """Osoby klienta (kontakty) do maski — w umowie stoją jako podpisujący."""
    names = (
        await db.scalars(select(Contact.name).where(Contact.client_id == client.id))
    ).all()
    return [
        Entity("OSOBA", name, inflect=True)
        for name in dict.fromkeys(n.strip() for n in names if n and n.strip())
    ]


async def store_findings(
    db: AsyncSession, client_id: int, findings: Sequence[engine.Finding]
) -> None:
    """Upsert po temacie; temat, którego nowe sprawdzenie nie znalazło, znika."""
    existing = {
        row.topic: row
        for row in (
            await db.scalars(
                select(LegalClientFitFinding).where(
                    LegalClientFitFinding.client_id == client_id
                )
            )
        ).all()
    }
    keep = {finding.topic for finding in findings}
    stale = [topic for topic in existing if topic not in keep]
    if stale:
        await db.execute(
            delete(LegalClientFitFinding).where(
                LegalClientFitFinding.client_id == client_id,
                LegalClientFitFinding.topic.in_(stale),
            )
        )
    for finding in findings:
        row = existing.get(finding.topic)
        if row is None:
            row = LegalClientFitFinding(client_id=client_id, topic=finding.topic)
            db.add(row)
        row.state = finding.state
        row.summary = finding.summary
        row.client_quote = finding.client_quote
        row.client_ref = finding.client_ref[:CLIENT_REF_MAX]
        row.client_source_kind = finding.client_source_kind
        row.client_source_id = finding.client_source_id
        row.our_quote = finding.our_quote
        row.our_ref = finding.our_ref
        row.next_step = finding.next_step
        row.annex_text = finding.annex_text
        # Zgłoszony szkic klauzuli zostaje z tekstem z chwili zgłoszenia.
        row.lawyer_review = list(finding.lawyer_review)


async def run_check(client_id: int) -> None:
    """Bieg w tle: źródła → model → ustalenia sprawdzone kodem → zapis."""
    async with AsyncSessionLocal() as db:
        row = await _check_row(db, client_id)
        if row is None:
            return
        row.status = "running"
        row.started_at = _now()
        await db.commit()
        client = await db.get(Client, client_id)
        if client is None or client.deleted_at is not None:
            await _finish(db, row, "failed", message=MSG_NO_CLIENT)
            return
        try:
            documents = await sources.load_client_documents(db, client_id)
            # Nieaktualny odczyt (plik podmieniony przed chwilą) czeka najwyżej
            # 30 s; potem porównujemy to, co już jest.
            await framework_contract_index.ensure_indexed(
                db, [*documents.contracts, *documents.amendments]
            )
            ours, label, template_digest = sources.load_template(client)
            fingerprint = sources.documents_fingerprint(documents, template_digest)
            if not documents.readable:
                await db.execute(
                    delete(LegalClientFitFinding).where(
                        LegalClientFitFinding.client_id == client_id
                    )
                )
                await _finish(
                    db,
                    row,
                    "no_contract",
                    message=MSG_NO_CONTRACT,
                    fingerprint=fingerprint,
                    template_label=label,
                )
                return
            # Odcisk zapisuje tylko bieg „gotowe” albo „brak umowy”, więc ten
            # sam odcisk = te same pliki i ten sam wzór dały już wynik.
            if row.trigger == "upload" and row.source_fingerprint == fingerprint:
                await _finish(db, row, "done", template_label=label)
                return
            passages = await sources.client_passages(db, documents)
            if not passages:
                await _finish(
                    db,
                    row,
                    "no_contract",
                    message=MSG_NO_CONTRACT,
                    fingerprint=fingerprint,
                    template_label=label,
                )
                return
            entities = await _entities(db, client)
            outcome = await engine.compare(
                db,
                client=passages,
                ours=ours,
                entities=entities,
                whole_texts=documents.texts,
            )
            if outcome.status != "done":
                await _finish(
                    db,
                    row,
                    outcome.status,
                    message=outcome.message,
                    template_label=label,
                    model=outcome.model,
                )
                return
            await store_findings(db, client_id, outcome.findings)
            await _finish(
                db,
                row,
                "done",
                fingerprint=fingerprint,
                template_label=label,
                model=outcome.model,
            )
        except Exception as exc:  # noqa: BLE001 — stan zamiast wyjątku w zadaniu tła
            logger.warning(
                "[legal_client_fit] sprawdzenie klienta %s nieudane: %s",
                client_id,
                type(exc).__name__,
            )
            await db.rollback()
            row = await _check_row(db, client_id)
            if row is not None:
                await _finish(db, row, "failed", message=engine.MSG_FAILED)


# ── odczyt ──────────────────────────────────────────────────────────────────


async def active_b2b_contracts(
    db: AsyncSession, client_ids: Sequence[int]
) -> dict[int, int]:
    """Aktywne kontrakty B2B klientów — tych umów dotyczy luka we wzorze."""
    if not client_ids:
        return {}
    rows = await db.execute(
        select(Contract.client_id, func.count(Contract.id))
        .where(
            Contract.client_id.in_(list(client_ids)),
            Contract.contract_type == ContractType.b2b,
            Contract.status.in_(ACTIVE_CONTRACT_STATUSES),
        )
        .group_by(Contract.client_id)
    )
    return {int(client_id): int(count) for client_id, count in rows}


@dataclass(frozen=True)
class ClientFitView:
    client: Client
    check: Optional[LegalClientFitCheck]
    findings: list[LegalClientFitFinding]
    documents: sources.ClientDocuments
    stale: bool
    template_label: str
    active_b2b: int
    drafters: dict[int, str]


def status_of(check: Optional[LegalClientFitCheck]) -> str:
    return check.status if check is not None else "never"


async def load_view(db: AsyncSession, client: Client) -> ClientFitView:
    check = await _check_row(db, client.id)
    documents = await sources.load_client_documents(db, client.id)
    _ours, label, template_digest = sources.load_template(client)
    fingerprint = sources.documents_fingerprint(documents, template_digest)
    findings: list[LegalClientFitFinding] = []
    if status_of(check) in SHOWS_FINDINGS:
        findings = list(
            (
                await db.scalars(
                    select(LegalClientFitFinding)
                    .where(LegalClientFitFinding.client_id == client.id)
                    .order_by(LegalClientFitFinding.id)
                )
            ).all()
        )
    stale = (
        check is not None
        and check.status == "done"
        and check.source_fingerprint is not None
        and check.source_fingerprint != fingerprint
    )
    drafter_ids = {
        f.clause_draft_requested_by_id
        for f in findings
        if f.clause_draft_requested_by_id
    }
    drafters: dict[int, str] = {}
    if drafter_ids:
        from app.models.user import User

        for user_id, name in (
            await db.execute(
                select(User.id, User.name).where(User.id.in_(list(drafter_ids)))
            )
        ).all():
            drafters[int(user_id)] = name
    counts = await active_b2b_contracts(db, [client.id])
    return ClientFitView(
        client=client,
        check=check,
        findings=findings,
        documents=documents,
        stale=stale,
        template_label=(
            check.template_label if check and check.template_label else label
        ),
        active_b2b=counts.get(client.id, 0),
        drafters=drafters,
    )


def source_names(documents: sources.ClientDocuments) -> dict[tuple[str, int], str]:
    return {
        **{(sources.SOURCE_FRAMEWORK, c.id): c.name for c in documents.contracts},
        **{(sources.SOURCE_AMENDMENT, a.id): a.name for a in documents.amendments},
    }


async def request_clause_draft(
    db: AsyncSession, finding: LegalClientFitFinding, user_id: int
) -> LegalClientFitFinding:
    """Szkic klauzuli klienta dla programisty — ``clause_overrides`` się nie zmienia."""
    finding.clause_draft_text = finding.annex_text
    finding.clause_draft_requested_at = _now()
    finding.clause_draft_requested_by_id = user_id
    await db.commit()
    await db.refresh(finding)
    return finding
