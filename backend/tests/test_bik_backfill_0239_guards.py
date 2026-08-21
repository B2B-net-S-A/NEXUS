"""Bramki jednorazowej korekty 0239 — bez nich cisza udaje sukces.

Testy czytają PLIK jako tekst (konwencja pozostałych testów migracji w tym
repo): produkcyjny alembic bywa osierocony, a i tak nie da się tu odpalić
prawdziwego ``UPDATE`` bez pełnego schematu.

Regresja, której pilnują, jest CICHA w obie strony:

* aktywacja SQL-em omijała ``validate_ready_for_activation``, więc niekompletny
  szkic wchodził do rejestru jako aktywny konsultant z marżą „—" i zerowym
  wkładem do kafla MRR — bez żadnego błędu;
* marker w ``app_settings`` zapisywał się bezwarunkowo, więc korekta, która nic
  nie zrobiła, konsumowała swoją jedyną szansę — bez retry i bez alarmu.

Oba stany wyglądają na produkcji identycznie jak powodzenie, więc jedynym
sposobem, żeby nie wróciły, jest asercja na kształt SQL-a.
"""

from __future__ import annotations

from pathlib import Path

from app.services.contract_service import ACTIVATION_REQUIRED_FIELDS

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0239_bik_contract_order_backfill.py"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_activation_requires_the_same_fields_the_api_requires():
    """Lustro ``ACTIVATION_REQUIRED_FIELDS`` — lista jest CZYTANA ze źródła.

    Dopisanie pola do tupli w ``contract_service`` ma tu wywołać czerwień, a nie
    cicho poszerzyć rozjazd między bramką API a bramką SQL.
    """
    sql = _sql()
    for field in ACTIVATION_REQUIRED_FIELDS:
        assert f"contract.{field} IS NOT NULL" in sql, field


def test_activation_leaves_an_audit_row():
    sql = _sql()
    assert "INSERT INTO activities" in sql
    assert "'contract_activated'" in sql
    # Bez ``from_status``/``to_status`` oś czasu kontraktu pokazuje zdarzenie,
    # z którego nie wynika, co się właściwie zmieniło.
    assert "'from_status', 'draft'" in sql
    assert "'to_status', 'active'" in sql


def test_recognised_but_incomplete_draft_stops_the_migration():
    """Zero zmienionych wierszy nie może znaczyć jednocześnie „nie ma czego
    poprawiać" i „rozpoznaję cel, ale nie umiem go ruszyć"."""
    sql = _sql()
    assert "IF contract_rows = 1 THEN" in sql
    assert "missing_activation_fields" in sql
    assert "cannot be activated" in sql


def test_zero_group_match_is_fail_closed_not_only_the_surplus():
    """Bramka łapała wyłącznie NADMIAR (>1); zero szło na marker."""
    sql = _sql()
    assert "IF target_group_count > 1 THEN" in sql
    assert "IF target_group_count = 0 THEN" in sql
    zero_branch = sql.split("IF target_group_count = 0 THEN", 1)[1].split(
        "IF target_group_count = 1 THEN", 1
    )[0]
    assert "RAISE EXCEPTION" in zero_branch
    # Rozpoznanie idzie po PARZE (klient, numer) + przyszły start, a nie po
    # pełnym, sześcioczłonowym kształcie z zapytania wyżej — inaczej gałąź
    # nigdy by się nie odpaliła, bo pytałaby dokładnie o to samo.
    assert "order_group.status = 'active'" in zero_branch
    assert "order_group.start_date > CURRENT_DATE" in zero_branch
    executable = "\n".join(
        line for line in zero_branch.splitlines() if not line.lstrip().startswith("--")
    )
    assert "predecessor_group_id" not in executable


def test_marker_is_written_after_both_gates_not_before():
    """Marker (jedyny bezpiecznik przed powtórką) musi stać ZA bramkami."""
    sql = _sql()
    marker_at = sql.index("INSERT INTO app_settings")
    assert sql.index("IF target_group_count = 0 THEN") < marker_at
    assert sql.index("missing_activation_fields") < marker_at
    # Liczba dopisanych wierszy audytu jest częścią śladu operacyjnego: bez
    # niej „contract_rows: 1" nie mówi, czy historia kontraktu ma zdarzenie.
    assert "'contract_activity_rows', activity_rows" in sql
