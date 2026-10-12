"""Ogłoszenie rekrutacji do wklejenia na portale (Pracuj.pl, JustJoin.IT).

* ``GET  /api/jobs/{job_id}/portal-ad`` — zapisane ogłoszenie, fakty
  „z tej rekrutacji”, gotowość danych, znaleziska kontroli i teksty do
  skopiowania dla obu portali;
* ``POST /api/jobs/{job_id}/portal-ad/generate`` — układa treść (model albo
  złożenie z pól rekrutacji) i ZAPISUJE ją;
* ``PUT  /api/jobs/{job_id}/portal-ad`` — ręczne poprawki rekrutera;
* ``GET/PUT /api/job-ads/fixed-blocks`` — stałe części firmy (admin i Head of
  Recruitment).

Bramka jak przy opisie publicznym (``career_links``): rola ``RecruiterPlus``
+ sekcja Pipeline (router) + członkostwo w rekrutacji. Front kopiuje wyłącznie
teksty ``rendered`` z odpowiedzi — policzone dla zapisanego stanu, po kontroli.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, RecruiterPlus
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.job import Job
from app.models.job_ad import JobAd
from app.models.job_public_profile import JobPublicProfile
from app.models.user import User
from app.schemas.job_ad import (
    AdGenerateRequest,
    AdUpdateRequest,
    FixedBlocksModel,
    JobAdResponse,
)
from app.services import job_public_profile as jpp
from app.services.job_ad import fixed_blocks, generate, lint, material, render

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    db: AsyncSession, job: Job, ad: Optional[JobAd], mat: material.AdMaterial
) -> JobAdResponse:
    base = {"facts": material.facts(mat), "readiness": material.readiness(mat)}
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
    )


@router.get("/jobs/{job_id}/portal-ad", response_model=JobAdResponse)
async def get_portal_ad(
    job_id: int, current_user: RecruiterPlus, db: AsyncSession = Depends(get_db)
) -> JobAdResponse:
    job = await _load_job(db, current_user, job_id)
    return await _response(
        db, job, await db.get(JobAd, job_id), await _material(db, job)
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
    """
    job = await _load_job(db, current_user, job_id)
    mat = await _material(db, job)
    existed = await db.get(JobAd, job_id) is not None
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
    # Upsert: model liczy kilka sekund, więc dwa równoległe „Przygotuj” na
    # rekrutacji bez ogłoszenia nie mogą skończyć się błędem klucza głównego.
    await db.execute(
        pg_insert(JobAd)
        .values(job_id=job_id, **values)
        .on_conflict_do_update(index_elements=[JobAd.job_id], set_=values)
    )
    await db.commit()
    ad = await db.get(JobAd, job_id, populate_existing=True)
    return await _response(db, job, ad, mat)


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
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_ad_changed",
                "message": (
                    "Ktoś w międzyczasie zmienił to ogłoszenie. Odśwież okno "
                    "i wprowadź poprawkę jeszcze raz."
                ),
            },
        )
    mat = await _material(db, job)
    ad.content = generate.clean_content(data.content.model_dump(), title=mat.title)
    ad.tech = render.clean_tech([item.model_dump() for item in data.tech])
    ad.updated_by = current_user.id
    ad.updated_at = _now()
    await db.commit()
    await db.refresh(ad)
    return await _response(db, job, ad, mat)


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
    try:
        blocks = fixed_blocks.validate_blocks(payload.model_dump())
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
