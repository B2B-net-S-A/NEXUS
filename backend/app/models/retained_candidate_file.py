"""Pliki CV usuniętych kandydatów, które zostają (migracja 0390, runda 9).

Decyzja Artura 26.09.2026: „nie usuwać nigdy żadnych CV”. Twarde usunięcie
kandydata kaskadą kasowało jednak wiersze trzymające CV w bazie (BYTEA:
``candidates.cv_file_content``, ``candidate_documents.file_content``,
oryginał i CV firmowe etapu, zatwierdzone wersje) — bajty znikały, a pliki
w magazynie obiektów zostawały bez żadnego wskaźnika (R9-N7-12).

Przed usunięciem bajty idą do magazynu obiektów, a KAŻDY klucz pliku tej
osoby trafia tutaj. Wiersz nie niesie id kandydata ani nazwiska — łączy go
pseudonim ``subject_ref`` (ten sam kluczowany HMAC, którym stemplowane są
odpięte umowy). Klucze sprzed tej zmiany bywają zbudowane z oryginalnej
nazwy pliku — to jedyny wskaźnik do obiektu, więc zostaje taki, jaki jest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RetainedCandidateFile(Base):
    __tablename__ = "retained_candidate_files"
    __table_args__ = (Index("ix_retained_candidate_files_subject_ref", "subject_ref"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    # Skąd plik pochodził (``candidate_cv``, ``document``, ``stage_original``…).
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    # Klucz w magazynie obiektów albo (``*_path``) ścieżka pliku na dysku.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    retained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
