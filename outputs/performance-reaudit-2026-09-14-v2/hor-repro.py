"""Offline checks of audited functions, extracted unchanged from the snapshot.

No application lifespan, Postgres, network, production records, or paid models.
The SQL witness runs only the original user-selection query in in-memory SQLite;
other aggregate result sets are deterministic synthetic fixtures.
"""
from __future__ import annotations

import ast
import asyncio
import enum
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import threading
import time
import types
import os
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, func, select, text
from sqlalchemy.dialects import sqlite

ROOT = Path('/tmp/nexus-performance-reaudit2-2026-09-14/backend')


def functions_from(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + nodes, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / path), 'exec'), namespace)


async def main():
    metadata = MetaData()
    users = Table('users', metadata, Column('id', Integer), Column('name', String), Column('role', String), Column('is_active', Boolean))
    calls = Table('calls', metadata, Column('id', Integer), Column('user_id', Integer), Column('status', String), Column('created_at', DateTime))
    candidates = Table('candidates', metadata, Column('id', Integer), Column('created_by', Integer), Column('created_at', DateTime))
    ns = dict(select=select, func=func, text=text, User=users.c, Call=calls.c, Candidate=candidates.c,
              CallStatus=SimpleNamespace(completed='completed'), _CALL_EFFECTIVE_AT=calls.c.created_at)
    functions_from('app/analytics/metrics.py', {'team_kpis'}, ns)
    local = sqlite3.connect(':memory:')
    local.execute('CREATE TABLE users (id INTEGER, name TEXT, role TEXT, is_active BOOLEAN)')
    local.execute("INSERT INTO users VALUES(700001,'Synthetic TCM Recruiter','talent_community_manager',1)")

    class Result:
        def __init__(self, rows): self.rows = rows
        def all(self): return self.rows

    class DatabaseFixture:
        n = 0
        async def execute(self, statement, params=None):
            self.n += 1
            if self.n == 1:
                compiled = statement.compile(dialect=sqlite.dialect(), compile_kwargs={'render_postcompile': True})
                bound = tuple(compiled.params[key] for key in compiled.positiontup)
                return Result(local.execute(str(compiled), bound).fetchall())
            if self.n == 2: return Result([(700001, 7)])
            if self.n == 3: return Result([SimpleNamespace(uid=700001, stage='hired', cnt=1)])
            return Result([(700001, 8)])

    from datetime import datetime
    db = DatabaseFixture()
    actual = await ns['team_kpis'](db, SimpleNamespace(start=datetime(2026,9,1), end=datetime(2026,10,1)), user_ids=frozenset({700001}), operational_roles_only=False)
    assert db.n == 4 and [r['user_id'] for r in actual['rows']] == [700001]
    # The actual role helpers accept the same synthetic primary+secondary user.
    user_tree = ast.parse((ROOT / 'app/models/user.py').read_text())
    user_cls = next(n for n in user_tree.body if isinstance(n, ast.ClassDef) and n.name == 'User')
    methods = [n for n in user_cls.body if isinstance(n, ast.FunctionDef) and n.name in {'has_role','has_any_role'}]
    role_cls = next(n for n in user_tree.body if isinstance(n, ast.ClassDef) and n.name == 'UserRole')
    role_ns = dict(enum=enum, Enum=enum.Enum)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), role_cls] + methods, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), 'original_user_role_helpers', 'exec'), role_ns)
    role_enum = role_ns['UserRole']
    model = type('SyntheticUser', (), {name: role_ns[name] for name in ('has_role','has_any_role')})()
    model.role = role_enum.talent_community_manager
    model.roles = ['talent_community_manager','recruiter']
    eligible = model.has_any_role(role_enum.sourcer,role_enum.recruiter,role_enum.tac)
    assert eligible and actual['rows']

    result={"roster_eligible":eligible,"returned_rows":actual["rows"],"queries":db.n}
    Path("/tmp/nexus-reaudit2-evidence-2026-09-14/hor-repro-results.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))

asyncio.run(main())
