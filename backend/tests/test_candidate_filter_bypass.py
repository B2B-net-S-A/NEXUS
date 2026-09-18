"""Filtr, którego nie da się spełnić, nie może cicho zwracać całej bazy.

Audyt 18.09.2026, zmierzone na produkcji (62 243 kandydatów):

    /api/candidates?q=a                 → total 62 243   (CAŁA baza)
    /api/candidates?q=%                 → total 62 243
    /api/candidates?q=jan               → total 11 199   ✓
    /api/candidates?current_company=%   → total 62 243
    /api/candidates?current_company=IT  → total 16 211   (26% bazy)

Dwie niezależne przyczyny, obie kończące się HTTP 200 pod interfejsem, który
twierdzi, że lista jest przefiltrowana:

1. `single_phrase_filter` zwraca `None` poniżej `_MIN_PHRASE_LEN`, a wołający
   nie dodawał wtedy ŻADNEGO `WHERE` — nie było gałęzi `else`.
2. Predykaty firmy i stanowiska budowały `%{v}%` bez escapowania, więc `%`
   z wejścia był wildcardem, a `_` dopasowywał dowolny znak.

Bliźniaczy `/api/search/global` miał obie rzeczy poprawnie od dawna —
`Query(..., min_length=2)` i `_contains_pattern`. Tu wyrównujemy kontrakt.
"""

import uuid

import pytest

from app.services.polish_ilike import contains_pattern


async def _cleanup(candidate_ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        if candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
            await db.commit()


class TestContainsPattern:
    """Jedno źródło escapowania dla każdego LIKE budowanego z tekstu usera."""

    def test_wildcards_are_literal(self):
        assert contains_pattern("%") == r"%\%%"
        assert contains_pattern("_") == r"%\_%"

    def test_backslash_is_escaped_first(self):
        """Inaczej własny escape zostałby potem potraktowany jako escape."""
        assert contains_pattern("a\\b") == "%a\\\\b%"

    def test_ordinary_text_is_untouched(self):
        assert contains_pattern("nordea") == "%nordea%"

    def test_polish_characters_survive(self):
        """Fold jest osobną decyzją (`folded_contains_pattern`) — tu bez zmian."""
        assert contains_pattern("Łódź") == "%Łódź%"


class TestShortQueryIsRefused:
    """`?q=` krótsze niż 2 znaki → 422, nie cicha pełna baza."""

    @pytest.mark.parametrize("query", ["a", "%", "_", "1"])
    async def test_single_character_query_is_a_validation_error(
        self, app_client, app_auth_headers, query
    ):
        response = await app_client.get(
            "/api/candidates", params={"q": query}, headers=app_auth_headers
        )

        assert response.status_code == 422, response.text
        assert any(
            error["loc"] == ["query", "q"] for error in response.json()["detail"]
        )

    async def test_two_characters_are_accepted(self, app_client, app_auth_headers):
        """Próg to 2, nie 3 — `/api/search/global` przyjmuje dokładnie tyle."""
        response = await app_client.get(
            "/api/candidates", params={"q": "ja"}, headers=app_auth_headers
        )

        assert response.status_code == 200, response.text

    async def test_absent_q_still_lists_everyone(self, app_client, app_auth_headers):
        """Brak filtra to nie to samo co filtr niemożliwy do spełnienia."""
        response = await app_client.get(
            "/api/candidates", params={"page_size": 1}, headers=app_auth_headers
        )

        assert response.status_code == 200, response.text


class TestWildcardsDoNotWidenTheFilter:
    """`%` w filtrze firmy/stanowiska ma być szukanym ZNAKIEM, nie wildcardem.

    Testy zasiewają własnego kandydata i asertują NA NIM, zamiast porównywać
    globalne sumy — inaczej na pustej bazie CI `0 < 0` przechodziłoby jako
    „naprawione".
    """

    @staticmethod
    async def _seed(app_client, app_auth_headers, company: str, role: str) -> int:
        payload = {
            "name": "Wildcard",
            "lastname": f"Probe-{uuid.uuid4().hex[:6]}",
            "email": f"wildcard-{uuid.uuid4().hex[:8]}@example.com",
            "linkedin_current_company": company,
            "experience": [{"company": company, "role": role, "end": None}],
        }
        response = await app_client.post(
            "/api/candidates", json=payload, headers=app_auth_headers
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    @staticmethod
    async def _total(app_client, app_auth_headers, **params) -> int:
        response = await app_client.get(
            "/api/candidates",
            params={**params, "page_size": 1},
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        return response.json()["total"]

    async def test_percent_is_searched_literally_not_as_a_wildcard(
        self, app_client, app_auth_headers
    ):
        company = f"Nordea-{uuid.uuid4().hex[:6]}"
        candidate_id = await self._seed(
            app_client, app_auth_headers, company, "Data Engineer"
        )
        try:
            # Zasiany kandydat jest znajdowalny po realnej nazwie…
            assert (
                await self._total(app_client, app_auth_headers, current_company=company)
                == 1
            )
            # …ale `%` nie może go złapać: nazwa nie zawiera znaku procenta.
            assert (
                await self._total(app_client, app_auth_headers, current_company="%")
                == 0
            )
        finally:
            await _cleanup([candidate_id])

    async def test_underscore_is_not_a_single_character_wildcard(
        self, app_client, app_auth_headers
    ):
        """„Bank_PL" nie może trafiać w „BankXPL"."""
        suffix = uuid.uuid4().hex[:6]
        candidate_id = await self._seed(
            app_client, app_auth_headers, f"BankXPL-{suffix}", "QA"
        )
        try:
            assert (
                await self._total(
                    app_client, app_auth_headers, current_company=f"BankXPL-{suffix}"
                )
                == 1
            )
            assert (
                await self._total(
                    app_client, app_auth_headers, current_company=f"Bank_PL-{suffix}"
                )
                == 0
            )
        finally:
            await _cleanup([candidate_id])

    async def test_title_filter_escapes_too(self, app_client, app_auth_headers):
        role = f"Tester-{uuid.uuid4().hex[:6]}"
        candidate_id = await self._seed(
            app_client, app_auth_headers, f"Firma-{uuid.uuid4().hex[:6]}", role
        )
        try:
            assert (
                await self._total(app_client, app_auth_headers, current_title=role) == 1
            )
            assert (
                await self._total(app_client, app_auth_headers, current_title="%") == 0
            )
        finally:
            await _cleanup([candidate_id])
