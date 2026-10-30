# Jarvis: powiadomienia według tematu (27.10.2026)
<!-- indeks: list_notifications z topic (tematy ikon paska) i offset -->

Na produkcji „kto mnie oznaczył w notatce?” przy 128 nieprzeczytanych
kończyło się na „w 20 najnowszych nie widzę”: narzędzie czytało tylko
pierwszą stronę bez filtra.

- `list_notifications` przyjmuje `topic` (te same tematy, co ikony paska:
  `services/notification_topics.py`) i `offset`. Wzmianki i czaty =
  `messages`. Lista tematów w narzędziu jest lustrem `NotificationTopic`
  (test `test_tool_topics_mirror_the_bar_topics`) — nowy temat paska = wpis
  w narzędziu.
- Prompt: „kto mnie oznaczył / moje wzmianki” → `topic=messages`, dalsze
  strony przez `offset`.
