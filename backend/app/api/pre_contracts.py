"""Umowa przedwstępna przy osobie w rekrutacji — prośba, kroki, pliki, lista.

Reguły: ``app/services/pre_contracts.py`` i
``docs/claude/kontrakty/generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md (sekcja „Umowa przedwstępna w rekrutacji”)``.

Dostęp jak do Tablicy: sekcja „Rekrutacje” i członkostwo w rekrutacji
(``ensure_job_read_access`` — admin i Head of Recruitment zawsze). Kto widzi
Tablicę, może poprosić o umowę i prowadzić jej kroki (decyzja „Kanban bez
bramek”). Wycofanie prośby — proszący albo Head of Recruitment; decyzja
o karze — Head of Recruitment albo admin. Podpisane pliki mają PESEL, ale
pobiera je ten sam krąg co Tablicę pary — jak CV i notatki osoby.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.models.b2b_contract_document import B2BContractDocument
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.pre_contract import (
    NEEDED_BEFORE,
    SIGNATURE_FORMS,
    WITHDRAWAL_KINDS,
    PreContractEvent,
    PreContractRequest,
    PreContractWatcher,
)
from app.models.user import User, UserRole
from app.services import pre_contracts as svc
from app.services import storage_service
from app.services.b2b_documents.signed_scan import read_scan
from app.services.board_tasks import dl_portfolio_client_ids
from app.services.stage_handoff_recipients import pair_recruiter_id

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

MSG_NOT_FOUND = "Nie ma takiej prośby o umowę przedwstępną."
MSG_CLOSED = "Ta prośba jest już zamknięta."
MSG_NOT_IN_JOB = "Ta osoba nie jest w tej rekrutacji."
MSG_DOC = (
    "Wskaż umowę przedwstępną wystawioną dla tej osoby w tej rekrutacji "
    "(Generator dokumentów)."
)
MSG_NO_DOC = "Najpierw wystaw umowę w Generatorze dokumentów."
MSG_NOT_SENT = "Najpierw oznacz umowę jako wysłaną kandydatowi."
MSG_NO_CANDIDATE_SIGNATURE = "Najpierw wgraj umowę podpisaną przez kandydata."
MSG_WITHDRAW_AFTER_SEND = (
    "Umowa jest już wysłana — zamiast wycofać prośbę, anuluj umowę z powodem."
)
MSG_ONLY_REQUESTER = (
    "Prośbę wycofuje osoba, która o nią poprosiła, albo Head of Recruitment."
)
MSG_ONLY_HOR = "O karze decyduje Head of Recruitment."
MSG_NO_FILE = "Ten plik nie jest zapisany przy umowie."

_OVERSIGHT = (UserRole.admin, UserRole.head_of_recruitment)

# ── Schematy ─────────────────────────────────────────────────────────────────

NeededBefore = Literal["cv_sent", "client_interview", "b2b_contract", "date"]
SignatureForm = Literal[
    "trusted_profile", "personal_signature", "qualified", "handwritten_scan", "other"
]
WithdrawalKind = Literal["no_show", "refused", "resigned", "bypassed"]

assert set(NeededBefore.__args__) == set(NEEDED_BEFORE)  # type: ignore[attr-defined]
assert set(SignatureForm.__args__) == set(SIGNATURE_FORMS)  # type: ignore[attr-defined]
assert set(WithdrawalKind.__args__) == set(WITHDRAWAL_KINDS)  # type: ignore[attr-defined]


class CreateRequest(BaseModel):
    candidate_id: int
    job_id: int
    needed_before: NeededBefore = "cv_sent"
    needed_by: Optional[date] = None
    reason: Optional[str] = Field(default=None, max_length=2000)
    assignee_id: Optional[int] = None


class UpdateRequest(BaseModel):
    needed_before: Optional[NeededBefore] = None
    needed_by: Optional[date] = None
    assignee_id: Optional[int] = None


class LinkDocument(BaseModel):
    document_id: int


class MarkSent(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class CloseBody(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class WithdrawalBody(BaseModel):
    kind: WithdrawalKind
    event_on: date
    note: str = Field(min_length=3, max_length=2000)
    decision_user_id: Optional[int] = None


class PenaltyDecision(BaseModel):
    decision: Literal["demand", "waive"]
    note: Optional[str] = Field(default=None, max_length=2000)


class PersonRef(BaseModel):
    id: int
    name: str


class EventOut(BaseModel):
    id: int
    kind: str
    label: str
    at: str
    actor: Optional[PersonRef] = None
    payload: Optional[dict[str, Any]] = None


class RequestOut(BaseModel):
    id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    state: str
    state_label: str
    badge: dict[str, str]
    is_open: bool
    needed_before: str
    needed_before_label: str
    needed_by: Optional[date] = None
    reason: Optional[str] = None
    requested_by: Optional[PersonRef] = None
    requested_at: str
    assignee: Optional[PersonRef] = None
    watchers: list[PersonRef] = []
    watching: bool = False
    document_id: Optional[int] = None
    document_type: Optional[str] = None
    sent_at: Optional[str] = None
    candidate_signed_at: Optional[str] = None
    candidate_signature_form: Optional[str] = None
    candidate_signature_form_label: Optional[str] = None
    candidate_file_name: Optional[str] = None
    company_signed_at: Optional[str] = None
    company_file_name: Optional[str] = None
    valid_until: Optional[date] = None
    b2b_deadline: Optional[date] = None
    closed_at: Optional[str] = None
    close_reason: Optional[str] = None
    withdrawal: Optional[dict[str, Any]] = None
    column: Optional[str] = None
    stage_name: Optional[str] = None
    can_withdraw: bool = False
    can_decide_penalty: bool = False
    events: list[EventOut] = []


class PairDocument(BaseModel):
    """Umowa przedwstępna z Generatora wystawiona dla tej pary."""

    id: int
    document_type: str
    document_date: date
    status: str
    signed: bool
    linked: bool


class PairOut(BaseModel):
    current: Optional[RequestOut] = None
    history: list[RequestOut] = []
    # Umowy z Generatora dla pary (bez anulowanych) — panel podpina je do
    # prośby jednym kliknięciem („Podepnij umowę z DD.MM”).
    documents: list[PairDocument] = []


class ListOut(BaseModel):
    items: list[RequestOut]
    counts: dict[str, int]


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _sees_all(user: User) -> bool:
    return user.has_any_role(*_OVERSIGHT)


async def _load(
    db: AsyncSession, request_id: int, *, lock: bool = False
) -> PreContractRequest:
    stmt = select(PreContractRequest).where(PreContractRequest.id == request_id)
    if lock:
        stmt = stmt.with_for_update()
    req = await db.scalar(stmt)
    if req is None:
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    return req


async def _load_for(
    db: AsyncSession, user: User, request_id: int, *, lock: bool = True
) -> PreContractRequest:
    req = await _load(db, request_id, lock=lock)
    await ensure_job_read_access(db, user, req.job_id)
    return req


def _require_open(req: PreContractRequest) -> None:
    if req.closed_at is not None:
        raise HTTPException(status_code=409, detail=MSG_CLOSED)


async def _people(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}


def _ref(names: dict[int, str], uid: Optional[int]) -> Optional[PersonRef]:
    if not uid:
        return None
    return PersonRef(id=uid, name=names.get(uid, "—"))


async def _serialize(
    db: AsyncSession,
    user: User,
    reqs: list[PreContractRequest],
    *,
    with_events: bool = False,
) -> list[RequestOut]:
    if not reqs:
        return []
    ids = [r.id for r in reqs]
    watchers: dict[int, list[int]] = {}
    for rid, uid in (
        await db.execute(
            select(PreContractWatcher.request_id, PreContractWatcher.user_id).where(
                PreContractWatcher.request_id.in_(ids)
            )
        )
    ).all():
        watchers.setdefault(rid, []).append(uid)
    events: dict[int, list[PreContractEvent]] = {}
    if with_events:
        for ev in (
            await db.scalars(
                select(PreContractEvent)
                .where(PreContractEvent.request_id.in_(ids))
                .order_by(PreContractEvent.at, PreContractEvent.id)
            )
        ).all():
            events.setdefault(ev.request_id, []).append(ev)
    people_ids: set[int] = set()
    for r in reqs:
        people_ids.update(
            uid for uid in (r.requested_by, r.assignee_id, r.closed_by) if uid
        )
        people_ids.update(watchers.get(r.id, []))
        people_ids.update(e.actor_id for e in events.get(r.id, []) if e.actor_id)
        decision_user = (r.withdrawal or {}).get("decision_user_id")
        if isinstance(decision_user, int):
            people_ids.add(decision_user)
    names = await _people(db, people_ids)
    candidates = {
        cid: f"{name} {lastname}".strip()
        for cid, name, lastname in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_({r.candidate_id for r in reqs})
                )
            )
        ).all()
    }
    jobs = {
        jid: (title, client_id)
        for jid, title, client_id in (
            await db.execute(
                select(Job.id, Job.title, Job.client_id).where(
                    Job.id.in_({r.job_id for r in reqs})
                )
            )
        ).all()
    }
    client_ids = {cid for _, cid in jobs.values() if cid} | {
        r.client_id for r in reqs if r.client_id
    }
    clients = (
        {
            cid: (display or name)
            for cid, name, display in (
                await db.execute(
                    select(Client.id, Client.name, Client.display_name).where(
                        Client.id.in_(client_ids)
                    )
                )
            ).all()
        }
        if client_ids
        else {}
    )
    doc_types = (
        {
            did: dtype
            for did, dtype in (
                await db.execute(
                    select(
                        B2BContractDocument.id, B2BContractDocument.document_type
                    ).where(
                        B2BContractDocument.id.in_(
                            {r.document_id for r in reqs if r.document_id}
                        )
                    )
                )
            ).all()
        }
        if any(r.document_id for r in reqs)
        else {}
    )
    columns = await svc.pair_columns(db, [(r.candidate_id, r.job_id) for r in reqs])
    today = svc.today()
    out: list[RequestOut] = []
    for r in reqs:
        column, stage_name = columns.get((r.candidate_id, r.job_id), (None, None))
        left = (
            svc.business_days_until(today, r.b2b_deadline)
            if r.b2b_deadline is not None
            else None
        )
        b = svc.badge(r, column=column, today=today, business_days_left=left)
        title, job_client = jobs.get(r.job_id, ("—", None))
        client_id = r.client_id or job_client
        state = svc.state_of(r)
        watching_ids = watchers.get(r.id, [])
        withdrawal = r.withdrawal
        decision_user = (withdrawal or {}).get("decision_user_id")
        can_decide = (
            r.close_reason == "candidate_withdrew"
            and not (withdrawal or {}).get("decision")
            and (_sees_all(user) or decision_user == user.id)
        )
        out.append(
            RequestOut(
                id=r.id,
                candidate_id=r.candidate_id,
                candidate_name=candidates.get(r.candidate_id, "—"),
                job_id=r.job_id,
                job_title=title,
                client_id=client_id,
                client_name=clients.get(client_id) if client_id else None,
                state=state,
                state_label=svc.STATE_LABEL.get(state)
                or svc.CLOSE_LABEL.get(state, state),
                badge=b.as_dict(),
                is_open=svc.is_open(r),
                needed_before=r.needed_before,
                needed_before_label=svc.NEEDED_BEFORE_LABEL.get(r.needed_before, ""),
                needed_by=r.needed_by,
                reason=r.reason,
                requested_by=_ref(names, r.requested_by),
                requested_at=r.requested_at.isoformat(),
                assignee=_ref(names, r.assignee_id),
                watchers=[
                    p for p in (_ref(names, uid) for uid in sorted(watching_ids)) if p
                ],
                watching=user.id in watching_ids,
                document_id=r.document_id,
                document_type=doc_types.get(r.document_id) if r.document_id else None,
                sent_at=_iso(r.sent_at),
                candidate_signed_at=_iso(r.candidate_signed_at),
                candidate_signature_form=r.candidate_signature_form,
                candidate_signature_form_label=svc.SIGNATURE_FORM_LABEL.get(
                    r.candidate_signature_form or ""
                ),
                candidate_file_name=r.candidate_file_name,
                company_signed_at=_iso(r.company_signed_at),
                company_file_name=r.company_file_name,
                valid_until=r.valid_until,
                b2b_deadline=r.b2b_deadline,
                closed_at=_iso(r.closed_at),
                close_reason=r.close_reason,
                withdrawal=withdrawal,
                column=column,
                stage_name=stage_name,
                can_withdraw=(
                    r.closed_at is None
                    and r.sent_at is None
                    and (r.requested_by == user.id or _sees_all(user))
                ),
                can_decide_penalty=can_decide,
                events=[
                    EventOut(
                        id=e.id,
                        kind=e.kind,
                        label=svc.EVENT_TITLE.get(e.kind, e.kind),
                        at=e.at.isoformat(),
                        actor=_ref(names, e.actor_id),
                        payload=e.payload,
                    )
                    for e in events.get(r.id, [])
                ],
            )
        )
    return out


async def _one(db: AsyncSession, user: User, req: PreContractRequest) -> RequestOut:
    return (await _serialize(db, user, [req], with_events=True))[0]


def _valid_until_of(doc: B2BContractDocument) -> Optional[date]:
    raw = ((doc.render_payload or {}).get("values") or {}).get("valid_until")
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


# ── Prośba ───────────────────────────────────────────────────────────────────


@router.post("/pre-contracts", response_model=RequestOut)
async def create_request(
    body: CreateRequest,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Poproś o przedwstępną dla osoby. Gdy prośba w toku już jest — dopisz się
    do obserwujących (druga prośba nie tworzy drugiej umowy)."""
    await ensure_job_read_access(db, current_user, body.job_id)
    job = await db.get(Job, body.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    columns = await svc.pair_columns(db, [(body.candidate_id, body.job_id)])
    if (body.candidate_id, body.job_id) not in columns:
        raise HTTPException(status_code=409, detail=MSG_NOT_IN_JOB)
    if body.needed_before == "date" and body.needed_by is None:
        raise HTTPException(
            status_code=422, detail="Podaj datę, do której umowa ma być podpisana."
        )

    existing = await db.scalar(
        select(PreContractRequest)
        .where(
            PreContractRequest.candidate_id == body.candidate_id,
            PreContractRequest.job_id == body.job_id,
            PreContractRequest.closed_at.is_(None),
        )
        .with_for_update()
    )
    if existing is not None:
        await svc.add_watchers(db, existing.id, [current_user.id])
        event = await svc.add_event(
            db,
            existing,
            "watcher_joined",
            actor_id=current_user.id,
            payload={"needed_before": body.needed_before, "reason": body.reason},
        )
        await svc.notify(
            db,
            existing,
            event,
            message=f"{current_user.name} też prosi o tę umowę"
            + (f": {body.reason}" if body.reason else "."),
            actor_id=current_user.id,
        )
        await db.commit()
        return await _one(db, current_user, existing)

    assignee = body.assignee_id or await pair_recruiter_id(
        db, candidate_id=body.candidate_id, job_id=body.job_id
    )
    if assignee is None:
        assignee = job.recruiter_id or current_user.id
    req = PreContractRequest(
        candidate_id=body.candidate_id,
        job_id=body.job_id,
        client_id=job.client_id,
        needed_before=body.needed_before,
        needed_by=body.needed_by,
        reason=(body.reason or "").strip() or None,
        requested_by=current_user.id,
        assignee_id=assignee,
    )
    db.add(req)
    await db.flush()
    await svc.add_watchers(db, req.id, [current_user.id, assignee])
    event = await svc.add_event(
        db,
        req,
        "requested",
        actor_id=current_user.id,
        payload={"needed_before": req.needed_before, "assignee_id": assignee},
    )
    needed = svc.NEEDED_BEFORE_LABEL.get(req.needed_before, "")
    await svc.notify(
        db,
        req,
        event,
        message=f"{current_user.name} prosi o umowę przedwstępną {needed}"
        + (f": {req.reason}" if req.reason else "."),
        actor_id=current_user.id,
        only_user_ids=[assignee],
    )
    await db.commit()
    return await _one(db, current_user, req)


@router.patch("/pre-contracts/{request_id}", response_model=RequestOut)
async def update_request(
    request_id: int,
    body: UpdateRequest,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    changes: dict[str, Any] = {}
    if body.needed_before is not None and body.needed_before != req.needed_before:
        changes["needed_before"] = [req.needed_before, body.needed_before]
        req.needed_before = body.needed_before
    if "needed_by" in body.model_fields_set and body.needed_by != req.needed_by:
        changes["needed_by"] = [_iso(req.needed_by), _iso(body.needed_by)]
        req.needed_by = body.needed_by
    if req.needed_before == "date" and req.needed_by is None:
        raise HTTPException(
            status_code=422, detail="Podaj datę, do której umowa ma być podpisana."
        )
    if body.assignee_id is not None and body.assignee_id != req.assignee_id:
        assignee = await db.get(User, body.assignee_id)
        if assignee is None or not assignee.is_active:
            raise HTTPException(status_code=422, detail="Wybierz aktywne konto.")
        changes["assignee_id"] = [req.assignee_id, body.assignee_id]
        req.assignee_id = body.assignee_id
        await svc.add_watchers(db, req.id, [body.assignee_id])
        event = await svc.add_event(
            db, req, "assignee_changed", actor_id=current_user.id, payload=changes
        )
        await svc.notify(
            db,
            req,
            event,
            message=f"{current_user.name} przekazał(a) Ci wystawienie umowy przedwstępnej.",
            actor_id=current_user.id,
            only_user_ids=[body.assignee_id],
        )
    elif changes:
        await svc.add_event(
            db, req, "updated", actor_id=current_user.id, payload=changes
        )
    await db.commit()
    return await _one(db, current_user, req)


@router.get("/pre-contracts/pair", response_model=PairOut)
async def pair_requests(
    current_user: CandidatePIIAccess,
    candidate_id: int = Query(...),
    job_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Prośba w toku i zamknięte — sekcja „Umowa przedwstępna” w panelu osoby."""
    await ensure_job_read_access(db, current_user, job_id)
    rows = (
        await db.scalars(
            select(PreContractRequest)
            .where(
                PreContractRequest.candidate_id == candidate_id,
                PreContractRequest.job_id == job_id,
            )
            .order_by(
                PreContractRequest.requested_at.desc(), PreContractRequest.id.desc()
            )
        )
    ).all()
    items = await _serialize(db, current_user, list(rows), with_events=True)
    current = next((i for i in items if i.is_open), None)
    linked = {r.document_id for r in rows if r.document_id}
    docs = (
        await db.scalars(
            select(B2BContractDocument)
            .where(
                B2BContractDocument.candidate_id == candidate_id,
                B2BContractDocument.job_id == job_id,
                B2BContractDocument.document_type.like("preliminary%"),
                B2BContractDocument.status != "cancelled",
            )
            .order_by(
                B2BContractDocument.document_date.desc(), B2BContractDocument.id.desc()
            )
        )
    ).all()
    return PairOut(
        current=current,
        history=[i for i in items if not i.is_open],
        documents=[
            PairDocument(
                id=d.id,
                document_type=d.document_type,
                document_date=d.document_date,
                status=d.status,
                signed=d.signature_status == "signed_both",
                linked=d.id in linked,
            )
            for d in docs
        ],
    )


@router.get("/pre-contracts/{request_id}", response_model=RequestOut)
async def get_request(
    request_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_for(db, current_user, request_id, lock=False)
    return await _one(db, current_user, req)


# ── Lista „Umowy przedwstępne” ───────────────────────────────────────────────

TABS = ("todo", "mine", "expiring", "b2b", "penalty", "all")


@router.get("/pre-contracts", response_model=ListOut)
async def list_requests(
    current_user: CandidatePIIAccess,
    tab: Literal["todo", "mine", "expiring", "b2b", "penalty", "all"] = Query("todo"),
    db: AsyncSession = Depends(get_db),
):
    """Lista dla Head of Recruitment (wszystko), Delivery Leada (swoi klienci
    i swoje prośby) i rekrutera (to, co ma wystawić, i to, o co prosił).

    Liczniki zakładek liczy ta sama reguła widoczności."""
    uid = current_user.id
    involved = or_(
        PreContractRequest.requested_by == uid,
        PreContractRequest.assignee_id == uid,
        exists().where(
            and_(
                PreContractWatcher.request_id == PreContractRequest.id,
                PreContractWatcher.user_id == uid,
            )
        ),
    )
    if _sees_all(current_user):
        visible = None
    elif current_user.has_role(UserRole.delivery_lead):
        portfolio = await dl_portfolio_client_ids(db, uid)
        visible = (
            or_(involved, PreContractRequest.client_id.in_(portfolio))
            if portfolio
            else involved
        )
    else:
        visible = involved
    today = svc.today()
    recent = svc.now_utc() - timedelta(days=90)
    open_ = PreContractRequest.closed_at.is_(None)
    filters = {
        "todo": and_(open_, PreContractRequest.company_signed_at.is_(None)),
        "mine": and_(involved, or_(open_, PreContractRequest.closed_at >= recent)),
        "expiring": and_(
            open_,
            PreContractRequest.company_signed_at.is_not(None),
            PreContractRequest.valid_until <= today + timedelta(days=svc.EXPIRING_DAYS),
        ),
        "b2b": and_(open_, PreContractRequest.b2b_deadline.is_not(None)),
        "penalty": and_(
            PreContractRequest.close_reason == "candidate_withdrew",
            PreContractRequest.withdrawal["decision"].astext.is_(None),
        ),
        "all": or_(open_, PreContractRequest.closed_at >= recent),
    }
    counts: dict[str, int] = {}
    from sqlalchemy import func  # noqa: PLC0415

    for key, clause in filters.items():
        stmt = select(func.count(PreContractRequest.id)).where(clause)
        if visible is not None:
            stmt = stmt.where(visible)
        counts[key] = int(await db.scalar(stmt) or 0)
    stmt = select(PreContractRequest).where(filters[tab])
    if visible is not None:
        stmt = stmt.where(visible)
    stmt = stmt.order_by(PreContractRequest.requested_at.desc()).limit(300)
    rows = list((await db.scalars(stmt)).all())
    return ListOut(items=await _serialize(db, current_user, rows), counts=counts)


# ── Kroki umowy ──────────────────────────────────────────────────────────────


@router.post("/pre-contracts/{request_id}/document", response_model=RequestOut)
async def link_document(
    request_id: int,
    body: LinkDocument,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Wskaż umowę wystawioną w Generatorze dokumentów (rodzina „preliminary”,
    ta sama osoba i rekrutacja). Data ważności przychodzi z umowy."""
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    doc = await db.get(B2BContractDocument, body.document_id)
    if (
        doc is None
        or not doc.document_type.startswith("preliminary")
        or doc.candidate_id != req.candidate_id
        or doc.job_id != req.job_id
        or doc.status == "cancelled"
    ):
        raise HTTPException(status_code=422, detail=MSG_DOC)
    first = req.document_id is None
    req.document_id = doc.id
    req.issued_at = req.issued_at or svc.now_utc()
    req.valid_until = _valid_until_of(doc) or req.valid_until
    event = await svc.add_event(
        db,
        req,
        "issued",
        actor_id=current_user.id,
        payload={"document_id": doc.id, "document_type": doc.document_type},
    )
    if first:
        await svc.notify(
            db,
            req,
            event,
            message=f"{current_user.name} wystawił(a) umowę przedwstępną.",
            actor_id=current_user.id,
        )
    await db.commit()
    return await _one(db, current_user, req)


@router.post("/pre-contracts/{request_id}/sent", response_model=RequestOut)
async def mark_sent(
    request_id: int,
    body: MarkSent,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    if req.document_id is None:
        raise HTTPException(status_code=409, detail=MSG_NO_DOC)
    req.sent_at = svc.now_utc()
    event = await svc.add_event(
        db,
        req,
        "sent",
        actor_id=current_user.id,
        payload={"note": body.note} if body.note else None,
    )
    await svc.notify(
        db,
        req,
        event,
        message=f"{current_user.name} wysłał(a) umowę przedwstępną kandydatowi.",
        actor_id=current_user.id,
    )
    await db.commit()
    return await _one(db, current_user, req)


async def _store(
    db: AsyncSession, req: PreContractRequest, upload: UploadFile
) -> tuple[str, str, Optional[str]]:
    name, _content_type, data = await read_scan(
        upload, format_msg="Podpisana umowa musi być plikiem PDF, JPG albo PNG."
    )
    path, _size = storage_service.save_pre_contract_file(req.id, name, data)
    return name, path, None


@router.post("/pre-contracts/{request_id}/candidate-signed", response_model=RequestOut)
async def candidate_signed(
    request_id: int,
    current_user: CandidatePIIAccess,
    signature_form: SignatureForm = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Plik podpisany przez kandydata — w dowolnej formie (decyzja 21.10.2026)."""
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    if req.document_id is None:
        raise HTTPException(status_code=409, detail=MSG_NO_DOC)
    name, path, _ = await _store(db, req, file)
    old = req.candidate_file_path
    req.sent_at = req.sent_at or svc.now_utc()
    req.candidate_signed_at = svc.now_utc()
    req.candidate_signature_form = signature_form
    req.candidate_file_path = path
    req.candidate_file_name = name
    event = await svc.add_event(
        db,
        req,
        "candidate_signed",
        actor_id=current_user.id,
        payload={"signature_form": signature_form, "file_name": name},
    )
    form = svc.SIGNATURE_FORM_LABEL.get(signature_form, signature_form)
    await svc.notify(
        db,
        req,
        event,
        message=f"Kandydat podpisał umowę przedwstępną ({form}) — czeka podpis firmy.",
        actor_id=current_user.id,
    )
    await db.commit()
    if old and old != path:
        storage_service.delete_pre_contract_file(old)
    return await _one(db, current_user, req)


@router.post("/pre-contracts/{request_id}/company-signed", response_model=RequestOut)
async def company_signed(
    request_id: int,
    current_user: CandidatePIIAccess,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Plik podpisany obustronnie. Umowa w Generatorze przechodzi na
    „podpisana” (przedwstępna niczego w kontraktach nie zmienia)."""
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    if req.candidate_signed_at is None:
        raise HTTPException(status_code=409, detail=MSG_NO_CANDIDATE_SIGNATURE)
    name, path, _ = await _store(db, req, file)
    old = req.company_file_path
    now = svc.now_utc()
    req.company_signed_at = now
    req.company_file_path = path
    req.company_file_name = name
    if req.document_id is not None:
        doc = await db.get(B2BContractDocument, req.document_id, with_for_update=True)
        if (
            doc is not None
            and doc.signature_status != "signed_both"
            and doc.status != "cancelled"
        ):
            doc.signature_status = "signed_both"
            doc.status = "signed"
            doc.signed_at = now
            doc.signed_by_user_id = current_user.id
    event = await svc.add_event(
        db, req, "company_signed", actor_id=current_user.id, payload={"file_name": name}
    )
    until = f" Ważna do {req.valid_until:%d.%m.%Y}." if req.valid_until else ""
    await svc.notify(
        db,
        req,
        event,
        message=f"Umowa przedwstępna podpisana obustronnie.{until}",
        actor_id=current_user.id,
    )
    await db.commit()
    if old and old != path:
        storage_service.delete_pre_contract_file(old)
    return await _one(db, current_user, req)


@router.get("/pre-contracts/{request_id}/files/{kind}")
async def download_file(
    request_id: int,
    kind: Literal["candidate", "company"],
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_for(db, current_user, request_id, lock=False)
    path = req.candidate_file_path if kind == "candidate" else req.company_file_path
    name = req.candidate_file_name if kind == "candidate" else req.company_file_name
    if not path:
        raise HTTPException(status_code=404, detail=MSG_NO_FILE)
    try:
        data = storage_service.read_pre_contract_file(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=MSG_NO_FILE) from exc
    media = "application/pdf"
    lowered = (name or "").lower()
    if lowered.endswith((".jpg", ".jpeg")):
        media = "image/jpeg"
    elif lowered.endswith(".png"):
        media = "image/png"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": content_disposition(name or "umowa.pdf")},
    )


# ── Obserwujący ──────────────────────────────────────────────────────────────


@router.post("/pre-contracts/{request_id}/watch", response_model=RequestOut)
async def watch(
    request_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_for(db, current_user, request_id, lock=False)
    await svc.add_watchers(db, req.id, [current_user.id])
    await db.commit()
    return await _one(db, current_user, req)


@router.delete("/pre-contracts/{request_id}/watch", response_model=RequestOut)
async def unwatch(
    request_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete  # noqa: PLC0415

    req = await _load_for(db, current_user, request_id, lock=False)
    await db.execute(
        delete(PreContractWatcher).where(
            PreContractWatcher.request_id == req.id,
            PreContractWatcher.user_id == current_user.id,
        )
    )
    await db.commit()
    return await _one(db, current_user, req)


# ── Zamknięcie ───────────────────────────────────────────────────────────────


async def _close(
    db: AsyncSession,
    req: PreContractRequest,
    *,
    reason: str,
    actor: User,
    message: str,
    payload: Optional[dict[str, Any]] = None,
    cancel_document: bool = False,
) -> None:
    req.closed_at = svc.now_utc()
    req.close_reason = reason
    req.closed_by = actor.id
    if cancel_document and req.document_id is not None:
        doc = await db.get(B2BContractDocument, req.document_id, with_for_update=True)
        if (
            doc is not None
            and doc.signature_status != "signed_both"
            and doc.status == "issued"
        ):
            doc.status = "cancelled"
            doc.cancelled_reason = (payload or {}).get("reason") or "Prośba zamknięta."
    event = await svc.add_event(db, req, reason, actor_id=actor.id, payload=payload)
    await svc.notify(db, req, event, message=message, actor_id=actor.id)


@router.post("/pre-contracts/{request_id}/withdraw", response_model=RequestOut)
async def withdraw_request(
    request_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Proszący wycofuje prośbę, dopóki umowa nie wyszła do kandydata."""
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    if req.sent_at is not None:
        raise HTTPException(status_code=409, detail=MSG_WITHDRAW_AFTER_SEND)
    if req.requested_by != current_user.id and not _sees_all(current_user):
        raise HTTPException(status_code=403, detail=MSG_ONLY_REQUESTER)
    await _close(
        db,
        req,
        reason="withdrawn",
        actor=current_user,
        message=f"{current_user.name} wycofał(a) prośbę o umowę przedwstępną.",
        cancel_document=True,
    )
    await db.commit()
    return await _one(db, current_user, req)


@router.post("/pre-contracts/{request_id}/cancel", response_model=RequestOut)
async def cancel_request(
    request_id: int,
    body: CloseBody,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    await _close(
        db,
        req,
        reason="cancelled",
        actor=current_user,
        message=f"{current_user.name} anulował(a) umowę przedwstępną: {body.reason}",
        payload={"reason": body.reason},
        cancel_document=True,
    )
    await db.commit()
    return await _one(db, current_user, req)


@router.post("/pre-contracts/{request_id}/candidate-refused", response_model=RequestOut)
async def candidate_refused(
    request_id: int,
    body: CloseBody,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    if req.candidate_signed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Kandydat już podpisał — użyj „Kandydat zrezygnował…”.",
        )
    await _close(
        db,
        req,
        reason="candidate_refused",
        actor=current_user,
        message=f"Kandydat odmówił podpisu umowy przedwstępnej: {body.reason}",
        payload={"reason": body.reason},
        cancel_document=True,
    )
    await db.commit()
    return await _one(db, current_user, req)


@router.post("/pre-contracts/{request_id}/fulfilled", response_model=RequestOut)
async def mark_fulfilled(
    request_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Umowa spełniła rolę (np. podpisana umowa B2B) — zamknij bez kary."""
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    if not svc.is_signed(req):
        raise HTTPException(
            status_code=409, detail="Zrealizować można tylko podpisaną umowę."
        )
    await _close(
        db,
        req,
        reason="fulfilled",
        actor=current_user,
        message="Umowa przedwstępna zrealizowana.",
    )
    await db.commit()
    return await _one(db, current_user, req)


@router.post(
    "/pre-contracts/{request_id}/candidate-withdrew", response_model=RequestOut
)
async def candidate_withdrew(
    request_id: int,
    body: WithdrawalBody,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Kandydat zrezygnował, gdy umowa obowiązywała — zbiera dowód do decyzji
    o karze (stan umowy w chwili zdarzenia). Sam niczego nie nalicza."""
    req = await _load_for(db, current_user, request_id)
    _require_open(req)
    if not svc.is_signed(req):
        raise HTTPException(
            status_code=409,
            detail="Umowa nie jest podpisana obustronnie — kara z niej nie przysługuje.",
        )
    decision_user = body.decision_user_id
    if decision_user is not None:
        target = await db.get(User, decision_user)
        if target is None or not target.is_active:
            raise HTTPException(status_code=422, detail="Wybierz aktywne konto.")
    req.withdrawal = {
        "kind": body.kind,
        "kind_label": svc.WITHDRAWAL_LABEL[body.kind],
        "event_on": body.event_on.isoformat(),
        "note": body.note,
        "decision_user_id": decision_user,
        "recorded_by": current_user.id,
        "contract_state": {
            "candidate_signed_at": _iso(req.candidate_signed_at),
            "company_signed_at": _iso(req.company_signed_at),
            "valid_until": _iso(req.valid_until),
            "in_force": req.valid_until is None or body.event_on <= req.valid_until,
        },
        "decision": None,
    }
    await _close(
        db,
        req,
        reason="candidate_withdrew",
        actor=current_user,
        message=(
            f"Kandydat {svc.WITHDRAWAL_LABEL[body.kind]} ({body.event_on:%d.%m.%Y}). "
            "Umowa przedwstępna obowiązywała — decyzja o karze."
        ),
        payload={"kind": body.kind, "event_on": body.event_on.isoformat()},
    )
    if decision_user:
        await svc.add_watchers(db, req.id, [decision_user])
    await db.commit()
    return await _one(db, current_user, req)


@router.post("/pre-contracts/{request_id}/penalty-decision", response_model=RequestOut)
async def penalty_decision(
    request_id: int,
    body: PenaltyDecision,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_for(db, current_user, request_id)
    withdrawal = dict(req.withdrawal or {})
    if req.close_reason != "candidate_withdrew" or withdrawal.get("decision"):
        raise HTTPException(status_code=409, detail="Tu nie ma decyzji do podjęcia.")
    if not (
        _sees_all(current_user) or withdrawal.get("decision_user_id") == current_user.id
    ):
        raise HTTPException(status_code=403, detail=MSG_ONLY_HOR)
    withdrawal["decision"] = body.decision
    withdrawal["decision_note"] = body.note
    withdrawal["decided_by"] = current_user.id
    withdrawal["decided_at"] = svc.now_utc().isoformat()
    req.withdrawal = withdrawal
    event = await svc.add_event(
        db,
        req,
        "penalty_decision",
        actor_id=current_user.id,
        payload={"decision": body.decision},
    )
    verdict = "wezwanie do zapłaty kary" if body.decision == "demand" else "bez kary"
    await svc.notify(
        db,
        req,
        event,
        message=f"{current_user.name} zdecydował(a): {verdict}.",
        actor_id=current_user.id,
    )
    await db.commit()
    return await _one(db, current_user, req)
