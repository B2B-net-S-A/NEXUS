"""Serialize retries before charging; callers authorize the requested resource first."""

import hashlib
import json
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, text
from app.models.cv_generation_request import CvGenerationRequest
from app.models.cv_generated_document import CvGeneratedDocument


def request_digest(kind, payload):
    return hashlib.sha256(
        json.dumps(
            {"kind": kind, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


async def reserve_request(db, user_id, key, kind, payload):
    if key is None:
        return None, None
    try:
        canonical_key = str(UUID(key))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            422, "Nieprawidłowy identyfikator ponowienia generacji."
        ) from None
    digest = request_digest(kind, payload)
    lock_key = int.from_bytes(
        hashlib.sha256(f"cv-request:{user_id}:{canonical_key}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    receipt = await db.scalar(
        select(CvGenerationRequest).where(
            CvGenerationRequest.user_id == user_id,
            CvGenerationRequest.request_key == canonical_key,
        )
    )
    if receipt is not None:
        if receipt.request_sha256 != digest:
            raise HTTPException(
                409,
                "Identyfikator ponowienia dotyczy innych danych. Rozpocznij nową generację.",
            )
        generated = (
            await db.get(CvGeneratedDocument, receipt.generated_id)
            if receipt.generated_id
            else None
        )
        if generated is None:
            raise HTTPException(
                410, "Wynik tej generacji został usunięty. Rozpocznij nową generację."
            )
        return receipt, generated
    receipt = CvGenerationRequest(
        user_id=user_id, request_key=canonical_key, request_sha256=digest
    )
    db.add(receipt)
    await db.flush()
    return receipt, None
