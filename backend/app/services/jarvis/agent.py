"""Pętla agenta Jarvisa: model ↔ narzędzia, z limitami i zapisem kroków.

Tura:
1. rezerwacja rozmowy (``store.claim_turn``) — jedna tura na osobę naraz;
2. historia z bazy, naprawiona (``store.repair_history``) + nowa wiadomość;
3. do ``JARVIS_MAX_STEPS`` wywołań modelu; po każdym narzędzia:
   - ``read``  → wywołanie API tokenem pytającego, wynik wraca do modelu;
   - ``write`` → ZAPIS PROPOZYCJI (``jarvis_actions``), karta dla człowieka,
     model dostaje informację, że akcja czeka na zatwierdzenie;
   - ``link``  → przycisk do ekranu, nic się nie wykonuje;
4. zwolnienie rezerwacji — zawsze, także po błędzie.

Całość to JEDNA operacja AI (``ai_feature(jarvis)``) i N wywołań dostawcy.
Zdarzenia wychodzą jako słowniki — trasa zamienia je na SSE.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, AsyncIterator, Optional

import anthropic
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey
from app.services import claude_client
from app.services.ai_models import fallbacks_for, model_for
from app.services.jarvis import store
from app.services.jarvis import web as jarvis_web
from app.services.jarvis.prompt import SYSTEM_PROMPT, context_block
from app.services.jarvis.tools import (
    TOOLS_BY_NAME,
    JarvisTool,
    RequestSpec,
    build_screen_link,
    render_result,
)
from app.services.jarvis.transport import (
    CallerIdentity,
    JarvisTransport,
    ToolResponse,
    describe_error,
)

logger = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = (
    "Nie działam teraz — spróbuj za chwilę. Wszystko inne w NEXUSIE działa normalnie."
)
CANCELLED_MESSAGE = "Przerwane na Twoją prośbę."
TRUNCATED_NOTE = "\n\n_(Odpowiedź ucięta — napisz „dalej”, dokończę.)_"

# Prośby o przerwanie tury („Zatrzymaj” w panelu). Backend to jeden proces
# uvicorn, więc zbiór w pamięci wystarcza; pętla sprawdza go przed każdym
# wywołaniem modelu i każdym narzędziem. Samego wywołania modelu w wątku nie
# da się przerwać — tura kończy się najpóźniej po bieżącym kroku.
_CANCEL_REQUESTS: set[uuid.UUID] = set()


def request_cancel(conversation_id: uuid.UUID) -> None:
    _CANCEL_REQUESTS.add(conversation_id)


def _cancelled(state: "_TurnState") -> bool:
    return state.conversation_id in _CANCEL_REQUESTS


@dataclass
class TurnInput:
    user_id: int
    user_name: str
    roles: list[str]
    message: str
    conversation_id: Optional[uuid.UUID]
    screen: Optional[dict[str, Any]]
    assistant_name: Optional[str]
    allowed_tools: list[JarvisTool]
    identity: CallerIdentity
    today: date
    # Wiadomość systemowa zamiast tekstu użytkownika (np. wynik akcji
    # zatwierdzonej kliknięciem) — trafia do modelu, nie do tytułu rozmowy.
    system_note: Optional[str] = None
    # Tura z internetem: wyszukiwarka, bez danych NEXUSA i bez historii.
    web: bool = False
    # Chwila tury w strefie firmy — godzina w kontekście („jutro o 10”).
    now: Optional[datetime] = None
    # „Co Jarvis o mnie wie” — preferencje wpisane przez użytkownika.
    notes: list[str] = field(default_factory=list)
    # Poziomy sekcji pytającego — do kotwic ``show_on_screen`` (element, którego
    # ta osoba nie widzi, nie jest podświetlany).
    sections: dict[str, int] = field(default_factory=dict)


@dataclass
class _TurnState:
    conversation_id: uuid.UUID
    entities: set[tuple[str, int]] = field(default_factory=set)
    # Żeton blokady tury (`store.TurnClaim`) — przedłużany z każdym krokiem.
    claim: Optional[store.TurnClaim] = None


# ── pomocniki ──────────────────────────────────────────────────────────────


def _block_to_dict(block: Any) -> Optional[dict[str, Any]]:
    kind = getattr(block, "type", None)
    if kind == "text":
        text = getattr(block, "text", "") or ""
        return {"type": "text", "text": text} if text else None
    if kind == "tool_use":
        return {
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": dict(getattr(block, "input", {}) or {}),
        }
    return None


def _tool_definitions(tools: list[JarvisTool]) -> list[dict[str, Any]]:
    definitions = [tool.to_anthropic() for tool in tools]
    if definitions:
        # Znacznik cache na OSTATNIM narzędziu: lista narzędzi idzie przed
        # promptem systemowym, więc cache obejmuje ją całą.
        definitions[-1] = {**definitions[-1], "cache_control": {"type": "ephemeral"}}
    return definitions


def sanitize_args(tool: JarvisTool, raw: Any) -> dict[str, Any]:
    """Tylko pola zadeklarowane w schemacie — model nie dopisze sobie ``_display``."""
    if not isinstance(raw, dict):
        return {}
    allowed = set((tool.input_schema.get("properties") or {}).keys())
    return {k: v for k, v in raw.items() if k in allowed}


_CANDIDATE_URL = re.compile(r"/candidates/(\d+)")
_CANDIDATE_ROW_TOOLS = frozenset(
    {"search_candidates", "get_candidate", "talent_radar_search"}
)


def collect_entities(
    tool: JarvisTool, args: dict[str, Any], result: Any
) -> set[tuple[str, int]]:
    """Kandydaci, których dane padły w rozmowie — do kasowania rozmów (art. 17).

    ``candidate_id`` na dowolnej głębokości i linki ``/candidates/{id}`` są
    jednoznaczne. Gołe ``id`` liczymy WYŁĄCZNIE w wierszach narzędzi, których
    wiersz JEST kandydatem — inaczej ID rekrutacji z zagnieżdżonych list
    wiązałyby rozmowę z przypadkowymi osobami.
    """
    found: set[tuple[str, int]] = set()

    def add(value: Any) -> None:
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            found.add(("candidate", value))

    add(args.get("candidate_id"))
    for cid in args.get("candidate_ids") or []:
        add(cid)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "candidate_id":
                    add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            for match in _CANDIDATE_URL.findall(node):
                add(int(match))

    walk(result)
    if tool.name in _CANDIDATE_ROW_TOOLS and isinstance(result, dict):
        for key in ("items", "results"):
            for row in result.get(key) or []:
                if isinstance(row, dict):
                    add(row.get("id"))
        person = result.get("candidate")
        if isinstance(person, dict):
            add(person.get("id"))
    return found


def _screen_entities(screen: Optional[dict[str, Any]]) -> set[tuple[str, int]]:
    entity = (screen or {}).get("entity") if isinstance(screen, dict) else None
    if (
        isinstance(entity, dict)
        and entity.get("type") == "candidate"
        and isinstance(entity.get("id"), int)
    ):
        return {("candidate", entity["id"])}
    return set()


async def _display_names(
    transport: JarvisTransport, args: dict[str, Any]
) -> dict[str, str]:
    """Nazwy do karty akcji — czytane przez API (sprawdza przy okazji dostęp)."""
    names: dict[str, str] = {}
    if isinstance(args.get("candidate_id"), int):
        resp = await transport.call(
            RequestSpec("GET", f"/api/candidates/{args['candidate_id']}/quick-view")
        )
        person = (
            resp.data.get("candidate")
            if resp.ok and isinstance(resp.data, dict)
            else None
        )
        if isinstance(person, dict):
            full = " ".join(
                str(person.get(k) or "").strip() for k in ("name", "lastname")
            ).strip()
            if full:
                names["candidate_id"] = full
    if isinstance(args.get("job_id"), int):
        resp = await transport.call(RequestSpec("GET", f"/api/jobs/{args['job_id']}"))
        if resp.ok and isinstance(resp.data, dict) and resp.data.get("title"):
            client = resp.data.get("client_name")
            if not client and isinstance(resp.data.get("client"), dict):
                client = resp.data["client"].get("name")
            names["job_id"] = str(resp.data["title"]) + (
                f" / {client}" if client else ""
            )
    return names


class ProposalRejected(Exception):
    """Propozycja zapisu nie przeszła sprawdzenia serwera — wraca do modelu."""


async def _resolve_move_stage(
    transport: JarvisTransport, args: dict[str, Any]
) -> dict[str, Any]:
    """Nazwa etapu docelowego i bieżącego — z tablicy, nie ze słów modelu."""
    board = await transport.call(
        RequestSpec("GET", f"/api/pipeline/kanban/{args['job_id']}")
    )
    if not board.ok or not isinstance(board.data, dict):
        raise ProposalRejected(describe_error(board))
    target_name = None
    current_name = None
    version = None
    for column in board.data.get("columns") or []:
        name = column.get("name") or column.get("stage")
        if column.get("stage_def_id") == args.get("stage_def_id"):
            target_name = name
        for card in column.get("items") or []:
            if card.get("candidate_id") == args.get("candidate_id"):
                current_name = name
                version = card.get("process_state_version")
    if target_name is None:
        raise ProposalRejected(
            "Tej rekrutacji nie ma etapu o podanym stage_def_id — odczytaj tablicę i użyj ID z niej."
        )
    if current_name is None:
        raise ProposalRejected("Tego kandydata nie ma na tablicy tej rekrutacji.")
    resolved = {**args, "stage_name": target_name}
    if (
        resolved.get("expected_state_version") is None
        and isinstance(version, int)
        and version > 0
    ):
        resolved["expected_state_version"] = version
    return {"args": resolved, "from_stage": current_name}


async def prepare_proposal(
    transport: JarvisTransport, tool: JarvisTool, args: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Zwraca (args do wykonania, podgląd karty). Rzuca ``ProposalRejected``."""
    try:
        tool.build(args)  # walidacja kształtu (brak pól wymaganych → ValueError)
    except (ValueError, TypeError) as exc:
        raise ProposalRejected(str(exc) or "Nieprawidłowe argumenty") from exc
    extra: dict[str, Any] = {}
    if tool.name == "remember_preference":
        args = await _merge_notes(transport, args)
    if tool.name == "move_candidate_stage":
        resolved = await _resolve_move_stage(transport, args)
        args = resolved["args"]
        extra["from_stage"] = resolved["from_stage"]
    display = await _display_names(transport, args)
    text = tool.preview({**args, "_display": display}) if tool.preview else tool.label
    if extra.get("from_stage"):
        text += f" (teraz: {extra['from_stage']})"
    preview = {"text": text, "tool_label": tool.label, "display": display}
    if tool.detail:
        preview["body"] = tool.detail(args)
    return args, preview


async def _merge_notes(
    transport: JarvisTransport, args: dict[str, Any]
) -> dict[str, Any]:
    """Pełna lista pamięci (zapisane + nowa) — PATCH podmienia całą listę."""
    from app.services.jarvis.prefs import MAX_NOTES

    resp = await transport.call(RequestSpec("GET", "/api/users/me/preferences"))
    if not resp.ok or not isinstance(resp.data, dict):
        raise ProposalRejected(describe_error(resp))
    jarvis = (
        resp.data.get("jarvis") if isinstance(resp.data.get("jarvis"), dict) else {}
    )
    current = [str(n) for n in jarvis.get("notes") or [] if str(n).strip()]
    text = " ".join(str(args.get("text") or "").split())
    if not text:
        raise ProposalRejected("Pusta treść do zapamiętania.")
    if text in current:
        raise ProposalRejected("To już jest zapamiętane.")
    if len(current) >= MAX_NOTES:
        raise ProposalRejected(
            f"Pamięć jest pełna ({MAX_NOTES} pozycji) — poproś użytkownika, żeby usunął "
            "coś w ustawieniach Jarvisa („Co Jarvis o mnie wie”)."
        )
    return {**args, "text": text, "_notes": [*current, text]}


def screen_anchor(
    turn: "TurnInput", anchor_id: str
) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Kotwica z przewodnika BIEŻĄCEGO ekranu, którą ta osoba widzi.

    Zwraca (kotwica albo ``None``, lista poprawnych identyfikatorów). Model
    nie może wymyślić selektora — tylko wybrać z zamkniętej listy.
    """
    from app.data.screen_guides import guide_for_user, load_guides

    key = (turn.screen or {}).get("key") if isinstance(turn.screen, dict) else None
    guide = load_guides().get(key) if isinstance(key, str) else None
    if guide is None:
        return None, []
    sections = turn.sections or {
        s: 2 for s in ("sourcing", "pipeline", "delivery", "insights", "finance")
    }
    shaped = guide_for_user(guide, set(turn.roles), sections)
    anchors = (shaped or {}).get("anchors") or []
    valid = [a["id"] for a in anchors]
    for anchor in anchors:
        if anchor["id"] == anchor_id:
            return anchor, valid
    return None, valid


def _sse_tool_label(tool: JarvisTool) -> str:
    return tool.label + "…"


async def execute_read(
    transport: JarvisTransport, tool: JarvisTool, args: dict[str, Any]
) -> tuple[bool, str, Any]:
    try:
        spec = tool.build(args)
    except (ValueError, TypeError) as exc:
        return False, f"Nieprawidłowe argumenty: {exc}", None
    response: ToolResponse = await transport.call(spec)
    if not response.ok:
        return False, describe_error(response), None
    shaped = tool.shape(response.data, args)
    return True, render_result(shaped), shaped


# ── tura ───────────────────────────────────────────────────────────────────


def _lock_seconds() -> float:
    return settings.JARVIS_TURN_TIMEOUT_SECONDS + 60


async def claim(turn: TurnInput) -> store.TurnClaim:
    """Rezerwuje rozmowę na turę PRZED otwarciem strumienia (409 zamiast SSE)."""
    return await store.claim_turn(
        user_id=turn.user_id,
        conversation_id=turn.conversation_id,
        first_message=turn.message or "Nowa rozmowa",
        context=turn.screen,
        lock_seconds=_lock_seconds(),
    )


async def run_turn(
    turn: TurnInput, claimed: store.TurnClaim
) -> AsyncIterator[dict[str, Any]]:
    """Generator zdarzeń tury na zarezerwowanej rozmowie (``claim``).

    Pierwsze zdarzenie to zawsze ``conversation``; rezerwacja jest zwalniana
    w ``finally`` — także gdy klient się rozłączył albo model zawiódł.
    """
    conversation_id = claimed.conversation_id
    # „Zatrzymaj” kliknięte po końcu poprzedniej tury (albo przy turze, która
    # padła przed sprzątaniem) nie może przerwać NOWEJ tury tej rozmowy.
    _CANCEL_REQUESTS.discard(conversation_id)
    state = _TurnState(
        conversation_id=conversation_id,
        entities=_screen_entities(turn.screen),
        claim=claimed,
    )
    try:
        # Powiązanie z kandydatem z ekranu od razu — tura ubita w połowie
        # (deploy) nie może zostawić rozmowy o nim bez powiązania (RODO).
        await _link_now(state, state.entities)
        yield {"type": "conversation", "conversation_id": str(conversation_id)}
        async for event in _run_loop(turn, state):
            yield event
        yield {"type": "done"}
    finally:
        try:
            await asyncio.shield(_finish_turn(state))
        except Exception:  # noqa: BLE001 — sprzątanie nie może zamaskować wyniku
            logger.exception("jarvis: nie udało się zwolnić tury %s", conversation_id)


async def _finish_turn(state: _TurnState) -> None:
    _CANCEL_REQUESTS.discard(state.conversation_id)
    if state.entities:
        await store.link_entities(state.conversation_id, state.entities)
    if state.claim is not None:
        await store.release_turn(state.claim)


async def _link_now(state: _TurnState, entities: set[tuple[str, int]]) -> None:
    """Zapisz powiązanie rozmowy z kandydatami ZARAZ po narzędziu.

    Wynik narzędzia trafia do historii rozmowy (dane osobowe) przed końcem
    tury — do 25.09.2026 powiązanie zapisywało dopiero ``_finish_turn``,
    więc tura ubita w połowie zostawiała rozmowę, której usunięcie kandydata
    (art. 17) nie kasowało.
    """
    if not entities:
        return
    try:
        await store.link_entities(state.conversation_id, entities)
    except Exception:  # noqa: BLE001 — `_finish_turn` spróbuje jeszcze raz
        logger.exception(
            "jarvis: nie udało się powiązać rozmowy %s z kandydatami",
            state.conversation_id,
        )


async def _extend_lock(state: _TurnState) -> bool:
    """Przedłuż własną blokadę tury; False = przejęła ją inna tura."""
    if state.claim is None:
        return True
    renewed = await store.extend_turn(state.claim, _lock_seconds())
    if renewed is None:
        return False
    state.claim = renewed
    return True


def _user_content(turn: TurnInput) -> list[dict[str, Any]]:
    blocks = [
        {
            "type": "text",
            "text": context_block(
                user_name=turn.user_name,
                roles=turn.roles,
                today=turn.today,
                now=turn.now,
                notes=turn.notes,
                screen=turn.screen,
                assistant_name=turn.assistant_name,
            ),
        }
    ]
    if turn.system_note:
        blocks.append({"type": "text", "text": turn.system_note})
    if turn.web:
        blocks.append({"type": "text", "text": jarvis_web.WEB_NOTE})
    if turn.message:
        blocks.append({"type": "text", "text": turn.message})
    return blocks


async def _run_loop(
    turn: TurnInput, state: _TurnState
) -> AsyncIterator[dict[str, Any]]:
    from app.services.ai_quota import ai_feature
    from app.services.llm_providers import api_key_configured

    model = model_for(AIFeatureKey.jarvis)
    if not api_key_configured(model):
        yield {"type": "error", "message": UNAVAILABLE_MESSAGE, "code": "no_api_key"}
        return

    # Tura z internetem NIE dostaje wcześniejszej rozmowy: mogły w niej paść
    # dane z NEXUSA, a stąd byłby krok do zapytania wysłanego na zewnątrz.
    history = (
        []
        if turn.web
        else await store.load_history(
            state.conversation_id, settings.JARVIS_HISTORY_WINDOW
        )
    )
    user_blocks = _user_content(turn)
    await store.append_message(state.conversation_id, "user", user_blocks)
    if history and history[-1]["role"] == "user":
        history[-1] = {"role": "user", "content": history[-1]["content"] + user_blocks}
    else:
        history.append({"role": "user", "content": user_blocks})

    allowed = [
        tool
        for tool in turn.allowed_tools
        if not turn.web or tool.name in jarvis_web.WEB_SAFE_TOOLS
    ]
    tools_by_name = {tool.name: tool for tool in allowed}
    definitions = _tool_definitions(allowed)
    if turn.web:
        definitions = [jarvis_web.web_tool_definition(), *definitions]
    deadline = time.monotonic() + settings.JARVIS_TURN_TIMEOUT_SECONDS
    fallbacks = [m for m in fallbacks_for(AIFeatureKey.jarvis) if m != model]

    async with AsyncSessionLocal() as db:
        async with ai_feature(db, AIFeatureKey.jarvis, user_id=turn.user_id):
            # Admisja zapisana PRZED pierwszym wywołaniem dostawcy; potem sesja
            # oddaje połączenie do puli na czas całej tury.
            await db.commit()
            async with JarvisTransport(turn.identity) as transport:
                async for event in _steps(
                    turn,
                    state,
                    history,
                    tools_by_name,
                    definitions,
                    model,
                    fallbacks,
                    deadline,
                    transport,
                ):
                    yield event


async def _steps(
    turn: TurnInput,
    state: _TurnState,
    history: list[dict[str, Any]],
    tools_by_name: dict[str, JarvisTool],
    definitions: list[dict[str, Any]],
    model: str,
    fallbacks: list[str],
    deadline: float,
    transport: JarvisTransport,
) -> AsyncIterator[dict[str, Any]]:
    for step in range(max(1, settings.JARVIS_MAX_STEPS)):
        if _cancelled(state):
            yield {"type": "message", "markdown": CANCELLED_MESSAGE, "final": True}
            return
        if not await _extend_lock(state):
            # Blokada wygasła i rozmowę przejęła inna tura — nie piszemy
            # równolegle do tej samej historii.
            yield {
                "type": "error",
                "message": "Ta rozmowa jest już obsługiwana w innym oknie — odśwież panel.",
                "code": "turn_lost",
            }
            return
        remaining = deadline - time.monotonic()
        if remaining < 5:
            yield {
                "type": "message",
                "markdown": "Zabrakło mi czasu na dokończenie — zadaj pytanie węziej albo podziel je na części.",
            }
            return
        yield {"type": "thinking", "step": step + 1}
        # Tekst odpowiedzi idzie do panelu na żywo (zdarzenia ``delta``);
        # pełna wiadomość (``message``) i tak przychodzi na końcu kroku
        # i zastępuje to, co zdążyło się pokazać.
        loop = asyncio.get_running_loop()
        deltas: asyncio.Queue = asyncio.Queue()

        def _on_delta(chunk: Optional[str]) -> None:
            loop.call_soon_threadsafe(deltas.put_nowait, chunk)

        call = asyncio.ensure_future(
            run_in_threadpool(
                claude_client.call_claude,
                model=model,
                fallback_models=fallbacks,
                max_tokens=settings.JARVIS_MAX_TOKENS_PER_STEP,
                system=SYSTEM_PROMPT,
                cache_system=True,
                tools=definitions,
                messages=history,
                total_timeout=remaining,
                stream_response=True,
                on_text_delta=_on_delta,
            )
        )
        while True:
            getter = asyncio.ensure_future(deltas.get())
            done, _ = await asyncio.wait(
                {call, getter}, return_when=asyncio.FIRST_COMPLETED
            )
            if getter in done:
                yield _delta_event(getter.result())
                continue
            getter.cancel()
            break
        while not deltas.empty():
            yield _delta_event(deltas.get_nowait())
        try:
            message = call.result()
        except (claude_client.ClaudeError, anthropic.APIError) as exc:
            logger.warning(
                "jarvis: wywołanie modelu nie powiodło się: %s", type(exc).__name__
            )
            yield {
                "type": "error",
                "message": UNAVAILABLE_MESSAGE,
                "code": "model_error",
            }
            return

        content = list(message.content or [])
        for query in jarvis_web.search_queries(content):
            yield {
                "type": "step",
                "tool": "web_search",
                "label": f"Szukam w internecie: „{query}”…",
                "status": "done",
            }
        sources = jarvis_web.collect_sources(content) if turn.web else []
        stop_reason = getattr(message, "stop_reason", None)
        paused = stop_reason == "pause_turn"
        truncated = stop_reason == "max_tokens"

        blocks = [b for b in (_block_to_dict(x) for x in content) if b]
        if truncated:
            # Ucięty blok narzędzia ma niepełne argumenty, a tool_use bez
            # tool_result rozbiłby następną turę — zostaje sam tekst z dopiskiem.
            texts = [b for b in blocks if b["type"] == "text"]
            if texts:
                texts[-1] = {"type": "text", "text": texts[-1]["text"] + TRUNCATED_NOTE}
            blocks = texts or [{"type": "text", "text": TRUNCATED_NOTE.strip()}]
        if not blocks and not paused:
            blocks = [{"type": "text", "text": "…"}]
        stored = list(blocks)
        if sources:
            stored.append({"type": jarvis_web.SOURCES_BLOCK, "items": sources})
        if stored:
            await store.append_message(state.conversation_id, "assistant", stored)

        if paused:
            # Wyszukiwarka przerwała turę (długa praca po stronie dostawcy) —
            # odsyłamy odpowiedź w oryginalnym kształcie i model kontynuuje.
            history.append(
                {"role": "assistant", "content": jarvis_web.raw_blocks(content)}
            )
            continue
        history.append({"role": "assistant", "content": blocks})

        text = jarvis_web.join_text(b["text"] for b in blocks if b["type"] == "text")
        tool_uses = [b for b in blocks if b["type"] == "tool_use"]
        if text:
            yield {
                "type": "message",
                "markdown": text,
                "final": not tool_uses and not sources,
            }
        if sources:
            yield {"type": "sources", "items": sources}
        if not tool_uses:
            return

        results: list[dict[str, Any]] = []
        for use in tool_uses:
            if _cancelled(state):
                # Każdy tool_use musi dostać wynik — inaczej historia rozmowy
                # byłaby niepoprawna dla następnej tury.
                results.append(
                    _tool_result(
                        str(use.get("id") or ""),
                        "Przerwane przez użytkownika.",
                        is_error=True,
                    )
                )
                continue
            events: list[dict[str, Any]] = []
            results.append(
                await _handle_tool(turn, state, tools_by_name, transport, use, events)
            )
            for event in events:
                yield event
        await store.append_message(state.conversation_id, "user", results)
        history.append({"role": "user", "content": results})
        if _cancelled(state):
            yield {"type": "message", "markdown": CANCELLED_MESSAGE, "final": True}
            return

    yield {
        "type": "message",
        "markdown": "Zatrzymałem się po kilku krokach, żeby nie przedłużać — napisz, co dalej sprawdzić.",
    }


def _delta_event(chunk: Optional[str]) -> dict[str, Any]:
    if chunk is None:
        return {"type": "delta_reset"}
    return {"type": "delta", "text": chunk}


def _tool_result(
    tool_use_id: str, content: str, *, is_error: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }
    if is_error:
        result["is_error"] = True
    return result


async def _handle_tool(
    turn: TurnInput,
    state: _TurnState,
    tools_by_name: dict[str, JarvisTool],
    transport: JarvisTransport,
    use: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    use_id = str(use.get("id") or "")
    tool = tools_by_name.get(str(use.get("name") or ""))
    if tool is None or TOOLS_BY_NAME.get(tool.name) is not tool:
        return _tool_result(
            use_id, "Nieznane albo niedostępne narzędzie.", is_error=True
        )
    args = sanitize_args(tool, use.get("input"))

    if tool.name == "show_on_screen":
        anchor, valid = screen_anchor(turn, str(args.get("anchor") or ""))
        if anchor is None:
            hint = (
                f"Poprawne na tym ekranie: {', '.join(valid)}."
                if valid
                else "Na tym ekranie nie ma elementów do pokazania — opisz drogę słowami."
            )
            return _tool_result(
                use_id, f"Nie ma takiego elementu. {hint}", is_error=True
            )
        events.append(
            {
                "type": "highlight",
                "anchor": anchor["id"],
                "label": anchor["label"],
                "reason": str(args.get("reason") or "")[:200],
            }
        )
        return _tool_result(use_id, f"Podświetliłem użytkownikowi: {anchor['label']}.")

    if tool.tier == "link":
        try:
            link = build_screen_link(args)
        except (ValueError, TypeError) as exc:
            return _tool_result(
                use_id, f"Nie udało się zbudować linku: {exc}", is_error=True
            )
        events.append({"type": "deep_link", **link})
        return _tool_result(
            use_id,
            f"Pokazałem użytkownikowi przycisk „{link['label']}” ({link['href']}).",
        )

    if tool.tier == "read":
        events.append(
            {
                "type": "step",
                "tool": tool.name,
                "label": _sse_tool_label(tool),
                "status": "running",
            }
        )
        ok, content, shaped = await execute_read(transport, tool, args)
        events.append(
            {
                "type": "step",
                "tool": tool.name,
                "label": _sse_tool_label(tool),
                "status": "done" if ok else "error",
            }
        )
        if ok:
            # Każde narzędzie, nie tylko „kandydackie”: `global_search`,
            # kalendarz i powiadomienia też zwracają nazwiska z `candidate_id`
            # albo linkiem `/candidates/{id}` (audyt 25.09.2026 — rozmowy po
            # nich przeżywały usunięcie kandydata).
            found = collect_entities(tool, args, shaped)
            state.entities |= found
            await _link_now(state, found)
        return _tool_result(use_id, content, is_error=not ok)

    # write — tylko propozycja
    events.append(
        {
            "type": "step",
            "tool": tool.name,
            "label": _sse_tool_label(tool),
            "status": "running",
        }
    )
    try:
        final_args, preview = await prepare_proposal(transport, tool, args)
    except ProposalRejected as exc:
        events.append(
            {
                "type": "step",
                "tool": tool.name,
                "label": _sse_tool_label(tool),
                "status": "error",
            }
        )
        return _tool_result(use_id, f"Nie mogę tego zaproponować: {exc}", is_error=True)
    action_id = await store.create_action(
        conversation_id=state.conversation_id,
        user_id=turn.user_id,
        tool_use_id=use_id,
        tool_name=tool.name,
        args=final_args,
        preview=preview,
    )
    found = collect_entities(tool, final_args, preview)
    state.entities |= found
    await _link_now(state, found)
    events.append(
        {
            "type": "step",
            "tool": tool.name,
            "label": _sse_tool_label(tool),
            "status": "done",
        }
    )
    events.append(
        {
            "type": "action_proposed",
            "action": {
                "id": str(action_id),
                "tool": tool.name,
                "status": "proposed",
                "preview": preview,
            },
        }
    )
    return _tool_result(
        use_id,
        f"Akcja przygotowana (id {action_id}) i CZEKA na zatwierdzenie przez użytkownika na karcie. "
        "Nic jeszcze nie zostało zapisane — nie pisz, że zostało wykonane.",
    )
