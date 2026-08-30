"""Zamówienia wielo-konsultantowe — bramka klientów + arytmetyka MD.

Klienci rozliczani w modelu T&M na MD (BIK, Polkomtel, BNP) dostają od klienta
JEDNO zamówienie obejmujące kilku konsultantów naraz, każdego z własną stawką
i własnym budżetem MD. Reszta klientów zostaje przy modelu „jeden kontraktor =
jedno zamówienie", który obsługuje ``app/api/client_orders.py``.

**Bramka idzie po ``client_id``, nigdy po nazwie.** Ten sam powód co przy
Centrum e-Zdrowia (``app/services/ezdrowie.py``): Traffit nadpisuje
``Client.name`` przy każdym syncu, a „BNP" to RODZINA rekordów, więc needle
nazwowy potrafi po cichu objąć albo pominąć klienta. Lista żyje w JEDNYM
miejscu — zmiennej ``MULTI_CONSULTANT_ORDER_CLIENT_IDS`` (CSV, Coolify env
vault) — więc dopisanie kolejnego klienta nie wymaga deployu.

Frontend NIE dostaje kopii tej listy. W odróżnieniu od ``ezdrowie.ts`` (gdzie
jedno stałe ID jest zduplikowane po obu stronach) tutaj lista jest zmienną
środowiskową, więc lustro w bundlu byłoby nieaktualne od pierwszej zmiany
w Coolify. Zamiast tego API wystawia wyliczoną flagę przy kliencie.

Arytmetyka MD i precyzja
------------------------
``md_calkowite = kwota / stawka_przychodowa`` bywa ułamkiem nieskończonym
(10 000 / 3), więc „bez zaokrąglenia" jest fizycznie nieosiągalne w typie
stałoprzecinkowym. Nośnikiem jest ``Numeric(16, 6)``: sześć miejsc po przecinku
to zapas rzędu czterech miejsc ponad prezentację (2 miejsca), więc kolejne
importy i zamiany kontraktora nie kumulują błędu widocznego dla użytkownika.
Zaokrąglenie do 2 miejsc następuje WYŁĄCZNIE przy wyświetlaniu — nigdy przed
zapisem i nigdy przed kolejnym działaniem.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.core.config import settings
from app.services.cyfrowy_polsat_orders import (
    is_cyfrowy_polsat_order_types_client,
)
from app.services.lotte_wedel_orders import is_lotte_wedel_order_types_client

# Skala przechowywania MD i kwot pochodnych. Musi zgadzać się ze scale kolumn
# Numeric(16, 6) w migracji — rozjazd oznaczałby, że baza dokłada własne,
# ciche zaokrąglenie na ścieżce zapisu.
MD_SCALE = Decimal("0.000001")

# Zaokrąglenie prezentacyjne (UI, treść wpisów w historii). NIE zapisywane.
MD_DISPLAY_SCALE = Decimal("0.01")

# Tryb wprowadzania budżetu linii konsultanta.
INPUT_MODE_MD = "md"
INPUT_MODE_AMOUNT = "amount"
INPUT_MODES: tuple[str, ...] = (INPUT_MODE_MD, INPUT_MODE_AMOUNT)

# Typy zdarzeń w historii zamówienia (lustro CHECK-a w migracji).
EVENT_ORDER_CREATED = "utworzenie"
EVENT_CONSULTANT_ADDED = "dodanie_konsultanta"
EVENT_MD_IMPORT = "import_md"
EVENT_CONSULTANT_SWAPPED = "zamiana_kontraktora"
EVENT_MANUAL_EDIT = "edycja_reczna"
EVENT_ORDER_CLOSED = "zakonczenie"
EVENT_ORDER_REOPENED = "przywrocenie"
EVENT_BUDGET_EXHAUSTED = "wyczerpanie"
EVENT_ORDER_EXTENDED = "przedluzenie"
EVENT_INVOICE_IMPORT = "import_faktur"
# Podział zużycia MD między zamówieniem bieżącym a jego następcą (migracja
# 0242). Produkuje go `client_order_lines`, ale stała mieszka TUTAJ razem
# z resztą — rozdzielony rejestr to dokładnie ten dryf, przez który wartość
# trafia do bazy bez etykiety i renderuje się użytkownikowi surowym slugiem.
EVENT_MD_TRANSFER = "transfer_md"
EVENT_CONSULTANT_ENDED = "zakonczenie_konsultanta"
EVENT_MD_OFFBOARDING_PENDING = "decyzja_md_wymagana"
EVENT_MD_OFFBOARDING_REMOVED = "usuniecie_puli_md"
EVENT_MD_OFFBOARDING_TRANSFERRED = "przeniesienie_puli_md"
EVENT_TYPES: tuple[str, ...] = (
    EVENT_ORDER_CREATED,
    EVENT_CONSULTANT_ADDED,
    EVENT_MD_IMPORT,
    EVENT_CONSULTANT_SWAPPED,
    EVENT_MANUAL_EDIT,
    EVENT_ORDER_CLOSED,
    EVENT_ORDER_REOPENED,
    EVENT_BUDGET_EXHAUSTED,
    EVENT_ORDER_EXTENDED,
    EVENT_INVOICE_IMPORT,
    EVENT_MD_TRANSFER,
    EVENT_CONSULTANT_ENDED,
    EVENT_MD_OFFBOARDING_PENDING,
    EVENT_MD_OFFBOARDING_REMOVED,
    EVENT_MD_OFFBOARDING_TRANSFERRED,
)

EVENT_TYPE_LABELS: dict[str, str] = {
    EVENT_ORDER_CREATED: "Utworzenie zamówienia",
    EVENT_CONSULTANT_ADDED: "Dodanie konsultanta",
    EVENT_MD_IMPORT: "Import MD",
    EVENT_CONSULTANT_SWAPPED: "Zamiana kontraktora",
    EVENT_MANUAL_EDIT: "Edycja ręczna",
    EVENT_ORDER_CLOSED: "Zakończenie zamówienia",
    EVENT_ORDER_REOPENED: "Przywrócenie zamówienia",
    EVENT_BUDGET_EXHAUSTED: "Wyczerpanie budżetu",
    EVENT_ORDER_EXTENDED: "Przedłużenie",
    EVENT_INVOICE_IMPORT: "Import faktur",
    EVENT_MD_TRANSFER: "Przejęcie zużycia MD",
    EVENT_CONSULTANT_ENDED: "Zakończenie współpracy konsultanta",
    EVENT_MD_OFFBOARDING_PENDING: "Decyzja o pozostałej puli MD",
    EVENT_MD_OFFBOARDING_REMOVED: "Usunięcie pozostałej puli MD",
    EVENT_MD_OFFBOARDING_TRANSFERRED: "Przeniesienie pozostałej puli MD",
}


def multi_consultant_client_ids() -> frozenset[int]:
    """Aktualna lista klientów objętych modelem wielo-konsultantowym."""
    return settings.multi_consultant_order_client_ids


def is_multi_consultant_client(client_id: int | None) -> bool:
    """Czy ten klient renderuje widok wielo-konsultantowy.

    Lista z ENV zachowuje dotychczasową konfigurację. Cyfrowy Polsat i Lotte
    Wedel są osobnymi, zahardkodowanymi wyjątkami swoich ticketów i pozostają
    włączone także przy pustej liście.
    """
    if client_id is None:
        return False
    return (
        client_id in multi_consultant_client_ids()
        or is_cyfrowy_polsat_order_types_client(client_id)
        or is_lotte_wedel_order_types_client(client_id)
    )


def assert_multi_consultant_client(client_id: int | None) -> None:
    """Rzuca ``ValueError`` z komunikatem PL, gdy klient nie jest na liście.

    Bramka stoi przy KAŻDEJ operacji na liniach, nie tylko przy renderowaniu
    widoku. Sam ukryty przycisk nie jest zabezpieczeniem — bez tego wywołanie
    API wprost założyłoby wielo-konsultantowe zamówienie u klienta, którego
    zakładka nigdy go nie pokaże, czyli dane nie do zobaczenia i nie do
    poprawienia z interfejsu.
    """
    if not is_multi_consultant_client(client_id):
        raise ValueError(
            "Zamówienia wielo-konsultantowe są włączone tylko dla wybranych "
            "klientów (BIK, Polkomtel, BNP). Skonfiguruj listę w "
            "MULTI_CONSULTANT_ORDER_CLIENT_IDS."
        )


def quantize_md(value: Decimal | int | float | str) -> Decimal:
    """Sprowadza wartość do skali przechowywania MD."""
    try:
        return Decimal(str(value)).quantize(MD_SCALE)
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise ValueError("Nieprawidłowa wartość liczbowa") from exc


def format_md(value: Decimal | int | float | None) -> str:
    """Prezentacja MD — 2 miejsca po przecinku (patrz docstring modułu)."""
    if value is None:
        return "—"
    return str(Decimal(str(value)).quantize(MD_DISPLAY_SCALE))


def compute_md_total(
    *,
    input_mode: str,
    input_value: Decimal,
    rate_revenue: Decimal,
) -> Decimal:
    """MD całkowite linii — z liczby MD albo z kwoty zamówienia.

    ``input_mode="md"``     → wartość wejściowa JEST liczbą MD.
    ``input_mode="amount"`` → ``md = kwota / stawka_przychodowa``.

    Stawka przychodowa jest dzielnikiem, więc zero jest odrzucane tutaj, a nie
    dopiero przez ``DivisionByZero`` w środku transakcji.
    """
    if input_mode not in INPUT_MODES:
        raise ValueError("Nieprawidłowy tryb wprowadzenia budżetu")
    if input_value is None:
        raise ValueError("Podaj wartość budżetu")
    value = Decimal(str(input_value))
    if value < 0:
        raise ValueError("Budżet nie może być ujemny")
    if input_mode == INPUT_MODE_MD:
        return quantize_md(value)
    rate = Decimal(str(rate_revenue or 0))
    if rate <= 0:
        raise ValueError(
            "Stawka przychodowa musi być większa od zera, żeby przeliczyć "
            "kwotę zamówienia na MD"
        )
    return quantize_md(value / rate)


def swap_md_total(
    *,
    md_remaining_old: Decimal,
    rate_revenue_old: Decimal,
    rate_revenue_new: Decimal,
) -> Decimal:
    """MD nowego konsultanta przy zamianie — zachowuje wartość w PLN.

    ``md_nowe × stawka_nowa == md_stare_pozostale × stawka_stara``

    Zamiana przelicza wyłącznie MD POZOSTAŁE. MD już zaraportowane rozlicza się
    stawką poprzednika — dlatego zamiana działa od dnia zamiany w przód i nie
    dotyka wpisów konsumpcji sprzed tej daty.

    Ujemne ``md_remaining_old`` (przekroczony budżet) jest przenoszone jako
    ujemne, a nie ścinane do zera: przekroczenie jest faktem handlowym i
    wyzerowanie go tutaj po cichu darowałoby klientowi różnicę.
    """
    new_rate = Decimal(str(rate_revenue_new or 0))
    if new_rate <= 0:
        raise ValueError("Stawka przychodowa nowego konsultanta musi być > 0")
    remaining_value_pln = Decimal(str(md_remaining_old)) * Decimal(
        str(rate_revenue_old)
    )
    return quantize_md(remaining_value_pln / new_rate)


def remaining_value_pln(*, md_remaining: Decimal, rate_revenue: Decimal) -> Decimal:
    """Wartość pozostała linii w PLN — do podglądu przy zamianie kontraktora."""
    return (Decimal(str(md_remaining)) * Decimal(str(rate_revenue))).quantize(
        MD_DISPLAY_SCALE
    )
