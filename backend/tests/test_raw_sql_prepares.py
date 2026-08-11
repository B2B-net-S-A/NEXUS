"""Every raw-SQL statement in `app/` must parse against the real schema.

CI could not previously catch a broken `text()` statement. Every test that
touches one replaces `db.execute` with an `AsyncMock`, so the SQL is asserted
on but never sent to PostgreSQL — the string could be anything. Two defects
shipped through that gap in the same statement:

* a bare Python name (`SOURCE_VALUE`) where a SQL literal belonged, which
  Postgres would have read as a column reference;
* bare parameters in an `INSERT ... SELECT`. Unlike `INSERT ... VALUES`,
  Postgres does not infer parameter types from the target columns there, so
  every execution raised `AmbiguousParameterError`. That one had been on main
  since #912 (2026-07-24) — three weeks, unnoticed, because nothing parsed it.

`PREPARE` is the cheap oracle: the server plans the statement — resolving
tables, columns, casts and parameter types — without executing it. The pytest
job already provides a Postgres service and runs `alembic upgrade heads`
first, so the schema here is the real one.
"""

import ast
import os
import re
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND = Path(__file__).resolve().parents[1]

# `::cast` must not be read as a bind parameter: the character after ':' has to
# be a letter, and the one before must not be another ':'.
_BIND = re.compile(r"(?<!:):([a-zA-Z_]\w*)")

# PREPARE accepts only these. Anything else in the corpus is a SQL *fragment*
# (a server_default, an order_by expression) rather than a statement.
_PREPARABLE = re.compile(r"^\s*(WITH|SELECT|INSERT|UPDATE|DELETE|VALUES)\b", re.I)


def _statements() -> list[tuple[str, int, str]]:
    """Collect `text("literal")` statements, with their source location."""

    found: list[tuple[str, int, str]] = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - app/ has to import anyway
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "text"
                and node.args
            ):
                continue
            body = node.args[0]
            # Only literals. An f-string cannot be checked without knowing what
            # gets interpolated, and there is a separate guard for those.
            if isinstance(body, ast.Constant) and isinstance(body.value, str):
                found.append((str(path.relative_to(BACKEND)), node.lineno, body.value))
    return found


def _to_positional(sql: str) -> str:
    """Rewrite `:name` to `$n`, reusing the slot when a name repeats."""

    slots: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in slots:
            slots[name] = f"${len(slots) + 1}"
        return slots[name]

    return _BIND.sub(replace, sql)


@pytest_asyncio.fixture
async def engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — no schema to prepare against")
    created = create_async_engine(url)
    try:
        yield created
    finally:
        await created.dispose()


@pytest.mark.asyncio
async def test_every_raw_sql_statement_prepares_against_the_real_schema(engine):
    statements = _statements()
    assert len(statements) > 150, (
        f"only {len(statements)} statements collected — the extractor is broken, "
        "not the code (a silent zero here would make this test vacuous)"
    )

    failures: list[str] = []
    checked = 0
    async with engine.connect() as conn:
        for index, (path, line, sql) in enumerate(statements):
            if not _PREPARABLE.match(sql):
                continue
            checked += 1
            name = f"_sqlcheck_{index}"
            try:
                await conn.execute(text(f"PREPARE {name} AS {_to_positional(sql)}"))
                await conn.execute(text(f"DEALLOCATE {name}"))
            except Exception as exc:  # noqa: BLE001 - the message is the report
                await conn.rollback()
                head = " ".join(sql.split())[:110]
                failures.append(
                    f"{path}:{line}\n    {str(exc).splitlines()[0][:180]}\n    SQL: {head}"
                )

    assert checked > 100, (
        f"only {checked} statements were preparable — filter too strict?"
    )
    assert not failures, "raw SQL that PostgreSQL cannot plan:\n\n" + "\n\n".join(
        failures
    )


def test_no_python_name_leaks_into_a_non_f_string_sql_body():
    """A bare Python name in `text("...")` reaches Postgres as an identifier.

    Kept separate from the PREPARE sweep because it needs no database: it holds
    even when the statement is a fragment, and it names the mistake precisely
    instead of reporting a downstream parse error.
    """

    leaks: list[str] = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        constants = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id.isupper()
        }
        if not constants:
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "text"
                and node.args
            ):
                continue
            body = node.args[0]
            if not (isinstance(body, ast.Constant) and isinstance(body.value, str)):
                continue
            for name in constants:
                # A leading ':' makes it a bind parameter, which is correct.
                if re.search(rf"(?<![\w:]){re.escape(name)}(?![\w])", body.value):
                    leaks.append(f"{path.relative_to(BACKEND)}:{node.lineno} → {name}")

    assert not leaks, "Python name(s) embedded in SQL text: " + "; ".join(leaks)


@pytest.mark.asyncio
async def test_overlong_filename_is_rejected_rather_than_silently_truncated(engine):
    """`CAST(:p AS varchar(n))` truncates; the column constraint refuses.

    The casts that make this statement plannable were first written as
    `CAST(:filename AS varchar(500))`, mirroring the Traffit importer. That is a
    worse bug than the one it fixed: an explicit cast to a length-bounded type
    silently cuts the value to fit, whereas assigning an over-long value to the
    column raises `value too long`. A truncated `filename` is cosmetic; a
    truncated `storage_key` points at a file that cannot be fetched again — and
    nothing anywhere would say so.

    `CAST(:p AS text)` supplies the same type context (which is all Postgres
    needed) without imposing a length, so the column stays the authority.
    """

    from app.services.talent_radar_importer import _UPSERT_CANDIDATE_DOCUMENT

    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            candidate_id = await conn.scalar(
                text(
                    "INSERT INTO candidates (name, lastname, created_at, updated_at) "
                    "VALUES ('T', 'T', NOW(), NOW()) RETURNING id"
                )
            )
            params = {
                "candidate_id": candidate_id,
                "filename": "x" * 900 + ".pdf",  # column is varchar(500)
                "file_content": b"x",
                "storage_key": None,
                "size_bytes": 1,
                "uploaded_at": None,
                "external_id": f"c-{candidate_id}",
                "external_source": "tr_legacy",
                "content_sha256": "a" * 64,
            }
            with pytest.raises(Exception) as excinfo:
                await conn.execute(_UPSERT_CANDIDATE_DOCUMENT, params)
            assert "too long" in str(excinfo.value).lower(), (
                "an over-long filename must be refused, not quietly cut to fit: "
                f"got {excinfo.value}"
            )
        finally:
            await transaction.rollback()
