"""Padnięty commit strony nie może zabrać ze sobą całego syncu skrzynki.

Regresja jest tu maksymalnie CICHA i kosztuje DANE, nie wydajność. Do sierpnia
2026 `_sync_messages_for_folder` robił `await db.commit()` POZA blokiem
`except`, który łapał błędy per wiadomość. Wystarczyła jedna kolizja na indeksie
UNIQUE `emails.m365_message_id` (dwa równoległe przebiegi tej samej skrzynki —
patrz `test_m365_sync_single_flight.py`), żeby sesja stała się nieużywalna:
`except` per wiadomość połykał `IntegrityError`, pętla leciała dalej na martwej
sesji, a commit strony rzucał wyjątkiem. Skutek: CAŁA strona zaciągniętych maili
przepadała, a wyjątek uciekał do wywołującego — w ścieżce `POST /sync/trigger`
całkowicie niewidocznie, bo tamten `_run()` był fire-and-forget.

Dlatego test sprawdza trzy rzeczy naraz, których żadna nie widać w UI:
 1. wyjątek NIE ucieka (sync kończy się i raportuje),
 2. sesja jest przywracana `rollback()`-iem, więc kolejna strona ma szansę,
 3. porażka jest POLICZONA — cicho pominięta strona wygląda w raporcie jak
    skrzynka bez nowych maili.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.m365 import sync as sync_mod


class _FakeGraphClient:
    """Zwraca dwie strony: pierwszą, na której padnie commit, i drugą zdrową."""

    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages

    async def paginate(self, url, params=None):  # noqa: ANN001 - atrapa
        for page in self._pages:
            yield page


class _FlakyDB:
    """Sesja, której PIERWSZY commit pada — jak na zatrutej sesji po IntegrityError."""

    def __init__(self, fail_on: int = 1) -> None:
        self.fail_on = fail_on
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.commits == self.fail_on:
            raise RuntimeError("current transaction is aborted")

    async def rollback(self) -> None:
        self.rollbacks += 1


def _connection() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        user_id=1,
        delta_token_inbox=None,
        delta_token_sent=None,
        delta_reset_count=0,
        delta_last_reset_at=None,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_failed_page_commit_is_contained_counted_and_rolled_back(monkeypatch):
    pages = [
        {"value": [{"id": "a"}]},
        {
            "value": [{"id": "b"}],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=z",
        },
    ]

    async def _fake_upsert(db, gc, conn, msg, folder):  # noqa: ANN001 - atrapa
        return SimpleNamespace(id=msg["id"])

    monkeypatch.setattr(sync_mod, "_upsert_message", _fake_upsert)

    db = _FlakyDB(fail_on=1)
    conn = _connection()
    result = sync_mod.SyncResult(connection_id=conn.id)

    # Brak `pytest.raises` jest TU asercją: wyjątek z commitu strony uciekał
    # wcześniej aż do wywołującego i przewracał cały przebieg skrzynki.
    await sync_mod._sync_messages_for_folder(
        db,
        _FakeGraphClient(pages),
        conn,
        result,
        folder="inbox",
        cursor_attr="delta_token_inbox",
        is_backfill=True,
    )

    assert db.rollbacks == 1, (
        "sesja nie została przywrócona — następna strona pada tak samo"
    )
    assert result.errors == 1, (
        "utrata strony maili musi być policzona, nie przemilczana"
    )
    assert any("page-commit" in s for s in result.error_samples)
    # Druga strona przeszła mimo porażki pierwszej — jej wiadomość jest zaciągnięta,
    # a kursor delta zapisany, więc sync nie zapętli się na tym samym oknie.
    assert result.messages_ingested == 2
    assert conn.delta_token_inbox is not None


@pytest.mark.asyncio
async def test_healthy_pages_do_not_roll_back_anything(monkeypatch):
    """Kontrola negatywna — inaczej test wyżej przechodziłby też dla kodu,
    który rollbackuje zawsze."""

    async def _fake_upsert(db, gc, conn, msg, folder):  # noqa: ANN001 - atrapa
        return SimpleNamespace(id=msg["id"])

    monkeypatch.setattr(sync_mod, "_upsert_message", _fake_upsert)

    db = _FlakyDB(fail_on=0)  # nigdy nie pada
    conn = _connection()
    result = sync_mod.SyncResult(connection_id=conn.id)

    await sync_mod._sync_messages_for_folder(
        db,
        _FakeGraphClient([{"value": [{"id": "a"}]}]),
        conn,
        result,
        folder="inbox",
        cursor_attr="delta_token_inbox",
        is_backfill=True,
    )

    assert db.rollbacks == 0
    assert result.errors == 0
    assert result.messages_ingested == 1
