"""Zgody kandydatów na przetwarzanie danych (0339, strona kariery).

Jeden wiersz = jedna zgoda złożona w formularzu. Wiersz wisi DOKŁADNIE na
jednym z dwóch obiektów:

* ``candidate_id`` — nowy kandydat utworzony przez formularz; FK z CASCADE,
  więc twarde usunięcie kandydata (art. 17 RODO) zabiera jego zgody;
* ``application_submission_id`` — zgłoszenie z adresem już obecnym w bazie
  (gałąź duplikatu nie dotyka istniejącego kandydata, patrz P0-CAND-01).

Od 0477 jedno zgłoszenie daje jeden albo dwa wiersze: obowiązkowy
``recruitment_current`` i — gdy kandydat zaznaczył — ``recruitment_future``.

Tekst zgody nie jest kopiowany do każdego wiersza — ``text_version`` wskazuje
wersję w ``services/career_consent.py``, a ``text_sha256`` dowodzi, którą
dokładnie treść zobaczył kandydat. Bez adresu IP w jawnej postaci.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Do 2026-10-19 jedna zgoda na oba cele; wiersze tego rodzaju zostają.
CONSENT_KIND_RECRUITMENT = "recruitment_current_future"
# Od 2026-10-19 (0477): obowiązkowa na tę rekrutację i dobrowolna na przyszłe.
CONSENT_KIND_CURRENT = "recruitment_current"
CONSENT_KIND_FUTURE = "recruitment_future"


class CandidateConsent(Base):
    __tablename__ = "candidate_consents"
    __table_args__ = (
        CheckConstraint(
            "(candidate_id IS NOT NULL) <> (application_submission_id IS NOT NULL)",
            name="ck_candidate_consents_one_subject",
        ),
        CheckConstraint(
            "kind IN ('recruitment_current_future', 'recruitment_current', "
            "'recruitment_future')",
            name="ck_candidate_consents_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True, index=True
    )
    application_submission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("application_submissions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    text_version: Mapped[str] = mapped_column(String(20), nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    given_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Nie-sekretny klucz linku (SHA-256 sekretu), przez który złożono zgodę.
    invite_link_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
