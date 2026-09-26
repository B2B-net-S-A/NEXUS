"""Durable, single-attempt mapping of immutable approved CV content."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from sqlalchemy import select, update, func, text
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_version_map import CvVersionMap
from app.models.user import User
from app.services.ai_quota import ai_feature
from app.services.cv_generator_b2b.requirement_map import generate_map_result
from app.services.cv_version_map_input import encode_map_input, decode_map_input
from app.services.lease_renewal import renew_lease

logger = logging.getLogger(__name__)
LEASE_SECONDS = 180
MAX_RUNNING = 2


async def enqueue_version_map(db, version, requirements, user_id):
    if not requirements:
        return
    raw, digest = encode_map_input(version, requirements)
    await db.execute(
        insert(CvVersionMap)
        .values(
            document_version_id=version.id,
            user_id=user_id,
            content_sha256=version.content_sha256,
            input_sha256=digest,
            input_content=raw,
            status="queued",
        )
        .on_conflict_do_nothing(index_elements=["document_version_id"])
    )
    # Caller commits the approved artifact and its job atomically.


async def claim_map(db, version_id):
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 0x43564D4150})
    running = await db.scalar(
        select(func.count())
        .select_from(CvVersionMap)
        .where(
            CvVersionMap.status == "running", CvVersionMap.lease_expires_at > func.now()
        )
    )
    if running >= MAX_RUNNING:
        await db.commit()
        return None
    token = str(uuid4())
    claimed = await db.scalar(
        update(CvVersionMap)
        .where(
            CvVersionMap.document_version_id == version_id,
            CvVersionMap.status == "queued",
            CvVersionMap.input_content.is_not(None),
        )
        .values(
            status="running",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=LEASE_SECONDS),
        )
        .returning(CvVersionMap.document_version_id)
    )
    await db.commit()
    return token if claimed is not None else None


def owned(version_id, token):
    return (
        CvVersionMap.document_version_id == version_id,
        CvVersionMap.status == "running",
        CvVersionMap.lease_token == token,
        CvVersionMap.lease_expires_at > func.now(),
    )


async def finish_map(db, version_id, token, *, result=None, error=None):
    await db.execute(
        update(CvVersionMap)
        .where(*owned(version_id, token))
        .values(
            status="complete" if result is not None else "failed",
            result=result,
            error_code=error,
            input_content=None,
            lease_token=None,
            lease_expires_at=None,
            finished_at=func.now(),
        )
    )
    await db.commit()


async def renew(version_id, token):
    # Runda 7 (R7-N6-2): przejściowy błąd bazy nie kończy opłaconej mapy.
    async def beat() -> bool:
        async with AsyncSessionLocal() as db:
            claimed = await db.scalar(
                update(CvVersionMap)
                .where(*owned(version_id, token))
                .values(
                    lease_expires_at=datetime.now(timezone.utc)
                    + timedelta(seconds=LEASE_SECONDS)
                )
                .returning(CvVersionMap.document_version_id)
            )
            await db.commit()
            return claimed is not None

    await renew_lease(beat, lease_seconds=LEASE_SECONDS, label="CV map")


async def measure(prepared, user_id):
    async with AsyncSessionLocal() as db:
        async with ai_feature(db, AIFeatureKey.cv_requirement_map, user_id=user_id):
            await db.commit()
            return await generate_map_result(
                prepared.public_payload(),
                [r.model_dump() for r in prepared.requirements],
            )


async def execute_map(version_id):
    from app.core.config import settings

    if not settings.CV_INTERACTIVE_ENABLED:
        return
    async with AsyncSessionLocal() as db:
        token = await claim_map(db, version_id)
    if token is None:
        return
    heartbeat = work = None
    try:
        async with AsyncSessionLocal() as db:
            job = await db.scalar(select(CvVersionMap).where(*owned(version_id, token)))
            if job is None:
                return
            version = await db.get(CvDocumentVersion, version_id)
            user = await db.get(User, job.user_id) if job.user_id else None
            if (
                version is None
                or user is None
                or not user.is_active
                or job.input_content is None
            ):
                raise ValueError("Unavailable map owner")
            prepared = decode_map_input(job.input_content, job.input_sha256, version)
            input_sha256 = job.input_sha256
            user_id = user.id
            await db.commit()
        heartbeat = asyncio.create_task(renew(version_id, token))
        work = asyncio.create_task(measure(prepared, user_id))
        done, _ = await asyncio.wait(
            (heartbeat, work), return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat in done:
            await heartbeat
            return
        result = await work
        if result is not None:
            result = {
                **result,
                "snapshot_sha256": input_sha256,
                "content_sha256": prepared.content_sha256,
            }
        async with AsyncSessionLocal() as db:
            await finish_map(
                db,
                version_id,
                token,
                result=result,
                error=None if result is not None else "provider_unavailable",
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        async with AsyncSessionLocal() as db:
            await finish_map(db, version_id, token, error="mapping_unavailable")
    finally:
        tasks = [task for task in (heartbeat, work) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def recovery_loop():
    active = {}
    try:
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(CvVersionMap)
                        .where(
                            CvVersionMap.status == "running",
                            CvVersionMap.lease_expires_at <= func.now(),
                        )
                        .values(
                            status="interrupted",
                            input_content=None,
                            lease_token=None,
                            lease_expires_at=None,
                            finished_at=func.now(),
                            error_code="lease_expired",
                        )
                    )
                    await db.commit()
                    ids = list(
                        (
                            await db.scalars(
                                select(CvVersionMap.document_version_id)
                                .where(CvVersionMap.status == "queued")
                                .order_by(CvVersionMap.created_at)
                                .limit(MAX_RUNNING)
                            )
                        ).all()
                    )
                for key in list(active):
                    if active[key].done():
                        await asyncio.gather(active.pop(key), return_exceptions=True)
                for key in ids:
                    if key not in active and len(active) < MAX_RUNNING:
                        active[key] = asyncio.create_task(execute_map(key))
            except Exception:
                logger.warning("CV version-map recovery unavailable")
            await asyncio.sleep(10)
    finally:
        for task in active.values():
            task.cancel()
        await asyncio.gather(*active.values(), return_exceptions=True)


async def schedule_approved_map(db, version, user_id):
    """Capture requirements at approval, never during public reads."""
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.models.job import Job
    from app.services.cv_generator_b2b.document_policy import interactive_client_enabled
    from app.services.cv_generator_b2b.requirement_map import build_requirements

    if version.generated_document_id is None:
        return
    doc = await db.get(CvGeneratedDocument, version.generated_document_id)
    if doc is None or not await interactive_client_enabled(db, doc):
        return
    requirements = []
    seen = set()
    cached = doc.requirement_map if isinstance(doc.requirement_map, dict) else {}
    items = cached.get("items") if isinstance(cached.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        name, kind = item.get("requirement"), item.get("kind")
        if (
            isinstance(name, str)
            and name.strip()
            and isinstance(kind, str)
            and kind in {"must", "nice"}
        ):
            key = name.strip().casefold()
            if key not in seen:
                seen.add(key)
                requirements.append({"name": name.strip(), "kind": kind})
    if not requirements and doc.job_id is not None:
        job = await db.get(Job, doc.job_id)
        if job is not None:
            requirements = build_requirements(job)
    try:
        if not requirements and getattr(doc, "mode", None) == "upload":
            from app.services.cv_review_sources import load_upload_requirements

            requirements = await load_upload_requirements(db, doc.id)
        if not requirements:
            return
        await enqueue_version_map(db, version, requirements, user_id)
    except ValueError:
        # Approved CV stays available; record why optional mapping cannot run.
        import hashlib

        await db.execute(
            insert(CvVersionMap)
            .values(
                document_version_id=version.id,
                user_id=user_id,
                content_sha256=version.content_sha256,
                input_sha256=hashlib.sha256(b"").hexdigest(),
                status="failed",
                error_code="input_unavailable",
                finished_at=func.now(),
            )
            .on_conflict_do_nothing(index_elements=["document_version_id"])
        )
