"""Ogłoszenie rekrutacji do wklejenia na portale (Pracuj.pl, JustJoin.IT).

* ``GET  /api/jobs/{job_id}/portal-ad`` — zapisane ogłoszenie, fakty
  „z tej rekrutacji”, gotowość danych, znaleziska kontroli i teksty do
  skopiowania dla obu portali;
* ``POST /api/jobs/{job_id}/portal-ad/generate`` — układa treść (model albo
  złożenie z pól rekrutacji) i ZAPISUJE ją;
* ``PUT  /api/jobs/{job_id}/portal-ad`` — ręczne poprawki rekrutera;
* ``PUT/DELETE /api/jobs/{job_id}/portal-ad/publications/{portal}`` — „wisi
  na portalu” (z linkiem) i „zdjęte z portalu” (0432);
* ``GET/PUT /api/job-ads/fixed-blocks`` — stałe części firmy (admin i Head of
  Recruitment);
* ``PUT/DELETE /api/jobs/{job_id}/portal-ad/skips/{channel}`` — „nie
  publikujemy tej rekrutacji na …” z powodem (0526, przypomnienia);
* ``POST /api/jobs/{job_id}/portal-ad/remind`` — DL prosi rekrutera o stronę
  kariery (mail od razu);
* ``GET /api/job-ads/missing`` — rekrutacje z brakiem, który robi osoba
  („Ogłoszenia do nadrobienia”);
* ``POST /api/jobs/{job_id}/portal-ad/pracuj-mail/preview`` i
  ``POST …/pracuj-mail`` — mail z ogłoszeniem do opiekuna Pracuj.pl ze
  skrzynki osoby (27.10.2026, ``job_ad.pracuj_mail``).

Bramka jak przy opisie publicznym (``career_links``): rola ``RecruiterPlus``
+ sekcja Pipeline (router) + członkostwo w rekrutacji. Front kopiuje wyłącznie
teksty ``rendered`` z odpowiedzi — policzone dla zapisanego stanu, po kontroli.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, OperationalUser, RecruiterPlus
from app.api.recruitment_access import ensure_job_membership, job_scope_clause
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.job import Job, JobStatus
from app.models.job_ad import JobAd
from app.models.activity import Activity
from app.models.job_ad_channel_skip import JobAdChannelSkip
from app.models.job_ad_publication import JobAdPublication
from app.models.m365 import M365Connection
from app.models.job_public_profile import JobPublicProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.schemas.job_ad import (
    AdCareerRequest,
    AdChannel,
    AdGenerateRequest,
    AdRemindResponse,
    AdSkipRequest,
    AdUpdateRequest,
    CareerQueueItem,
    CareerQueueResponse,
    FixedBlocksModel,
    JobAdResponse,
    MissingAdsItem,
    MissingAdsResponse,
    PracujMailPreview,
    PracujMailPreviewRequest,
    PracujMailRequest,
    PracujRequestRead,
)
from app.schemas.job_ad_publication import AdPortal, AdPublishRequest
from app.services import job_public_profile as jpp
from app.services.job_ad import (
    career,
    fixed_blocks,
    generate,
    lint,
    material,
    pracuj_mail,
    publications,
    reminders,
    render,
)
from app.services.job_ad_reminder_schema import CHANNEL_PRACUJ

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _changed(message: str) -> HTTPException:
    return HTTPException(
        status_code=409, detail={"code": "job_ad_changed", "message": message}
    )


async def _load_job(db: AsyncSession, user: User, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji")
    await ensure_job_membership(db, user, job_id)
    return job


async def _material(db: AsyncSession, job: Job) -> material.AdMaterial:
    profile = await db.get(JobPublicProfile, job.id)
    _default, title = await jpp.public_titles(db, job, profile)
    return material.build_material(job, title)


async def _response(
    db: AsyncSession,
    job: Job,
    ad: Optional[JobAd],
    mat: material.AdMaterial,
    *,
    user_id: int,
) -> JobAdResponse:
    base = {
        "facts": material.facts(mat),
        "readiness": material.readiness(mat),
        "career": (await career.career_state(db, job, ad, user_id=user_id)).as_dict(),
        "reminders": await _reminders_panel(db, job.id, user_id),
        "pracuj_request": await _pracuj_request(db, job.id),
    }
    if ad is None:
        return JobAdResponse(**base)
    all_blocks = await fixed_blocks.load_blocks(db)
    blocks = all_blocks.for_lang(ad.lang)
    rendered = render.render_ad(
        ad.content,
        ad.tech,
        mat,
        blocks,
        lang=ad.lang,
        title_suffix=all_blocks.title_suffix,
    )
    # Kontrola czyta to, co pójdzie do schowka: pola ogłoszenia, miasto
    # z rekrutacji, stałe bloki i na końcu komplet wyrenderowanych napisów.
    findings = lint.lint_ad(
        ad.content,
        ad.tech,
        terms=[mat.city or ""],
        fixed=[*blocks.offer, *blocks.process, blocks.about],
        rendered=render.rendered_texts(rendered),
        client_names=await jpp.client_lint_names(db, job.client_id),
        person_names=await jpp.person_names(db, job),
    )
    return JobAdResponse(
        **base,
        ad={
            "lang": ad.lang,
            "content": ad.content,
            "tech": ad.tech,
            "source": ad.source,
            "generated_at": ad.generated_at,
            "updated_at": ad.updated_at,
            "stale": ad.material_hash != material.material_hash(mat),
        },
        findings=[f.as_dict() for f in findings],
        rendered=rendered,
        can_copy=not lint.has_blocking(findings),
        publications=[
            vars(item) for item in await publications.for_job(db, job.id, ad)
        ],
    )


async def _pracuj_request(db: AsyncSession, job_id: int) -> Optional[PracujRequestRead]:
    found = (await pracuj_mail.last_requests(db, [job_id])).get(job_id)
    if found is None:
        return None
    return PracujRequestRead(
        sent_at=found.sent_at,
        sent_by_name=found.sent_by_name,
        to=found.to,
        waiting=pracuj_mail.is_waiting(found.sent_at, reminders.today_local()),
    )


async def _reminders_panel(
    db: AsyncSession, job_id: int, user_id: int
) -> Optional[dict]:
    """Trzy kanały i kto je robi; zamknięta rekrutacja = ``None``."""
    found = await reminders.load_statuses(db, [job_id])
    user = await db.get(User, user_id)
    if not found or user is None:
        return None
    await reminders.with_skip_authors(db, found)
    return reminders.panel(found[0], user)


async def _managed_status(
    db: AsyncSession, user: User, job: Job
) -> reminders.JobAdStatus:
    """Stan otwartej rekrutacji, gdy osoba decyduje o jej ogłoszeniach."""
    found = await reminders.load_statuses(db, [job.id])
    if not found:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_not_open",
                "message": "Rekrutacja jest zamknięta — przypomnienia o niej nie przychodzą.",
            },
        )
    status = found[0]
    if not reminders.can_manage(user, status):
        raise HTTPException(
            status_code=403,
            detail=(
                "O ogłoszeniach tej rekrutacji decyduje jej Delivery Lead, "
                "Head of Recruitment albo admin."
            ),
        )
    return status


@router.get("/jobs/{job_id}/portal-ad", response_model=JobAdResponse)
async def get_portal_ad(
    job_id: int, current_user: OperationalUser, db: AsyncSession = Depends(get_db)
) -> JobAdResponse:
    job = await _load_job(db, current_user, job_id)
    return await _response(
        db,
        job,
        await db.get(JobAd, job_id),
        await _material(db, job),
        user_id=current_user.id,
    )


@router.post("/jobs/{job_id}/portal-ad/generate", response_model=JobAdResponse)
async def generate_portal_ad(
    job_id: int,
    data: AdGenerateRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobAdResponse:
    """Układa treść od nowa i zapisuje ją w miejsce poprzedniej.

    Awaria modelu NIE zastępuje istniejącej treści złożeniem z pól
    rekrutacji — rekruter mógł ją już poprawić. Złożenie bez modelu powstaje
    tylko jako pierwsza wersja ogłoszenia (i tylko po polsku).

    Model liczy od kilku sekund do minuty. Zapis jest więc warunkowy: jeśli
    w tym czasie ktoś zapisał poprawkę albo przygotował ogłoszenie, nowa
    treść przepada z 409 zamiast po cichu zastąpić cudzą pracę. Istniejące
    ogłoszenie zastępuje się tylko z wersją, którą okno miało na ekranie.
    """
    job = await _load_job(db, current_user, job_id)
    mat = await _material(db, job)
    before = await db.get(JobAd, job_id)
    existed = before is not None
    seen = before.updated_at if before is not None else None
    if existed and data.expected_updated_at is None:
        # Okno bez wersji myśli, że ogłoszenia nie ma (pierwsze „Przygotuj”),
        # a ktoś je w tym czasie przygotował. Bez tej odmowy druga osoba
        # zastępowała poprawioną treść pierwszej (audyt 13.10.2026).
        raise _changed(
            "Ktoś w międzyczasie przygotował to ogłoszenie. Wczytałem je — "
            "sprawdź treść, zanim przygotujesz ją ponownie."
        )
    if (
        data.expected_updated_at is not None
        and seen is not None
        and data.expected_updated_at != seen
    ):
        raise _changed(
            "Ktoś w międzyczasie zmienił to ogłoszenie. Wczytałem aktualną "
            "wersję — sprawdź ją, zanim przygotujesz treść ponownie."
        )
    try:
        content, source = await generate.generate_content(
            db,
            mat,
            lang=data.lang,
            user_id=current_user.id,
            log_ref=f"job={job_id}",
            allow_template=not existed,
        )
    except generate.AdGenerationFailed as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Model jest chwilowo niedostępny. Zapisane ogłoszenie zostało "
                "bez zmian — spróbuj ponownie za chwilę."
                if existed
                else "Wersja angielska powstaje tylko z modelem, a ten jest "
                "chwilowo niedostępny. Spróbuj ponownie za chwilę albo "
                "przygotuj ogłoszenie po polsku."
            ),
        ) from exc
    now = _now()
    values = {
        "lang": data.lang,
        "content": content,
        "tech": render.tech_from_material(mat),
        "source": source,
        "material_hash": material.material_hash(mat),
        "generated_by": current_user.id,
        "generated_at": now,
        "updated_by": current_user.id,
        "updated_at": now,
    }
    if existed:
        statement = (
            update(JobAd)
            .where(JobAd.job_id == job_id, JobAd.updated_at == seen)
            .values(**values)
        )
    else:
        # Dwa równoległe „Przygotuj” na rekrutacji bez ogłoszenia: drugie nie
        # kończy się błędem klucza głównego ani nie zastępuje pierwszego.
        statement = (
            pg_insert(JobAd)
            .values(job_id=job_id, **values)
            .on_conflict_do_nothing(index_elements=[JobAd.job_id])
        )
    written = (await db.execute(statement)).rowcount
    if not written:
        await db.rollback()
        raise _changed(
            "Ktoś zmienił to ogłoszenie, kiedy układałem nową treść. Nic nie "
            "zostało zastąpione — wczytałem aktualną wersję."
        )
    await db.commit()
    ad = await db.get(JobAd, job_id, populate_existing=True)
    return await _response(db, job, ad, mat, user_id=current_user.id)


@router.put("/jobs/{job_id}/portal-ad", response_model=JobAdResponse)
async def put_portal_ad(
    job_id: int,
    data: AdUpdateRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobAdResponse:
    """Ręczne poprawki. Odpowiedź niesie świeżą kontrolę i teksty do skopiowania."""
    job = await _load_job(db, current_user, job_id)
    ad = await db.get(JobAd, job_id, with_for_update=True)
    if ad is None:
        raise HTTPException(
            status_code=404,
            detail="Najpierw przygotuj ogłoszenie — potem można je poprawiać.",
        )
    if (
        data.expected_updated_at is not None
        and ad.updated_at is not None
        and data.expected_updated_at != ad.updated_at
    ):
        raise _changed(
            "Ktoś w międzyczasie zmienił to ogłoszenie. Wczytałem aktualną "
            "wersję — Twój tekst został w polu, zapisz go jeszcze raz."
        )
    mat = await _material(db, job)
    ad.content = generate.clean_content(data.content.model_dump(), title=mat.title)
    ad.tech = render.clean_tech([item.model_dump() for item in data.tech])
    ad.updated_by = current_user.id
    ad.updated_at = _now()
    await db.commit()
    await db.refresh(ad)
    return await _response(db, job, ad, mat, user_id=current_user.id)


@router.put(
    "/jobs/{job_id}/portal-ad/publications/{portal}", response_model=JobAdResponse
)
async def mark_ad_published(
    job_id: int,
    portal: AdPortal,
    data: AdPublishRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobAdResponse:
    """Ogłoszenie wisi na portalu (link opcjonalny).

    Pierwsze oznaczenie i ``content_updated`` potwierdzają OBECNĄ treść —
    przy znalezisku blokującym odmowa: takiej treści nie wolno było wkleić.
    Sama zmiana linku przy aktywnym oznaczeniu niczego nie potwierdza.
    """
    job = await _load_job(db, current_user, job_id)
    ad = await db.get(JobAd, job_id)
    if ad is None:
        raise HTTPException(
            status_code=404,
            detail="Najpierw przygotuj ogłoszenie — potem oznaczysz publikację.",
        )
    try:
        url = publications.clean_url(data.url, portal)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    mat = await _material(db, job)
    try:
        await publications.mark_published(
            db,
            ad,
            portal=portal,
            url=url,
            user_id=current_user.id,
            content_updated=data.content_updated,
            blocked=not (
                await _response(db, job, ad, mat, user_id=current_user.id)
            ).can_copy,
        )
    except publications.ContentBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_ad_blocked",
                "message": (
                    "W treści są fragmenty, których nie publikujemy. Usuń je, "
                    "zanim oznaczysz ogłoszenie jako opublikowane."
                ),
            },
        ) from exc
    await db.commit()
    return await _response(db, job, ad, mat, user_id=current_user.id)


@router.delete(
    "/jobs/{job_id}/portal-ad/publications/{portal}", response_model=JobAdResponse
)
async def mark_ad_removed(
    job_id: int,
    portal: AdPortal,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobAdResponse:
    """Ogłoszenie zdjęte z portalu — wiersz zostaje jako ślad."""
    job = await _load_job(db, current_user, job_id)
    if not await publications.mark_removed(
        db, job_id, portal=portal, user_id=current_user.id
    ):
        raise HTTPException(
            status_code=404,
            detail="To ogłoszenie nie jest oznaczone jako opublikowane.",
        )
    await db.commit()
    return await _response(
        db,
        job,
        await db.get(JobAd, job_id),
        await _material(db, job),
        user_id=current_user.id,
    )


@router.post("/jobs/{job_id}/portal-ad/career", response_model=JobAdResponse)
async def publish_career_page(
    job_id: int,
    data: AdCareerRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobAdResponse:
    """„Opublikuj na stronie” (21.10.2026): treść ogłoszenia trafia na stronę
    kariery i od razu jest zatwierdzona; osoba dostaje swój link.

    Publikuje się dokładnie wersja z ekranu (``expected_updated_at``), tylko
    bez znalezisk blokujących i tylko w otwartej rekrutacji. Kontrola strony
    kariery czyta dodatkowo kody wewnętrzne (RITM, numer u klienta) — jej
    znalezisko = 422 z listą.
    """
    job = await _load_job(db, current_user, job_id)
    ad = await db.get(JobAd, job_id, with_for_update=True)
    if ad is None:
        raise HTTPException(
            status_code=404,
            detail="Najpierw przygotuj ogłoszenie — potem opublikujesz je na stronie.",
        )
    if (
        data.expected_updated_at is not None
        and ad.updated_at is not None
        and data.expected_updated_at != ad.updated_at
    ):
        raise _changed(
            "Ktoś w międzyczasie zmienił to ogłoszenie. Wczytałem aktualną "
            "wersję — przeczytaj ją, zanim opublikujesz."
        )
    if not jpp.job_is_open(job):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_not_open",
                "message": "Na stronie kariery publikujemy tylko otwarte rekrutacje.",
            },
        )
    mat = await _material(db, job)
    if not (await _response(db, job, ad, mat, user_id=current_user.id)).can_copy:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_ad_blocked",
                "message": (
                    "W treści są fragmenty, których nie publikujemy. Usuń je, "
                    "zanim opublikujesz ogłoszenie na stronie."
                ),
            },
        )
    try:
        await career.publish(db, job, ad, user_id=current_user.id)
    except career.NothingToPublish as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ogłoszenie nie ma wstępu, opisu projektu ani obowiązków — "
                "dopisz choć jedno z nich."
            ),
        ) from exc
    except jpp.ProfileFindings as exc:
        await db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PUBLIC_PROFILE_FINDINGS",
                "message": (
                    "Strona kariery nie przyjmie tej treści: "
                    + "; ".join(f.message for f in exc.findings[:3])
                ),
                "findings": [f.as_dict() for f in exc.findings],
            },
        ) from exc
    await db.commit()
    ad = await db.get(JobAd, job_id, populate_existing=True)
    return await _response(db, job, ad, mat, user_id=current_user.id)


_QUEUE_LIMIT = 300


@router.get("/job-ads/career-queue", response_model=CareerQueueResponse)
async def get_career_queue(
    current_user: RecruiterPlus,
    scope: Literal["mine", "all"] = Query("mine"),
    # 0 = same liczby (przycisk na liście rekrutacji).
    limit: int = Query(_QUEUE_LIMIT, ge=0, le=_QUEUE_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> CareerQueueResponse:
    """Otwarte rekrutacje bez strony kariery, od najnowszej (21.10.2026).

    „Wszystkie” = te, w których osoba może publikować (zakres
    ``ensure_job_membership``), „Moje” = te, w których jest Rekruterem albo
    Delivery Leadem. Treść każdej przygotowuje noc (``tasks.job_ad_prepare``);
    publikuje człowiek — ``POST …/portal-ad/career``.
    """
    from sqlalchemy.orm import aliased

    from app.services.job_team import jobs_worked_by_clause

    # Alias, nie `User`: klauzula „Moje” ma podzapytania po `users` skorelowane
    # z `Job` — z gołym `User` w zewnętrznym FROM SQLAlchemy skorelowałby je
    # całe i zostawił bez FROM (500 w CI 21.10.2026).
    lead = aliased(User)

    live = exists().where(
        JobPublicProfile.job_id == Job.id, JobPublicProfile.approved_at.is_not(None)
    )
    base = and_(
        Job.status == JobStatus.published,
        ~live,
        job_scope_clause(current_user, Job.id),
    )
    mine = or_(
        jobs_worked_by_clause([current_user.id]),
        Job.delivery_lead_id == current_user.id,
    )
    all_count = await db.scalar(select(func.count()).select_from(Job).where(base))
    mine_count = await db.scalar(
        select(func.count()).select_from(Job).where(base, mine)
    )
    rows = (
        []
        if limit == 0
        else (
            await db.execute(
                select(Job, JobAd.source, lead.name)
                .outerjoin(JobAd, JobAd.job_id == Job.id)
                .outerjoin(lead, lead.id == Job.delivery_lead_id)
                .where(base, *([mine] if scope == "mine" else []))
                .order_by(Job.opened_at.desc().nulls_last(), Job.id.desc())
                .limit(limit)
            )
        ).all()
    )
    items = [
        CareerQueueItem(
            job_id=job.id,
            title=job.working_title or job.title,
            city=job.location,
            remote_policy=job.remote_policy.value if job.remote_policy else None,
            delivery_lead_name=lead_name,
            opened_at=job.opened_at,
            ad=(
                "missing"
                if source is None
                else "template"
                if source == "template"
                else "ready"
            ),
        )
        for job, source, lead_name in rows
    ]
    return CareerQueueResponse(
        scope=scope,
        mine_count=mine_count or 0,
        all_count=all_count or 0,
        items=items,
    )


@router.get("/job-ads/fixed-blocks", response_model=FixedBlocksModel)
async def get_fixed_blocks(
    current_user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
) -> FixedBlocksModel:
    return FixedBlocksModel(**(await fixed_blocks.load_blocks(db)).as_dict())


@router.put("/job-ads/fixed-blocks", response_model=FixedBlocksModel)
async def put_fixed_blocks(
    payload: FixedBlocksModel,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> FixedBlocksModel:
    current = await fixed_blocks.load_blocks(db)
    try:
        blocks = fixed_blocks.validate_blocks(
            payload.model_dump(), keep_caretaker=current.pracuj_caretaker
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Blok trafia do każdego ogłoszenia i rekruter go nie poprawi — kwota
    # albo telefon wpisane tutaj wyszłyby na wszystkie portale naraz.
    findings = lint.lint_fixed_blocks(
        text
        for part in (blocks.pl, blocks.en)
        for text in (*part.offer, *part.process, part.about)
    )
    if findings:
        raise HTTPException(422, findings[0].message)
    await fixed_blocks.save_blocks(db, blocks, user_id=current_user.id)
    await db.commit()
    return FixedBlocksModel(**blocks.as_dict())


# ── Przypomnienia o brakujących ogłoszeniach (0526, 27.10.2026) ──────────────


async def _job_ad_reply(db: AsyncSession, job: Job, user: User) -> JobAdResponse:
    return await _response(
        db, job, await db.get(JobAd, job.id), await _material(db, job), user_id=user.id
    )


@router.put("/jobs/{job_id}/portal-ad/skips/{channel}", response_model=JobAdResponse)
async def skip_ad_channel(
    job_id: int,
    channel: AdChannel,
    data: AdSkipRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobAdResponse:
    """„Nie publikujemy tej rekrutacji na …” — kanał przestaje być brakiem.

    Decyduje DL rekrutacji, Head of Recruitment albo admin; powód jest
    obowiązkowy i trafia do Historii zdarzeń rekrutacji.
    """
    job = await _load_job(db, current_user, job_id)
    await _managed_status(db, current_user, job)
    reason = " ".join(data.reason.split())
    if len(reason) < 3:
        raise HTTPException(422, "Napisz krótko, dlaczego tu nie publikujemy.")
    stmt = pg_insert(JobAdChannelSkip).values(
        job_id=job_id, channel=channel, reason=reason, created_by=current_user.id
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[JobAdChannelSkip.job_id, JobAdChannelSkip.channel],
            set_={
                "reason": reason,
                "created_by": current_user.id,
                "updated_at": _now(),
            },
        )
    )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="job_ad_channel_skipped",
            user_id=current_user.id,
            details={"channel": channel, "reason": reason},
        )
    )
    await db.commit()
    return await _job_ad_reply(db, job, current_user)


@router.delete("/jobs/{job_id}/portal-ad/skips/{channel}", response_model=JobAdResponse)
async def unskip_ad_channel(
    job_id: int,
    channel: AdChannel,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobAdResponse:
    """Cofnięcie „nie publikujemy” — przypomnienia o kanale wracają."""
    job = await _load_job(db, current_user, job_id)
    await _managed_status(db, current_user, job)
    row = await db.get(JobAdChannelSkip, (job_id, channel))
    if row is None:
        raise HTTPException(404, "Ten kanał nie jest oznaczony jako „nie publikujemy”.")
    await db.delete(row)
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="job_ad_channel_unskipped",
            user_id=current_user.id,
            details={"channel": channel},
        )
    )
    await db.commit()
    return await _job_ad_reply(db, job, current_user)


@router.post("/jobs/{job_id}/portal-ad/remind", response_model=AdRemindResponse)
async def remind_recruiters(
    job_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> AdRemindResponse:
    """DL prosi rekruterów rekrutacji o stronę kariery — mail od razu.

    Raz dziennie na osobę i rekrutację (dzienny dedup dzwonka); drugi klik
    tego dnia mówi, komu już przypomniano.
    """
    from app.models.notification import Notification
    from app.services.notification_triggers import emit

    job = await _load_job(db, current_user, job_id)
    status = await _managed_status(db, current_user, job)
    career_state = status.channel(reminders.CHANNEL_CAREER)
    if career_state.state != "missing":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "career_not_missing",
                "message": "Strona kariery już wisi albo jej nie publikujemy.",
            },
        )
    targets = [
        uid
        for uid in status.recruiter_ids
        if uid != current_user.id and uid in career_state.owners
    ]
    if not targets:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "no_recruiter",
                "message": (
                    "Rekrutacja nie ma rekrutera — stronę kariery możesz "
                    "opublikować sam(a) albo najpierw przydzielić rekrutera."
                ),
            },
        )
    day_start = reminders.local_day_start(_now())
    already_ids = set(
        (
            await db.scalars(
                select(Notification.user_id).where(
                    Notification.notification_type == NotificationType.job_ad_nudge,
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job_id,
                    Notification.user_id.in_(targets),
                    Notification.created_at >= day_start,
                )
            )
        ).all()
    )
    sent: list[str] = []
    already: list[str] = []
    for uid in targets:
        name = status.names.get(uid) or ""
        if uid in already_ids:
            already.append(name)
            continue
        row = await emit(
            db,
            user_id=uid,
            title=f"{reminders.TITLE_NUDGE}: {status.title}"[:255],
            message=reminders.nudge_message(current_user.name),
            ntype=NotificationType.job_ad_nudge,
            related_entity_type="job",
            related_entity_id=job_id,
            link=reminders.job_link(job_id, ogloszenie=reminders.CHANNEL_CAREER),
        )
        if row is not None:
            sent.append(name)
    await db.commit()
    return AdRemindResponse(sent_to=sent, already=already)


@router.get("/job-ads/missing", response_model=MissingAdsResponse)
async def get_missing_ads(
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> MissingAdsResponse:
    """Otwarte rekrutacje z brakiem, który robi osoba (albo prowadzi jako DL).

    Ten sam stan co poranne maile (``job_ad.reminders``), od najnowszej;
    ekran „Ogłoszenia do nadrobienia” otwiera je jedną po drugiej.
    """
    statuses = [
        s for s in await reminders.load_statuses(db) if s.concerns(current_user.id)
    ]
    await reminders.with_skip_authors(db, statuses)
    cutoff = await reminders.launch_cutoff(db)
    statuses.sort(
        key=lambda s: (
            s.opened_at or datetime.min.replace(tzinfo=timezone.utc),
            s.job_id,
        ),
        reverse=True,
    )
    return MissingAdsResponse(
        items=[
            MissingAdsItem(
                job_id=s.job_id,
                title=s.title,
                client=s.client,
                opened_at=s.opened_at,
                backlog=not reminders.is_new(s.opened_at, cutoff),
                channels=[
                    reminders.channel_view(s, c, current_user.id) for c in s.channels
                ],
            )
            for s in statuses
        ]
    )


# ── Pracuj.pl mailem do opiekuna (27.10.2026) ────────────────────────────────


_MAILBOX_MISSING = (
    "Twoja skrzynka Microsoft 365 nie jest podłączona. Podłącz ją w Ustawieniach "
    "→ Moje konto → „Outlook i kalendarz” albo skopiuj treść maila do Outlooka."
)


async def _pracuj_ad(
    db: AsyncSession, job: Job, user: User
) -> tuple[JobAd, material.AdMaterial, JobAdResponse]:
    ad = await db.get(JobAd, job.id)
    if ad is None:
        raise HTTPException(
            status_code=404,
            detail="Najpierw przygotuj ogłoszenie — mail do opiekuna to jego treść.",
        )
    mat = await _material(db, job)
    return ad, mat, await _response(db, job, ad, mat, user_id=user.id)


def _compose(
    reply: JobAdResponse,
    caretaker: fixed_blocks.PracujCaretaker,
    rate: str,
) -> pracuj_mail.PracujMail:
    assert reply.rendered is not None  # ogłoszenie istnieje
    return pracuj_mail.compose(
        reply.rendered.model_dump(),
        [fact.model_dump() for fact in reply.facts],
        caretaker=caretaker,
        rate=rate,
    )


@router.post(
    "/jobs/{job_id}/portal-ad/pracuj-mail/preview", response_model=PracujMailPreview
)
async def preview_pracuj_mail(
    job_id: int,
    data: PracujMailPreviewRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> PracujMailPreview:
    """Podgląd maila do opiekuna — ten sam skład co wysyłka, nic nie zapisuje."""
    job = await _load_job(db, current_user, job_id)
    await _managed_status(db, current_user, job)
    _ad, _mat, reply = await _pracuj_ad(db, job, current_user)
    rate_error: Optional[str] = None
    try:
        rate = pracuj_mail.rate_text(data.rate_from, data.rate_to)
    except pracuj_mail.RateInvalid as exc:
        rate_error, rate = str(exc), "…"
    caretaker = (await fixed_blocks.load_blocks(db)).pracuj_caretaker
    mail = _compose(reply, caretaker, rate)
    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == current_user.id)
    )
    return PracujMailPreview(
        to_name=caretaker.name,
        to_email=caretaker.email,
        mailbox=(
            "missing" if conn is None else "ready" if conn.is_active else "reconnect"
        ),
        from_address=conn.mailbox_upn if conn is not None else None,
        subject=mail.subject,
        body_text=mail.body_text,
        rate_error=rate_error,
    )


@router.post("/jobs/{job_id}/portal-ad/pracuj-mail", response_model=JobAdResponse)
async def send_pracuj_mail(
    job_id: int,
    data: PracujMailRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobAdResponse:
    """Mail z ogłoszeniem do opiekuna Pracuj.pl ze skrzynki osoby.

    Wysyła DL rekrutacji, Head of Recruitment albo admin; tylko otwarta
    rekrutacja, wersja ogłoszenia z ekranu, treść bez znalezisk blokujących
    i ze stawką. Ślad w Historii zdarzeń — z niego stan „wysłane”.
    """
    from app.api.email_threads import _graph_refusal_http, _send_conflict_http
    from app.services.m365 import sender as m365_sender
    from app.services.m365.access import M365OwnerIneligible
    from app.services.m365.graph_client import GraphRequestError

    job = await _load_job(db, current_user, job_id)
    await _managed_status(db, current_user, job)
    ad, mat, reply = await _pracuj_ad(db, job, current_user)
    if data.expected_updated_at != ad.updated_at:
        raise _changed(
            "Ktoś w międzyczasie zmienił to ogłoszenie. Wczytałem aktualną "
            "wersję — przeczytaj ją, zanim wyślesz."
        )
    live = await db.scalar(
        select(JobAdPublication.job_id).where(
            JobAdPublication.job_id == job_id,
            JobAdPublication.portal == CHANNEL_PRACUJ,
            JobAdPublication.removed_at.is_(None),
        )
    )
    if live is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pracuj_live",
                "message": "Ogłoszenie już wisi na Pracuj.pl — nie wysyłam go drugi raz.",
            },
        )
    if not reply.can_copy:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_ad_blocked",
                "message": (
                    "W treści są fragmenty, których nie publikujemy. Usuń je, "
                    "zanim wyślesz ogłoszenie opiekunowi."
                ),
            },
        )
    try:
        rate = pracuj_mail.rate_text(data.rate_from, data.rate_to)
    except pracuj_mail.RateInvalid as exc:
        raise HTTPException(422, str(exc)) from exc
    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == current_user.id)
    )
    if conn is None or not conn.is_active:
        raise HTTPException(
            status_code=412,
            detail={"code": "mailbox_missing", "message": _MAILBOX_MISSING},
        )
    caretaker = (await fixed_blocks.load_blocks(db)).pracuj_caretaker
    mail = _compose(reply, caretaker, rate)
    try:
        row = await m365_sender.send_new(
            db,
            conn,
            to=[caretaker.email],
            subject=mail.subject,
            body_html=mail.body_html,
            client_request_id=data.client_request_id,
            commit_reservation=True,
        )
    except M365OwnerIneligible as exc:
        raise HTTPException(
            403, "Z tego konta nie wyślesz maila z NEXUSA — poproś admina o dostęp."
        ) from exc
    except m365_sender.EmailSendConflict as exc:
        # Wynik nieznany (np. Graph nie odpowiedział na /send) — mail mógł
        # wyjść. Ślad zostaje, żeby jutrzejszy mail nie kazał wysłać drugi raz.
        if exc.state == m365_sender.SEND_STATE_UNCERTAIN and exc.email_id:
            await _log_pracuj_request(
                db,
                job_id,
                current_user.id,
                caretaker.email,
                exc.email_id,
                uncertain=True,
            )
            await db.commit()
        raise _send_conflict_http(exc) from exc
    except GraphRequestError as exc:
        if 400 <= exc.status < 500:
            raise _graph_refusal_http(exc) from exc
        raise
    await _log_pracuj_request(db, job_id, current_user.id, caretaker.email, row.id)
    await db.commit()
    return await _response(db, job, ad, mat, user_id=current_user.id)


async def _log_pracuj_request(
    db: AsyncSession,
    job_id: int,
    user_id: int,
    to: str,
    email_id: int,
    *,
    uncertain: bool = False,
) -> None:
    """Wpis w Historii zdarzeń — raz na mail (ponowienie oddaje ten sam wiersz)."""
    seen = await db.scalar(
        select(Activity.id).where(
            Activity.entity_type == "job",
            Activity.entity_id == job_id,
            Activity.action == pracuj_mail.ACTION,
            Activity.details["email_id"].astext == str(email_id),
        )
    )
    if seen is not None:
        return
    details: dict = {"to": to, "email_id": email_id}
    if uncertain:
        details["uncertain"] = True
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=pracuj_mail.ACTION,
            user_id=user_id,
            details=details,
        )
    )
