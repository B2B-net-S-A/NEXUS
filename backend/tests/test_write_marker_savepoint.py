"""Runda 9: wycofanie SAVEPOINT-u nie kasuje flagi niezatwierdzonych zapisów."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core import database


def _session_has_marker(session: Session) -> bool:
    return bool(session.info.get(database._UNCOMMITTED_WRITES_KEY))


def test_savepoint_rollback_keeps_the_outer_write_marker() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.execute(text("CREATE TABLE t (x INTEGER)"))
        session.execute(text("INSERT INTO t VALUES (1)"))
        assert _session_has_marker(session)
        nested = session.begin_nested()
        session.execute(text("INSERT INTO t VALUES (2)"))
        nested.rollback()
        # Zewnętrzny INSERT nadal czeka na commit — flaga musi zostać.
        assert _session_has_marker(session)
        session.commit()
        assert not _session_has_marker(session)


def test_outer_rollback_clears_the_marker() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.execute(text("CREATE TABLE t (x INTEGER)"))
        assert _session_has_marker(session)
        session.rollback()
        assert not _session_has_marker(session)
