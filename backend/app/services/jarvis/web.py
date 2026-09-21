"""Tryb internetu Jarvisa (21.09.2026).

Wyszukiwarka to narzędzie SERWEROWE Anthropic (``web_search_20250305``):
wykonuje się po stronie dostawcy, a wynik wraca w tej samej odpowiedzi.

Zasada bezpieczeństwa: internet ALBO baza, nigdy oba w jednej turze. Tura
z włączonym przełącznikiem nie dostaje narzędzi czytających dane NEXUSA ani
wcześniejszej historii rozmowy — wstrzyknięta w CV/notatkę instrukcja nie ma
czego wkleić do zapytania wysłanego do zewnętrznej wyszukiwarki (RODO
i wyciek). Zostają wyłącznie Pomoc (procedury bez danych osobowych) i link.
"""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import urlparse

from app.core.config import settings

WEB_MARKER = "[Tryb internetu]"
WEB_SAFE_TOOLS = frozenset({"search_help", "get_help_article", "open_screen"})
SOURCES_BLOCK = "x_sources"
MAX_SOURCES = 8

WEB_NOTE = (
    WEB_MARKER
    + " W tej wiadomości masz wyszukiwarkę internetową i NIE masz dostępu do danych "
    "NEXUSA ani do wcześniejszej rozmowy. Szukaj wyłącznie tego, o co prosi użytkownik. "
    "Nie wpisuj do zapytań danych osobowych (nazwisk kandydatów, kontaktów, stawek). "
    "Odpowiadaj zwięźle i opieraj się na znalezionych źródłach; gdy są sprzeczne albo "
    "nieaktualne, powiedz to wprost. Nie wymyślaj adresów stron."
)


def _domains(raw: str) -> list[str]:
    return [d.strip().lower() for d in (raw or "").split(",") if d.strip()]


def web_tool_definition() -> dict[str, Any]:
    tool: dict[str, Any] = {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": max(1, int(settings.JARVIS_WEB_MAX_SEARCHES_PER_TURN)),
        "user_location": {
            "type": "approximate",
            "country": "PL",
            "timezone": "Europe/Warsaw",
        },
    }
    allowed = _domains(settings.JARVIS_WEB_ALLOWED_DOMAINS)
    blocked = _domains(settings.JARVIS_WEB_BLOCKED_DOMAINS)
    if allowed:
        tool["allowed_domains"] = allowed
    elif blocked:
        tool["blocked_domains"] = blocked
    return tool


def _safe_url(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return url


def collect_sources(content: Iterable[Any]) -> list[dict[str, str]]:
    """Źródła z odpowiedzi: najpierw CYTOWANE w tekście, potem pozostałe wyniki."""
    cited: list[dict[str, str]] = []
    found: list[dict[str, str]] = []

    def get(obj: Any, key: str) -> Any:
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    for block in content or []:
        kind = get(block, "type")
        if kind == "text":
            for citation in get(block, "citations") or []:
                url = _safe_url(get(citation, "url"))
                if url:
                    cited.append(
                        {"url": url, "title": str(get(citation, "title") or url)[:200]}
                    )
        elif kind == "web_search_tool_result":
            results = get(block, "content")
            if isinstance(results, list):
                for result in results:
                    url = _safe_url(get(result, "url"))
                    if url:
                        found.append(
                            {
                                "url": url,
                                "title": str(get(result, "title") or url)[:200],
                            }
                        )
    seen: set[str] = set()
    ordered: list[dict[str, str]] = []
    for item in cited + found:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        ordered.append(item)
    return ordered[:MAX_SOURCES]


def search_queries(content: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for block in content or []:
        kind = (
            block.get("type")
            if isinstance(block, dict)
            else getattr(block, "type", None)
        )
        if kind == "server_tool_use":
            raw = (
                block.get("input")
                if isinstance(block, dict)
                else getattr(block, "input", None)
            )
            query = raw.get("query") if isinstance(raw, dict) else None
            if isinstance(query, str) and query.strip():
                out.append(query.strip()[:120])
    return out


def raw_blocks(content: Iterable[Any]) -> list[dict[str, Any]]:
    """Bloki odpowiedzi w kształcie do odesłania modelowi (kontynuacja `pause_turn`)."""
    out: list[dict[str, Any]] = []
    for block in content or []:
        if isinstance(block, dict):
            out.append(block)
        elif hasattr(block, "model_dump"):
            out.append(block.model_dump(exclude_none=True))
    return out


_TIGHT_START = ",.;:)!?%»”"


def join_text(parts: Iterable[str]) -> str:
    """Skleja bloki tekstu jednej odpowiedzi modelu w jeden akapit.

    Odpowiedź z cytatami przychodzi jako wiele bloków tekstu — jeden akapit
    pocięty na granicach cytatów. Pusta linia między nimi (dawne ``"\\n\\n"``)
    rozrywała zdania, a historia rozmowy pokazywała każdy kawałek jako osobny
    dymek. Bloki niosą własne spacje; gdy ich brak, zdanie zamknięte kropką
    zaczyna nowy akapit, a pozostałe łączy spacja.
    """
    out = ""
    for part in parts:
        if not part:
            continue
        if out and not (
            out[-1].isspace() or part[0].isspace() or part[0] in _TIGHT_START
        ):
            out += "\n\n" if out.rstrip()[-1:] in (".", "!", "?", ":") else " "
        out += part
    return out.strip()
