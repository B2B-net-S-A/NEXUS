"""FE-N09 (audyt 22.09 r2): alert SLA kontaktów prowadzi do panelu nadzoru
parametrem `?panel=nadzor-kontaktu`, który pulpit czyta także przy miękkiej
nawigacji. Wartość parametru musi być tą samą, której szuka front."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_alert_link_matches_the_dashboard_panel_param() -> None:
    backend = (ROOT / "backend/app/services/dashboard_v2.py").read_text()
    assert 'href="/dashboard?panel=nadzor-kontaktu"' in backend
    assert "#nadzor-kontaktu" not in backend.split('href="/dashboard?panel=')[1][:40]
    front = ROOT / "frontend/src/components/v2/dashboard/custom/CustomDashboard.tsx"
    if front.exists():  # obraz testowy backendu nie ma frontendu
        assert 'CONTACT_OVERSIGHT_PANEL = "nadzor-kontaktu"' in front.read_text()
