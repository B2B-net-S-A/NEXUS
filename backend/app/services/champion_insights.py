"""Zapis sekcji 8 „Wiedza z rozmów" — scalanie notatek przysłanych z edytora.

Edytor odsyła CAŁĄ listę, którą dostał z `champion_view.insights` (widok:
notatki zapisane + wpisy składane ze starych pól i z weryfikacji). Tu
rozstrzygamy, co z tej listy naprawdę trafia do bazy:

* `verification:*` — pomijane. Źródłem jest blok `verification`, stemplowany
  przez `POST …/verification`; zwykły PUT nie może go podrobić.
* `legacy:*` — pomijane. To widok starych pól `client.consultant_insight`
  i `client.historical_questions`; edytor zmienia te pola w sekcji `client`
  (edycja wpisu = nowa wartość pola, usunięcie = pusty napis). Zapis zwrotny
  po stronie serwera czyściłby stare pola przy KAŻDYM zapisie, który odsyła
  zapisany kształt z pustą listą notatek (zapis bez zmian, import dokumentu).
* reszta — notatki. Autor i daty stempluje SERWER: istniejąca notatka zachowuje
  autora i `created_at` z bazy, nowa (brak id, `new-…` albo id nieznane w bazie)
  dostaje świeże id i autora z sesji. Pola autora z żądania są ignorowane.

Wartości spoza słowników i za długie teksty są naprawiane, nie odrzucane —
`ChampionProfile.model_validate` na końcu `prepare_profile` zamieniłby
pojedynczą złą notatkę w 500 na zapisie całego profilu.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.schemas.champion import (
    INSIGHT_TEXT_MAX_CHARS,
    INSIGHTS_MAX,
    STORED_INSIGHT_ORIGINS,
)

_SOURCES = ("client", "consultant")
_AUDIENCES = ("team", "candidate")
_TOPICS = (
    "needs",
    "rejections",
    "decision",
    "process",
    "team",
    "project",
    "pitch",
    "ask_client",
    "other",
)


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _text(value: Any) -> str:
    return str(value).strip()[:INSIGHT_TEXT_MAX_CHARS] if isinstance(value, str) else ""


def merge_insights(
    stored_profile: Mapping[str, Any],
    patch_notes: Any,
    *,
    actor_id: Optional[int],
    actor_name: Optional[str],
    default_origin: str = "manual",
    now: Optional[datetime] = None,
) -> list[dict]:
    """Zwraca notatki do zapisu (bez wpisów składanych przy odczycie)."""
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    stored_notes = {
        str(note.get("id")): dict(note)
        for note in (stored_profile.get("insights") or [])
        if isinstance(note, Mapping) and note.get("id")
    }
    notes: list[dict] = []
    seen_ids: set[str] = set()

    for raw in patch_notes if isinstance(patch_notes, list) else []:
        if not isinstance(raw, Mapping):
            continue
        note_id = str(raw.get("id") or "")
        if note_id.startswith(("verification:", "legacy:")):
            continue
        text = _text(raw.get("text"))
        if not text:
            continue
        content = {
            "source": _choice(raw.get("source"), _SOURCES, "client"),
            "topic": _choice(raw.get("topic"), _TOPICS, "other"),
            "audience": _choice(raw.get("audience"), _AUDIENCES, "team"),
            "text": text,
            "done": bool(raw.get("done")),
        }
        previous = stored_notes.get(note_id)
        if previous is None or note_id in seen_ids:
            note_id = f"n-{uuid.uuid4().hex[:12]}"
            origin = raw.get("origin")
            origin = origin if origin in STORED_INSIGHT_ORIGINS else default_origin
            author_id, author_name, created_at = actor_id, actor_name, stamp
            updated_at = stamp
        else:
            origin = previous.get("origin") or "manual"
            if origin not in STORED_INSIGHT_ORIGINS:
                origin = "manual"
            author_id = previous.get("author_id")
            author_name = previous.get("author_name")
            created_at = previous.get("created_at")
            changed = any(
                content[key] != previous.get(key, False if key == "done" else None)
                for key in content
            )
            updated_at = stamp if changed else previous.get("updated_at")
        seen_ids.add(note_id)
        notes.append(
            {
                "id": note_id,
                **content,
                "origin": origin,
                "author_id": author_id,
                "author_name": author_name,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
        if len(notes) >= INSIGHTS_MAX:
            break

    return notes
