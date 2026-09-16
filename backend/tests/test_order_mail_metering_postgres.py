"""Poczta zamówień zapisuje operację i odpowiedź dostawcy w telemetrii AI.

Do 09.2026 odczyt maila wołał model poza bramką kwot, więc wywołania nie
trafiały do ``ai_operations`` ani ``ai_provider_calls`` (1–15.09: 47 dokumentów
z maila odczytanych modelem, a 24 zmierzone operacje ``order_parser`` pochodziły
wyłącznie z innych ścieżek — poczta nie miała bramki, więc żadna nie była jej).
Test idzie przez PRAWDZIWE ``call_claude`` z syntetyczną odpowiedzią dostawcy,
czyli przez tę samą granicę, na której stoją ``_assert_declared`` i zapis tokenów.
"""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.models.ai_feature import AIFeatureKey
from app.models.ai_metering import AIOperation, AIProviderCall
from app.services import ai_quota, claude_client
from app.services import order_mail_ingest as ingest
from app.services.order_document_text import OrderDocumentText

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="hosted PostgreSQL required"
)

_ANSWER = '{"title": "7/2031", "consultant_rows": [], "confidence": {}}'


class _FakeMessages:
    """Syntetyczna odpowiedź dostawcy; zapamiętuje operację widoczną w chwili wywołania."""

    def __init__(self, seen: list):
        self._seen = seen

    def create(self, **kwargs):
        call = ai_quota.current_ai_call()
        self._seen.append(call.state.operation_id if call else None)
        return SimpleNamespace(
            id=f"msg_test_{uuid4().hex}",
            model=kwargs["model"],
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=_ANSWER)],
            usage=SimpleNamespace(
                input_tokens=321,
                output_tokens=45,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


async def test_mail_order_read_is_metered_as_a_system_operation(monkeypatch):
    from app.core.database import AsyncSessionLocal

    seen: list = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ingest.settings, "ORDER_EXTRACTION_ENABLED", True)
    monkeypatch.setattr(
        claude_client.anthropic,
        "Anthropic",
        lambda **_kwargs: SimpleNamespace(messages=_FakeMessages(seen)),
    )
    monkeypatch.setattr(
        ingest,
        "extract_order_text",
        lambda *_args: OrderDocumentText(
            text="Zamówienie nr 7/2031\nOkres: 01.10.2031 - 31.12.2031",
            page_count=1,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0,
        ),
    )
    monkeypatch.setattr(
        ingest,
        "identify_client",
        lambda *_a, **_kw: SimpleNamespace(method="none", reason="", client_key=None),
    )
    monkeypatch.setattr(
        ingest, "resolve_order_client_id", AsyncMock(return_value=(None, None))
    )
    row = SimpleNamespace(
        attachment_name="7-2031.pdf",
        sender_email="orders@example.com",
        gate_verdict=None,
    )

    try:
        async with AsyncSessionLocal() as db:
            await ingest.process_pdf_bytes(
                db, row, b"%PDF-1.4 synthetic", registry=None
            )

        assert row.extraction["source"] == "claude"
        assert len(seen) == 1 and seen[0] is not None
        async with AsyncSessionLocal() as db:
            operation = await db.get(AIOperation, seen[0])
            assert (operation.feature, operation.actor_key, operation.units) == (
                AIFeatureKey.order_parser.value,
                "system",
                1,
            )
            calls = (
                await db.scalars(
                    select(AIProviderCall).where(AIProviderCall.operation_id == seen[0])
                )
            ).all()
            assert [(c.input_tokens, c.output_tokens) for c in calls] == [(321, 45)]
    finally:
        ids = [operation_id for operation_id in seen if operation_id]
        if ids:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(AIProviderCall).where(AIProviderCall.operation_id.in_(ids))
                )
                await db.execute(delete(AIOperation).where(AIOperation.id.in_(ids)))
                await db.commit()
