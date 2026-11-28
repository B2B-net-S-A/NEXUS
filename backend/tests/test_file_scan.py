"""Skan antywirusowy plików z zewnątrz (clamd INSTREAM) — bez Dockera.

Udawany clamd z ``tests/_clamd_fake.py`` rozpoznaje plik testowy EICAR tak
jak prawdziwy (``Eicar-Test-Signature``). Reguła:
``docs/claude/podstawy/skan-plikow-i-altcha.md``.
"""

from __future__ import annotations

import json
import logging
import socket

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services import file_scan
from tests._clamd_fake import EICAR, eicar_docx, fake_clamd

pytestmark = pytest.mark.asyncio


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def clamd_at(monkeypatch):
    def _point(port: int) -> None:
        monkeypatch.setattr(settings, "CLAMAV_HOST", "127.0.0.1")
        monkeypatch.setattr(settings, "CLAMAV_PORT", port)
        monkeypatch.setattr(settings, "CLAMAV_TIMEOUT_SECONDS", 5.0)

    return _point


def _scan_events(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event_kind", None) == "file_scan"]


async def test_eicar_is_rejected_on_public_form_with_polish_message(clamd_at, caplog):
    from app.services.cv_text_extractor import sniff_extension_bytes

    # Plik przechodzi bramkę formatu CV, więc odrzuca go dopiero skaner.
    assert sniff_extension_bytes(eicar_docx()) == ".docx"
    async with fake_clamd() as port:
        clamd_at(port)
        with caplog.at_level(logging.INFO), pytest.raises(HTTPException) as exc:
            await file_scan.require_clean_public_upload(
                eicar_docx(), source="career_apply"
            )

    assert exc.value.status_code == 422
    assert exc.value.detail[0]["loc"] == ["body", "cv"]
    assert exc.value.detail[0]["msg"] == (
        "Nie udało się przyjąć pliku. Wyślij CV ponownie w PDF albo DOCX."
    )
    (event,) = _scan_events(caplog)
    assert event.levelno == logging.WARNING
    assert event.scan_verdict == "infected"
    assert event.signature == "Eicar-Test-Signature"
    assert event.scan_source == "career_apply"
    assert len(event.sha256) == 64
    # Pola zdarzenia dają się zapisać jako JSON (Loki, Wazuh).
    json.dumps({k: getattr(event, k) for k in ("scan_verdict", "signature", "sha256")})


async def test_clean_file_passes_public_form(clamd_at, caplog):
    async with fake_clamd() as port:
        clamd_at(port)
        with caplog.at_level(logging.INFO):
            await file_scan.require_clean_public_upload(
                b"%PDF-1.4\n" + b"x" * 200_000, source="career_apply"
            )
    (event,) = _scan_events(caplog)
    assert event.scan_verdict == "clean"


async def test_public_form_fails_closed_when_clamd_is_down(clamd_at, caplog):
    clamd_at(_free_port())
    with caplog.at_level(logging.INFO), pytest.raises(HTTPException) as exc:
        await file_scan.require_clean_public_upload(b"%PDF-1.4", source="invite_apply")

    assert exc.value.status_code == 503
    assert exc.value.detail == file_scan.MSG_UNAVAILABLE
    (event,) = _scan_events(caplog)
    assert event.levelno == logging.ERROR
    assert event.scan_verdict == "unavailable"
    assert event.scan_policy == "fail_closed"


async def test_internal_upload_fails_open_when_clamd_is_down(clamd_at, caplog):
    clamd_at(_free_port())
    with caplog.at_level(logging.INFO):
        await file_scan.require_clean_internal_upload(
            b"%PDF-1.4", source="recruiter_upload"
        )
    (event,) = _scan_events(caplog)
    assert event.levelno == logging.WARNING
    assert event.scan_policy == "fail_open"


async def test_internal_upload_still_rejects_eicar(clamd_at):
    async with fake_clamd() as port:
        clamd_at(port)
        with pytest.raises(HTTPException) as exc:
            await file_scan.require_clean_internal_upload(
                EICAR, source="recruiter_upload"
            )
    assert exc.value.status_code == 422
    assert exc.value.detail == file_scan.MSG_INTERNAL_INFECTED


async def test_large_file_is_streamed_in_chunks(clamd_at):
    payload = b"A" * (3 * 1024 * 1024) + EICAR
    async with fake_clamd() as port:
        clamd_at(port)
        result = await file_scan.scan_bytes(payload)
    assert result.verdict is file_scan.Verdict.INFECTED


async def test_scan_disabled_without_host(monkeypatch):
    monkeypatch.setattr(settings, "CLAMAV_HOST", "")
    assert (await file_scan.scan_bytes(EICAR)).verdict is file_scan.Verdict.DISABLED
    # Wyłączony skan nie blokuje (dev/CI); produkcja ma `clamav` w compose.
    await file_scan.require_clean_public_upload(EICAR, source="career_apply")
    assert await file_scan.ping() == "disabled"


async def test_ping_reports_health(clamd_at):
    async with fake_clamd() as port:
        clamd_at(port)
        assert await file_scan.ping() == "healthy"
    clamd_at(_free_port())
    assert await file_scan.ping() == "unhealthy"


@pytest.mark.parametrize(
    ("reply", "verdict", "signature"),
    [
        ("stream: OK", file_scan.Verdict.CLEAN, None),
        (
            "stream: Win.Test.EICAR_HDB-1 FOUND",
            file_scan.Verdict.INFECTED,
            "Win.Test.EICAR_HDB-1",
        ),
        ("INSTREAM size limit exceeded. ERROR", file_scan.Verdict.UNAVAILABLE, None),
        ("", file_scan.Verdict.UNAVAILABLE, None),
    ],
)
async def test_parse_reply(reply, verdict, signature):
    result = file_scan.parse_reply(reply)
    assert result.verdict is verdict
    assert result.signature == signature
