"""Runda 10 (R10-N2-4): widoczność klienta w zapytaniach DL w Insights.

``CLIENT_VISIBLE_SQL`` (ranking DL, Portfele DL, placementy per klient) ma być
lustrem ``job_client_listed_clause`` (UAT B73) plus scalenie: klient ukryty,
usunięty albo scalony nie pokazuje nazwy, a archiwalny prawdziwy klient —
pokazuje. Do 27.09.2026 filtr brał ``archived_at`` (archiwalny klient
dostawał „(klient ukryty lub scalony)”) i pomijał ``deleted_at`` (usunięty
klient z cofniętą archiwizacją wracał z nazwą).
"""

from __future__ import annotations

import re

from sqlalchemy.dialects import postgresql

from app.services.client_identity import job_client_listed_clause
from app.services.insights_dl_scope import CLIENT_VISIBLE_SQL


def _columns(sql: str) -> set[str]:
    return set(re.findall(r"\b(?:c|clients)\.(\w+)", sql))


def test_client_visible_sql_mirrors_job_client_listed_clause_plus_merge():
    listed = str(job_client_listed_clause(1).compile(dialect=postgresql.dialect()))
    listed_columns = _columns(listed) - {"id"}
    assert listed_columns == {"hidden", "deleted_at"}
    assert _columns(CLIENT_VISIBLE_SQL) == listed_columns | {"merged_into_client_id"}


def test_archived_client_is_not_hidden_but_deleted_one_is():
    assert "archived_at" not in CLIENT_VISIBLE_SQL
    assert "c.deleted_at IS NULL" in CLIENT_VISIBLE_SQL
