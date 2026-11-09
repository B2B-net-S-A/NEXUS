"""Rekrutacja własna: trasy właściciela i asystentki.

Dostęp wynika z listy osób w procesie, nie z roli ani sekcji: asystentka może mieć
konto bez sekcji rekrutacji, a inni admini nie widzą procesu.
Reguły: ``docs/claude/rekrutacja-tablica/rekrutacja-wlasna.md``.
"""

from datetime import date, datetime, time, timezone
from typing import Annotated, Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.scheduling import DEFAULT_TZ
from app.models.user import User, UserRole
from app.services.own_hiring import booking as booking_service
from app.services.own_hiring import service
from app.services.own_hiring.service import Context, OwnHiringError

router = APIRouter()


def _http(exc: OwnHiringError) -> HTTPException:
    return HTTPException(
        status_code=exc.status, detail={"code": exc.code, "message": exc.message}
    )


def require_own_hiring_access(*roles: str):
    """Bramka modułu: osoba musi być w procesie, w jednej z podanych ról."""

    async def _gate(user: CurrentUser, db: AsyncSession = Depends(get_db)) -> Context:
        ctx = await service.context_for(db, user)
        if ctx is None or ctx.role not in roles:
            raise HTTPException(status_code=403, detail="Brak dostępu do tego procesu.")
        return ctx

    return _gate


OwnerContext = Annotated[Context, Depends(require_own_hiring_access("owner"))]
MemberContext = Annotated[
    Context, Depends(require_own_hiring_access("owner", "assistant"))
]


class IdsIn(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=200)


class ProcessIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=160)
    ad_titles: list[str] = Field(default_factory=list, max_length=30)
    intake_since: date

    @field_validator("ad_titles")
    @classmethod
    def _clean_titles(cls, value: list[str]) -> list[str]:
        return [" ".join(item.split())[:300] for item in value if item.strip()]


class Settings(BaseModel):
    windows: dict[str, list[list[str]]]
    slot_minutes: int = Field(..., ge=15, le=120)
    office_minutes: int = Field(..., ge=30, le=240)
    buffer_minutes: int = Field(..., ge=0, le=60)
    lead_hours: int = Field(..., ge=1, le=168)
    horizon_days: int = Field(..., ge=1, le=60)
    response_business_days: int = Field(..., ge=1, le=10)
    office_address: str = Field("", max_length=300)

    @field_validator("windows")
    @classmethod
    def _valid_windows(
        cls, value: dict[str, list[list[str]]]
    ) -> dict[str, list[list[str]]]:
        for day, spans in value.items():
            if day not in {"0", "1", "2", "3", "4", "5", "6"}:
                raise ValueError("Nieznany dzień tygodnia.")
            for span in spans:
                if len(span) != 2:
                    raise ValueError("Okno ma początek i koniec.")
                start, end = (_parse_clock(item) for item in span)
                if start >= end:
                    raise ValueError("Początek okna musi być przed końcem.")
        return value


def _parse_clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Godzina w formacie GG:MM.") from exc


class SettingsIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=160)
    ad_titles: list[str] = Field(default_factory=list, max_length=30)
    assistant_user_id: Optional[int] = None
    settings: Settings

    @field_validator("ad_titles")
    @classmethod
    def _clean_titles(cls, value: list[str]) -> list[str]:
        return [" ".join(item.split())[:300] for item in value if item.strip()]


class MoveIn(BaseModel):
    stage: str = Field(..., max_length=20)


class TeamsOutcomeIn(BaseModel):
    availability: Optional[Literal["now", "month", "quarter", "later"]] = None
    expected_money: Optional[str] = Field(None, max_length=160)
    tech_level: Optional[Literal["good", "partial", "poor"]] = None
    note: Optional[str] = Field(None, max_length=4000)
    decision: Literal["office", "reject"]
    office_start: Optional[AwareDatetime] = None


class OfficeOutcomeIn(BaseModel):
    note: Optional[str] = Field(None, max_length=4000)
    decision: Literal["contract", "withdraw"]
    contract_kind: Optional[Literal["b2b", "employment", "mandate"]] = None


class ContractOutcomeIn(BaseModel):
    decision: Literal["signed", "withdrawn"]


class BookIn(BaseModel):
    start: AwareDatetime


class CallResultIn(BaseModel):
    result: Literal["no_answer", "callback", "withdrawn"]
    callback_at: Optional[AwareDatetime] = None


@router.get("/me")
async def me(user: CurrentUser, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Tylko o własnym członkostwie: po tym menu wie, czy pokazać wejście."""
    ctx = await service.context_for(db, user)
    return {
        "role": ctx.role if ctx else None,
        "can_create": user.has_role(UserRole.admin),
    }


@router.post("/process", status_code=201)
async def create_process(
    body: ProcessIn,
    user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    since = datetime.combine(
        body.intake_since, time(0, 0), tzinfo=ZoneInfo(DEFAULT_TZ)
    ).astimezone(timezone.utc)
    try:
        process = await service.create_process(
            db,
            owner=user,
            title=body.title,
            ad_titles=body.ad_titles,
            intake_since=since,
        )
    except OwnHiringError as exc:
        raise _http(exc) from exc
    return service.process_out(process)


@router.get("/process")
async def get_process(ctx: OwnerContext) -> dict[str, Any]:
    return service.process_out(ctx.process)


@router.put("/process")
async def put_process(
    body: SettingsIn, ctx: OwnerContext, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        process = await service.update_settings(
            db,
            ctx,
            title=body.title,
            ad_titles=body.ad_titles,
            assistant_user_id=body.assistant_user_id,
            settings=body.settings.model_dump(),
        )
    except OwnHiringError as exc:
        raise _http(exc) from exc
    return service.process_out(process)


@router.get("/assistant-options")
async def assistant_options(
    ctx: OwnerContext, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    return await service.assistant_options(db)


@router.get("/board")
async def board(
    ctx: OwnerContext, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await service.board(db, ctx.process)


@router.get("/new")
async def new_list(
    ctx: OwnerContext,
    bucket: Literal["match", "review", "filtered"] = Query("match"),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    return await service.new_list(db, ctx.process, bucket=bucket)


@router.get("/invitation-preview")
async def invitation_preview(ctx: OwnerContext) -> dict[str, Any]:
    return service.invitation_preview(ctx.process)


@router.post("/applications/invite")
async def invite(
    body: IdsIn, ctx: OwnerContext, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        return {"results": await service.invite(db, ctx, body.ids)}
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/applications/reject")
async def reject(
    body: IdsIn, ctx: OwnerContext, db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    return {"rejected": await service.reject(db, ctx, body.ids)}


@router.post("/applications/hand-off")
async def hand_off(
    body: IdsIn, ctx: OwnerContext, db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    try:
        return {"handed_off": await service.hand_off(db, ctx, body.ids)}
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.get("/applications/{application_id}")
async def detail(
    application_id: int, ctx: OwnerContext, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        return await service.detail(db, ctx.process, application_id)
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/applications/{application_id}/move")
async def move(
    application_id: int,
    body: MoveIn,
    ctx: OwnerContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await service.move(db, ctx, application_id, body.stage)
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/applications/{application_id}/teams-outcome")
async def teams_outcome(
    application_id: int,
    body: TeamsOutcomeIn,
    ctx: OwnerContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await service.teams_outcome(
            db,
            ctx,
            application_id,
            availability=body.availability,
            expected_money=body.expected_money,
            tech_level=body.tech_level,
            note=body.note,
            decision=body.decision,
            office_start=body.office_start,
        )
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/applications/{application_id}/no-show")
async def no_show(
    application_id: int, ctx: OwnerContext, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        return await service.no_show(db, ctx, application_id)
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/applications/{application_id}/office-outcome")
async def office_outcome(
    application_id: int,
    body: OfficeOutcomeIn,
    ctx: OwnerContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await service.office_outcome(
            db,
            ctx,
            application_id,
            note=body.note,
            decision=body.decision,
            contract_kind=body.contract_kind,
        )
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/applications/{application_id}/contract-outcome")
async def contract_outcome(
    application_id: int,
    body: ContractOutcomeIn,
    ctx: OwnerContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await service.contract_outcome(
            db, ctx, application_id, decision=body.decision
        )
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.get("/slots")
async def slots(
    ctx: MemberContext,
    kind: Literal["teams", "office"] = Query("teams"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await booking_service.slots_payload(db, ctx.process, kind=kind)


@router.get("/queue")
async def queue(
    ctx: MemberContext, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    return await service.call_queue(db, ctx.process)


@router.post("/queue/{application_id}/book")
async def queue_book(
    application_id: int,
    body: BookIn,
    ctx: MemberContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    try:
        await booking_service.book_from_queue(db, ctx, application_id, start=body.start)
    except OwnHiringError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.post("/queue/{application_id}/result")
async def queue_result(
    application_id: int,
    body: CallResultIn,
    ctx: MemberContext,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    try:
        await service.call_result(
            db, ctx, application_id, result=body.result, callback_at=body.callback_at
        )
    except OwnHiringError as exc:
        raise _http(exc) from exc
    return {"ok": True}
