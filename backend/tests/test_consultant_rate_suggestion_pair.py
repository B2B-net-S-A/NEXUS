"""Para (podpowiedź stawki, ostrzeżenie) w pickerze konsultanta.

Obie wartości liczą się z RÓŻNYCH zbiorów kontraktów: podpowiedź wyłącznie
z ``active``/``ending``, ostrzeżenie ze WSZYSTKICH nieanulowanych. Front
renderuje na ich podstawie dwa różne komunikaty, więc ich rozjazd nie jest
detalem implementacyjnym — jest kontraktem. Bez tego testu zmiana katalogu
statusów cicho przywraca ekran, na którym pod PUSTYM polem stoi zdanie
„Wstawiono stawkę z aktywnego kontraktu".
"""

from datetime import date, timedelta
from decimal import Decimal

from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.client_order_lines import _rate_suggestion

_TODAY = date.today()
_PLN = {"PLN": Decimal("1")}


def _contract(
    *, contract_id: int, status: ContractStatus, rate: str, days_ago: int
) -> Contract:
    """Kontrakt dzienny w PLN — 22 MD w miesiącu, więc /MD == stawka dzienna."""
    return Contract(
        id=contract_id,
        candidate_id=1,
        client_id=1,
        status=status,
        start_date=_TODAY - timedelta(days=days_ago),
        rate_candidate=Decimal(rate),
        rate_unit=RateUnit.daily,
        currency="PLN",
    )


def test_returning_consultant_warns_without_suggesting() -> None:
    """Konsultant wraca do klienta: stary ``ended`` + nowy ``draft``.

    Dokładnie scenariusz, wokół którego zbudowany jest ten moduł. Żywego
    kontraktu nie ma, więc podpowiedzi być nie może; stawki historyczna
    i szkicowa różnią się, więc ostrzeżenie MUSI się zapalić. To jest ta
    para, której poprzedni jeden komunikat nie umiał opisać.
    """
    suggested, has_different, current_id = _rate_suggestion(
        [
            _contract(
                contract_id=1,
                status=ContractStatus.ended,
                rate="500.000",
                days_ago=400,
            ),
            _contract(
                contract_id=2,
                status=ContractStatus.draft,
                rate="700.000",
                days_ago=5,
            ),
        ],
        on=_TODAY,
        currency_rates=_PLN,
    )

    assert suggested is None
    assert has_different is True
    assert current_id is None


def test_two_drafts_with_different_rates_warn_without_suggesting() -> None:
    """Drugi wariant tej samej pary — dwa szkice, zero kontraktów żywych."""
    suggested, has_different, current_id = _rate_suggestion(
        [
            _contract(
                contract_id=3,
                status=ContractStatus.draft,
                rate="600.000",
                days_ago=10,
            ),
            _contract(
                contract_id=4,
                status=ContractStatus.draft,
                rate="800.000",
                days_ago=2,
            ),
        ],
        on=_TODAY,
        currency_rates=_PLN,
    )

    assert suggested is None
    assert has_different is True
    assert current_id is None


def test_live_contract_still_supplies_the_suggestion() -> None:
    """Kontrola dodatnia: przy żywym kontrakcie podpowiedź nadal istnieje."""
    suggested, has_different, current_id = _rate_suggestion(
        [
            _contract(
                contract_id=5,
                status=ContractStatus.ended,
                rate="500.000",
                days_ago=400,
            ),
            _contract(
                contract_id=6,
                status=ContractStatus.active,
                rate="700.000",
                days_ago=5,
            ),
        ],
        on=_TODAY,
        currency_rates=_PLN,
    )

    assert suggested == Decimal("700.000000")
    assert has_different is True
    assert current_id == 6
