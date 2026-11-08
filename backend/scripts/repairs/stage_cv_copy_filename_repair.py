"""Jednorazowo: nazwy plików kopii CV etapu po poprawce nazwy roli (15.10.2026).

Kopia CV etapu (plik Word, CV z profilu, CV z innej rekrutacji) do 15.10.2026
liczyła nazwę pliku z surowego ``jobs.title``. U PKO dawało to numer zapytania
dwa razy („ZOB-2949_… (ZOB-2949)_….docx”), u pozostałych klientów — nazwę
klienta i numer, których plik z generatora nie ma. Nazwa jest zamrożona na
wierszu CV etapu i na zatwierdzonych wersjach (pobranie oddaje
``cv_document_versions.docx_filename``), więc poprawka kodu sama nie zmienia
plików z wersji już zatwierdzonych.

Krok liczy starą nazwę (surowy tytuł) i nową (nazwa roli) tą samą funkcją co
kopia, z zastępczym imieniem w miejscu osoby, i podmienia wyłącznie nazwę
zbudowaną ze starego wzoru — osoba w nazwie zostaje taka, jaka była (także
„Kandydat” w CV blind). Nazwy zmienionej ręcznie albo policzonej inną regułą
nie rusza. Treść, sumy kontrolne i ``updated_at`` bez zmian.

Marker w ``app_settings`` + advisory lock → drugi start kończy się od razu.
Polityka klienta czekająca na synchronizację (503) = wiersze pominięte i bez
markera: następny start spróbuje ponownie, podmiana jest warunkowa, więc
powtórka niczego nie psuje. Paragon: same liczby (repo i logi są publiczne).
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.models.job import Job

MARKER = "stage_cv_copy_filename_2026_10"
# Wartości `branded_render_metadata.source` kopii odłączonej (`detached_metadata`).
COPY_SOURCES = ("document", "generated_other_job")
# Zastępcze imię: same litery, więc przechodzi przez każde czyszczenie nazwy.
_PERSON = "QQOSOBAQQ"


def renamed_copy_filename(
    stored: Optional[str],
    rule,
    raw_title: Optional[str],
    role_title: Optional[str],
    project: Optional[str],
) -> Optional[str]:
    """Nowa nazwa dla ``stored`` zbudowanej z surowego tytułu; inaczej ``None``."""
    from app.services.candidate_stage_cv_service import copy_filename

    old = copy_filename(rule, raw_title, _PERSON, project)
    new = copy_filename(rule, role_title, _PERSON, project)
    if not stored or old == new or old.count(_PERSON) != 1 or new.count(_PERSON) != 1:
        return None
    old_head, old_tail = old.split(_PERSON)
    if (
        len(stored) <= len(old_head) + len(old_tail)
        or not stored.startswith(old_head)
        or not stored.endswith(old_tail)
    ):
        return None
    person = stored[len(old_head) : len(stored) - len(old_tail)]
    new_head, new_tail = new.split(_PERSON)
    return f"{new_head}{person}{new_tail}"


async def _job_names(db: AsyncSession, job_id: int):
    """``(reguła, surowy tytuł, nazwa roli, numer projektu)``; ``None`` = brak
    rekrutacji; ``"pending"`` = polityka klienta czeka na synchronizację."""
    from app.services.cv_generator_b2b.client_rules import (
        resolve_client_rule,
        snapshot_rule,
    )
    from app.services.cv_packages import pko_job_reference
    from app.services.job_working_title import cv_role_title_for_job

    job = await db.get(Job, job_id)
    if job is None:
        return None
    try:
        rule = snapshot_rule(await resolve_client_rule(db, job.client_id))
    except HTTPException:
        return "pending"
    role = await cv_role_title_for_job(db, job)
    return rule, job.title, role, pko_job_reference(job)


async def rename_copy_filenames(
    db: AsyncSession, *, only_csv_ids: Optional[set[int]] = None
) -> Optional[dict[str, int]]:
    """Podmień nazwy plików kopii zbudowane z surowego tytułu. Wołający commituje.

    ``only_csv_ids`` zawęża przebieg — wyłącznie dla testów (bez markera).
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": MARKER}
    )
    if only_csv_ids is None and await db.get(AppSetting, MARKER):
        return None
    source = CandidateStageCV.branded_render_metadata["source"].as_string()
    query = (
        select(
            CandidateStageCV.id,
            CandidateStageCV.job_id,
            CandidateStageCV.branded_docx_filename,
        )
        .where(
            source.in_(COPY_SOURCES),
            CandidateStageCV.branded_docx_filename.is_not(None),
        )
        .order_by(CandidateStageCV.id)
    )
    if only_csv_ids is not None:
        query = query.where(CandidateStageCV.id.in_(only_csv_ids))
    rows = (await db.execute(query)).all()
    counts = {"renamed": 0, "versions_renamed": 0, "policy_pending": 0}
    jobs: dict[int, object] = {}
    copies = CandidateStageCV.__table__
    versions = CvDocumentVersion.__table__
    for row in rows:
        if row.job_id not in jobs:
            jobs[row.job_id] = await _job_names(db, row.job_id)
        names = jobs[row.job_id]
        if names == "pending":
            counts["policy_pending"] += 1
            continue
        if names is None:
            continue
        rule, raw_title, role_title, project = names
        old = row.branded_docx_filename
        new = renamed_copy_filename(old, rule, raw_title, role_title, project)
        if new is None:
            continue
        # Ktoś zmienił nazwę w trakcie — jego wartość wygrywa.
        result = await db.execute(
            copies.update()
            .where(copies.c.id == row.id, copies.c.branded_docx_filename == old)
            .values(branded_docx_filename=new, updated_at=copies.c.updated_at)
        )
        if not result.rowcount:
            continue
        counts["renamed"] += 1
        result = await db.execute(
            versions.update()
            .where(
                versions.c.candidate_stage_cv_id == row.id,
                versions.c.docx_filename == old,
            )
            .values(docx_filename=new)
        )
        counts["versions_renamed"] += result.rowcount or 0
    receipt = {"copies_seen": len(rows), **counts}
    if only_csv_ids is None and not counts["policy_pending"]:
        db.add(AppSetting(key=MARKER, value=receipt))
    return receipt
