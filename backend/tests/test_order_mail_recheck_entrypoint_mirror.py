"""Migracja 0312 i jej lustro w ``entrypoint.sh`` muszą się zgadzać.

Prod alembic bywa osierocony — safety-net w ``entrypoint.sh`` JEST wdrożeniem.
Bez kolumny ``gate_reason_codes`` godzinowa ponowna weryfikacja czytałaby pustą
listę kodów i każde wstrzymanie kwalifikowała jako „inny powód", czyli zaczęłaby
alarmować Delivery Leada o zamówieniach czekających na podpis umowy. Bez tabeli
``order_mail_recheck_runs`` sekcja „Historia automatycznej weryfikacji" nie ma
skąd czytać.

Obie strony czytane ze ŹRÓDŁA, bez wykonania heredocu (import podmienia
``sys.modules["asyncpg"]`` atrapą i zatruwa testy z bazą w tej samej sesji).
"""

from __future__ import annotations

from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
_MIGRATION = (
    _BACKEND / "alembic" / "versions" / "0312_order_mail_auto_recheck.py"
).read_text(encoding="utf-8")


def _shape(text: str) -> str:
    return " ".join(text.split()).lower()


def test_the_gate_reason_codes_column_has_a_mirror():
    assert "gate_reason_codes" in _MIGRATION
    assert (
        "add column if not exists gate_reason_codes jsonb"
        in _shape(_ENTRYPOINT)
    )


def test_the_recheck_history_table_has_a_mirror():
    shape = _shape(_ENTRYPOINT)
    assert "create table if not exists order_mail_recheck_runs" in shape
    assert "ck_order_mail_recheck_runs_trigger" in shape
    assert "ix_order_mail_recheck_runs_started" in shape


def test_every_column_of_the_model_exists_on_both_sides():
    from app.models.order_mail import OrderMailRecheckRun

    mirror = _shape(_ENTRYPOINT)
    migration = _shape(_MIGRATION)
    for column in OrderMailRecheckRun.__table__.columns:
        assert column.name in mirror, f"brak {column.name} w entrypoint.sh"
        assert column.name in migration, f"brak {column.name} w migracji 0312"
