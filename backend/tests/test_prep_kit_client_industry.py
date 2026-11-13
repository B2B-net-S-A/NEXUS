"""Prep kit pisał „Bank Przykładowy — firma z branży IT.” dla każdego klienta bez
wypełnionego `clients.industry` (11 ze 155 aktywnych klientów ma branżę), więc
kartka na rozmowę u banku czy w energetyce podawała kandydatowi fałszywą
branżę. Bez danych zdanie nie zgaduje branży."""

from types import SimpleNamespace

import pytest

from app.api.prep_kit import _client_overview_line

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("industry", [None, "", "   "])
def test_client_without_industry_gets_no_made_up_industry(industry):
    line = _client_overview_line(
        SimpleNamespace(name="Bank Przykładowy", industry=industry)
    )
    assert line == "Bank Przykładowy."
    assert "branży" not in line


def test_client_with_industry_keeps_it():
    line = _client_overview_line(
        SimpleNamespace(name="Bank Przykładowy", industry="Bankowość")
    )
    assert line == "Bank Przykładowy — firma z branży Bankowość."


def test_job_without_client_has_no_industry():
    assert _client_overview_line(None) == "Klient."
