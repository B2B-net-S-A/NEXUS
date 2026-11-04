"""Odmowy modułu „Sprzęt” — polskie zdanie dla recepcji i kod HTTP trasy."""

from __future__ import annotations


class EquipmentError(Exception):
    """Odmowa z polskim zdaniem dla recepcji; ``status`` = kod HTTP trasy."""

    status = 422

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class EquipmentNotFound(EquipmentError):
    status = 404


class EquipmentConflict(EquipmentError):
    status = 409
