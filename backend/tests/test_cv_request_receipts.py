from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.services.cv_generator_b2b.request_receipts import (
    reserve_request,
    request_digest,
)


@pytest.mark.parametrize(
    "case", ["new", "retry", "changed", "deleted", "no_key", "invalid"]
)
async def test_request_receipt_replays_only_exact_attempt(case):
    key = str(uuid4())
    existing = SimpleNamespace(
        request_sha256=request_digest("upload", {"file": "hash"}), generated_id=7
    )
    if case == "changed":
        existing.request_sha256 = "different"
    if case == "deleted":
        existing.generated_id = None
    doc = SimpleNamespace(id=7)
    db = SimpleNamespace(
        execute=AsyncMock(),
        scalar=AsyncMock(return_value=None if case == "new" else existing),
        get=AsyncMock(return_value=doc),
        add=Mock(),
        flush=AsyncMock(),
    )
    selected_key = None if case == "no_key" else "invalid" if case == "invalid" else key
    if case in {"changed", "deleted", "invalid"}:
        with pytest.raises(HTTPException) as exc:
            await reserve_request(db, 9, selected_key, "upload", {"file": "hash"})
        assert (
            exc.value.status_code
            == {"changed": 409, "deleted": 410, "invalid": 422}[case]
        )
        db.add.assert_not_called()
    else:
        receipt, replay = await reserve_request(
            db, 9, selected_key, "upload", {"file": "hash"}
        )
        if case == "retry":
            assert replay is doc and receipt is existing
            db.add.assert_not_called()
        elif case == "new":
            assert replay is None and receipt.user_id == 9
            assert receipt.request_key == key
            db.flush.assert_awaited_once()
        else:
            assert receipt is replay is None
            db.execute.assert_not_awaited()
    if case not in {"no_key", "invalid"}:
        assert "pg_advisory_xact_lock" in str(db.execute.call_args.args[0])
        sql = str(db.scalar.call_args.args[0])
        assert "user_id =" in sql and "request_key =" in sql


def test_request_digest_is_order_independent_and_kind_sensitive():
    assert request_digest("new", {"a": 1, "b": 2}) == request_digest(
        "new", {"b": 2, "a": 1}
    )
    assert request_digest("new", {}) != request_digest("upload", {})


@pytest.mark.parametrize("deleted", [False, True])
async def test_preview_retry_uses_preview_record_not_generated_document(deleted):
    from app.models.client_cv_rule_preview import ClientCvRulePreview

    existing = SimpleNamespace(
        request_sha256=request_digest("preview", {"client_id": 3}),
        preview_id=None if deleted else 17,
        generated_id=999,
    )
    preview = SimpleNamespace(id=17)
    db = SimpleNamespace(
        execute=AsyncMock(),
        scalar=AsyncMock(return_value=existing),
        get=AsyncMock(return_value=preview),
    )
    if deleted:
        with pytest.raises(HTTPException) as exc:
            await reserve_request(db, 9, str(uuid4()), "preview", {"client_id": 3})
        assert exc.value.status_code == 410
        db.get.assert_not_awaited()
    else:
        _, replay = await reserve_request(
            db, 9, str(uuid4()), "preview", {"client_id": 3}
        )
        assert replay is preview
        db.get.assert_awaited_once_with(ClientCvRulePreview, 17)
