"""Wydatki na AI: co jest deklarowane, co jest oznaczone i co zatrzymuje kill-switch.

Trzy klasy defektów, każda cicha:

* wywołanie LLM obciążone kwotą, ale NIEZADEKLAROWANE — liczy się poprawnie,
  a na granicy providera loguje się jako „UNGATED", więc detektor, na którym
  stoi `AI_QUOTA_STRICT`, składa się głównie z fałszywych alarmów;
* awaria dostawcy zwijana po cichu do szablonu ze zmyślonymi widełkami
  płacowymi, w kształcie odpowiedzi nie do odróżnienia od wyjścia AI;
* powierzchnia Claude'a całkowicie poza systemem kwot, której główny wyłącznik
  AI nie zatrzymuje.

Generator ogłoszeń (`ai_writer`, od 12.10.2026 `services/job_ad`) ma te
kontrakty w `test_job_ad_generate.py`.
"""

from __future__ import annotations

# ── MINDY: własny kubełek kwoty (`mindy_chat`) ───────────────────────────────


def test_mindy_endpoints_are_gone() -> None:
    """MINDY zastąpił Jarvis (0330). Jej dwa płatne endpointy nie mogą wrócić
    cichym przywróceniem routera — asystent AI ma jedną powierzchnię,
    `/api/jarvis/*`, za kwotą `jarvis`."""
    from app.main import app
    from tests._route_introspection import iter_api_routes

    paths = {path for path, _route in iter_api_routes(app)}
    assert not any(path.startswith("/api/dynareporter/mindy") for path in paths)
    assert "/api/jarvis/chat" in paths
