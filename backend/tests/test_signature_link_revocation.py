"""M5-P0.2 — a cancelled signature must be un-completable.

Two independent holes were closed:

1. ``withdraw_signature`` / ``regenerate_link`` set ``sig.status`` but never
   revoked the outstanding ``SignatureLink`` rows. Because ``_load_valid_link``
   only checks ``revoked`` / expiry / ``used_at`` (never ``sig.status``), a party
   who already held the URL could still submit and complete after the withdraw.
   Fixed by flipping every unused link to ``revoked=True``. Asserted
   structurally — the ``update(SignatureLink).values(revoked=...)`` must stay.

2. ``finalize_signed_pdf`` unconditionally set ``status=completed`` with no
   guard, so even a still-live token finalized a withdrawn signature. A
   fail-closed status check now rejects anything not in-flight. This is the real
   safety net (guards BOTH the public /submit and the recruiter /upload-signed),
   tested behaviourally: the guard is the first statement and raises 409 before
   touching the DB or the provider. A lightweight stand-in for the signature is
   used deliberately — instantiating the real ORM model would trigger full
   mapper configuration (and fail without every model imported).
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.document_signature import SignatureStatus
from app.services.signing.sender import finalize_signed_pdf

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "bad_status",
    [
        SignatureStatus.withdrawn,
        SignatureStatus.completed,
        SignatureStatus.rejected,
        SignatureStatus.expired,
        SignatureStatus.draft,
        SignatureStatus.failed,
    ],
)
async def test_finalize_rejects_non_inflight_signature(
    bad_status: SignatureStatus,
) -> None:
    """finalize must 409 for any non-in-flight status, before any side effect."""
    sig = SimpleNamespace(status=bad_status, provider="in_house", contract_id=1)
    db = AsyncMock()  # must never be reached — the guard fires first

    with pytest.raises(HTTPException) as exc:
        await finalize_signed_pdf(db, sig, b"%PDF-fake", moved_by=1)

    assert exc.value.status_code == 409, exc.value.detail
    db.execute.assert_not_called()
    db.flush.assert_not_called()
    assert sig.status is bad_status, "finalize mutated a signature it should reject"


def _function_source(module_rel: str, func_name: str) -> str:
    path = BACKEND / module_rel
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{func_name} not found in {module_rel}")


def test_finalize_guard_allows_exactly_inflight_states() -> None:
    """The guard must admit exactly {sent, in_progress} — not be over-broad.

    Structural: proves the guard references both in-flight states, so a future
    edit that widens it (or drops in_progress) is visible in review.
    """
    src = _function_source("app/services/signing/sender.py", "finalize_signed_pdf")
    assert "SignatureStatus.sent" in src and "SignatureStatus.in_progress" in src, (
        "finalize status guard no longer names the in-flight states"
    )


@pytest.mark.parametrize("func_name", ["withdraw_signature", "regenerate_link"])
def test_endpoint_revokes_outstanding_links(func_name: str) -> None:
    """Both must revoke unused SignatureLink rows (update ... revoked=True)."""
    src = _function_source("app/api/signing.py", func_name)
    tree = ast.parse(src)

    updates_signature_link = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "update"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "SignatureLink"
        for node in ast.walk(tree)
    )
    mentions_revoked = "revoked" in src

    assert updates_signature_link and mentions_revoked, (
        f"{func_name} no longer revokes outstanding signature links — a handed-out "
        "URL survives cancellation (M5-P0.2 regressed)"
    )
