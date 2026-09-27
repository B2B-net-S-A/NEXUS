"""Runda 9 (R9-N12-8): daty kart DL i eksportu liczone w czasie firmy.

Karta „zamówienie z maila czeka na weryfikację" podpisywała dzień wpłynięcia
datą UTC, a eksport XLSX pisał surowe ISO w UTC — mail z 00:30 czasu
polskiego i reakcja DL z późnego wieczoru lądowały pod innym dniem niż
w panelu.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


def test_export_timestamp_is_business_time_without_offset():
    from app.api.dl_alerts import export_local_timestamp

    # 22:30 UTC w lecie = 00:30 następnego dnia w Warszawie (UTC+2).
    assert (
        export_local_timestamp(datetime(2026, 9, 26, 22, 30, tzinfo=timezone.utc))
        == "2026-09-27 00:30:00"
    )
    # Zima: UTC+1.
    assert (
        export_local_timestamp(datetime(2026, 12, 31, 23, 15, tzinfo=timezone.utc))
        == "2027-01-01 00:15:00"
    )
    assert export_local_timestamp(None) == ""


@pytest.mark.asyncio
async def test_order_mail_review_card_uses_the_business_day(monkeypatch):
    import app.services.dl_alerts as dl_alerts
    from app.services.order_mail_ingest import notify_review

    captured: dict = {}

    async def _recipients(_db, _client_id, scope=None):
        return [7]

    async def _emit(_db, **kwargs):
        captured.update(kwargs)
        return [object()]

    class _Db:
        async def scalar(self, _stmt):
            return "Klient"

    monkeypatch.setattr(dl_alerts, "dl_user_ids_for_client", _recipients)
    monkeypatch.setattr(dl_alerts, "emit", _emit)
    row = SimpleNamespace(
        id=11,
        client_id=5,
        extraction={},
        gate_reasons=[],
        attachment_name="zam.pdf",
        outcome="needs_review",
        # 23:40 UTC 26.09 = 01:40 27.09 w Warszawie.
        received_at=datetime(2026, 9, 26, 23, 40, tzinfo=timezone.utc),
    )

    assert await notify_review(_Db(), row) == 1
    assert captured["payload"]["received_at"] == "2026-09-27"
