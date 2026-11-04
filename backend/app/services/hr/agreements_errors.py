"""Odmowy modułu umów z ludźmi — polskie zdanie dla Kadr i kod HTTP trasy."""

from __future__ import annotations


class AgreementError(Exception):
    """Odmowa z polskim zdaniem; ``status`` = kod HTTP trasy (domyślnie 422)."""

    status = 422

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class AgreementNotFound(AgreementError):
    status = 404


class AgreementConflict(AgreementError):
    status = 409


class AgreementUnavailable(AgreementError):
    """Usługa obok (Autenti, LibreOffice) nie odpowiada albo nie jest ustawiona."""

    status = 503


__all__ = [
    "AgreementConflict",
    "AgreementError",
    "AgreementNotFound",
    "AgreementUnavailable",
]
