"""Encryption, blind ordering and deterministic checks for AI evaluations."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIError
from app.core.config import settings
from app.models.ai_evaluation import AIEvalOutput


OUTPUT_TTL = timedelta(days=14)


def _key() -> bytes:
    raw = settings.AI_EVAL_ENCRYPTION_KEY.strip()
    if not raw:
        raise AIError(
            "evaluation_encryption_unconfigured",
            "AI_EVAL_ENCRYPTION_KEY nie jest ustawiony",
            status_code=503,
        )
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as exc:
        raise AIError(
            "evaluation_encryption_invalid",
            "Klucz ewaluacji nie jest poprawnym base64",
            status_code=503,
        ) from exc
    if len(key) != 32:
        raise AIError(
            "evaluation_encryption_invalid",
            "Klucz ewaluacji musi mieć dokładnie 32 bajty",
            status_code=503,
        )
    return key


def ensure_encryption_configured() -> None:
    _key()


def _aad(run_id: int, case_id: int, variant: str) -> bytes:
    return f"nexus-ai-eval:v1:{run_id}:{case_id}:{variant}".encode()


def encrypt_output(
    content: Any, *, run_id: int, case_id: int, variant: str
) -> tuple[bytes, bytes, str]:
    plaintext = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(
        nonce, plaintext, _aad(run_id, case_id, variant)
    )
    return ciphertext, nonce, hashlib.sha256(plaintext).hexdigest()


def decrypt_output(row: AIEvalOutput) -> Any:
    if row.expires_at <= datetime.now(timezone.utc):
        raise AIError(
            "evaluation_output_expired", "Wynik ewaluacji wygasł", status_code=410
        )
    plaintext = AESGCM(_key()).decrypt(
        row.nonce, row.ciphertext, _aad(row.run_id, row.case_id, row.variant)
    )
    return json.loads(plaintext)


def blind_variants(run_id: int, case_id: int) -> dict[str, str]:
    """Stable A/B assignment prevents reviewers inferring the model by order."""
    digest = hashlib.sha256(f"{run_id}:{case_id}:blind-v1".encode()).digest()
    if digest[0] & 1:
        return {"A": "challenger", "B": "champion"}
    return {"A": "champion", "B": "challenger"}


def parser_metrics(content: Any) -> dict[str, Any]:
    """Safe deterministic shape checks; LLM judges never determine winners."""
    if not isinstance(content, dict):
        return {"schema_valid": False, "contact_fields_present": 0}
    contacts = sum(bool(content.get(key)) for key in ("email", "phone"))
    return {
        "schema_valid": True,
        "contact_fields_present": contacts,
        "skills_count": len(content.get("skills") or []),
        "needs_human_review": not bool(
            content.get("skills") or content.get("current_position")
        ),
    }


async def purge_expired_outputs(db: AsyncSession) -> int:
    result = await db.execute(
        delete(AIEvalOutput).where(
            AIEvalOutput.expires_at <= datetime.now(timezone.utc)
        )
    )
    return int(result.rowcount or 0)


def output_expiry() -> datetime:
    return datetime.now(timezone.utc) + OUTPUT_TTL
