"""Nocne przygotowanie ogłoszeń (21.10.2026) — okno czasu firmy, bez bazy."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.tasks import job_ad_prepare

_WARSAW = ZoneInfo("Europe/Warsaw")


@pytest.mark.parametrize(
    ("hour", "inside"),
    [(0, True), (3, True), (5, True), (6, False), (12, False), (23, False)],
)
def test_preparation_runs_only_at_night_in_company_time(monkeypatch, hour, inside):
    monkeypatch.setattr(
        job_ad_prepare,
        "local_now",
        lambda: datetime(2026, 10, 22, hour, 30, tzinfo=_WARSAW),
    )
    assert job_ad_prepare.in_night_window() is inside
