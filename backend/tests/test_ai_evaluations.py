from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import pytest

from app.ai.adapters import OpenAIResponsesAdapter
from app.ai.registry import get_feature_route
from app.ai.types import AIError, AIRequest
from app.core.config import settings
from app.models.ai_evaluation import AIEvalCase, AIEvalOutput
from app.models.ai_feature import AIFeatureKey
from app.services.ai_evaluation import blind_variants, decrypt_output, encrypt_output
from app.services.cv_parser import openai_cv_parse_json_schema


def test_eval_case_stores_references_not_cv_payloads() -> None:
    columns = set(AIEvalCase.__table__.columns.keys())
    assert {"candidate_id", "source_ref"}.issubset(columns)
    assert not {"cv_text", "raw_cv_text", "prompt", "response"}.intersection(columns)


def test_openai_parser_schema_is_strict() -> None:
    schema = openai_cv_parse_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    skill = schema["$defs"]["_CVSkill"]
    assert skill["additionalProperties"] is False
    assert set(skill["required"]) == set(skill["properties"])


def test_blind_variants_are_stable_and_balanced() -> None:
    assert blind_variants(4, 9) == blind_variants(4, 9)
    assert set(blind_variants(4, 9)) == {"A", "B"}
    assert set(blind_variants(4, 9).values()) == {"champion", "challenger"}


def test_eval_output_aes_gcm_roundtrip(monkeypatch) -> None:
    key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    monkeypatch.setattr(settings, "AI_EVAL_ENCRYPTION_KEY", key)
    ciphertext, nonce, digest = encrypt_output(
        {"skills": [{"name": "Python"}]}, run_id=2, case_id=3, variant="champion"
    )
    assert b"Python" not in ciphertext
    row = AIEvalOutput(
        run_id=2,
        case_id=3,
        variant="champion",
        provider="anthropic",
        model="test",
        ciphertext=ciphertext,
        nonce=nonce,
        output_hash=digest,
        deterministic_metrics={},
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    assert decrypt_output(row)["skills"][0]["name"] == "Python"


@pytest.mark.asyncio
async def test_openai_responses_is_eval_only_and_store_false(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"ok":true}'}],
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            }

    class FakeClient:
        def __init__(self, **kwargs):
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    route = get_feature_route("v1_current", AIFeatureKey.cv_parser_challenger)
    response = await OpenAIResponsesAdapter().call(
        AIRequest(
            feature=AIFeatureKey.cv_parser_challenger,
            messages=[{"role": "user", "content": "cv"}],
            metadata={"evaluation": True, "store": True},
        ),
        route,
        model="gpt-5.6-terra",
    )
    assert response.content == '{"ok":true}'
    assert captured["url"].endswith("/v1/responses")
    assert captured["body"]["store"] is False


@pytest.mark.asyncio
async def test_openai_batch_is_rejected_before_network(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    route = get_feature_route("v1_current", AIFeatureKey.cv_parser_challenger)
    with pytest.raises(AIError) as exc:
        await OpenAIResponsesAdapter().call(
            AIRequest(
                feature=AIFeatureKey.cv_parser_challenger,
                messages=[],
                metadata={"evaluation": True, "batch": True},
            ),
            route,
            model="gpt-5.6-terra",
        )
    assert exc.value.code == "batch_forbidden"
