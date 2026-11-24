"""Filtr „Kończy u nas w ciągu 60 dni” tylko z dostępem do Delivery (09.11.2026)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.candidates import _reject_ending_soon_without_delivery


def _user(delivery: str) -> SimpleNamespace:
    return SimpleNamespace(effective_section_access={"delivery": delivery})


def test_recruiter_without_delivery_gets_403():
    with pytest.raises(HTTPException) as exc:
        _reject_ending_soon_without_delivery(["ending_soon"], _user("none"))

    assert exc.value.status_code == 403


@pytest.mark.parametrize("access", ["read", "write"])
def test_delivery_access_passes(access: str):
    _reject_ending_soon_without_delivery(["ending_soon"], _user(access))


@pytest.mark.parametrize("employment", [None, [], ["at_client"], ["available"]])
def test_other_employment_filters_stay_open(employment):
    _reject_ending_soon_without_delivery(employment, _user("none"))


# ── eksport (audyt r4, 24.11.2026) ──────────────────────────────────────────
# POST /api/candidates/export bierze te same filtry co lista, ale bramka stała
# tylko na liście: bez dostępu do Delivery filtr dawał plik zamiast 403.


class _ReachedQuery(Exception):
    """Eksport minął bramkę i zaczął budować zapytanie."""


class _NoDb:
    def __getattr__(self, name):
        raise AssertionError(f"bramka ma odmówić przed bazą (db.{name})")


async def _export(employment: list[str], delivery: str, monkeypatch):
    from app.api import candidates as candidates_api

    async def _stop(*_args, **_kwargs):
        raise _ReachedQuery

    monkeypatch.setattr(candidates_api, "_resolve_semantic_text", _stop)
    payload = candidates_api.CandidateExportRequest(
        scope="filtered", filters={"employment": employment}
    )
    user = SimpleNamespace(id=1, effective_section_access={"delivery": delivery})
    return await candidates_api.export_candidates_v2(payload, user, _NoDb())


@pytest.mark.asyncio
async def test_export_ending_soon_without_delivery_gets_403(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        await _export(["ending_soon"], "none", monkeypatch)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("employment", "delivery"),
    [(["ending_soon"], "read"), (["ending_soon"], "write"), (["at_client"], "none")],
)
async def test_export_passes_gate_with_delivery_or_other_filter(
    employment, delivery, monkeypatch
):
    with pytest.raises(_ReachedQuery):
        await _export(employment, delivery, monkeypatch)
