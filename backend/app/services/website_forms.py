"""Pola formularzy trenera i polecenia ze strony B2B Network (serwer strony → NEXUS).

Strona waliduje to samo po swojej stronie (``src/lib/forms/parse.ts``), więc
422 tutaj to błąd albo zmiana strony, a nie literówka osoby z formularza.
Pola jednowierszowe nie mogą mieć nowej linii: trafiają do kolejki i opisów
jako „Etykieta: wartość”, a nowa linia dopisałaby tam udawany wiersz.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.services.public_apply import field_error

MAX_CONSENTS = 5

_EMAIL = TypeAdapter(EmailStr)


def text(
    form: Any, name: str, max_len: int, *, multiline: bool = False
) -> Optional[str]:
    """Pole tekstowe: przycięte, puste = ``None``, za długie albo z nową linią = 422."""
    value = form.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise field_error(name, "Pole musi być tekstem.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise field_error(
            name, f"Pole może mieć najwyżej {max_len} znaków.", cleaned[:50]
        )
    if not multiline and ("\n" in cleaned or "\r" in cleaned):
        raise field_error(name, "Pole musi mieć jedną linię.", cleaned[:50])
    return cleaned


def required(form: Any, name: str, max_len: int, message: str, **kwargs: Any) -> str:
    value = text(form, name, max_len, **kwargs)
    if value is None:
        raise field_error(name, message)
    return value


def email(value: Optional[str]) -> Optional[str]:
    """Adres po walidacji składni albo ``None``, gdy to nie jest adres."""
    if value is None:
        return None
    try:
        return str(_EMAIL.validate_python(value))
    except ValidationError:
        return None


def required_email(form: Any, name: str, max_len: int, message: str) -> str:
    raw = required(form, name, max_len, message)
    parsed = email(raw)
    if parsed is None:
        raise field_error(name, "Niepoprawny adres e-mail.", raw)
    return parsed


def http_url(form: Any, name: str, max_len: int) -> Optional[str]:
    """Pełny adres http(s). Inne schematy (``javascript:``, ``data:``) = 422."""
    raw = text(form, name, max_len)
    if raw is None:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise field_error(name, "Podaj pełny adres http(s).", raw[:50])
    return raw


def consents(form: Any, name: str, max_len: int) -> tuple[str, ...]:
    """Dosłowne treści zaznaczonych zgód (dowód z RODO art. 7 ust. 1)."""
    picked: list[str] = []
    for value in form.getlist(name):
        if not isinstance(value, str):
            raise field_error(name, "Pole musi być tekstem.")
        cleaned = value.strip()
        if len(cleaned) > max_len:
            raise field_error(name, f"Zgoda może mieć najwyżej {max_len} znaków.")
        if cleaned and cleaned not in picked:
            picked.append(cleaned)
    if not picked:
        raise field_error(
            name,
            "Brak zgody na przetwarzanie danych — bez niej nie możemy przyjąć "
            "zgłoszenia.",
        )
    if len(picked) > MAX_CONSENTS:
        raise field_error(name, "Za dużo zgód w jednym zgłoszeniu.")
    return tuple(picked)
