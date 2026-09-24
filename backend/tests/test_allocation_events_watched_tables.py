"""Outbox automatu przydziału nasłuchuje wyłącznie tabel, które istnieją.

Do 24.09.2026 lista miała ``job_secondary_ccs``, a tabela nazywa się
``job_secondary_cc`` — zmiana kategorii pobocznej rekrutacji nigdy nie
zapisywała zdarzenia. Literówka w nazwie tabeli nie daje żadnego błędu, więc
pilnuje jej ten test.
"""

import pytest

import app.models  # noqa: F401 — komplet mapperów w Base.metadata
from app.core.database import Base
from app.services.recruitment_allocation_events import _WATCHED_TABLES


@pytest.mark.unit
def test_every_watched_table_is_a_mapped_table() -> None:
    known = set(Base.metadata.tables)
    assert sorted(_WATCHED_TABLES - known) == []


@pytest.mark.unit
def test_secondary_competence_categories_are_watched() -> None:
    assert "job_secondary_cc" in _WATCHED_TABLES
