"""Oznaczenie zapisów wykonanych przez Jarvisa — bez dotykania 241 miejsc `Activity(`.

Narzędzia Jarvisa wołają API in-process (``transport.py``) z nagłówkiem
``X-Jarvis-Internal`` niosącym sekret wygenerowany przy starcie PROCESU.
``deps.get_authenticated_user`` porównuje go (``hmac.compare_digest``) i przy
zgodności stempluje sesję żądania (``stamp_via``). Listener ``before_flush``
dopisuje wtedy ``details["via"] = "jarvis"`` do każdego NOWEGO wiersza
``activities``.

Nagłówek wysłany z przeglądarki nic nie daje: sekret nie opuszcza procesu
(nie ma go w env, logach ani odpowiedziach), więc nikt spoza procesu nie
oznaczy własnego zapisu jako „zrobione przez Jarvisa" ani odwrotnie.
Wzór: ``order_change_audit.stamp_actor`` + ``_capture_before_flush``.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

INTERNAL_HEADER = "X-Jarvis-Internal"
VIA_INFO_KEY = "jarvis.via"
VIA_JARVIS = "jarvis"

_PROCESS_SECRET = secrets.token_hex(32)


def internal_secret() -> str:
    return _PROCESS_SECRET


def is_internal_request(header_value: Optional[str]) -> bool:
    if not header_value:
        return False
    return hmac.compare_digest(header_value.encode(), _PROCESS_SECRET.encode())


def stamp_via(session_info: dict, header_value: Optional[str]) -> None:
    if is_internal_request(header_value):
        session_info[VIA_INFO_KEY] = VIA_JARVIS


@event.listens_for(Session, "before_flush")
def _tag_new_activities(
    session: Session, _flush_context: object, _instances: object
) -> None:
    via = session.info.get(VIA_INFO_KEY)
    if not via:
        return
    from app.models.activity import Activity

    for obj in session.new:
        if isinstance(obj, Activity):
            details = obj.details if isinstance(obj.details, dict) else {}
            if details.get("via") != via:
                # Nowy słownik, nie mutacja w miejscu — JSONB bez MutableDict
                # nie śledzi zmian wewnątrz obiektu.
                obj.details = {**details, "via": via}
