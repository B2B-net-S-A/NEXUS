"""Jarvis: powiadomienia według tematu (27.10.2026).

Na produkcji „kto mnie oznaczył w notatce?” przy 128 nieprzeczytanych
kończyło się na „w 20 najnowszych nie widzę”: narzędzie nie umiało zawęzić.
Trasa ma filtr ``topic`` (tematy ikon paska) — Jarvis go teraz podaje.
"""

from __future__ import annotations

from app.services.jarvis.tools import TOOLS_BY_NAME
from app.services.notification_topics import NotificationTopic

TOOL = TOOLS_BY_NAME["list_notifications"]


def test_mentions_ask_for_the_messages_topic_and_next_page():
    spec = TOOL.build({"topic": ["messages"], "offset": 20, "limit": 20})
    assert spec.path == "/api/notifications"
    assert spec.params == {"limit": 20, "topic": ["messages"], "offset": 20}


def test_plain_call_is_unchanged():
    spec = TOOL.build({})
    assert spec.params == {"limit": 10}


def test_tool_topics_mirror_the_bar_topics():
    """Nowy temat paska bez wpisu tutaj = Jarvis go nie zna."""
    offered = set(TOOL.input_schema["properties"]["topic"]["items"]["enum"])
    assert offered == {t.value for t in NotificationTopic}
