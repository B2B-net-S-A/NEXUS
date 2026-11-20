"""Ręczny aneks, który niczego nie zmienia, nie powstaje (decyzja Artura 19.11.2026).

Odczyt produkcji 19.11.2026: wśród 130 aneksów kontraktów były 3 grupy
identycznych (ten sam kontrakt, typ, dzień wejścia i nowe wartości: #116, #155,
#444) i jedno „przedłużenie” skracające koniec umowy (#398). Wszystkie powstały
ręcznie w oknie „Dodaj aneks” 29.06–10.07.2026. Aneksu nie da się poprawić ani
usunąć, więc pomyłkę poprawiano kolejnym aneksem. Kwot to nie zmieniało, ale
zakładka „Aneksy” pokazywała trzy aneksy zamiast jednego.

Reguła działa wyłącznie przy ręcznym zapisie (``POST /api/contracts/{id}/amendments``).
Podpis aneksu w Generatorze i wpis stawki z dokumentu (`contract_rate_documents`)
idą bez niej: podpisany dokument ma swój skutek, a automat sam porównuje stawkę
z harmonogramem przed zapisem.

Stawkę porównujemy z harmonogramem w dniu kroku aneksu, nie ze zrzutem
``old_values``. Zrzut trzyma stawkę z kolumny „na dziś”, więc aneks, który
przesuwał dzień wejścia stawki (#398: ta sama stawka od 10.07 przesunięta na
01.07), wyglądał w nim na zmianę „X → X”, choć zmieniał stawkę na dni 01–09.07.
Taki aneks przechodzi.

Moduł nie zna bazy ani routera: stan kontraktu (``AmendmentBaseline``) i
istniejące aneksy podaje wołający (`app/api/contracts.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Protocol, Sequence

from app.core.scheduling import business_date
from app.models.contract_amendment import ContractAmendmentType
from app.schemas.contract_amendment import ContractAmendmentCreate

REASON_DUPLICATE = "amendment_duplicate"
REASON_NO_CHANGE = "amendment_no_change"
REASON_EXTENSION_SHORTENS = "extension_shortens"

# Klucze ``new_values``, po których rozpoznajemy ten sam aneks danego typu.
# Przedłużenie dopisuje też status i koniec zamówienia; to skutek, nie treść aneksu.
_COMPARED_KEYS: dict[ContractAmendmentType, frozenset[str]] = {
    ContractAmendmentType.rate_change: frozenset(
        {"rate_candidate", "rate_client", "rate_unit", "billing_hours_per_month"}
    ),
    ContractAmendmentType.extension: frozenset({"end_date"}),
    ContractAmendmentType.scope_change: frozenset({"project_name", "team_name"}),
}
_NUMERIC_KEYS = frozenset({"rate_candidate", "rate_client", "billing_hours_per_month"})


class ExistingAmendment(Protocol):
    id: int
    new_values: Optional[dict]
    created_at: datetime


@dataclass(frozen=True)
class AmendmentBaseline:
    """Stan kontraktu przed aneksem, z którym porównujemy wpis.

    Stawki to stawki z harmonogramu w dniu, od którego aneks dopisze krok
    (``_amendment_step_from`` w routerze), a przy pustym harmonogramie stawka
    z kolumny, bo od niej powstaje krok „Stawka początkowa”.
    """

    candidate_rate: Optional[Decimal]
    client_rate: Optional[Decimal]
    rate_unit: Optional[str]
    billing_hours_per_month: Optional[int]
    end_date: Optional[date]
    project_name: Optional[str]
    team_name: Optional[str]


@dataclass(frozen=True)
class RedundantAmendment:
    status_code: int
    reason: str
    message: str
    amendment_id: Optional[int] = None

    def detail(self) -> dict[str, Any]:
        out: dict[str, Any] = {"reason": self.reason, "message": self.message}
        if self.amendment_id is not None:
            out["amendment_id"] = self.amendment_id
        return out


def _pl(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _same(key: str, a: object, b: object) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if key in _NUMERIC_KEYS:
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except (InvalidOperation, ValueError):
            return False
    return str(a) == str(b)


def requested_values(data: ContractAmendmentCreate) -> dict[str, Any]:
    """To, co aneks zapisze jako swoją treść w ``new_values``."""

    if data.amendment_type == ContractAmendmentType.rate_change:
        pairs: dict[str, Any] = {
            "rate_candidate": data.new_rate_candidate,
            "rate_client": data.new_rate_client,
            "rate_unit": data.new_rate_unit,
            "billing_hours_per_month": data.new_billing_hours_per_month,
        }
    elif data.amendment_type == ContractAmendmentType.extension:
        pairs = {
            "end_date": data.new_end_date.isoformat() if data.new_end_date else None
        }
    elif data.amendment_type == ContractAmendmentType.scope_change:
        pairs = {"project_name": data.new_project_name, "team_name": data.new_team_name}
    else:
        return {}
    return {key: value for key, value in pairs.items() if value is not None}


def same_amendment(
    amendment_type: ContractAmendmentType,
    requested: Mapping[str, Any],
    stored: Optional[Mapping[str, Any]],
) -> bool:
    """Czy zapisany aneks tego typu ma dokładnie tę treść co żądanie."""

    keys = _COMPARED_KEYS.get(amendment_type)
    if not keys or not requested:
        return False
    stored = stored or {}
    stored_keys = {key for key in keys if stored.get(key) is not None}
    if stored_keys != set(requested):
        return False
    return all(_same(key, requested[key], stored.get(key)) for key in requested)


def _unchanged(data: ContractAmendmentCreate, baseline: AmendmentBaseline) -> bool:
    """Czy każde podane pole ma już tę wartość (pusta lista = nie oceniamy)."""

    checks: list[bool] = []
    if data.amendment_type == ContractAmendmentType.rate_change:
        if data.new_rate_candidate is not None:
            checks.append(
                _same(
                    "rate_candidate", data.new_rate_candidate, baseline.candidate_rate
                )
            )
        if data.new_rate_client is not None:
            checks.append(
                _same("rate_client", data.new_rate_client, baseline.client_rate)
            )
        if data.new_rate_unit is not None:
            checks.append(_same("rate_unit", data.new_rate_unit, baseline.rate_unit))
        if data.new_billing_hours_per_month is not None:
            checks.append(
                _same(
                    "billing_hours_per_month",
                    data.new_billing_hours_per_month,
                    baseline.billing_hours_per_month,
                )
            )
    elif data.amendment_type == ContractAmendmentType.scope_change:
        if data.new_project_name is not None:
            checks.append(
                _same("project_name", data.new_project_name, baseline.project_name)
            )
        if data.new_team_name is not None:
            checks.append(_same("team_name", data.new_team_name, baseline.team_name))
    return bool(checks) and all(checks)


def find_redundant_amendment(
    data: ContractAmendmentCreate,
    baseline: AmendmentBaseline,
    existing: Sequence[ExistingAmendment],
) -> Optional[RedundantAmendment]:
    """Powód odmowy ręcznego aneksu albo ``None``, gdy aneks coś zmienia.

    ``existing`` to aneksy tego kontraktu z tym samym typem i dniem wejścia,
    od najstarszego. Duplikatem jest powtórzenie OSTATNIEGO z nich. Powrót do
    wartości, które później tego samego dnia nadpisał inny aneks, coś zmienia,
    więc rozstrzyga go dopiero porównanie ze stanem kontraktu.
    """

    requested = requested_values(data)
    if existing:
        amendment = existing[-1]
        if same_amendment(data.amendment_type, requested, amendment.new_values):
            saved = business_date(amendment.created_at)
            return RedundantAmendment(
                status_code=409,
                reason=REASON_DUPLICATE,
                message=(
                    f"Taki aneks już jest (zapisany {_pl(saved)}). "
                    "Drugi taki sam niczego nie zmieni."
                ),
                amendment_id=amendment.id,
            )

    if data.amendment_type == ContractAmendmentType.extension:
        new_end = data.new_end_date
        current = baseline.end_date
        if new_end is None or current is None:
            return None
        if new_end == current:
            return RedundantAmendment(
                status_code=422,
                reason=REASON_NO_CHANGE,
                message=(
                    f"Umowa już kończy się {_pl(current)}, "
                    "więc przedłużenie niczego nie zmienia."
                ),
            )
        if new_end < current:
            return RedundantAmendment(
                status_code=422,
                reason=REASON_EXTENSION_SHORTENS,
                message=(
                    f"Przedłużenie nie może skracać umowy (koniec {_pl(current)}). "
                    "Wcześniejszy koniec zapisz oknem „Zakończ współpracę”."
                ),
            )
        return None

    if _unchanged(data, baseline):
        return RedundantAmendment(
            status_code=422,
            reason=REASON_NO_CHANGE,
            message=(
                f"Od {_pl(data.effective_date)} obowiązują już te same wartości, "
                "więc aneks niczego nie zmienia."
            ),
        )
    return None
