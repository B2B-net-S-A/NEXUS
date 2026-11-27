"""Strażnik: wszystkie wywołania białej listy MF idą pod adres z jednego miejsca.

Stary host ``wl-api.mf.gov.pl`` (i testowy ``wl-test.mf.gov.pl``) MF obsługuje
tylko do 1.12.2026. Gdyby któryś moduł znów wpisał adres na sztywno, po tej
dacie „Pobierz z rejestru”, sprawdzenie rachunku albo noc Sprzedaży przestałyby
działać bez czerwonego testu.
"""

from pathlib import Path

from app.services.b2b_contract_generator import registry_lookup
from app.services.hr import white_list
from app.services.mf_white_list_hosts import MF_WHITE_LIST_LIVE, MF_WHITE_LIST_TEST
from app.services.sales import registry

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_moduly_biorą_host_z_jednej_stalej() -> None:
    assert MF_WHITE_LIST_LIVE == "https://wykazpodatnikowvat.mf.gov.pl"
    assert MF_WHITE_LIST_TEST == "https://wykazpodatnikowvat-test.mf.gov.pl"
    assert registry_lookup._WL_BASE == MF_WHITE_LIST_LIVE
    assert registry.MF_BASE == MF_WHITE_LIST_LIVE
    assert white_list.BASE_URLS == {
        "test": MF_WHITE_LIST_TEST,
        "live": MF_WHITE_LIST_LIVE,
    }


def test_w_kodzie_nie_ma_starego_hosta() -> None:
    stale = [
        f"{path.relative_to(APP_DIR)}"
        for path in APP_DIR.rglob("*.py")
        if "://wl-api.mf.gov.pl" in (text := path.read_text(encoding="utf-8"))
        or "://wl-test.mf.gov.pl" in text
    ]
    assert stale == []
