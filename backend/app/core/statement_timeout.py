"""Rozpoznanie instrukcji przerwanej przez `statement_timeout` (SQLSTATE 57014).

Reguła i pomiar: ``docs/claude/podstawy/statement-timeout.md``.
"""

STATEMENT_TIMEOUT_DETAIL = (
    "Operacja trwała zbyt długo i została przerwana. Spróbuj ponownie za chwilę, "
    "a jeśli błąd się powtarza, zgłoś go z podaniem godziny."
)


def is_statement_timeout(exc: BaseException) -> bool:
    """Idzie po przyczynach (``orig`` SQLAlchemy i ``__cause__``), jak ``integer_range``."""
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if getattr(node, "sqlstate", None) == "57014":
            return True
        node = getattr(node, "orig", None) or node.__cause__
    return False
