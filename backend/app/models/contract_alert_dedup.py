"""Kontrakty — atomic dedup log dla alertów wygasania.

Append-only tabela. Jeden `dedup_key` = jeden wpis na zawsze. Używana w
`app/tasks/contract_alerts.py`: przed utworzeniem notyfikacji pętla „claimuje"
klucz przez `INSERT ... ON CONFLICT (dedup_key) DO NOTHING`. Dzięki temu
nakładające się / równoległe przebiegi pętli (restart, wiele workerów) nie
wygenerują duplikatu tego samego alertu — tylko jeden przebieg wygrywa claim,
reszta widzi konflikt i pomija (wcześniej dedup był nieatomowym
SELECT-then-INSERT, więc dwa przebiegi mogły wstawić dublet).

`dedup_key` to stabilny string per (kategoria, próg, encja), np.:
  * ``ending:30:<contract_id>``
  * ``compliance:<contract_document_id>``
  * ``equipment:<contract_equipment_id>``
  * ``client_order:<contract_id>``

Brak FK — klucz jest nieprzezroczystym stringiem obejmującym różne encje.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ContractAlertDedup(Base):
    """Append-only log dedupujący alerty wygasania kontraktów (atomic claim)."""

    __tablename__ = "contract_alert_dedup"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_contract_alert_dedup_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dedup_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ContractAlertDedup key={self.dedup_key!r}>"
