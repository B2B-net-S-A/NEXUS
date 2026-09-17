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


# ── Pozostałe strony z `?tab=` (audyt narzędzi rekrutera 17.09.2026) ─────────
#
# Ten sam defekt żył poza profilem klienta: wzmianka w notatce linkowała do
# `?tab=notes` (klucz nieznany profilowi kandydata), „Email odrzucenia
# niewysłany" do nieistniejącej trasy `/settings/integrations`, raport
# PowerCalling do `/reports`. Nieznany klucz zawsze kończy się cichym
# wylądowaniem na zakładce domyślnej, więc bez tego testu nikt tego nie widzi.

FRONTEND = BACKEND.parent / "frontend" / "src"
JOB_PAGE_TSX = FRONTEND / "app" / "jobs" / "[id]" / "page.tsx"
CANDIDATE_NAV_TS = (
    FRONTEND / "components" / "v2" / "pages" / "candidate-profile-navigation.ts"
)
SETTINGS_TAB_TS = FRONTEND / "lib" / "settings-tab.ts"
INSIGHTS_VIEW_TSX = FRONTEND / "components" / "insights" / "InsightsView.tsx"


def _array_literal(source: str, name: str) -> set[str]:
    block = re.search(rf"{name}[^=]*=\s*\[(.*?)\]", source, re.S)
    assert block, f"Nie znalazłem tablicy {name}"
    return set(re.findall(r'"([a-z-]+)"', block.group(1)))


def _object_keys(source: str, anchor: str) -> set[str]:
    start = source.find(anchor)
    assert start >= 0, f"Nie znalazłem {anchor}"
    body = source[source.index("{", source.index("=", start)) :]
    body = body[: body.index("};")]
    return set(re.findall(r'^\s*"?([a-z][a-z-]*)"?\s*:', body, re.M))


def _job_tab_keys() -> set[str]:
    source = JOB_PAGE_TSX.read_text(encoding="utf-8")
    return _array_literal(source, "JOB_DETAIL_TABS") | _object_keys(
        source, "JOB_DETAIL_TAB_ALIASES"
    )


def _candidate_tab_keys() -> set[str]:
    source = CANDIDATE_NAV_TS.read_text(encoding="utf-8")
    return _array_literal(source, "PROFILE_SECTIONS") | _object_keys(
        source, "const legacy"
    )


def _candidate_activity_keys() -> set[str]:
    source = CANDIDATE_NAV_TS.read_text(encoding="utf-8")
    return _array_literal(source, "ACTIVITY_VIEWS")


def _settings_tab_keys() -> set[str]:
    return _array_literal(
        SETTINGS_TAB_TS.read_text(encoding="utf-8"), "SETTINGS_TAB_KEYS"
    )


def _insights_tab_keys() -> set[str]:
    source = INSIGHTS_VIEW_TSX.read_text(encoding="utf-8")
    block = re.search(r"const TABS[^=]*=\s*\[(.*?)\];", source, re.S)
    assert block, "Nie znalazłem TABS w InsightsView.tsx"
    ids = set(re.findall(r'id:\s*"([a-z-]+)"', block.group(1)))
    return ids | _object_keys(source, "LEGACY_TAB_ALIASES")


_PAGE_LINKS = {
    "jobs": re.compile(r"/jobs/\{[^}]+\}\?tab=([A-Za-z0-9_-]+)"),
    "candidates": re.compile(r"/candidates/\{[^}]+\}\?tab=([A-Za-z0-9_-]+)"),
    "settings": re.compile(r"/settings\?tab=([A-Za-z0-9_-]+)"),
    "insights": re.compile(r"/insights\?tab=([A-Za-z0-9_-]+)"),
}
_CANDIDATE_ACTIVITY = re.compile(
    r"/candidates/\{[^}]+\}\?[^\"'\s]*activity=([A-Za-z0-9_-]+)"
)


def test_frontend_tab_key_sources_are_parsed() -> None:
    # Strażnik parsera: zmiana kształtu pliku po stronie frontu nie może
    # zamienić testu w „zawsze zielony" przez pusty zbiór kluczy.
    assert {
        "pipeline",
        "chat",
        "champion",
        "champion-profile",
        "similar",
    } <= _job_tab_keys()
    assert {"summary", "activity", "chat", "notes", "notatki"} <= _candidate_tab_keys()
    assert {"timeline", "notes", "calls", "chat"} <= _candidate_activity_keys()
    assert {"integracje", "administracja"} <= _settings_tab_keys()
    assert {
        "rekrutacja",
        "delivery-lead",
        "rada",
        "klienci",
        "zarzad",
    } <= _insights_tab_keys()


def test_backend_page_links_use_real_frontend_tab_keys() -> None:
    known = {
        "jobs": _job_tab_keys(),
        "candidates": _candidate_tab_keys(),
        "settings": _settings_tab_keys(),
        "insights": _insights_tab_keys(),
    }
    activity_keys = _candidate_activity_keys()
    offenders: list[str] = []
    seen = {page: 0 for page in known}
    for path in sorted((BACKEND / "app").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        where = path.relative_to(BACKEND)
        for page, pattern in _PAGE_LINKS.items():
            for match in pattern.finditer(text):
                seen[page] += 1
                if match.group(1) not in known[page]:
                    offenders.append(f"{where}: /{page}?tab={match.group(1)}")
        for match in _CANDIDATE_ACTIVITY.finditer(text):
            if match.group(1) not in activity_keys:
                offenders.append(f"{where}: activity={match.group(1)}")
    assert all(seen.values()), f"Wzorzec linku przestał cokolwiek dopasowywać: {seen}"
    assert not offenders, offenders


def test_page_link_check_rejects_unknown_key() -> None:
    # Negatywny przypadek: klucz, którego front nie zna, musi zostać wyłapany.
    assert "notes-legacy-typo" not in _candidate_tab_keys()
    assert _PAGE_LINKS["candidates"].search(
        'f"/candidates/{cid}?tab=notes-legacy-typo"'
    )
    assert "integrations" not in _settings_tab_keys()
