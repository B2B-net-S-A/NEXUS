"""Teczka leada bez bazy: wybór stanowisk, strona firmy, pusta teczka, flaga."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.services.sales import lead_dossier

NOW = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)


def test_decision_makers_keep_board_and_heads_up_to_four_without_repeats() -> None:
    titles = [
        "Specjalista ds. zakupów",
        "Head of Data",
        "CTO",
        "cto",
        "Prezes Zarządu",
        "Director of IT",
        "Kierownik zespołu",
        "Head of Risk",
        None,
        "",
    ]
    picked = lead_dossier.decision_makers(titles)
    # Zarząd i VP przed Head i Director, w obrębie poziomu kolejność kontaktów.
    assert picked[:2] == ["CTO", "Prezes Zarządu"]
    assert len(picked) == lead_dossier.MAX_DECISION_MAKERS
    assert "Specjalista ds. zakupów" not in picked
    assert "cto" not in picked


def test_decision_makers_empty_without_decision_titles() -> None:
    assert lead_dossier.decision_makers(["Analityk", "Kierownik projektu"]) == []


@pytest.mark.parametrize(
    ("domain", "website", "expected"),
    [
        ("example.com", "https://www.other.pl", "example.com"),
        (None, "https://www.example.pl/o-nas", "example.pl"),
        ("  ", None, None),
        # Nazwa spółki w polu domeny (import z Atlasa): nie udaje strony.
        ("nazwa spółki sp. z o.o.", None, None),
        ("nazwa spółki sp. z o.o.", "https://firma.example.pl", "firma.example.pl"),
        (None, None, None),
    ],
)
def test_website_is_domain_or_host_without_www(
    domain: str | None, website: str | None, expected: str | None
) -> None:
    assert lead_dossier._host(domain, website) == expected


def test_dossier_without_any_data_has_no_content() -> None:
    assert not lead_dossier.LeadDossier(company_id=1).has_content()
    assert lead_dossier.LeadDossier(company_id=1, points=2).has_content()
    assert lead_dossier.LeadDossier(company_id=1, owner="Opiekun").has_content()


@pytest.mark.asyncio
async def test_order_without_the_flag_does_not_touch_the_database(monkeypatch) -> None:
    class _NoDb:
        async def execute(self, *a, **kw):  # noqa: ANN002, ANN003
            raise AssertionError("bez flagi zadań teczka nie pyta bazy")

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    assert await lead_dossier.order(_NoDb(), now=NOW) == {
        "enrich": 0,
        "people": 0,
        "briefing": 0,
    }
