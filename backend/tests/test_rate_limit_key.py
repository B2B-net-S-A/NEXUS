"""Regresja: wspólny kubełek limitu dla całej firmy.

Zgłoszenie (Wiktoria Denka): „mam problem z zalogowaniem do Nexusa. Pokazuje ten
błąd - Request failed with status code 429".

Mechanizm: backend stoi za Traefikiem, a ``entrypoint.sh`` startuje uvicorna bez
``--forwarded-allow-ips``. Domyślna allow-lista uvicorna to ``127.0.0.1``, więc
przy peerze z sieci dockerowej ``X-Forwarded-For`` jest ignorowany i
``request.client.host`` to adres TRAEFIKA — ten sam dla każdego użytkownika.
Klucz limitu był więc globalny: ``/api/auth/microsoft/authorize`` miał 10 zapytań
na minutę ŁĄCZNIE dla wszystkich, więc wystarczyło, że w tej samej minucie
logowało się kilka osób.

Kontrakt: klucz limitu to prawdziwy IP klienta, brany ze skrajnie PRAWEGO wpisu
``X-Forwarded-For`` (dopisanego przez nasze proxy), a nie z lewego — lewe wpisy
może dopisać klient i podszyć się pod cudzy klucz albo ominąć limit logowania.
"""

from types import SimpleNamespace
from typing import Dict, Optional

from app.core.rate_limit import client_ip_key, user_or_ip_key
from app.core.security import create_access_token, create_refresh_token


def _request(headers: Optional[Dict[str, str]], peer: Optional[str] = "172.18.0.5"):
    """Minimalny stub Starlette Request — key_func czyta tylko headers/client."""
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=peer) if peer else None,
    )


def test_different_clients_behind_proxy_get_different_keys():
    """Sedno buga: dwie osoby zza tego samego Traefika != jeden kubełek."""
    a = client_ip_key(_request({"x-forwarded-for": "203.0.113.7"}))
    b = client_ip_key(_request({"x-forwarded-for": "198.51.100.9"}))

    assert a == "203.0.113.7"
    assert b == "198.51.100.9"
    assert a != b


def test_takes_rightmost_entry_not_client_spoofable_left():
    """Proxy dokleja adres, który FAKTYCZNIE zobaczyło — bierzemy ten."""
    key = client_ip_key(_request({"x-forwarded-for": "1.1.1.1, 203.0.113.7"}))

    # 1.1.1.1 to wpis podrzucony przez klienta — nie może zostać kluczem,
    # inaczej każdy omija limit logowania zmieniając nagłówek.
    assert key == "203.0.113.7"


def test_spoofed_header_cannot_forge_another_users_key():
    """Podszycie się pod cudzy klucz przez lewy wpis nie działa."""
    victim = client_ip_key(_request({"x-forwarded-for": "203.0.113.7"}))
    attacker = client_ip_key(_request({"x-forwarded-for": "203.0.113.7, 198.51.100.9"}))

    assert victim != attacker


def test_falls_back_to_peer_without_forwarded_header():
    """Bez proxy (testy, ruch wewnętrzny) klucz to adres peera."""
    assert client_ip_key(_request(None, peer="127.0.0.1")) == "127.0.0.1"


def test_handles_missing_client_and_blank_entries():
    """Nie wywalamy się na braku client ani na pustych wpisach w nagłówku."""
    assert client_ip_key(_request(None, peer=None)) == "127.0.0.1"
    assert (
        client_ip_key(_request({"x-forwarded-for": "203.0.113.7,  , "}))
        == "203.0.113.7"
    )


def test_user_key_is_the_access_token_subject_not_the_office_ip():
    """Biuro wychodzi jednym adresem (NAT): kubełek per zalogowany użytkownik."""
    office = {"x-forwarded-for": "203.0.113.7"}
    first = user_or_ip_key(
        _request(
            {
                **office,
                "authorization": f"Bearer {create_access_token(41, 'recruiter')}",
            }
        )
    )
    second = user_or_ip_key(
        _request(
            {
                **office,
                "authorization": f"Bearer {create_access_token(42, 'recruiter')}",
            }
        )
    )

    assert (first, second) == ("user:41", "user:42")


def test_user_key_falls_back_to_the_ip_without_a_valid_access_token():
    """Brak tokena, śmieć, inny schemat albo token odświeżania → klucz po IP."""
    office = {"x-forwarded-for": "203.0.113.7"}
    for extra in (
        {},
        {"authorization": "Bearer nie-jwt"},
        {"authorization": "Basic dXNlcjpwYXNz"},
        {"authorization": f"Bearer {create_refresh_token(41)}"},
    ):
        assert user_or_ip_key(_request({**office, **extra})) == "203.0.113.7", extra


# --- Cloudflare przed Traefikiem (plan przejścia API na proxy, 27.11.2026) ---
# Z proxy Cloudflare prawy wpis ``X-Forwarded-For`` to adres EDGE'A Cloudflare,
# wspólny dla wszystkich ludzi z tego samego PoP-a (WAW). Bez czytania
# ``CF-Connecting-IP`` wróciłby bug z #824: jeden kubełek logowania dla firmy.
_CF_EDGE_V4 = "162.158.102.17"  # w 162.158.0.0/15
_CF_EDGE_V6 = "2a06:98c0:3600::103"  # w 2a06:98c0::/29


def test_cloudflare_edge_peer_uses_cf_connecting_ip():
    """Dwie osoby przez ten sam edge Cloudflare != jeden kubełek."""
    a = client_ip_key(
        _request({"x-forwarded-for": _CF_EDGE_V4, "cf-connecting-ip": "203.0.113.7"})
    )
    b = client_ip_key(
        _request({"x-forwarded-for": _CF_EDGE_V4, "cf-connecting-ip": "198.51.100.9"})
    )

    assert (a, b) == ("203.0.113.7", "198.51.100.9")


def test_cloudflare_ipv6_edge_is_recognised():
    key = client_ip_key(
        _request(
            {
                "x-forwarded-for": f"203.0.113.7, {_CF_EDGE_V6}",
                "cf-connecting-ip": "203.0.113.7",
            }
        )
    )

    assert key == "203.0.113.7"


def test_cf_connecting_ip_from_outside_cloudflare_is_ignored():
    """Ktoś omija Cloudflare i łączy się wprost: nagłówek jest jego, nie edge'a."""
    key = client_ip_key(
        _request({"x-forwarded-for": "198.51.100.9", "cf-connecting-ip": "203.0.113.7"})
    )

    assert key == "198.51.100.9"


def test_spoofed_left_entry_cannot_fake_a_cloudflare_peer():
    """Zakres Cloudflare liczy się tylko jako wpis dopisany przez Traefika (prawy)."""
    key = client_ip_key(
        _request(
            {
                "x-forwarded-for": f"{_CF_EDGE_V4}, 198.51.100.9",
                "cf-connecting-ip": "203.0.113.7",
            }
        )
    )

    assert key == "198.51.100.9"


def test_cloudflare_peer_without_usable_header_keeps_the_edge_address():
    """Brak albo śmieć w ``CF-Connecting-IP`` → adres edge'a, nigdy wyjątek."""
    for extra in ({}, {"cf-connecting-ip": ""}, {"cf-connecting-ip": "nie-ip"}):
        key = client_ip_key(_request({"x-forwarded-for": _CF_EDGE_V4, **extra}))
        assert key == _CF_EDGE_V4, extra


def test_direct_cloudflare_peer_without_traefik_header():
    """Peer TCP z zakresu Cloudflare bez XFF (np. port wystawiony wprost)."""
    key = client_ip_key(_request({"cf-connecting-ip": "203.0.113.7"}, peer=_CF_EDGE_V4))

    assert key == "203.0.113.7"
