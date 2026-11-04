"""Błędy spraw wejścia i odejścia — wspólne dla serwisu, szablonów i tras."""

from __future__ import annotations


class LifecycleError(ValueError):
    """Błąd walidacji z komunikatem dla użytkownika (422)."""


class LifecycleConflict(Exception):
    """Stan sprawy nie pozwala na zmianę (409)."""
