"""Błąd SQL nie może wynieść danych osobowych do logów i Sentry.

Bez ``hide_parameters=True`` każdy ``IntegrityError``/``DataError`` niesie
w treści ``[parameters: (...)]`` — e-mail, telefon, nazwisko, stawkę
kandydata. Ta treść trafia do ``logger.exception`` i do zdarzeń Sentry.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal, engine


def test_engine_hides_statement_parameters():
    assert engine.sync_engine.hide_parameters is True


@pytest.mark.asyncio
async def test_sql_error_message_does_not_carry_bound_values():
    secret = "kandydat-pii@example.com"
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError) as caught:
            # Dzielenie przez zero: komunikat bazy nie powtarza wartości, więc
            # jedyną drogą e-maila do treści byłoby `[parameters: …]`.
            await db.execute(
                text(
                    "SELECT 1 / (length(CAST(:v AS text)) - length(CAST(:v AS text)))"
                ),
                {"v": secret},
            )
        await db.rollback()
    message = str(caught.value)
    assert "hide_parameters" in message
    assert secret not in message
