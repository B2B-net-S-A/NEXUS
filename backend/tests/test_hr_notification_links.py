"""Linki w powiadomieniach HR prowadzą na istniejące ekrany z właściwym stanem.

Lista miesięcy płac nie czyta parametrów (miesiąc to segment `/people/payroll/RRRR-MM`),
a „Mój czas” otwiera zakładkę z `?tab=` — link bez tego ląduje na złym widoku.
"""

from __future__ import annotations

from pathlib import Path

from app.services.hr import time_flow

FRONTEND_APP = Path(__file__).resolve().parents[2] / "frontend" / "src" / "app"
SERVICES = Path(__file__).resolve().parents[1] / "app" / "services" / "hr"


def test_payroll_link_targets_month_segment() -> None:
    assert time_flow.payroll_link(2026, 9) == "/people/payroll/2026-09"
    assert (FRONTEND_APP / "people" / "payroll" / "[ym]" / "page.tsx").exists()


def test_my_time_links_name_their_tab() -> None:
    assert time_flow.my_month_link(2026, 9).startswith("/my-time?tab=month&")
    for name in ("payroll_bonuses.py", "payroll_rates.py"):
        source = (SERVICES / name).read_text(encoding="utf-8")
        assert 'link="/my-time"' not in source, name
        assert 'link="/my-time?tab=bonuses"' in source, name
