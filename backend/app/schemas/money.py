"""Koercja kwot dla pól schematu, które niosą PEŁNE złotówki.

Kilka schematów odpowiedzi deklaruje kwoty PLN jako ``int``, ale wartości
przychodzą z ``Contract.monthly_rate_client`` / ``Contract.monthly_margin``,
które zwracają ``Decimal`` — stawka ``Numeric(12,3)`` przemnożona przez liczbę
godzin billingowych (``rate_unit == hourly`` → ``× billing_hours_per_month``).
Pydantic v2 **odrzuca** ``Decimal`` z niezerową częścią dziesiętną dla pola
``int`` (błąd ``int_from_float``), a to leci jako ``ResponseValidationError``
poza handlerami → nieobsłużony wyjątek → 5xx bez nagłówków CORS, czyli w UI
„Nie udało się wczytać…".

Tak padł profil klienta Alior Bank (2026-08-12): stawka godzinowa 141,18 zł
× 160 h = 22 588,80 zł. Na 531 kontraktów w bazie był to jedyny klient
z niecałkowitą kwotą miesięczną — dlatego 29 innych klientów działało i defekt
przeżył miesiące. Gorszy przypadek to ``GET /api/admin/clients-overview``:
zwraca ``list[OverviewRow]``, więc JEDEN taki wiersz wywracał **całą** listę
dla wszystkich użytkowników.

Dlaczego zaokrąglenie, a nie ``Optional[float]``: pole już obiecuje pełne
złotówki (``int``), a sąsiednie kwoty w tych samych klasach są typu
``Decimal | int | None``, który pydantic serializuje do **stringa** w JSON
(patrz komentarz przy ``MoneyPLN`` w ``app/api/contract_analytics.py``) —
zmiana na taki typ podmieniłaby liczbę na tekst i front sklejałby ją
konkatenacją. Zaokrąglamy więc pół w górę, zamiast wywracać odpowiedź:
to implementacja zadeklarowanego kontraktu, nie jego rozszerzenie.

To NIE jest szerokie tłumienie błędu — konwertujemy wyłącznie typy liczbowe
(``Decimal``/``float``). Cokolwiek innego przechodzi nietknięte do zwykłej
walidacji pydantica, więc śmieci nadal dostają 422/500, a nie cichy ``None``.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator

_ONE = Decimal("1")


def to_whole_pln(value: Any) -> Any:
    """Zaokrągl kwotę do pełnych złotych (pół w górę). Reszta typów bez zmian.

    ``bool`` przechodzi nietknięty świadomie — pydantic sam odrzuca ``bool``
    dla pola ``int``, a specjalna gałąź tylko by to zachowanie ukryła.

    PUBLICZNA, bo agregaty muszą zaokrąglać DOKŁADNIE tak samo jak pojedyncze
    wiersze. Kafel „Aktywne MRR" sumował surowe ``Decimal``-e i zaokrąglał raz
    na końcu, a każdy wiersz przechodził przez ``WholePLN`` osobno — suma
    zaokrągleń ≠ zaokrąglenie sumy, więc kafel różnił się od sumy kolumny
    o złotówkę. Kto liczy sumę czegoś, co użytkownik widzi zaokrąglone, musi
    użyć tej funkcji na SKŁADNIKACH, nie na wyniku.
    """
    if isinstance(value, Decimal):
        return int(value.quantize(_ONE, rounding=ROUND_HALF_UP))
    if isinstance(value, float):
        # przez str(), żeby nie wciągać błędu reprezentacji binarnej floata
        return int(Decimal(str(value)).quantize(_ONE, rounding=ROUND_HALF_UP))
    return value


WholePLN = Annotated[int, BeforeValidator(to_whole_pln)]
"""``int`` w pełnych złotych, tolerancyjny na ``Decimal``/``float`` na wejściu."""
