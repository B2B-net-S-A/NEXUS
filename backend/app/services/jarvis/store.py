"""Zapis stanu rozmów Jarvisa — krótkie, niezależne transakcje.

Pętla agenta NIE trzyma połączenia z bazą podczas wywołań modelu ani narzędzi
(pula 20+40; tura trwa do półtorej minuty). Każda operacja tutaj otwiera
własną sesję i zamyka ją od razu.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.models.jarvis import (
    JarvisAction,
    JarvisConversation,
    JarvisConversationEntity,
    JarvisMessage,
)

_MODEL_BLOCK_TYPES = frozenset({"text", "tool_use", "tool_result"})

INTERRUPTED_RESULT = "Przerwane — ta operacja nie dokończyła się (np. restart serwera). Nie zakładaj jej wyniku."


class TurnBusy(Exception):
    """Użytkownik ma już trwającą turę Jarvisa."""


class ConversationNotFound(Exception):
    """Rozmowa nie istnieje albo należy do kogoś innego (celowo to samo)."""


@dataclass(frozen=True)
class TurnClaim:
    """Rezerwacja tury: rozmowa + żeton blokady.

    Żetonem jest dokładna wartość ``busy_until`` zapisana przy rezerwacji
    (i przy każdym przedłużeniu). Zwolnienie i przedłużenie działają tylko
    na WŁASNEJ blokadzie — tura, której blokada wygasła i którą przejęła
    następna, nie zdejmie cudzej rezerwacji w swoim ``finally`` (audyt
    25.09.2026). Bez nowej kolumny: znacznik czasu ma mikrosekundy.
    """

    conversation_id: uuid.UUID
    token: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _title_from(message: str) -> str:
    text = " ".join(message.split())
    return (text[:57] + "…") if len(text) > 60 else (text or "Nowa rozmowa")


async def claim_turn(
    *,
    user_id: int,
    conversation_id: Optional[uuid.UUID],
    first_message: str,
    context: Optional[dict[str, Any]],
    lock_seconds: float,
) -> TurnClaim:
    """Zakłada/rezerwuje rozmowę na jedną turę. Jedna trwająca tura na osobę."""
    now = _now()
    until = now + timedelta(seconds=lock_seconds)
    async with AsyncSessionLocal() as db:
        busy = await db.scalar(
            select(func.count())
            .select_from(JarvisConversation)
            .where(
                JarvisConversation.user_id == user_id,
                JarvisConversation.busy_until.is_not(None),
                JarvisConversation.busy_until > now,
            )
        )
        if busy:
            raise TurnBusy()
        if conversation_id is None:
            conversation = JarvisConversation(
                id=uuid.uuid4(),
                user_id=user_id,
                title=_title_from(first_message),
                last_context=context,
                busy_until=until,
            )
            db.add(conversation)
            await db.commit()
            return TurnClaim(conversation.id, until)
        claimed = await db.execute(
            update(JarvisConversation)
            .where(
                JarvisConversation.id == conversation_id,
                JarvisConversation.user_id == user_id,
            )
            .where(
                (JarvisConversation.busy_until.is_(None))
                | (JarvisConversation.busy_until <= now)
            )
            .values(busy_until=until, last_context=context, updated_at=now)
            .returning(JarvisConversation.id)
        )
        row = claimed.first()
        if row is None:
            exists = await db.scalar(
                select(JarvisConversation.id).where(
                    JarvisConversation.id == conversation_id,
                    JarvisConversation.user_id == user_id,
                )
            )
            await db.rollback()
            if exists is None:
                raise ConversationNotFound()
            raise TurnBusy()
        await db.commit()
        return TurnClaim(row[0], until)


async def extend_turn(claim: TurnClaim, lock_seconds: float) -> Optional[TurnClaim]:
    """Przedłuża WŁASNĄ blokadę tury; None = blokada już nie jest nasza."""
    until = _now() + timedelta(seconds=lock_seconds)
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                update(JarvisConversation)
                .where(
                    JarvisConversation.id == claim.conversation_id,
                    JarvisConversation.busy_until == claim.token,
                )
                .values(busy_until=until)
                .returning(JarvisConversation.id)
            )
        ).first()
        await db.commit()
    return TurnClaim(claim.conversation_id, until) if row is not None else None


async def release_turn(claim: TurnClaim) -> None:
    """Zwalnia blokadę tylko wtedy, gdy nadal jest nasza (żeton)."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(JarvisConversation)
            .where(
                JarvisConversation.id == claim.conversation_id,
                JarvisConversation.busy_until == claim.token,
            )
            .values(busy_until=None, updated_at=_now())
        )
        await db.commit()


async def append_message(
    conversation_id: uuid.UUID, role: str, content: list[dict[str, Any]]
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            JarvisMessage(conversation_id=conversation_id, role=role, content=content)
        )
        await db.commit()


async def load_history(conversation_id: uuid.UUID, window: int) -> list[dict[str, Any]]:
    """Ostatnie ``window`` wiadomości w kształcie Anthropic, naprawione."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(JarvisMessage.role, JarvisMessage.content)
                .where(JarvisMessage.conversation_id == conversation_id)
                .order_by(JarvisMessage.id.desc())
                .limit(max(window, 1) * 2)
            )
        ).all()
    messages = [
        {"role": role, "content": list(content or [])}
        for role, content in reversed(rows)
    ]
    return repair_history(messages, window=window)


def _is_plain_user_turn(message: dict[str, Any]) -> bool:
    return message["role"] == "user" and not any(
        isinstance(b, dict) and b.get("type") == "tool_result"
        for b in message["content"]
    )


def repair_history(
    messages: list[dict[str, Any]], *, window: int
) -> list[dict[str, Any]]:
    """Doprowadza historię do kształtu, który API Anthropic przyjmie.

    - każdy ``tool_use`` ma ``tool_result`` w NASTĘPNEJ wiadomości użytkownika
      (deploy potrafi uciąć turę między jednym a drugim) — brakujące dostają
      syntetyczny wynik „przerwane”;
    - role się przeplatają (kolejne wiadomości tej samej roli są scalane);
    - okno zaczyna się od zwykłej wiadomości użytkownika, nie od wyników
      narzędzi, których wywołanie wypadło poza okno.
    """
    fixed: list[dict[str, Any]] = []
    for message in messages:
        # Tylko bloki, które API przyjmie — np. zapisane źródła (`x_sources`)
        # są dla interfejsu, nie dla modelu.
        content = [
            b
            for b in message["content"]
            if isinstance(b, dict) and b.get("type") in _MODEL_BLOCK_TYPES
        ]
        if not content:
            continue
        if fixed and fixed[-1]["role"] == message["role"]:
            fixed[-1] = {
                "role": message["role"],
                "content": fixed[-1]["content"] + content,
            }
        else:
            fixed.append({"role": message["role"], "content": content})

    # Runda 8 (R8-N1-6): ``tool_result`` musi odpowiadać ``tool_use`` z
    # BEZPOŚREDNIO poprzedzającej wiadomości asystenta, i to raz. Tura, której
    # blokada wygasła, potrafiła dopisać wyniki za wiadomościami następnej —
    # osierocony albo zdublowany wynik to 400 od dostawcy w każdej kolejnej
    # turze tej rozmowy. Osierocone wyniki wypadają (brakujące i tak dostaną
    # niżej syntetyczne „przerwane”).
    cleaned: list[dict[str, Any]] = []
    for message in fixed:
        content = message["content"]
        if message["role"] == "user":
            prev = (
                cleaned[-1] if cleaned and cleaned[-1]["role"] == "assistant" else None
            )
            allowed = (
                {b.get("id") for b in prev["content"] if b.get("type") == "tool_use"}
                if prev is not None
                else set()
            )
            seen: set[Any] = set()
            kept: list[dict[str, Any]] = []
            for block in content:
                if block.get("type") == "tool_result":
                    tid = block.get("tool_use_id")
                    if tid not in allowed or tid in seen:
                        continue
                    seen.add(tid)
                kept.append(block)
            content = kept
        if not content:
            continue
        if cleaned and cleaned[-1]["role"] == message["role"]:
            cleaned[-1] = {
                "role": message["role"],
                "content": cleaned[-1]["content"] + content,
            }
        else:
            cleaned.append({"role": message["role"], "content": content})
    fixed = cleaned

    result: list[dict[str, Any]] = []
    for index, message in enumerate(fixed):
        result.append(message)
        if message["role"] != "assistant":
            continue
        tool_ids = [
            b.get("id")
            for b in message["content"]
            if b.get("type") == "tool_use" and b.get("id")
        ]
        if not tool_ids:
            continue
        nxt = fixed[index + 1] if index + 1 < len(fixed) else None
        answered = set()
        if nxt is not None and nxt["role"] == "user":
            answered = {
                b.get("tool_use_id")
                for b in nxt["content"]
                if b.get("type") == "tool_result"
            }
        missing = [tid for tid in tool_ids if tid not in answered]
        if not missing:
            continue
        synthetic = [
            {
                "type": "tool_result",
                "tool_use_id": tid,
                "content": INTERRUPTED_RESULT,
                "is_error": True,
            }
            for tid in missing
        ]
        if nxt is not None and nxt["role"] == "user":
            nxt["content"] = synthetic + nxt["content"]
        else:
            result.append({"role": "user", "content": synthetic})

    # Wyniki narzędzi muszą stać na początku wiadomości użytkownika.
    for message in result:
        if message["role"] == "user":
            message["content"].sort(
                key=lambda b: 0 if b.get("type") == "tool_result" else 1
            )

    if len(result) > window:
        result = result[-window:]
    while result and not _is_plain_user_turn(result[0]):
        result.pop(0)
    return result


async def link_entities(
    conversation_id: uuid.UUID, entities: Iterable[tuple[str, int]]
) -> None:
    rows = [
        {
            "conversation_id": conversation_id,
            "entity_type": kind,
            "entity_id": int(entity_id),
        }
        for kind, entity_id in {(k, int(i)) for k, i in entities}
    ]
    if not rows:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            pg_insert(JarvisConversationEntity).values(rows).on_conflict_do_nothing()
        )
        await db.commit()


async def create_action(
    *,
    conversation_id: uuid.UUID,
    user_id: int,
    tool_use_id: str,
    tool_name: str,
    args: dict[str, Any],
    preview: dict[str, Any],
) -> uuid.UUID:
    action_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(
            JarvisAction(
                id=action_id,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                args=args,
                preview=preview,
            )
        )
        await db.commit()
    return action_id


# Akcja, której wykonanie się urwało (restart, wyjątek po wywołaniu trasy).
# Front pokazuje ``uncertain`` jako „nie wiadomo”, nie jako „nie udało się”.
UNCERTAIN_RESULT: dict[str, Any] = {
    "ok": False,
    "uncertain": True,
    "error": (
        "Wykonanie zostało przerwane — nie wiadomo, czy zmiana się zapisała. "
        "Sprawdź na ekranie, zanim poprosisz o powtórkę."
    ),
}

# Wykonanie akcji to jedno wywołanie trasy (limit transportu 45 s) — akcja
# dłużej w ``confirmed`` została osierocona (deploy w trakcie, zerwane żądanie).
CONFIRMED_STALE_MINUTES = 5


def uncertain_note(preview_text: str) -> str:
    return (
        f"[Wynik akcji] Wykonanie przerwane w trakcie: {preview_text}. Nie wiadomo, "
        "czy się zapisało — nie zakładaj wyniku, poproś użytkownika o sprawdzenie."
    )


async def expire_stale_actions(ttl_minutes: int) -> int:
    cutoff = _now() - timedelta(minutes=ttl_minutes)
    confirmed_cutoff = _now() - timedelta(minutes=CONFIRMED_STALE_MINUTES)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(JarvisAction)
            .where(JarvisAction.status == "proposed", JarvisAction.created_at < cutoff)
            .values(status="expired", decided_at=_now())
        )
        # Runda 8 (R8-N1-5): ``confirmed`` bez wyniku (proces ubity w trakcie
        # wykonania) wisiał na zawsze — karta kręciła „Wykonuję…”, model nie
        # wiedział, co się stało. Teraz: „nie wiadomo” + notatka w rozmowie.
        orphaned = (
            await db.execute(
                update(JarvisAction)
                .where(
                    JarvisAction.status == "confirmed",
                    JarvisAction.decided_at < confirmed_cutoff,
                )
                .values(status="failed", result=UNCERTAIN_RESULT)
                .returning(JarvisAction.conversation_id, JarvisAction.preview)
            )
        ).all()
        for conversation_id, preview in orphaned:
            text = str((preview or {}).get("text") or "akcja Jarvisa")
            db.add(
                JarvisMessage(
                    conversation_id=conversation_id,
                    role="user",
                    content=[{"type": "text", "text": uncertain_note(text)}],
                )
            )
        await db.commit()
        return int(result.rowcount or 0) + len(orphaned)


async def release_turns_after_restart() -> int:
    """Zdejmuje blokady tur przy starcie procesu (backend = jeden uvicorn).

    Runda 8 (R8-N1-7): tura ubita deployem zostawiała ``busy_until`` do 150 s
    w przyszłości, więc pierwsze pytanie po deployu dostawało 409 „Jarvis
    jeszcze odpowiada”. Po starcie procesu żadna tura nie trwa. Gdyby jednak
    stary kontener jeszcze kończył turę, jego żeton przestaje pasować i tura
    kończy się ``turn_lost`` bez dopisania wyników (``_steps``).
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(JarvisConversation)
            .where(JarvisConversation.busy_until.is_not(None))
            .values(busy_until=None)
        )
        await db.commit()
        return int(result.rowcount or 0)


async def purge_old_conversations(retention_days: int) -> int:
    cutoff = _now() - timedelta(days=retention_days)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(JarvisConversation).where(
                JarvisConversation.updated_at < cutoff,
                (JarvisConversation.busy_until.is_(None))
                | (JarvisConversation.busy_until < _now()),
            )
        )
        await db.commit()
        return int(result.rowcount or 0)


UI_EVENTS_RETENTION_DAYS = 90


async def purge_old_ui_events(retention_days: int = UI_EVENTS_RETENTION_DAYS) -> int:
    from app.models.jarvis import JarvisUiEvent

    cutoff = _now() - timedelta(days=retention_days)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(JarvisUiEvent).where(JarvisUiEvent.created_at < cutoff)
        )
        await db.commit()
        return int(result.rowcount or 0)
