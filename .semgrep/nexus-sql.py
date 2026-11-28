# Przykłady dla `semgrep --test .semgrep/` (reguły w nexus-sql.yml).
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy import text as sa_text

LITERAL = "SELECT 1"


def build(where):
    return "SELECT 1 FROM t WHERE " + where


def cases(sql, clauses, mod):
    # ok: nexus-sqlalchemy-text-built-elsewhere
    text("SELECT 1")
    # ok: nexus-sqlalchemy-text-built-elsewhere
    text(LITERAL)
    # ok: nexus-sqlalchemy-text-built-elsewhere
    text(f"SELECT {sql}")
    # ok: nexus-sqlalchemy-text-built-elsewhere
    text("SELECT " + sql)
    # ruleid: nexus-sqlalchemy-text-built-elsewhere
    text(sql)
    # ruleid: nexus-sqlalchemy-text-built-elsewhere
    text(build(sql))
    # ruleid: nexus-sqlalchemy-text-built-elsewhere
    text(" AND ".join(clauses))
    # ruleid: nexus-sqlalchemy-text-built-elsewhere
    sa.text(mod.QUERY)
    # ruleid: nexus-sqlalchemy-text-built-elsewhere
    sa_text(clauses[0])
