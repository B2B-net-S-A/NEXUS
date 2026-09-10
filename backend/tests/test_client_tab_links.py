"""Linki powiadomień do profilu klienta muszą używać kluczy zakładek frontu.

``/clients/{id}?tab=…`` jest load-bearing: nieznany klucz nie daje błędu,
tylko cicho otwiera zakładkę „Profil" (``isClientTab`` w
``frontend/src/lib/client-tab.ts``), więc powiadomienie prowadzi donikąd.
Do 10.09.2026 tak kończyły się alerty „Nowy kontraktor" z maila zamówień
(``?tab=orders``) i wszystkie powiadomienia umów ramowych
(``?tab=framework-contracts``).
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CLIENT_TAB_TS = BACKEND.parent / "frontend" / "src" / "lib" / "client-tab.ts"
_LINK = re.compile(r"/clients/\{[^}]+\}\?tab=([A-Za-z0-9_-]+)")


def _frontend_tab_keys() -> set[str]:
    source = CLIENT_TAB_TS.read_text(encoding="utf-8")
    block = re.search(r"CLIENT_TAB_KEYS[^=]*=\s*\[(.*?)\]", source, re.S)
    assert block, "Nie znalazłem CLIENT_TAB_KEYS w client-tab.ts"
    return set(re.findall(r'"([a-z-]+)"', block.group(1)))


def test_backend_client_links_use_real_frontend_tab_keys() -> None:
    keys = _frontend_tab_keys()
    assert {"zamowienia", "umowy-ramowe"} <= keys
    offenders = []
    seen = 0
    for path in sorted((BACKEND / "app").rglob("*.py")):
        for match in _LINK.finditer(path.read_text(encoding="utf-8")):
            seen += 1
            if match.group(1) not in keys:
                offenders.append(f"{path.relative_to(BACKEND)}: ?tab={match.group(1)}")
    assert seen, "Wzorzec linku przestał cokolwiek dopasowywać"
    assert not offenders, offenders
