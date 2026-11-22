"""Kto robi kroki z listy w kolejce „Koszty” (``costs.Approvers``).

Listy „Księgowi” i „Weryfikujący kontraktorów” leżą w ustawieniach Księgowości
(``app_settings['ledger']``, ``services/ledger/settings.py``), które same
importują ``costs`` — dlatego wczytanie jest osobnym modułem, a ``costs`` dostaje
gotowy wynik od trasy.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.finance_ledger.costs import Approvers
from app.services.ledger import settings as ledger_settings


async def load(db: AsyncSession, user: User) -> Approvers:
    current = await ledger_settings.load(db)
    return Approvers(
        accountant=ledger_settings.can_approve(user, current),
        verifier=ledger_settings.can_verify_contractors(user, current),
    )
