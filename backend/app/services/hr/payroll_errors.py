"""Błędy modułu Płace — komunikat po polsku dla użytkownika i status HTTP.

Router zamienia je na ``HTTPException``; ``detail`` bywa słownikiem
(``code`` + ``message`` + dane), gdy front ma coś pokazać obok zdania
(np. ostrzeżenia przed zamknięciem miesiąca).
"""

from __future__ import annotations

from typing import Any, Optional


class PayrollError(Exception):
    status_code = 422

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        *,
        code: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.code = code
        self.data = data

    @property
    def detail(self) -> Any:
        if self.code is None and self.data is None:
            return self.message
        return {"code": self.code, "message": self.message, **(self.data or {})}


class PayrollConflict(PayrollError):
    status_code = 409


class PayrollForbidden(PayrollError):
    status_code = 403


class PayrollNotFound(PayrollError):
    status_code = 404


__all__ = ["PayrollConflict", "PayrollError", "PayrollForbidden", "PayrollNotFound"]
