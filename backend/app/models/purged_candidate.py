"""Nagrobki usuniętych kandydatów dla syncu źródłowego (migracja 0388).

Runda 6 audytu (RODO-01): twarde usunięcie kandydata (art. 17 RODO) kasowało
wiersz, ale nocny import Traffita pytał o pełną listę ``/employees/`` i —
nie znajdując ``(external_source, external_id)`` w bazie — zakładał tę osobę
od nowa, a za nią etapy, notatki i pliki CV. Bliźniak ``purged_clients``
(0303) dla klientów.

Wiersz nie niesie ŻADNYCH danych osobowych: ani id kandydata, ani surowego
``external_id`` — tylko kluczowany HMAC identyfikatora źródłowego
(``candidate_audit.candidate_source_tombstone``), bo nagrobek przeżywa osobę,
której dane właśnie usuwamy. Importer liczy ten sam HMAC dla każdego rekordu
źródła i pomija trafienia.

Scalenie duplikatów (``candidate_merge``) nagrobka NIE stawia: ocalały
przejmuje ``external_id`` duplikatu, więc rekord źródła dalej ma właściciela.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PurgedCandidate(Base):
    __tablename__ = "purged_candidates"
    __table_args__ = (
        UniqueConstraint(
            "external_source",
            "external_id_hash",
            name="uq_purged_candidates_source_hash",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    external_source: Mapped[str] = mapped_column(String(50), nullable=False)
    # HMAC-SHA256 (hex) identyfikatora w systemie źródłowym — bez klucza
    # `CANDIDATE_IDENTITY_FINGERPRINT_KEY` nie da się go odwrócić tablicą id.
    external_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
