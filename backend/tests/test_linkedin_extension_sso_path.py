"""Wtyczka LinkedIn ma dzialajaca sciezke logowania w trybie SSO-only.

Wtyczka miala JEDYNA sciezke: email + haslo. Produkcja odrzuca ja od 19 lipca
(`{"detail":"Logowanie haslem jest wylaczone. Zaloguj sie przez Microsoft."}`),
a wtyczka nie miala przycisku Microsoft. Rekruter, ktory ja zainstalowal,
wyczyscil profil Chrome albo dostal zmiane roli (co bumpuje
`authorization_version` i uniewaznia refresh token), NIE MIAL jak sie
zalogowac - jedyna sciezka "jednym klknieciem z LinkedIna do bazy" byla dla
nowego uzytkownika martwa przez miesiac, bez sladu w zadnym healthchecku.

CZEGO SWIADOMIE NIE ZROBILEM: nie uzylem kont serwisowych (`X-API-Key`,
migracja 0220), mimo ze szkic naprawy je proponowal. Ich wlasny docstring mowi
"nieosobowa tozsamosc automatyzacji (cron, CI, skrypt operacyjny)", konto NIE
MA roli, a CRUD stoi za `AdminUser`. Dla wtyczki uzywanej przez ludzi znaczyloby
to: jedno konto per rekruter zakladane przez admina, dystrybucja kluczy,
rotacja co 90 dni - i utrata atrybucji, bo konto serwisowe nie jest uzytkownikiem.
Backend mial juz komplet SSO dla przegladarki; brakowalo wylacznie mostu.
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"


def test_backend_sso_endpoints_the_bridge_depends_on_exist():
    """Most nie dziala bez tych trzech - i to jedyne, czego wymaga od backendu."""
    src = (ROOT / "backend/app/api/auth_microsoft.py").read_text(encoding="utf-8")
    for route in ('"/authorize"', '"/callback"', '"/exchange"'):
        assert route in src, f"brak {route} - most SSO nie ma z czym rozmawiac"


def test_extension_has_a_login_path_that_is_not_a_password():
    opts = (EXT / "src/options/options.html").read_text(encoding="utf-8")
    assert 'id="btn-sso"' in opts, (
        "brak przycisku Microsoft - dla nowego uzytkownika wtyczka pozostaje "
        "martwa, bo logowanie haslem jest na produkcji wylaczone"
    )


def test_bridge_content_script_is_scoped_to_the_callback_path_only():
    """Most slucha na JEDNEJ stronie, nie na calej aplikacji."""
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    bridges = [
        cs
        for cs in manifest.get("content_scripts", [])
        if any("sso-bridge" in j for j in cs.get("js", []))
    ]
    assert bridges, "content script mostu nie jest zarejestrowany w manifescie"
    for cs in bridges:
        for pattern in cs["matches"]:
            assert "/login/microsoft/callback" in pattern, (
                f"most nasluchuje na '{pattern}' - powierzchnia szersza niz "
                "jedna strona callbacku"
            )


def test_bridge_verifies_origin_and_source():
    """Bez tych trzech warunkow kazdy skrypt na stronie moglby podac tokeny."""
    js = (EXT / "src/content/sso-bridge.js").read_text(encoding="utf-8")
    assert "event.source !== window" in js, "brak sprawdzenia zrodla wiadomosci"
    assert "event.origin !== window.location.origin" in js, "brak sprawdzenia origin"
    assert 'data.source !== "nexus-app"' in js, "brak sprawdzenia nadawcy"


def test_app_hands_over_session_only_when_the_extension_started_the_login():
    """Bez markera SSO provisionowaloby wtyczke po cichu przy KAZDYM logowaniu."""
    cb = (ROOT / "frontend/src/app/login/microsoft/callback/page.tsx").read_text(
        encoding="utf-8"
    )
    assert 'sessionStorage.getItem("nexus_ext_login")' in cb, (
        "callback oddaje sesje bez sprawdzenia, czy logowanie zaczela wtyczka"
    )
    assert 'sessionStorage.removeItem("nexus_ext_login")' in cb, (
        "marker nie jest kasowany - kolejne logowanie tez oddaloby sesje"
    )
    login = (ROOT / "frontend/src/app/login/page.tsx").read_text(encoding="utf-8")
    assert 'sessionStorage.setItem("nexus_ext_login"' in login, (
        "strona logowania nie zapisuje markera, wiec callback nigdy go nie zobaczy"
    )


def test_postmessage_targets_own_origin_not_wildcard():
    """`postMessage(..., '*')` rozeslaloby tokeny do kazdej ramki na stronie."""
    cb = (ROOT / "frontend/src/app/login/microsoft/callback/page.tsx").read_text(
        encoding="utf-8"
    )
    i = cb.index("NEXUS_EXT_AUTH")
    window_ = cb[i : i + 600]
    assert "window.location.origin" in window_, "brak ograniczenia targetOrigin"
    assert '"*"' not in window_, "targetOrigin ustawiony na wildcard"
