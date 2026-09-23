"""Router `/api/board-tasks` — kolejka „Czeka na Ciebie" (0348, 0353).

Odczyt listy (DZ, do wysłania do Cpro, wysłane do Cpro, przegląd DL przed
wysłaniem CV do klienta), przegląd DZ (CV dla klienta obok oryginału
i zapytania klienta, podpowiedzi Luny) i osoba, która wysyła do Cpro
kandydatów rekrutacji. Samo zatwierdzenie DZ i oznaczenie „wysłane" to zwykły
ruch w pipeline (`POST /api/pipeline/move`) — ta trasa nie ma własnej ścieżki
zapisu etapu, żeby reguły ruchu (wersja procesu, ostrzeżenia dopuszczalności,
odznaki) obowiązywały bez kopii.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services import board_tasks as svc
from app.services import dz_review
from app.services.board_stage_badges import DZ_BADGE_ROLES, cpro_enabled_for_client

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class BoardTaskRow(BaseModel):
    kind: Literal["dz", "cpro_to_send", "cpro_sent", "dl_review"]
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    since: datetime
    process_state_version: int
    target_stage_def_id: Optional[int] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    # Tylko przegląd DL (`dl_review`); przy pozostałych rodzajach puste.
    rejected_stage_def_id: Optional[int] = None
    verified_by_id: Optional[int] = None
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None
    expected_rate_value: Optional[float] = None
    expected_rate_unit: Optional[str] = None
    expected_rate_currency: Optional[str] = None
    screening_stage_id: Optional[int] = None
    job_sender_id: Optional[int] = None
    job_sender_name: Optional[str] = None


class BoardTasksResponse(BaseModel):
    dz: list[BoardTaskRow]
    cpro_to_send: list[BoardTaskRow]
    cpro_sent: list[BoardTaskRow]
    dl_review: list[BoardTaskRow]
    window_days: int
    dl_review_window_days: int
    can_approve_dz: bool
    # Ruch na „CV wysłane" ze stawką do klienta (u klientów spoza Nordei)
    # wykonuje wyłącznie admin albo Delivery Lead — Head of Recruitment widzi
    # kolejkę, ale serwer odmówiłby mu wysyłki.
    can_send_to_client: bool


class CproSenderUpdate(BaseModel):
    assignee_id: int


class CproSenderResponse(BaseModel):
    job_id: int
    assignee_id: int
    assignee_name: Optional[str] = None
    added_to_team: bool = False


class DzCheck(BaseModel):
    label: str
    # Frazy, których szukamy w CV (nazwa bez opisu i nawiasów) — front
    # podświetla dokładnie je.
    terms: list[str] = []
    in_cv: bool
    # None = pogrubień nie da się odczytać (CV dla klienta z PDF-a).
    bolded: Optional[bool] = None
    in_original: bool
    original_roles: list[str]
    missing_in_roles: list[str]
    roles_absent: list[str]


class DzClientRequest(BaseModel):
    must: list[str]
    nice: list[str]
    description: Optional[str] = None
    project_about: Optional[str] = None


class DzCvRun(BaseModel):
    t: str
    b: bool


class DzCvBlock(BaseModel):
    kind: Literal["h", "p", "li"]
    section: Optional[str] = None
    runs: list[DzCvRun]


class DzGeneratedCv(BaseModel):
    # `document` = plik „…B2B…" kandydata (CV zrobione poza generatorem).
    source: Literal["branded_finalized", "branded_draft", "generated", "document"]
    stage_id: Optional[int] = None
    generated_document_id: Optional[int] = None
    document_id: Optional[int] = None
    filename: Optional[str] = None
    bold_known: bool = True
    updated_at: Optional[datetime] = None
    blocks: list[DzCvBlock]


class DzOriginalCv(BaseModel):
    source: Optional[Literal["snapshot", "profile_text"]] = None
    stage_id: Optional[int] = None
    filename: Optional[str] = None
    text: Optional[str] = None


class DzReviewResponse(BaseModel):
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    client_request: DzClientRequest
    generated_cv: Optional[DzGeneratedCv] = None
    original_cv: DzOriginalCv
    checks: list[DzCheck]
    extra_bold: list[str]
    summary: dict[str, Any]


class DzHint(BaseModel):
    kind: str
    severity: Literal["high", "medium", "low"]
    must_have: Optional[str] = None
    message: str
    quote: Optional[str] = None


class DzHintsResponse(BaseModel):
    status: Literal["ok", "unavailable", "no_cv"]
    verdict: Optional[Literal["ok", "fix"]] = None
    hints: list[DzHint]
    model: Optional[str] = None
    cached: bool = False


@router.get("", response_model=BoardTasksResponse)
async def list_board_tasks(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> BoardTasksResponse:
    snapshot = await svc.load_snapshot(db)
    portfolio = await svc.dl_portfolio_client_ids(db, current_user.id)
    mine = svc.tasks_for_user(snapshot, current_user, portfolio=portfolio)
    return BoardTasksResponse(
        dz=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_DZ]],
        cpro_to_send=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_CPRO_TO_SEND]],
        # Najdłużej czekające na Nordeę na górze — wysłane rośnie w czasie.
        cpro_sent=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_CPRO_SENT]],
        dl_review=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_DL_REVIEW]],
        window_days=svc.WINDOW_DAYS,
        dl_review_window_days=svc.DL_REVIEW_WINDOW_DAYS,
        can_approve_dz=current_user.has_any_role(*DZ_BADGE_ROLES),
        can_send_to_client=current_user.has_any_role(
            UserRole.admin, UserRole.delivery_lead
        ),
    )


async def _dz_stage(db: AsyncSession, stage_id: int, user) -> CandidateStage:
    """Wiersz etapu do przeglądu DZ: rola z prawem DZ + dostęp do rekrutacji."""

    if not user.has_any_role(*DZ_BADGE_ROLES):
        raise HTTPException(
            status_code=403,
            detail="Przegląd DZ jest dla Delivery Leada i Head of Recruitment.",
        )
    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu kandydata.")
    await ensure_job_read_access(db, user, stage.job_id)
    return stage


@router.get("/dz/{stage_id}/review", response_model=DzReviewResponse)
async def get_dz_review(
    stage_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> DzReviewResponse:
    """CV dla klienta, oryginalne CV i zapytanie klienta + trzy sprawdzenia
    must-have (w CV, pogrubione, w każdej roli z oryginału). Tylko odczyt."""

    stage = await _dz_stage(db, stage_id, current_user)
    return DzReviewResponse(**await dz_review.build_review(db, stage))


@router.post("/dz/{stage_id}/hints", response_model=DzHintsResponse)
async def get_dz_hints(
    stage_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> DzHintsResponse:
    """Podpowiedzi GPT-6 Luny. Doradcze: awaria = ``unavailable``, nigdy 5xx.

    POST, bo pierwsze wywołanie dla danej treści CV płaci za model i zapisuje
    wynik; kolejne z tą samą treścią czytają zapamiętany.
    """

    stage = await _dz_stage(db, stage_id, current_user)
    review = await dz_review.build_review(db, stage)
    result = await dz_review.generate_hints(db, stage, review, user_id=current_user.id)
    return DzHintsResponse(**result)


@router.put("/cpro/jobs/{job_id}/sender", response_model=CproSenderResponse)
async def set_cpro_sender(
    job_id: int,
    body: CproSenderUpdate,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproSenderResponse:
    """Ustawia JEDNĄ osobę, która wysyła do Cpro kandydatów tej rekrutacji.

    Decyzja Artura 23.09.2026: „nie wysyła inna osoba per kandydat, tylko
    jedna osoba per cały proces". Dotyczy wyłącznie rekrutacji Nordei.
    """

    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    await ensure_job_membership(db, current_user, job.id)
    if not cpro_enabled_for_client(job.client_id):
        raise HTTPException(
            status_code=409,
            detail="Ta rekrutacja nie wysyła kandydatów do Cpro.",
        )
    assignee = await svc.load_assignee(db, body.assignee_id)
    added = await svc.ensure_assignee_can_move(
        db, job_id=job.id, assignee=assignee, actor=current_user
    )
    previous = job.cpro_sender_id
    job.cpro_sender_id = assignee.id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="cpro_sender_changed",
            user_id=current_user.id,
            details={"from": previous, "to": assignee.id, "added_to_team": added},
        )
    )
    if previous != assignee.id:
        snapshot = await svc.load_snapshot(db)
        waiting = sum(
            1
            for t in snapshot.tasks
            if t.kind == svc.KIND_CPRO_TO_SEND and t.job_id == job.id
        )
        await svc.notify_cpro_sender(
            db,
            job_id=job.id,
            job_title=job.title,
            waiting=waiting,
            sender_id=assignee.id,
            actor=current_user,
        )
    await db.commit()
    return CproSenderResponse(
        job_id=job.id,
        assignee_id=assignee.id,
        assignee_name=assignee.name or assignee.email,
        added_to_team=added,
    )
