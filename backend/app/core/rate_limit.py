"""Rate limiter shared across routers.

Uses slowapi's `Limiter`. The shared instance is attached to the FastAPI
app state in ``main.py``; individual routers import ``limiter`` from here
and apply decorators like ``@limiter.limit("5/minute")``.

Klucz limitu to **prawdziwy IP klienta**, wyciągany z ``X-Forwarded-For``.

Dlaczego nie samo ``get_remote_address``: backend stoi za Traefikiem (Coolify),
a ``entrypoint.sh`` startuje ``uvicorn`` bez ``--forwarded-allow-ips``. Domyślna
allow-lista uvicorna to ``127.0.0.1``, więc przy peerze z sieci dockerowej
(172.x) uvicorn **ignoruje** ``X-Forwarded-For`` i ``request.client.host`` jest
adresem TRAEFIKA — identycznym dla wszystkich. Efekt: cały ruch świata dzielił
JEDEN kubełek, więc ``/api/auth/microsoft/authorize`` miał 10 zapytań na minutę
łącznie dla całej firmy. Ludzie dostawali 429 przy logowaniu przez sam fakt, że
ktoś inny logował się w tej samej minucie (zgłoszenie: Wiktoria Denka). Był to
też darmowy DoS — dowolny anonim mógł zablokować logowanie wszystkim, paląc
limit z jednego hosta.

Zweryfikowane empirycznie na uvicorn 0.34.0 (wersja z requirements.txt):
peer 127.0.0.1 → XFF uszanowany; peer spoza loopbacka → XFF zignorowany, klucz
= IP peera, ten sam dla różnych XFF.

Bierzemy wpis **skrajnie PRAWY**, nie lewy. Proxy dokleja na koniec adres, który
faktycznie zobaczyło, więc prawy wpis pochodzi od naszego Traefika, a lewe mogą
być dopisane przez klienta. Uvicorn z ``--forwarded-allow-ips="*"`` bierze wpis
skrajnie lewy, czyli ten kontrolowany przez klienta — dlatego NIE naprawiamy
tego flagą uvicorna, bo dałaby trywialne omijanie limitu logowania przez
podrzucenie własnego nagłówka.

UWAGA na przyszłość: to jest poprawne dla łańcucha ``klient → Traefik → backend``.
``api.nexus.dynaminds.pl`` jest dziś gray-cloud (poza proxy Cloudflare —
sprawdzone: brak nagłówka ``cf-ray``). Gdyby ktoś przełączył ten host na orange
cloud, doszedłby hop i prawy wpis stałby się adresem edge'a Cloudflare — wtedy
trzeba czytać ``CF-Connecting-IP``.
"""

from typing import Optional

from slowapi import Limiter
from starlette.requests import Request

# Nagłówki, którym ufamy — w kolejności pierwszeństwa.
_FORWARDED_HEADER = "x-forwarded-for"


def _peer_address(request: Request) -> str:
    """Adres bezpośredniego peera (za proxy: adres proxy)."""
    client = request.client
    return client.host if client and client.host else "127.0.0.1"


def client_ip_key(request: Request) -> str:
    """Klucz limitu = prawdziwy IP klienta.

    Zwraca skrajnie PRAWY wpis z ``X-Forwarded-For`` (dopisany przez nasze
    proxy), a gdy nagłówka nie ma — adres bezpośredniego peera. Dzięki temu
    limity działają per użytkownik/sieć, a nie globalnie dla całej instancji.
    """
    forwarded: Optional[str] = request.headers.get(_FORWARDED_HEADER)
    if forwarded:
        # "klient-podrobiony, prawdziwy-klient" → bierzemy ostatni niepusty.
        candidates = [part.strip() for part in forwarded.split(",")]
        for value in reversed(candidates):
            if value:
                return value
    return _peer_address(request)


# ``default_limits=[]`` jest ŚWIADOME i nie wolno go "naprawić" w tym pliku.
#
# W slowapi limity globalne (``_application_limits``) sprawdza wyłącznie
# ``SlowAPIMiddleware`` — ``Limiter._check_request_limit`` wchodzi w nie tylko
# przy ``in_middleware=True``. Ścieżka dekoratora (``@limiter.limit``) czyta
# ``_route_limits`` i globalne pomija. ``app/main.py`` montuje wyłącznie
# ``SecurityHeadersMiddleware``, ``LegacyStatsDeprecationMiddleware`` i CORS —
# ``SlowAPIMiddleware`` NIE jest tam dodany.
#
# Skutek: wpisanie tutaj np. ``["60/minute"]`` daje konfigurację, która wygląda
# jak ochrona całej aplikacji, a nie limituje NICZEGO. To najgorszy z możliwych
# stanów — gorszy niż pusta lista, bo pustej nikt nie bierze za zabezpieczenie.
#
# Kto chce limitu globalnego, musi w JEDNYM commicie dołożyć obie rzeczy:
# ``app.add_middleware(SlowAPIMiddleware)`` ORAZ tę listę. Pilnuje tego
# ``tests/test_rate_limit_default_limits_not_inert.py``.
#
# Kontekst historyczny (#74): audyt wskazywał tę linię jako powód, dla którego
# nielimitowane ``/openapi.json`` mogło zapchać jednoprocesową pętlę zdarzeń.
# Naprawą było USUNIĘCIE tej trasy poza dev-em (``main.py``, ``openapi_url=None``
# przy ``DEBUG=false``), a nie limit globalny — trasa wbudowana FastAPI i tak
# nie ma dekoratora, więc dekoratorowa ścieżka slowapi nigdy by jej nie objęła.
limiter = Limiter(key_func=client_ip_key, default_limits=[])
