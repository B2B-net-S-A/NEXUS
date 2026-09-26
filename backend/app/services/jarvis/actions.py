"""Zatwierdzenie / odrzucenie akcji zaproponowanej przez Jarvisa.

Wykonanie następuje WYŁĄCZNIE tu, po kliknięciu człowieka, i używa DOKŁADNIE
``args`` zapisanych przy propozycji (model nie może ich podmienić po
pokazaniu karty). Idempotencja: przejście ``proposed → confirmed`` jest
warunkowym UPDATE, więc drugie kliknięcie (albo dwie karty naraz) dostaje 409.

Wynik trafia do historii rozmowy jako notatka systemowa — następna tura
modelu wie, co się naprawdę stało. Bez kolejnego wywołania modelu: potwierdzenie
ma być natychmiastowe i nic nie kosztować.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.jarvis import JarvisAction
from app.services.jarvis import store
from app.services.jarvis.tools import TOOLS_BY_NAME, render_result
from app.services.jarvis.transport import (
    CallerIdentity,
    JarvisTransport,
    ToolResponse,
    describe_error,
)


logger = logging.getLogger(__name__)


class _NotExecutable(Exception):
    """Akcji nie da się wykonać, zanim cokolwiek poszło do trasy."""


class ActionNotFound(Exception):
    pass


class ActionNotPending(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


@dataclass
class ActionOutcome:
    action: dict[str, Any]
    message: str
    follow_up: Optional[dict[str, Any]] = None
    invalidates: tuple[tuple[str, ...], ...] = ()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ActionRow:
    """Migawka wiersza zrobiona PRZED commitem — obiekt ORM po commicie wygasa,
    a leniwe doczytanie w sesji async kończy się ``MissingGreenlet``."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    tool_use_id: str
    tool_name: str
    args: dict[str, Any]
    preview: dict[str, Any]
    status: str
    result: Optional[dict[str, Any]]
    created_at: Optional[datetime]
    decided_at: Optional[datetime]

    @classmethod
    def of(cls, action: JarvisAction) -> "ActionRow":
        return cls(
            id=action.id,
            conversation_id=action.conversation_id,
            tool_use_id=action.tool_use_id,
            tool_name=action.tool_name,
            args=dict(action.args or {}),
            preview=dict(action.preview or {}),
            status=action.status,
            result=dict(action.result) if isinstance(action.result, dict) else None,
            created_at=action.created_at,
            decided_at=action.decided_at,
        )


def serialize_action(action: "JarvisAction | ActionRow") -> dict[str, Any]:
    return {
        "id": str(action.id),
        "tool": action.tool_name,
        "status": action.status,
        "preview": action.preview,
        "result": action.result,
        "created_at": action.created_at.isoformat() if action.created_at else None,
        "decided_at": action.decided_at.isoformat() if action.decided_at else None,
    }


async def _transition(action_id: uuid.UUID, user_id: int, new_status: str) -> ActionRow:
    ttl = timedelta(minutes=settings.JARVIS_ACTION_TTL_MINUTES)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(JarvisAction)
            .where(
                JarvisAction.id == action_id,
                JarvisAction.user_id == user_id,
                JarvisAction.status == "proposed",
                JarvisAction.created_at > _now() - ttl,
            )
            .values(status=new_status, decided_at=_now())
            .returning(JarvisAction)
        )
        row = result.scalars().first()
        if row is None:
            current = await db.scalar(
                select(JarvisAction.status).where(
                    JarvisAction.id == action_id, JarvisAction.user_id == user_id
                )
            )
            await db.rollback()
            if current is None:
                raise ActionNotFound()
            if current == "proposed":
                # Przeterminowana — domykamy, żeby karta przestała kusić.
                await store.expire_stale_actions(settings.JARVIS_ACTION_TTL_MINUTES)
                raise ActionNotPending("expired")
            raise ActionNotPending(current)
        snapshot = ActionRow.of(row)
        await db.commit()
        return snapshot


async def _finish(
    action_id: uuid.UUID, status: str, result: dict[str, Any]
) -> ActionRow:
    async with AsyncSessionLocal() as db:
        row = (
            (
                await db.execute(
                    update(JarvisAction)
                    .where(JarvisAction.id == action_id)
                    .values(status=status, result=result)
                    .returning(JarvisAction)
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        snapshot = ActionRow.of(row)
        await db.commit()
        return snapshot


def _eligibility_warning(response: ToolResponse) -> Optional[dict[str, Any]]:
    if response.status != 409 or not isinstance(response.data, dict):
        return None
    detail = response.data.get("detail")
    if isinstance(detail, dict) and detail.get("code") == "ELIGIBILITY_WARNING":
        return detail
    return None


def _version_conflict(response: ToolResponse) -> bool:
    if response.status != 409 or not isinstance(response.data, dict):
        return False
    detail = response.data.get("detail")
    code = detail.get("code") if isinstance(detail, dict) else detail
    return code == "PIPELINE_VERSION_CONFLICT"


async def confirm_action(
    action_id: uuid.UUID, *, user_id: int, identity: CallerIdentity
) -> ActionOutcome:
    action = await _transition(action_id, user_id, "confirmed")
    tool = TOOLS_BY_NAME.get(action.tool_name)
    if tool is None or tool.tier != "write":
        finished = await _finish(action.id, "failed", {"error": "Nieznane narzędzie"})
        return ActionOutcome(serialize_action(finished), "Nie mogę wykonać tej akcji.")

    preview_text = str((action.preview or {}).get("text") or tool.label)
    args = dict(action.args)
    # Runda 8 (R8-N1-5): wszystko po ``proposed → confirmed`` ma zakończyć się
    # ``executed`` albo ``failed`` — wcześniej wyjątek w ``build``/``shape``
    # (np. args sprzed zmiany schematu po deployu) zostawiał kartę na zawsze
    # w „Wykonuję…”, a model nie dostawał wyniku.
    try:
        async with JarvisTransport(identity) as transport:
            if tool.name == "remember_preference":
                args = await _fresh_notes(transport, args)
            try:
                spec = tool.build(args)
            except (ValueError, TypeError) as exc:
                raise _NotExecutable(
                    str(exc) or "Nieprawidłowe argumenty akcji"
                ) from exc
            response = await transport.call(spec)
    except _NotExecutable as exc:
        error = str(exc)
        finished = await _finish(action.id, "failed", {"ok": False, "error": error})
        await _note(
            action, f"[Wynik akcji] Nie udało się: {preview_text}. Powód: {error}"
        )
        return ActionOutcome(serialize_action(finished), f"Nie udało się: {error}")
    except Exception:
        # Wywołanie trasy mogło już coś zapisać — nie wiemy, czy się wykonało.
        logger.exception("jarvis: wykonanie akcji %s padło", tool.name)
        finished = await _finish(action.id, "failed", store.UNCERTAIN_RESULT)
        await _note(action, store.uncertain_note(preview_text))
        return ActionOutcome(
            serialize_action(finished), str(store.UNCERTAIN_RESULT["error"])
        )

    if response.ok:
        try:
            shaped = tool.shape(response.data, args)
        except Exception:  # noqa: BLE001 — zapis się udał, psuje się tylko skrót
            logger.warning("jarvis: shape akcji %s padł", tool.name)
            shaped = None
        finished = await _finish(action.id, "executed", {"ok": True, "data": shaped})
        message = tool.done
        await _note(
            action,
            f"[Wynik akcji] Użytkownik zatwierdził i wykonano: {preview_text}. "
            f"Odpowiedź systemu: {render_result(shaped)[:1500]}",
        )
        return ActionOutcome(
            serialize_action(finished), message, invalidates=tool.invalidates
        )

    warning = (
        _eligibility_warning(response) if tool.name == "move_candidate_stage" else None
    )
    if warning is not None:
        reason = str(
            warning.get("message")
            or warning.get("reason")
            or "ostrzeżenie o kandydacie"
        )
        finished = await _finish(action.id, "failed", {"ok": False, "warning": warning})
        follow_up = None
        if warning.get("can_acknowledge"):
            args = {**dict(action.args), "acknowledge_eligibility": True}
            preview = {
                **(action.preview or {}),
                "text": f"{preview_text} — mimo ostrzeżenia: {reason}",
                "warning": reason,
            }
            new_id = await store.create_action(
                conversation_id=action.conversation_id,
                user_id=user_id,
                tool_use_id=action.tool_use_id,
                tool_name=action.tool_name,
                args=args,
                preview=preview,
            )
            follow_up = {
                "id": str(new_id),
                "tool": action.tool_name,
                "status": "proposed",
                "preview": preview,
            }
        await _note(
            action, f"[Wynik akcji] Przesunięcie zatrzymane ostrzeżeniem: {reason}."
        )
        return ActionOutcome(
            serialize_action(finished),
            f"NEXUS ostrzega: {reason}"
            + (" Możesz przenieść mimo to." if follow_up else ""),
            follow_up=follow_up,
        )

    if _version_conflict(response):
        error = "Ktoś w międzyczasie przesunął tego kandydata. Poproś mnie o ponowne sprawdzenie tablicy."
    else:
        error = describe_error(response)
    finished = await _finish(
        action.id, "failed", {"ok": False, "error": error, "status": response.status}
    )
    await _note(action, f"[Wynik akcji] Nie udało się: {preview_text}. Powód: {error}")
    return ActionOutcome(serialize_action(finished), f"Nie udało się: {error}")


async def _fresh_notes(
    transport: JarvisTransport, args: dict[str, Any]
) -> dict[str, Any]:
    """Pamięć składana z listy ZAPISANEJ teraz, nie z chwili propozycji.

    Runda 8 (R8-N1-4): PATCH podmienia całą listę, więc dwie karty albo edycja
    w ustawieniach między propozycją a kliknięciem gubiły notatki.
    """
    from app.services.jarvis.agent import ProposalRejected, _merge_notes

    try:
        return await _merge_notes(transport, args)
    except ProposalRejected as exc:
        raise _NotExecutable(str(exc)) from exc


async def reject_action(action_id: uuid.UUID, *, user_id: int) -> ActionOutcome:
    action = await _transition(action_id, user_id, "rejected")
    preview_text = str((action.preview or {}).get("text") or action.tool_name)
    await _note(
        action, f"[Wynik akcji] Użytkownik ODRZUCIŁ propozycję: {preview_text}."
    )
    return ActionOutcome(
        serialize_action(action), "Anulowane — nic nie zostało zmienione."
    )


async def _note(action: ActionRow, text: str) -> None:
    await store.append_message(
        action.conversation_id, "user", [{"type": "text", "text": text}]
    )
