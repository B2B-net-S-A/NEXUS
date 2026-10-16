"""Publiczny link do podpisu protokołu (D8): token w adresie, w bazie hash.

Dobry link pokazuje jeden protokół i przyjmuje podpis raz. Zły, zużyty,
wygasły i unieważniony link dają TO SAMO 404 z tym samym zdaniem. Każda trasa
ma limit zapytań, a moduł nie ma ``from __future__ import annotations``.
"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest_asyncio
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.rate_limit import limiter
from app.models.equipment import EquipmentProtocolLink
from app.models.notification import Notification, NotificationType
from app.services.equipment.protocols import token_hash
from tests.test_equipment_api import (
    _headers,
    _issued_protocol,
    make_people,
    modules_state,
)


@pytest_asyncio.fixture
async def modules_on():
    async with modules_state(True):
        yield


@pytest_asyncio.fixture
async def people():
    return await make_people()


PUBLIC = "/api/public/equipment-protocols"
SOURCE = Path(__file__).resolve().parents[1] / "app" / "api" / "equipment_public.py"


def _token(url: str) -> str:
    return urlparse(url).path.rsplit("/", 1)[-1]


async def _link(app_client, people, protocol_id: int) -> str:
    response = await app_client.post(
        f"/api/equipment/protocols/{protocol_id}/link",
        headers=_headers(people["reception"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["url"].split("/protocol/")[0]  # adres strony podpisu we froncie
    return _token(body["url"])


def test_public_module_is_rate_limited_and_has_no_future_import() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            raise AssertionError("from __future__ psuje @limiter.limit (422 na ciele)")
    routes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name)
            and d.func.value.id == "router"
            for d in node.decorator_list
        )
    ]
    assert len(routes) == 3
    for node in routes:
        assert any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr == "limit"
            for d in node.decorator_list
        ), node.name


async def test_good_link_shows_one_protocol_and_signs_once(
    app_client, modules_on, people
) -> None:
    protocol = await _issued_protocol(app_client, people)
    token = await _link(app_client, people, protocol["id"])
    async with AsyncSessionLocal() as db:
        stored = (
            await db.scalars(
                select(EquipmentProtocolLink.token_sha256).where(
                    EquipmentProtocolLink.protocol_id == protocol["id"]
                )
            )
        ).all()
    assert stored == [token_hash(token)]  # surowego tokenu w bazie nie ma

    page = await app_client.get(f"{PUBLIC}/{token}")
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["number"] == protocol["number"]
    assert len(body["lines"]) == 1
    texts = [b.get("text") for b in body["document"] if b["type"] == "paragraph"]
    assert f"nr {protocol['number']}" in texts
    assert "id" not in body and "issuer_user_id" not in body

    short = await app_client.post(
        f"{PUBLIC}/{token}/sign", json={"signer_name": "A", "accepted": True}
    )
    assert short.status_code == 422
    not_accepted = await app_client.post(
        f"{PUBLIC}/{token}/sign",
        json={"signer_name": "Anna Przykładowa", "accepted": False},
    )
    assert not_accepted.status_code == 422
    signed = await app_client.post(
        f"{PUBLIC}/{token}/sign",
        json={"signer_name": "Anna Przykładowa", "accepted": True},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "podpisany"

    used = await app_client.get(f"{PUBLIC}/{token}")
    assert used.status_code == 404
    again = await app_client.post(
        f"{PUBLIC}/{token}/sign",
        json={"signer_name": "Anna Przykładowa", "accepted": True},
    )
    assert again.status_code == 404

    async with AsyncSessionLocal() as db:
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == people["reception"].id,
                Notification.notification_type
                == NotificationType.equipment_protocol_signed,
                Notification.related_entity_id == protocol["id"],
            )
        )
    assert bell is not None
    assert protocol["number"] in bell.title

    detail = await app_client.get(
        f"/api/equipment/protocols/{protocol['id']}",
        headers=_headers(people["reception"]),
    )
    assert detail.json()["signer_name"] == "Anna Przykładowa"
    assert detail.json()["signature_method"] == "link"
    confirmed = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/confirm",
        json={},
        headers=_headers(people["reception"]),
    )
    assert confirmed.json()["status"] == "potwierdzony"


async def test_bad_expired_and_replaced_links_look_the_same(
    app_client, modules_on, people
) -> None:
    protocol = await _issued_protocol(app_client, people)
    old = await _link(app_client, people, protocol["id"])
    new = await _link(app_client, people, protocol["id"])  # unieważnia poprzedni

    replaced = await app_client.get(f"{PUBLIC}/{old}")
    unknown = await app_client.get(f"{PUBLIC}/{uuid.uuid4().hex}")
    assert replaced.status_code == unknown.status_code == 404
    assert (
        replaced.json()
        == unknown.json()
        == {"detail": "Link nieprawidłowy lub wygasły."}
    )

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(EquipmentProtocolLink)
            .where(EquipmentProtocolLink.token_sha256 == token_hash(new))
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await db.commit()
    expired = await app_client.get(f"{PUBLIC}/{new}")
    assert expired.status_code == 404
    assert expired.json() == unknown.json()
    expired_sign = await app_client.post(
        f"{PUBLIC}/{new}/sign",
        json={"signer_name": "Anna Przykładowa", "accepted": True},
    )
    assert expired_sign.status_code == 404


async def test_link_is_valid_fourteen_days(app_client, modules_on, people) -> None:
    protocol = await _issued_protocol(app_client, people)
    response = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/link",
        headers=_headers(people["reception"]),
    )
    expires = datetime.fromisoformat(response.json()["expires_at"])
    delta = expires - datetime.now(timezone.utc)
    assert timedelta(days=13, hours=23) < delta <= timedelta(days=14)


async def test_sign_endpoint_is_rate_limited_per_token_and_per_address(
    app_client,
) -> None:
    async def sign(token: str) -> int:
        response = await app_client.post(
            f"{PUBLIC}/{token}/sign",
            json={"signer_name": "Anna Przykładowa", "accepted": True},
        )
        return response.status_code

    was_enabled = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        same = [await sign("ten-sam-token") for _ in range(6)]
        limiter.reset()
        # Seria różnych tokenów z jednego adresu: wspólny kubełek per IP.
        rotating = [await sign(uuid.uuid4().hex) for _ in range(11)]
    finally:
        limiter.reset()
        limiter.enabled = was_enabled
    assert same == [404] * 5 + [429]
    assert rotating == [404] * 10 + [429]
