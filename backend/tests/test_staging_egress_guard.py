"""Zapora wyjścia sieciowego stagingu (``app/core/staging.py``).

Połączenie do hosta spoza listy ma paść, zanim cokolwiek wyjdzie z laptopa —
testy nie potrzebują więc sieci: zablokowane żądanie nie dochodzi do gniazda.
"""

from __future__ import annotations

import asyncio
import smtplib

import httpx
import pytest
import urllib3

from app.core.staging import (
    StagingEgressBlocked,
    host_allowed,
    install_egress_guard,
    uninstall_egress_guard,
)


@pytest.mark.parametrize(
    "host",
    [
        "postgres",
        "qdrant",
        "mailpit",
        "localhost",
        "127.0.0.1",
        "[::1]",
        "10.0.0.5",
        "host.docker.internal",
        "nexus.staging.localhost",
        "api.anthropic.com",
        "API.VOYAGEAI.COM.",
    ],
)
def test_local_and_ai_hosts_are_allowed(host):
    assert host_allowed(host)


@pytest.mark.parametrize(
    "host",
    [
        "graph.microsoft.com",
        "login.microsoftonline.com",
        "api.nexus.b2bnetwork.pl",
        "91.99.199.112",
        "nbg1.your-objectstorage.com",
        "hooks.slack.com",
        "my.cloudtalk.io",
        "",
        None,
    ],
)
def test_external_hosts_are_refused(host):
    assert not host_allowed(host)


def test_extra_hosts_extend_the_list():
    assert host_allowed("minio.example.org", extra=["minio.example.org"])
    assert not host_allowed("minio.example.org")


@pytest.fixture
def guard():
    install_egress_guard()
    yield
    uninstall_egress_guard()


def test_httpx_sync_and_async_refuse_external_host(guard):
    with httpx.Client() as client:
        with pytest.raises(httpx.ConnectError, match="staging"):
            client.get("https://graph.microsoft.com/v1.0/me")

    async def call() -> None:
        async with httpx.AsyncClient() as client:
            await client.post("https://hooks.slack.com/services/x", json={})

    with pytest.raises(httpx.ConnectError, match="staging"):
        asyncio.run(call())


def test_urllib3_refuses_external_host(guard):
    pool = urllib3.HTTPSConnectionPool("nbg1.your-objectstorage.com")
    with pytest.raises(StagingEgressBlocked):
        pool.urlopen("GET", "/")


def test_smtp_refuses_external_host(guard):
    with pytest.raises(StagingEgressBlocked):
        smtplib.SMTP("smtp.office365.com", 587, timeout=1)


def test_uninstall_restores_original_methods(guard):
    patched = httpx.AsyncHTTPTransport.handle_async_request
    uninstall_egress_guard()
    assert httpx.AsyncHTTPTransport.handle_async_request is not patched
    install_egress_guard()
