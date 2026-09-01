"""SSRF regression tests for the iCal import fetcher (Module 6 finding P0.8).

The importer accepted any http/https/webcal URL, followed redirects with no
IP validation, no size cap, and echoed the URL back. It could be pointed at
loopback / RFC1918 / cloud-metadata addresses. Containment: an https-only,
public-IP-validated, size-capped fetcher that never returns the URL.
"""

import socket

import pytest

from app.services import ical_import as ii


def _addrinfo(ip: str):
    """Shape a socket.getaddrinfo result for a single address."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]


def test_is_public_ip_accepts_public():
    assert ii._is_public_ip("8.8.8.8")
    assert ii._is_public_ip("2001:4860:4860::8888")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC1918
        "192.168.1.10",  # RFC1918
        "172.16.0.1",  # RFC1918
        "169.254.169.254",  # cloud metadata (link-local)
        "::1",  # IPv6 loopback
        "fd00::1",  # IPv6 ULA
        "0.0.0.0",  # unspecified
    ],
)
def test_is_public_ip_rejects_internal(ip):
    assert not ii._is_public_ip(ip)


@pytest.mark.asyncio
async def test_assert_host_is_public_rejects_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("10.1.2.3"))
    with pytest.raises(ii.ICalFetchError):
        await ii._assert_host_is_public("internal.example")


@pytest.mark.asyncio
async def test_assert_host_is_public_allows_public(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: _addrinfo("93.184.216.34")
    )
    await ii._assert_host_is_public("example.com")  # must not raise


@pytest.mark.asyncio
async def test_fetch_rejects_non_https():
    with pytest.raises(ii.ICalFetchError):
        await ii._fetch_ical_safely("http://example.com/cal.ics")


@pytest.mark.asyncio
async def test_fetch_rejects_private_host(monkeypatch):
    # Even an https URL is refused when the host resolves to a private address —
    # before any socket connection is attempted.
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("127.0.0.1"))
    with pytest.raises(ii.ICalFetchError):
        await ii._fetch_ical_safely("https://localhost/cal.ics")


@pytest.mark.asyncio
async def test_import_url_masks_host_and_records_error(monkeypatch):
    """A rejected feed leaves no full URL in the result and does no writes."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("10.0.0.9"))

    class _FailDB:
        async def scalar(self, *a, **k):  # pragma: no cover - must never run
            raise AssertionError("no DB access should happen on a rejected feed")

    res = await ii.import_ical_url(
        _FailDB(),
        "https://secret-host.example/private/feed.ics?token=abc123",
        creator_id=1,
    )
    assert res.errors == 1
    assert res.events_fetched == 0
    # source_url is masked to the host — no path, no token.
    assert res.source_url == "secret-host.example"
    assert "token" not in " ".join(res.error_samples)
    assert "feed.ics" not in " ".join(res.error_samples)
