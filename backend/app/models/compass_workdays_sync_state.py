"""Stan dawnej pętli dni roboczych z COMPASSA (decyzja D5, migracja 0276).

Compass jest wygaszony od 22.11.2026 (serwer usunięty), a pętla
``compass_workdays_sync`` i sonda ``checks.compass_workdays`` zniknęły z kodu.
Nikt już tu nie pisze. Tabela, lustro w ``entrypoint.sh`` i sonda schematu
w ``/api/health/deep`` zostają do osobnej migracji z ``DROP TABLE`` —
model trzyma tabelę w ``Base.metadata``, żeby „Rozjazd schematu” nie
pokazywał jej jako tabeli bez modelu.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CompassWorkdaysSyncState(Base):
    """Jednowierszowy stan pętli (``id = 1``) — watermark w bazie, nie w pamięci.

    Coolify restartuje kontener przy każdym pushu na main, więc licznik
    w pamięci procesu nie przetrwałby do następnego biegu.
    """

    __tablename__ = "compass_workdays_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_run_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_run_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # ``ok`` | ``errors`` | ``error`` | ``running``. ``errors`` (liczba mnoga)
    # znaczy „bieg doszedł do końca, ale któryś kubełek zgłosił problem" —
    # sonda traktuje go jako degradację, nie jako awarię.
    last_status: Mapped[Optional[str]] = mapped_column(String(20))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    stats: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


__all__ = ["CompassWorkdaysSyncState"]
