"""Stan pętli zaciągania dni roboczych z COMPASSA (decyzja D5).

PO CO TA TABELA ISTNIEJE
------------------------
Do 09.2026 ``compass_workdays_sync`` był JEDYNYM integratorem, którego awarii
nie dało się wykryć żadnym kanałem:

* pętla ``return``uje czysto przy wyłączonej fladze i przy braku sekretu, więc
  ``classify_background_tasks`` klasyfikuje ją jako ``exited_cleanly`` — stan
  CICHY (alarmy Slack obejmują tylko ``ai_spend_alerts`` i ``slack_sla_alerts``);
* ciało pętli łyka każdy wyjątek, więc nigdy nie osiągnie ``crashed``;
* wynik ``sync_workdays`` — w tym ``fetch_failed:`` i ``basis_mismatch:`` —
  trafiał wyłącznie do logu INFO i przepadał.

Skutkiem cichej awarii jest regres dokładnie tego defektu, który D5 usuwał:
``workdays_source`` wraca na ``"unavailable"``, mianownikiem znów jest stała 5,
a osoba na urlopie ląduje na IMIENNEJ liście „poniżej progu".

DLACZEGO TABELA, A NIE ``MAX(synced_at)`` Z ``user_workday_periods``
-------------------------------------------------------------------
Tamten znacznik wykrywa przestój, ale nie odróżnia „COMPASS nie odpowiada" od
„żaden aktywny user się nie dopasował" — a to dwie różne naprawy. Jest też
zapisywany per (user, okres), więc bieg, który nic nie zapisał, nie zostawia
po sobie ŻADNEGO śladu.

``stats`` NIESIE NIEDOPASOWANIA I TO NIE JEST OZDOBA
----------------------------------------------------
``WorkdaySyncResult.as_payload()`` zawiera ``unmatched_compass_emails`` oraz
``nexus_users_without_compass``. Docstring ``insights_workdays`` ostrzega, że
join po e-mailu przestanie trafiać w dniu migracji domenowej (konta
``@inframinds.eu`` już istnieją, dziś nieaktywne). **Wzrost tej liczby jest
jedynym sygnałem, że ten dzień nadszedł** — a sygnał trzymany wyłącznie
w logach nie przetrwa rotacji.

Kalka ``OrderMailSyncState`` (jeden wiersz, ``id = 1``), nie
``TraffitSyncState`` (wiersz per faza): ta pętla ma jedną fazę.
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
