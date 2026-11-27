"""Zakresy adresów Cloudflare i odczyt ``CF-Connecting-IP`` tylko od nich.

Po włączeniu proxy Cloudflare dla API połączenie do Traefika otwiera edge
Cloudflare, więc adres widziany przez nasze proxy jest adresem edge'a.
Prawdziwy klient jest wtedy w ``CF-Connecting-IP``, który Cloudflare zawsze
nadpisuje. Ten sam nagłówek wysłany wprost na serwer (z pominięciem Cloudflare)
ustawia sam klient, dlatego ufamy mu wyłącznie, gdy połączenie przyszło z
zakresów poniżej. → ``docs/claude/podstawy/cloudflare-przed-api.md``

Lista z https://www.cloudflare.com/ips-v4 i /ips-v6, pobrana 27.11.2026.
Cloudflare zmienia ją rzadko i zapowiada zmiany; tę samą listę trzeba wtedy
poprawić w zaporze serwera.
"""

import ipaddress
from typing import Optional, Union

_Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

CLOUDFLARE_RANGES = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def _parse(value: Optional[str]) -> Optional[_Address]:
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def is_cloudflare_address(value: Optional[str]) -> bool:
    address = _parse(value)
    return address is not None and any(address in net for net in CLOUDFLARE_RANGES)


def cloudflare_client_ip(
    seen: Optional[str], cf_connecting_ip: Optional[str]
) -> Optional[str]:
    """Adres klienta z ``CF-Connecting-IP``, gdy ``seen`` to edge Cloudflare.

    ``seen`` to adres, który zobaczyło nasze proxy (prawy wpis XFF albo peer).
    Zwraca ``None``, gdy połączenie nie przyszło od Cloudflare albo nagłówek
    nie jest adresem IP — wtedy wołający zostaje przy ``seen``.
    """
    if not is_cloudflare_address(seen):
        return None
    client = _parse(cf_connecting_ip)
    return str(client) if client is not None else None
