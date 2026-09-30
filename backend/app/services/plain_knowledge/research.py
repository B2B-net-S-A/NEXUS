"""Research z internetu dla bazy wiedzy „po ludzku” (F26, klucz `plain_knowledge_research`).

Dwa kroki, bo odpowiedź z cytatami przychodzi pocięta na wiele bloków tekstu
i parsowanie JSON-a z niej jest kruche:

1. wyszukanie z narzędziem serwerowym ``web_search_20250305`` (tylko Anthropic),
   notatki tekstem + źródła z wyników (``jarvis.web.collect_sources``);
2. ułożenie notatek w JSON wywołaniem bez narzędzi.

Zasady, które łatwo cofnąć:

* **Do wyszukiwarki idzie tylko nazwa** technologii, roli albo firmy — nigdy
  profil Championa, dane kandydata ani notatki (ta sama zasada co tryb
  internetu Jarvisa, ``jarvis/web.py``). Funkcja ``research`` przyjmuje
  wyłącznie nazwę i listę umiejętności roli, więc nie ma jak tego złamać.
* **AI to dodatek.** Każda awaria kończy się ``None``; wołający zapisuje
  ``status=failed`` i nic nie rzuca do użytkownika.
* **Bez blokady na czas wywołania.** ``db.commit()`` przed modelem oddaje
  połączenie do puli; zajęcie wiersza robi ``knowledge.claim_*``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "term": "technologia, narzędzie albo dziedzina w IT",
    "role": "stanowisko w branży IT",
    "client": "firma (klient agencji rekrutacyjnej IT)",
}
INSTRUCTIONS = {
    "term": (
        "Ustal: czym to jest, do czego się tego używa w firmach, jak to się nazywa "
        "w CV (inne nazwy, wersje, produkty pokrewne) i z czym łatwo to pomylić. "
        "Gdy nazwa ma kilka znaczeń, opisz WYŁĄCZNIE znaczenie z branży IT "
        "(oprogramowanie, platforma, narzędzie, standard). Research 29.09 opisał "
        "„Ferryt” (platformę low-code dla banków) jako materiał z metalurgii."
    ),
    "role": (
        "Ustal: czym zajmuje się osoba na tym stanowisku, jak wygląda jej zwykły dzień "
        "pracy, z kim współpracuje i o co kandydaci na to stanowisko zwykle pytają."
    ),
    "client": (
        "Ustal: czym firma się zajmuje, jak jest duża (klienci, pracownicy, kraje), "
        "gdzie w Polsce ma biura albo centra technologiczne i co jest w niej ciekawe "
        "dla specjalisty IT. Tylko publiczne informacje o firmie."
    ),
}
_STRUCTURE = {
    "term": "PLAIN_TERM_STRUCTURE",
    "role": "PLAIN_ROLE_STRUCTURE",
    "client": "PLAIN_CLIENT_STRUCTURE",
}

MAX_TEXT = 600
MAX_LIST = 6
MAX_PAUSES = 3

_budget: dict[str, Any] = {"day": None, "used": 0}


def _take_budget() -> bool:
    """Dzienny sufit researchu (w pamięci procesu; backend to jeden uvicorn)."""
    from app.core.scheduling import business_today

    today = business_today().isoformat()
    if _budget["day"] != today:
        _budget["day"], _budget["used"] = today, 0
    if _budget["used"] >= max(0, int(settings.PLAIN_KNOWLEDGE_RESEARCH_DAILY_LIMIT)):
        return False
    _budget["used"] += 1
    return True


def enabled() -> bool:
    return bool(settings.PLAIN_KNOWLEDGE_WEB_ENABLED)


def _clean_text(value: Any, limit: int = MAX_TEXT) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text[:limit] or None


def _clean_list(value: Any, limit: int = MAX_LIST, item_limit: int = 200) -> list[str]:
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = _clean_text(item, item_limit)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def clean_structured(kind: str, raw: Any) -> dict[str, Any]:
    """Wynik modelu → tylko znane pola, przycięte. Czysta funkcja (testy)."""
    data = raw if isinstance(raw, dict) else {}
    if kind == "term":
        return {
            "display_name": _clean_text(data.get("display_name"), 200),
            "summary": _clean_text(data.get("summary")),
            "does": _clean_text(data.get("does")),
            "cv_hints": _clean_list(data.get("cv_hints"), 8, 80),
            "confused_with": _clean_text(data.get("confused_with")),
        }
    if kind == "role":
        return {
            "summary": _clean_text(data.get("summary")),
            "example": _clean_text(data.get("example")),
            "day_to_day": _clean_list(data.get("day_to_day"), 3, 300),
            "candidate_questions": _clean_list(data.get("candidate_questions"), 5, 200),
        }
    return {"about": _clean_text(data.get("about"), 1200)}


def _texts(content: Any) -> list[str]:
    out: list[str] = []
    for block in content or []:
        kind = (
            block.get("type")
            if isinstance(block, dict)
            else getattr(block, "type", None)
        )
        if kind == "text":
            text = (
                block.get("text")
                if isinstance(block, dict)
                else getattr(block, "text", "")
            )
            if text:
                out.append(text)
    return out


def _search_sync(
    kind: str, name: str, model: str, fallbacks: list[str]
) -> tuple[str, list[dict[str, str]]]:
    from app.services.claude_client import call_claude
    from app.services.jarvis import web
    from app.services.llm_prompts import PLAIN_WEB_RESEARCH

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": PLAIN_WEB_RESEARCH.render(
                name=name[:120],
                kind_label=KIND_LABELS[kind],
                instructions=INSTRUCTIONS[kind],
            ),
        }
    ]
    tool = web.web_tool_definition(max_uses=settings.PLAIN_KNOWLEDGE_MAX_SEARCHES)
    texts: list[str] = []
    sources: list[dict[str, str]] = []
    for _ in range(MAX_PAUSES + 1):
        message = call_claude(
            model=model,
            fallback_models=fallbacks,
            max_tokens=2500,
            system=PLAIN_WEB_RESEARCH.system_prompt,
            tools=[tool],
            messages=messages,
            thinking={"type": "disabled"},
        )
        content = list(message.content or [])
        texts.extend(_texts(content))
        for src in web.collect_sources(content):
            if src["url"] not in {s["url"] for s in sources}:
                sources.append(src)
        if getattr(message, "stop_reason", None) != "pause_turn":
            break
        messages.append({"role": "assistant", "content": web.raw_blocks(content)})
    return web.join_text(texts), sources[: web.MAX_SOURCES]


def _structure_sync(
    kind: str,
    name: str,
    notes: str,
    skills: list[str],
    model: str,
    fallbacks: list[str],
) -> Any:
    from app.services import llm_prompts
    from app.services.champion_draft_service import _strip_code_fences
    from app.services.claude_client import call_claude
    from app.services.prompt_fencing import fence

    template = getattr(llm_prompts, _STRUCTURE[kind])
    kwargs: dict[str, Any] = {"name": name[:120], "notes": fence("notes", notes[:6000])}
    if kind == "role":
        kwargs["skills"] = ", ".join(skills[:12]) or "brak danych"
    message = call_claude(
        model=model,
        fallback_models=fallbacks,
        max_tokens=1500,
        system=template.system_prompt,
        messages=[{"role": "user", "content": template.render(**kwargs)}],
        thinking={"type": "disabled"},
    )
    raw = "".join(_texts(message.content))
    return json.loads(_strip_code_fences(raw))


async def research(
    db: AsyncSession,
    kind: str,
    name: str,
    *,
    skills: Optional[list[str]] = None,
    user_id: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Research jednej nazwy. ``None`` = nie udało się (albo wyłączone / limit)."""
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import fallbacks_for, model_for
    from app.services.ai_quota import ai_feature

    if kind not in KIND_LABELS or not (name or "").strip():
        return None
    if not enabled() or not _take_budget():
        return None
    model = model_for(AIFeatureKey.plain_knowledge_research)
    fallbacks = list(fallbacks_for(AIFeatureKey.plain_knowledge_research))
    try:
        async with ai_feature(
            db, AIFeatureKey.plain_knowledge_research, user_id=user_id
        ):
            await db.commit()
            notes, sources = await run_in_threadpool(
                _search_sync, kind, name.strip(), model, fallbacks
            )
            if not notes:
                return None
            raw = await run_in_threadpool(
                _structure_sync,
                kind,
                name.strip(),
                notes,
                list(skills or []),
                model,
                fallbacks,
            )
    except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
        logger.warning(
            "plain_knowledge research failed: kind=%s err=%s", kind, type(exc).__name__
        )
        return None
    result = clean_structured(kind, raw)
    result["sources"] = sources
    return result
