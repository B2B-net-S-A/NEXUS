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

from app.core.rate_limit import client_ip_key


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
    attacker = client_ip_key(
        _request({"x-forwarded-for": "203.0.113.7, 198.51.100.9"})
    )

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
