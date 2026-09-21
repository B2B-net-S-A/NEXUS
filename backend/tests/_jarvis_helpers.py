"""Wspólne pomocniki testów Jarvisa (nie jest plikiem testowym)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any, Iterable

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.user import User, UserRole


async def make_user(role: UserRole = UserRole.recruiter) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"jarvis-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"J4rvis_{tag}!pw"),
            name=f"Jarvis {role.value} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(
            user.id,
            role.value,
            roles=[role.value],
            authorization_version=user.authorization_version,
        )
        return user.id, {"Authorization": f"Bearer {token}"}


async def make_candidate(lastname: str = "Testowa") -> int:
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Anna",
            lastname=f"{lastname}-{tag}",
            email=f"jarvis-cand-{tag}@example.com",
        )
        db.add(cand)
        await db.commit()
        return cand.id


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def tool_block(
    name: str, tool_input: dict[str, Any], tool_id: str | None = None
) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": tool_id or f"toolu_{uuid.uuid4().hex[:12]}",
        "name": name,
        "input": tool_input,
    }


def fake_message(*blocks: dict[str, Any]) -> SimpleNamespace:
    stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(
        content=[SimpleNamespace(**block) for block in blocks],
        stop_reason=stop,
        id=f"msg_{uuid.uuid4().hex[:8]}",
        usage=None,
    )


class ScriptedModel:
    """Podmiana ``claude_client.call_claude``: kolejne odpowiedzi z listy."""

    def __init__(self, responses: Iterable[SimpleNamespace]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> SimpleNamespace:
        # Kopia wiadomości — pętla dopisuje do tej samej listy po wywołaniu.
        self.calls.append(
            {**kwargs, "messages": json.loads(json.dumps(kwargs["messages"]))}
        )
        if not self.responses:
            raise AssertionError(
                "Model wywołany więcej razy, niż przewiduje scenariusz"
            )
        return self.responses.pop(0)


def parse_sse(body: str) -> list[dict[str, Any]]:
    events = []
    for chunk in body.split("\n\n"):
        data_lines = [
            line[5:].strip() for line in chunk.splitlines() if line.startswith("data:")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


def enable_jarvis(monkeypatch, model: ScriptedModel) -> None:
    from app.api import jarvis as jarvis_api
    from app.core.config import settings
    from app.services import claude_client, llm_providers

    monkeypatch.setattr(settings, "JARVIS_ENABLED", True)
    monkeypatch.setattr(llm_providers, "api_key_configured", lambda _model: True)
    monkeypatch.setattr(jarvis_api, "api_key_configured", lambda _model: True)
    monkeypatch.setattr(claude_client, "call_claude", model)
