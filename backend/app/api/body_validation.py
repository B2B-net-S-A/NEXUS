"""Ciało żądania sprawdzane ręcznie w handlerze: odmowa 422 zamiast 500.

FastAPI zamienia na 422 tylko błędy modeli zadeklarowanych w sygnaturze trasy.
Model budowany w ciele handlera (ciało przyjęte jako słownik, ponowna walidacja
po PATCH-u) rzuca ``pydantic.ValidationError`` — do 02.10.2026 kończyło się to
odpowiedzią 500, a treść wyjątku z wartościami z żądania szła do logu i Sentry.

Globalnego handlera na ``ValidationError`` świadomie nie ma: ten sam wyjątek
rzucają modele budowane z danych wewnętrznych (odpowiedzi, JSON z bazy, odczyt
modelu AI) i tam ma zostać błędem serwera. Zamianę robi więc ten, kto wie, że
sprawdza dane z żądania.
"""

from typing import Any, Optional, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

INVALID_BODY = "Nieprawidłowe dane żądania."


def invalid_body(exc: ValidationError, message: Optional[str] = None) -> HTTPException:
    """422 po polsku: własne zdanie wołającego albo ogólne z nazwami pól.

    Bez surowego zrzutu Pydantica i bez wartości z żądania.
    """
    if message is not None:
        return HTTPException(status_code=422, detail=message)
    fields = sorted(
        {
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors(include_url=False, include_input=False)
            if error.get("loc")
        }
    )
    where = f" Pola do poprawy: {', '.join(fields[:5])}." if fields else ""
    return HTTPException(status_code=422, detail=f"{INVALID_BODY}{where}")


def validated_body(
    model: type[ModelT], payload: Any, message: Optional[str] = None
) -> ModelT:
    """``model.model_validate(payload)``; błąd schematu = 422, nie wyjątek."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise invalid_body(exc, message) from None
