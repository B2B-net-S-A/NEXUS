"""Treść okna „Ogłoszenie” w kształcie dla portalu (03.11.2026).

Publikacja na JustJoin.IT przez API wysyła to, co pokazuje zakładka: ten sam
render i ta sama kontrola co odpowiedź okna, liczone od nowa tuż przed wysyłką.
Reguły: ``docs/claude/rekrutacja-tworzenie/ogloszenie-justjoin-przez-api.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.job_ad import JobAd
from app.models.job_public_profile import JobPublicProfile
from app.services import job_public_profile as jpp
from app.services.job_ad import fixed_blocks, lint, material, publications, render


@dataclass(frozen=True)
class PreparedAd:
    title: str
    # Kształt ``jjit_payload``: gotowy opis i podział technologii.
    job: dict[str, Any]
    ad_hash: str
    blocked: bool


async def ad_material(db: AsyncSession, job: Job) -> material.AdMaterial:
    profile = await db.get(JobPublicProfile, job.id)
    _default, title = await jpp.public_titles(db, job, profile)
    return material.build_material(job, title)


async def checked_render(
    db: AsyncSession, job: Job, ad: JobAd, mat: material.AdMaterial
) -> tuple[dict[str, Any], list[lint.AdFinding]]:
    """Teksty dla portali i znaleziska kontroli dla zapisanego ogłoszenia."""
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
    return rendered, findings


async def prepare(db: AsyncSession, job: Job, ad: JobAd) -> PreparedAd:
    rendered, findings = await checked_render(db, job, ad, await ad_material(db, job))
    stack = render.clean_tech(ad.tech)
    must = [
        {"name": item["name"]}
        for level in (render.LEVEL_CRITICAL, render.LEVEL_MUST)
        for item in stack
        if item["level"] == level
    ]
    nice = [item["name"] for item in stack if item["level"] == render.LEVEL_NICE]
    return PreparedAd(
        title=rendered["title"],
        job={"body_html": rendered["jjit"]["body_html"], "must": must, "nice": nice},
        ad_hash=publications.ad_hash(ad),
        blocked=lint.has_blocking(findings),
    )
