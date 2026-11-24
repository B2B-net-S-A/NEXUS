"""Robot Cpro: szkice ofert w portalu Nordei (nordea.onevms.se) bez Grok Bota.

Osobny kontener (``Dockerfile.cpro-robot``, usługa ``cpro-robot`` w compose).
NEXUS budzi go tym samym webhookiem co dawniej rutynę Grok Bota
(``GROK_BOT_CPRO_WEBHOOK_URL``); robot pobiera zlecenie, CV i oddaje raport
trasami biegu z tokenem (``api/integrations_cpro_bot.py``).

Pakiet nie importuje ``app`` — obraz robota nie ma zależności backendu.
Reguła: ``docs/claude/integracje/cpro-bot-grok.md``.
"""
