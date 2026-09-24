"""Jedna kolejność blokad dla writerów zamówień: kontrakty → zamówienia (PR2).

Do 09.2026 writery zamówień blokowały ``client_orders`` (albo je po prostu
aktualizowały), a ``commit_order_write`` → ``resync_contract`` brał potem
``contracts FOR UPDATE``. Handlery kontraktu (status, wypowiedzenie, aneks,
cron) robią odwrotnie — kontrakt, potem zamówienia. Dwie transakcje na tej
samej parze zakleszczały się (ABBA; „Znany dług” w CLAUDE.md).

Test strukturalny (AST), jak ``test_contract_status_concurrency``: każda
funkcja writerów, która bierze ``FOR UPDATE`` na zamówieniu, musi wcześniej
zawołać ``lock_contract_then_orders`` (albo ``_lock_group_lines``) — chyba że
jest na liście wyjątków z powodem. Wyścig nie byłby deterministyczny, a
kolejność instrukcji jest dokładnie tym, co defekt naruszał.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

WRITER_MODULES = (
    "api/client_orders.py",
    "api/client_order_groups.py",
    "api/md_consumption.py",
    "services/client_order_lines.py",
    "services/order_mail_apply.py",
    "services/order_mail_signature.py",
    "services/order_group_lifecycle.py",
    "services/nordea_order_import.py",
    "services/ezdrowie_md_seed.py",
    "services/contract_order_offboarding.py",
    "services/contract_client_reassign.py",
    "services/b2b_contract_automation.py",
    "services/order_line_takeover.py",
    "services/contract_lifecycle.py",
)

LOCK_HELPERS = (
    "lock_contract_then_orders(",
    "lock_order_group_lines(",
    "_lock_group_lines(",
)

# Funkcje, które blokują zamówienie bez helpera — z powodem.
EXEMPT: dict[tuple[str, str], str] = {
    (
        "services/contract_lifecycle.py",
        "lock_contract_then_orders",
    ): "to jest sam helper",
    (
        "services/contract_lifecycle.py",
        "lock_order_group_lines",
    ): "to jest sam helper (grupy → helper kontrakt → linie)",
    (
        "services/contract_lifecycle.py",
        "hard_delete_contract",
    ): "blokuje Contract jako pierwszy, potem jego zamówienia",
    (
        "services/order_mail_apply.py",
        "_renewal_of_completed_order",
    ): "FOR SHARE w pętli _write_document, po blokadzie całego dokumentu",
}


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            yield node


def _order_locks(src: str, fn: ast.AST) -> list[int]:
    """Linie ``.with_for_update(`` na zapytaniu o zamówienie w tej funkcji."""

    lines: list[int] = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "with_for_update"
        ):
            segment = ast.get_source_segment(src, node) or ""
            head = segment.split(".where(", 1)[0]
            if (
                "select(ClientOrder)" in head
                or "select(ClientOrder.id)" in head
                or "_line_query()" in head
                or segment.startswith("query.with_for_update")
            ):
                lines.append(node.lineno)
    return lines


def _helper_calls(src: str, fn: ast.AST) -> list[int]:
    out: list[int] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            segment = ast.get_source_segment(src, node) or ""
            if segment.startswith(LOCK_HELPERS) or any(
                f".{h}" in segment[:40] for h in LOCK_HELPERS
            ):
                out.append(node.lineno)
    return out


def _violations() -> list[str]:
    problems: list[str] = []
    for rel in WRITER_MODULES:
        src = (APP / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in _functions(tree):
            locks = _order_locks(src, fn)
            if not locks or (rel, fn.name) in EXEMPT:
                continue
            helpers = _helper_calls(src, fn)
            first_lock = min(locks)
            if not helpers or min(helpers) > first_lock:
                problems.append(f"{rel}:{first_lock} {fn.name}")
    return problems


def test_every_order_writer_locks_contracts_first():
    problems = _violations()
    assert not problems, (
        "Te funkcje blokują zamówienie przed kontraktem. Zawołaj "
        "`lock_contract_then_orders` (services/contract_lifecycle.py) PRZED "
        "pierwszą blokadą albo dopisz wyjątek z powodem:\n" + "\n".join(problems)
    )


def test_detector_flags_a_writer_without_the_helper():
    """Strażnik ma sens tylko, jeśli potrafi paść."""

    src = (
        "async def bad(db):\n"
        "    order = await db.scalar(select(ClientOrder).where(ClientOrder.id == 1)"
        ".with_for_update())\n"
        "async def good(db):\n"
        "    await lock_contract_then_orders(db, order_ids=[1])\n"
        "    order = await db.scalar(select(ClientOrder).where(ClientOrder.id == 1)"
        ".with_for_update())\n"
    )
    tree = ast.parse(src)
    verdict = {}
    for fn in _functions(tree):
        locks = _order_locks(src, fn)
        helpers = _helper_calls(src, fn)
        verdict[fn.name] = bool(helpers) and min(helpers) < min(locks)
    assert verdict == {"bad": False, "good": True}


def test_exemptions_still_exist():
    for rel, name in EXEMPT:
        src = (APP / rel).read_text(encoding="utf-8")
        names = {fn.name for fn in _functions(ast.parse(src))}
        assert name in names, f"nieaktualny wyjątek: {rel} {name}"


# ── Zachowanie helpera (bez bazy) ────────────────────────────────────────────


class _RecordingSession:
    """Zapisuje wykonane instrukcje; ``scalars`` oddaje kontrakty zamówień."""

    def __init__(self, contract_ids: list[int]):
        self.statements: list[object] = []
        self._contract_ids = contract_ids
        self.no_autoflush = _NullContext()

    async def scalars(self, stmt):
        self.statements.append(("read", stmt))
        return SimpleNamespace(all=lambda: list(self._contract_ids))

    async def execute(self, stmt):
        self.statements.append(("lock", stmt))
        return None


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _locked_table_and_ids(stmt) -> tuple[str, list[int]]:
    table = stmt.get_final_froms()[0].name
    return table, list(stmt.whereclause.right.value)


@pytest.mark.asyncio
async def test_helper_locks_sorted_contracts_before_sorted_orders():
    from app.services.contract_lifecycle import lock_contract_then_orders

    db = _RecordingSession(contract_ids=[9, 3, None])
    await lock_contract_then_orders(db, contract_ids=[7, 3], order_ids=[40, 12, 40])

    locks = [stmt for kind, stmt in db.statements if kind == "lock"]
    assert [_locked_table_and_ids(stmt) for stmt in locks] == [
        ("contracts", [3, 7, 9]),
        ("client_orders", [12, 40]),
    ]
    assert all(stmt._for_update_arg is not None for stmt in locks)


@pytest.mark.asyncio
async def test_helper_is_a_noop_without_ids():
    from app.services.contract_lifecycle import lock_contract_then_orders

    db = _RecordingSession(contract_ids=[])
    await lock_contract_then_orders(db)
    assert db.statements == []


# ── Audyt 24.09.2026 (blok C, S5): masowe UPDATE i zapisy bez FOR UPDATE ────

MASS_UPDATE_MODULES = (
    *WRITER_MODULES,
    "tasks/dl_portal_expiry_scanner.py",
    "services/contract_order_sync.py",
)

MASS_UPDATE_EXEMPT: dict[tuple[str, str], str] = {
    (
        "services/contract_client_reassign.py",
        "execute_reassign",
    ): "lock_contract + lock_orders (helper kontrakt → zamówienia) przed zapisem",
}

# Writery, które zmieniają pola zamówienia BEZ ``FOR UPDATE`` (więc strażnik
# wyżej ich nie widzi): zapis pliku PO i przebieg dobowy kosztów. Do 24.09
# pisały do zamówień przed blokadą kontraktu, którą bierze potem
# ``commit_order_write``/``resync_contract``.
FIELD_WRITERS: tuple[tuple[str, str], ...] = (
    ("api/client_orders.py", "replace_order_po"),
    ("api/client_orders.py", "delete_order_po"),
    ("services/contract_order_sync.py", "run_daily_order_cost_sync"),
    ("tasks/dl_portal_expiry_scanner.py", "_promote_statuses"),
)


def _mass_order_updates(src: str, fn: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "update"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "ClientOrder"
        ):
            lines.append(node.lineno)
    return lines


def test_mass_order_updates_lock_contracts_first():
    problems: list[str] = []
    for rel in MASS_UPDATE_MODULES:
        src = (APP / rel).read_text(encoding="utf-8")
        for fn in _functions(ast.parse(src)):
            updates = _mass_order_updates(src, fn)
            if not updates or (rel, fn.name) in MASS_UPDATE_EXEMPT:
                continue
            helpers = _helper_calls(src, fn)
            if not helpers or min(helpers) > min(updates):
                problems.append(f"{rel}:{min(updates)} {fn.name}")
    assert not problems, (
        "Masowy UPDATE zamówień przed blokadą kontraktów (ABBA). Zawołaj "
        "`lock_contract_then_orders` przed zapisem:\n" + "\n".join(problems)
    )


def test_field_writers_without_for_update_call_the_helper():
    problems: list[str] = []
    for rel, name in FIELD_WRITERS:
        src = (APP / rel).read_text(encoding="utf-8")
        fns = [fn for fn in _functions(ast.parse(src)) if fn.name == name]
        assert fns, f"nie ma już {rel} {name} — zaktualizuj listę"
        if not _helper_calls(src, fns[0]):
            problems.append(f"{rel} {name}")
    assert not problems, "\n".join(problems)


def test_mass_update_detector_can_fail():
    src = (
        "async def bad(db):\n"
        "    await db.execute(update(ClientOrder).values(status='completed'))\n"
        "async def good(db):\n"
        "    await lock_contract_then_orders(db, order_ids=[1])\n"
        "    await db.execute(update(ClientOrder).values(status='completed'))\n"
    )
    verdict = {}
    for fn in _functions(ast.parse(src)):
        updates = _mass_order_updates(src, fn)
        helpers = _helper_calls(src, fn)
        verdict[fn.name] = bool(helpers) and min(helpers) < min(updates)
    assert verdict == {"bad": False, "good": True}
