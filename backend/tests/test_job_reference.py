"""Tests for auto-generated job reference numbers (Traffit parity).

Unit tests cover the pure helpers (initials derivation, formatting, seq
parsing). Integration tests hit POST /api/jobs to assert a reference is
generated and that the per-(client, year) sequence increments.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from httpx import AsyncClient

from app.services.job_reference import (
    client_initials,
    format_reference,
    _parse_seq,
)


# ── Unit: client_initials ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Bank Pocztowy", "BP"),
        ("ATOS", "ATOS"),
        ("Allegro", "ALLE"),  # single word → first 4 chars
        ("NTT Data", "ND"),
        ("Roche - Square One", "RSO"),  # dash word drops to empty → skipped
        ("mLeasing", "MLEA"),
        (None, "NXS"),
        ("", "NXS"),
        ("   ", "NXS"),
    ],
)
def test_client_initials(name: Optional[str], expected: str) -> None:
    assert client_initials(name) == expected


def test_client_initials_caps_at_four() -> None:
    # 5-word client → only first 4 initials
    assert client_initials("Alpha Beta Gamma Delta Epsilon") == "ABGD"


def test_client_initials_strips_non_alnum() -> None:
    assert client_initials("A&B / C") == "AC"


# ── Unit: format_reference ───────────────────────────────────────────────────


def test_format_reference_zero_pads() -> None:
    assert format_reference("BP", 7, 2026) == "BP/007/2026"
    assert format_reference("ATOS", 123, 2026) == "ATOS/123/2026"
    assert format_reference("NXS", 1, 2025) == "NXS/001/2025"


# ── Unit: _parse_seq ─────────────────────────────────────────────────────────


def test_parse_seq_extracts_middle_segment() -> None:
    assert _parse_seq("BP/007/2026") == 7
    assert _parse_seq("ATOS/123/2026") == 123


def test_parse_seq_ignores_traffit_imported_shape() -> None:
    # Traffit refs have 5 segments (71/5/2026/AT/4537) — not our namespace.
    assert _parse_seq("71/5/2026/AT/4537") is None
    assert _parse_seq(None) is None
    assert _parse_seq("garbage") is None
    assert _parse_seq("BP/notanumber/2026") is None


# ── Integration: POST /api/jobs auto-generates a reference ───────────────────


async def _cleanup_jobs(job_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for jid in job_ids:
            await db.execute(delete(Job).where(Job.id == jid))
        await db.commit()


@pytest.mark.asyncio
async def test_post_job_generates_reference(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """A job created without a reference gets one auto-assigned (no client → NXS)."""
    created: list[int] = []
    try:
        resp = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={"title": f"Ref test {uuid.uuid4().hex[:6]}"},
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        created.append(body["id"])
        ref = body["reference_number"]
        assert ref is not None
        # No client → NXS prefix; ends with current year.
        assert ref.startswith("NXS/")
        parts = ref.split("/")
        assert len(parts) == 3
        assert parts[1].isdigit()
        assert len(parts[2]) == 4  # year
    finally:
        await _cleanup_jobs(created)


@pytest.mark.asyncio
async def test_post_job_sequence_increments_for_same_prefix(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Two client-less jobs in the same year get consecutive NXS sequences."""
    created: list[int] = []
    try:
        r1 = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={"title": f"Seq A {uuid.uuid4().hex[:6]}"},
        )
        r2 = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={"title": f"Seq B {uuid.uuid4().hex[:6]}"},
        )
        assert r1.status_code in (200, 201), r1.text
        assert r2.status_code in (200, 201), r2.text
        created += [r1.json()["id"], r2.json()["id"]]
        seq1 = _parse_seq(r1.json()["reference_number"])
        seq2 = _parse_seq(r2.json()["reference_number"])
        assert seq1 is not None and seq2 is not None
        assert seq2 == seq1 + 1, f"{seq1=} {seq2=}"
    finally:
        await _cleanup_jobs(created)


@pytest.mark.asyncio
async def test_post_job_respects_caller_supplied_reference(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """If the caller explicitly passes a reference_number, we keep it."""
    created: list[int] = []
    explicit = f"CUSTOM/{uuid.uuid4().hex[:8]}/2026"
    try:
        resp = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={
                "title": f"Explicit ref {uuid.uuid4().hex[:6]}",
                "reference_number": explicit,
            },
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        created.append(body["id"])
        assert body["reference_number"] == explicit
    finally:
        await _cleanup_jobs(created)
