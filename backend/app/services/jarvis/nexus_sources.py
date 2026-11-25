"""Źródła odpowiedzi z NEXUSA — dokumenty, z których Jarvis czytał w tej turze.

Ramka źródeł pokazywała tylko linki z internetu. Odpowiedź o zapisie umowy
(podpisana umowa konsultanta, umowa ramowa klienta) powinna wskazywać
dokument, z którego pochodzi cytat, żeby człowiek mógł go otworzyć.

Źródło powstaje z WYNIKU narzędzia (identyfikatory z bazy), nigdy z tekstu
modelu. Adres to zawsze ścieżka NEXUSA zaczynająca się od jednego „/” —
front otwiera ją w tej samej aplikacji.
"""

from __future__ import annotations

from typing import Any

ORIGIN = "nexus"
MAX_SOURCES = 8

_CONTRACT_DOCUMENT_TOOLS = frozenset(
    {"search_contract_documents", "read_contract_document"}
)
_FRAMEWORK_TOOLS = frozenset(
    {"search_framework_contracts", "read_framework_contract", "read_contract_amendment"}
)
TOOLS = _CONTRACT_DOCUMENT_TOOLS | _FRAMEWORK_TOOLS


def _int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _passages(shaped: Any) -> list[dict[str, Any]]:
    if not isinstance(shaped, dict):
        return []
    if isinstance(shaped.get("passages"), list):
        return [p for p in shaped["passages"] if isinstance(p, dict)]
    passage = shaped.get("passage")
    return [passage] if isinstance(passage, dict) else []


def collect(tool_name: str, args: dict[str, Any], shaped: Any) -> list[dict[str, str]]:
    """Źródła z wyniku jednego narzędzia: ``{url, title, origin, kind}``."""
    out: list[dict[str, str]] = []
    if tool_name in _CONTRACT_DOCUMENT_TOOLS:
        from_result = shaped.get("contract_id") if isinstance(shaped, dict) else None
        contract_id = _int(from_result) or _int(args.get("contract_id"))
        if contract_id is None:
            return []
        for passage in _passages(shaped):
            title = str(passage.get("ref") or passage.get("filename") or "").strip()
            if title:
                out.append(
                    {
                        "url": f"/contracts/{contract_id}?tab=documents",
                        "title": title[:200],
                        "origin": ORIGIN,
                        "kind": "contract_document",
                    }
                )
    elif tool_name in _FRAMEWORK_TOOLS:
        client_id = _int(args.get("client_id"))
        if client_id is None:
            return []
        for passage in _passages(shaped):
            name = str(passage.get("contract_name") or "").strip()
            amendment = str(passage.get("amendment_name") or "").strip()
            title = f"{name} — {amendment}" if name and amendment else name or amendment
            if title:
                out.append(
                    {
                        "url": f"/clients/{client_id}?tab=umowy-ramowe",
                        "title": title[:200],
                        "origin": ORIGIN,
                        "kind": "framework_contract",
                    }
                )
    return out


def merge(existing: list[dict[str, str]], found: list[dict[str, str]]) -> None:
    """Dokłada nowe źródła bez powtórek (ten sam adres i tytuł), najwyżej ``MAX_SOURCES``."""
    seen = {(item["url"], item["title"]) for item in existing}
    for item in found:
        key = (item["url"], item["title"])
        if key in seen or len(existing) >= MAX_SOURCES:
            continue
        seen.add(key)
        existing.append(item)
