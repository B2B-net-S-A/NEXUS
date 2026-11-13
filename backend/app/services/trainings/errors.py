"""Błąd ścieżki szkolenia: status HTTP, zdanie dla człowieka i stały kod dla frontu."""

from __future__ import annotations


class TrainingError(Exception):
    def __init__(self, status: int, message: str, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
