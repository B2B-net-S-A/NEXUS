"""Praktykant — „Telefony na dziś” i panel Head of Recruitment (0374).

Trasy praktykanta stoją poza sekcjami (praktykant nie ma żadnej) na
``TraineeUser`` i widzą wyłącznie pozycje własnej listy; karta kandydata to
wąski odczyt z tej listy, nie profil. Trasy panelu — admin i Head of
Recruitment (``HeadOfRecruitmentPlus``). Kontrakt:
``docs/trainee-call-lists-contract.md``.
"""

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, TraineeUser
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.services import trainee_call_list as lists
from app.services import trainee_program as program_service
from app.services import trainee_rules as rules_mod

router = APIRouter()


class MinRate(BaseModel):
    value: float = Field(gt=0, lt=1_000_000)
    unit: Literal["hour", "day", "month"] = "hour"


class CallFactsIn(BaseModel):
    b2b_willingness: Literal["b2b", "would_switch", "employment_only"]
    min_rate: Optional[MinRate] = None
    accepts_below_min_rate: Optional[bool] = None
    remote_modes: list[Literal["remote", "hybrid", "onsite"]] = Field(
        default_factory=list, max_length=3
    )
    max_onsite_days: Optional[int] = Field(default=None, ge=0, le=5)
    accepts_more_office_days: Optional[bool] = None
    office_cities: list[str] = Field(default_factory=list, max_length=10)
    work_time_preference: Optional[
        Literal["full_time_only", "also_part_time", "part_time_only"]
    ] = None
    availability: Optional[Literal["now", "within_1m", "within_3m", "later"]] = None
    open_to_offers: Optional[Literal["yes", "maybe", "no"]] = None
    wants: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("office_cities")
    @classmethod
    def _cities(cls, value: list[str]) -> list[str]:
        out = []
        for city in value:
            clean = city.strip()[:80]
            if clean and clean not in out:
                out.append(clean)
        return out

    @field_validator("wants")
    @classmethod
    def _wants(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None

    def to_facts(self) -> program_service.CallFacts:
        return program_service.CallFacts(
            b2b_willingness=self.b2b_willingness,
            min_rate_value=self.min_rate.value if self.min_rate else None,
            min_rate_unit=self.min_rate.unit if self.min_rate else "hour",
            accepts_below_min_rate=self.accepts_below_min_rate,
            remote_modes=tuple(dict.fromkeys(self.remote_modes)),
            max_onsite_days=self.max_onsite_days,
            accepts_more_office_days=self.accepts_more_office_days,
            office_cities=tuple(self.office_cities),
            work_time_preference=self.work_time_preference,
            availability=self.availability,
            open_to_offers=self.open_to_offers,
            wants=self.wants,
        )


class OutcomeIn(BaseModel):
    outcome: Literal["noanswer", "later", "wrong", "declined"]
    later_date: Optional[date] = None


class HandoverIn(BaseModel):
    job_id: int
    note: Optional[str] = Field(default=None, max_length=1000)


class ProgramIn(BaseModel):
    start_date: Optional[date] = None
    workdays: Optional[int] = Field(default=None, ge=1, le=250)
    daily_list_size: Optional[int] = Field(default=None, ge=1, le=300)


class DecisionIn(BaseModel):
    action: Literal["promote", "extend", "end"]
    role: Optional[Literal["sourcer", "recruiter"]] = None
    add_to_my_people: bool = True
    extend_days: int = Field(default=20, ge=1, le=120)


class QualityIn(BaseModel):
    verdict: Literal["ok", "issue"]
    note: Optional[str] = Field(default=None, max_length=1000)


# ── Praktykant ────────────────────────────────────────────────────────────


def _is_preview(request: Request) -> bool:
    """Admin w „podglądzie jako” — GET ma wtedy niczego nie zapisywać."""
    return getattr(request.state, "impersonator_id", None) is not None


@router.get("/today")
async def get_today(
    request: Request, user: TraineeUser, db: AsyncSession = Depends(get_db)
):
    return await program_service.today_view(db, user, read_only=_is_preview(request))


@router.post("/items/{item_id}/call")
async def save_call(
    item_id: int,
    body: CallFactsIn,
    user: TraineeUser,
    db: AsyncSession = Depends(get_db),
):
    return await program_service.save_call(db, user, item_id, body.to_facts())


@router.post("/items/{item_id}/outcome")
async def save_outcome(
    item_id: int,
    body: OutcomeIn,
    user: TraineeUser,
    db: AsyncSession = Depends(get_db),
):
    return await program_service.record_outcome(
        db, user, item_id, body.outcome, body.later_date
    )


@router.get("/items/{item_id}/open-jobs")
async def get_open_jobs(
    item_id: int, user: TraineeUser, db: AsyncSession = Depends(get_db)
):
    return await program_service.open_jobs(db, user, item_id)


@router.post("/items/{item_id}/handover")
async def post_handover(
    item_id: int,
    body: HandoverIn,
    user: TraineeUser,
    db: AsyncSession = Depends(get_db),
):
    return await program_service.handover(db, user, item_id, body.job_id, body.note)


# ── Head of Recruitment i admin ───────────────────────────────────────────
# Sufit sekcji Pipeline (lustro „Moich ludzi” i propozycji) + rola.


@router.get("/overview", dependencies=PIPELINE_SECTION_DEPENDENCIES)
async def get_overview(
    _user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
):
    return await program_service.overview(db)


@router.put("/programs/{user_id}", dependencies=PIPELINE_SECTION_DEPENDENCIES)
async def put_program(
    user_id: int,
    body: ProgramIn,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    return await program_service.update_program(
        db,
        user_id,
        start_date=body.start_date,
        workdays=body.workdays,
        daily_list_size=body.daily_list_size,
    )


@router.post("/programs/{user_id}/decision", dependencies=PIPELINE_SECTION_DEPENDENCIES)
async def post_decision(
    user_id: int,
    body: DecisionIn,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    return await program_service.decide(
        db,
        user,
        user_id,
        action=body.action,
        role=body.role,
        add_to_my_people=body.add_to_my_people,
        extend_days=body.extend_days,
    )


@router.get("/quality-sample", dependencies=PIPELINE_SECTION_DEPENDENCIES)
async def get_quality_sample(
    _user: HeadOfRecruitmentPlus,
    user_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    return await program_service.quality_sample(db, user_id)


@router.post("/quality-sample/{item_id}", dependencies=PIPELINE_SECTION_DEPENDENCIES)
async def post_quality(
    item_id: int,
    body: QualityIn,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    return await program_service.set_quality(db, user, item_id, body.verdict, body.note)


@router.get("/rules", dependencies=PIPELINE_SECTION_DEPENDENCIES)
async def get_rules(_user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)):
    return await lists.load_rules(db)


@router.put("/rules", dependencies=PIPELINE_SECTION_DEPENDENCIES)
async def put_rules(
    body: dict,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    rules = await lists.save_rules(db, body, user_id=user.id)
    await db.commit()
    lists.reset_ranking_cache()
    return rules


@router.get("/rules/preview", dependencies=PIPELINE_SECTION_DEPENDENCIES)
async def get_rules_preview(
    request: Request,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Wielkość puli przy regułach z formularza (niezapisane wartości w query
    nadpisują zapisane). Liczone świeżo — kilka sekund, w wątku, jedno
    liczenie na te same reguły i pamiętane chwilę (runda 6 audytu).
    Statystyki panelu zapisujemy tylko dla reguł zapisanych."""
    saved = await lists.load_rules(db)
    overrides = _query_rules(request.query_params)
    rules = rules_mod.normalize_rules({**saved, **overrides})
    stats = await lists.preview_pool_stats(db, rules, today=business_today())
    if rules == saved and not _is_preview(request):
        await lists.store_pool_stats(db, stats)
        await db.commit()
    return stats


def _query_rules(params) -> dict:
    out: dict = {}
    for key, raw in params.items():
        if key not in rules_mod.DEFAULT_RULES:
            continue
        if isinstance(rules_mod.DEFAULT_RULES[key], bool):
            if raw.lower() in ("true", "1"):
                out[key] = True
            elif raw.lower() in ("false", "0"):
                out[key] = False
        else:
            out[key] = raw
    return out
