"""Adapter Recommand: przyjęcie, stan doręczenia i rodzaje błędów (bez sieci)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.peppol import providers

pytestmark = pytest.mark.asyncio

REQUEST = providers.SendRequest(xml=b"<Invoice/>", doctype_id="urn:doc", recipient="0088:7332545042126")


def _provider(handler) -> providers.RecommandProvider:
    return providers.RecommandProvider(
        base_url="https://peppol.example",
        api_key="key_test",
        api_secret="secret_test",
        company_id="c_1",
        transport=httpx.MockTransport(handler),
    )


async def test_send_posts_raw_xml_and_reads_delivery_state():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"success": True, "id": "doc_1", "deliveryStatus": "pending", "deliveries": []})

    result = await _provider(handler).send(REQUEST)

    assert seen["path"] == "/api/v1/c_1/send"
    assert seen["body"] == {
        "recipient": "0088:7332545042126",
        "documentType": "xml",
        "doctypeId": "urn:doc",
        "document": "<Invoice/>",
    }
    assert seen["auth"].startswith("Basic ")
    assert (result.document_id, result.state) == ("doc_1", providers.PENDING)


async def test_status_reports_failed_peppol_delivery_with_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/documents/doc_1"
        return httpx.Response(
            200,
            json={
                "success": True,
                "document": {
                    "deliveryStatus": "failed",
                    "deliveries": [
                        {"channel": "peppol", "status": "failed", "failure": {"category": "recipient_not_found", "message": "not registered"}}
                    ],
                },
            },
        )

    result = await _provider(handler).status("doc_1")

    assert result.state == providers.FAILED
    assert result.detail == "recipient_not_found: not registered"


@pytest.mark.parametrize(
    ("handler", "retry", "uncertain"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r)), True, False),
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), True, True),
        (lambda r: httpx.Response(503), True, True),
        (lambda r: httpx.Response(429), True, False),
        (lambda r: httpx.Response(401), True, False),
        (lambda r: httpx.Response(400, json={"success": False, "errors": {"document": ["BR-AE-10"]}}), False, False),
    ],
    ids=["connect", "read-timeout", "5xx", "429", "auth", "validation"],
)
async def test_send_errors_say_whether_the_document_may_have_gone(handler, retry, uncertain):
    with pytest.raises(providers.ProviderError) as exc:
        await _provider(handler).send(REQUEST)

    assert (exc.value.retry, exc.value.uncertain) == (retry, uncertain)


def test_visma_direct_is_named_but_waits_for_specification(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PEPPOL_PROVIDER", "visma_direct")

    config = providers.load_config()

    assert config.name == "visma_direct"
    assert not config.enabled
    assert "technika Vismy" in config.disabled_reason
    assert providers.open_provider() is None
