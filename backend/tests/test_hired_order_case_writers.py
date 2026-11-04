"""Każdy writer zamówień zamyka sprawę „uzupełnij zamówienie” po zatrudnieniu.

Audyt 05.10.2026: zamówienie z maila (`order_mail_apply`) synchronizowało
kontrakt i braki, ale nie gasiło dzwonka Finansów `hired_order_missing` —
zamykał go wyłącznie `commit_order_write`. Bez bazy: test czyta źródła.
"""

from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"

WRITERS = (
    "services/order_write_errors.py",
    "services/order_mail_apply.py",
)


def test_every_order_writer_resolves_hired_order_cases():
    for path in WRITERS:
        source = (_APP / path).read_text(encoding="utf-8")
        assert "await resolve_hired_order_cases_safely(" in source, path
