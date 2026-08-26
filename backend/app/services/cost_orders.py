"""Zamówienia kosztowe: ustalona kwota, z której schodzi się fakturami.

U Polkomtela obok zamówień rozliczanych liczbą MD funkcjonują zamówienia
z kwotą ustaloną z góry na całe zamówienie. Kwota mieszka na GRUPIE, bo to
jedna pula dzielona przez kilku konsultantów — trzymanie jej per linia
wymagałoby podziału budżetu z góry, czego nikt nie robi, i uniemożliwiłoby
odpowiedź na jedyne pytanie, które tu ma znaczenie: ile jeszcze zostało.

**Rozliczenie jest przeliczane od zera przy każdej zmianie**, dokładnie jak
``md_remaining`` przy liniach MD. To jest mechanizm idempotencji importu, a nie
ostrożność: powtórny import tego samego miesiąca NADPISUJE wiersze konsumpcji
(UNIQUE ``(order_id, period_month)``) i każe przeliczyć budżet od
``budget_amount``, zamiast odjąć kwoty po raz drugi.

**Kolejność rozliczania jest ustalona i musi taka zostać.** Odpowiedź na
pytanie „której osobie zabrakło budżetu" zależy od tego, w jakiej kolejności
faktury schodzą z puli. Sortowanie po ``(period_month, order_id)`` jest
deterministyczne i stabilne między przebiegami, więc ten sam zestaw wierszy
zawsze daje ten sam wynik — inaczej komunikat „brakuje X zł" wskazywałby raz
jedną, raz drugą osobę, zależnie od tego, jak baza akurat zwróciła wiersze.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client_order import ClientOrder
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_EXHAUSTED,
    ClientOrderGroup,
)
from app.models.md_consumption import (
    CONSUMPTION_SOURCE_IMPORT,
    ClientOrderInvoiceConsumption,
)

# Kwoty w złotych — dwa miejsca po przecinku. W odróżnieniu od MD (sześć
# miejsc, bo `kwota / stawka` bywa ułamkiem nieskończonym) tutaj wartości
# wejściowe SĄ kwotami i nic ich nie dzieli.
MONEY_SCALE = Decimal("0.01")
ZERO = Decimal("0.00")


def quantize_money(value: Decimal | int | float | str) -> Decimal:
    """Sprowadza wartość do skali przechowywania kwot."""
    return Decimal(str(value)).quantize(MONEY_SCALE)


def cost_order_client_ids() -> frozenset[int]:
    """Aktualna lista klientów, u których zamówienie może być kosztowe."""
    return settings.cost_order_client_ids


def is_cost_order_client(client_id: int | None) -> bool:
    """Czy u tego klienta wolno założyć zamówienie kosztowe.

    Pusta lista → ``False`` dla każdego klienta (fail-closed): dopóki zmienna
    nie jest ustawiona w Coolify, checkbox nie renderuje się nigdzie, a API
    odrzuca próbę założenia takiego zamówienia.
    """
    if client_id is None:
        return False
    return client_id in cost_order_client_ids()


def assert_cost_order_client(client_id: int | None) -> None:
    """Rzuca ``ValueError`` z komunikatem PL, gdy klient nie jest na liście.

    Bramka stoi przy operacji, nie tylko przy renderowaniu — ukryty checkbox
    nie jest zabezpieczeniem, a zamówienie kosztowe założone u klienta, który
    nigdy nie przyśle faktur z jego numerem, wisiałoby w rejestrze z budżetem,
    którego nic nigdy nie zmniejszy.
    """
    if not is_cost_order_client(client_id):
        raise ValueError(
            "Zamówienia kosztowe są włączone tylko dla wybranych klientów. "
            "Skonfiguruj listę w COST_ORDER_CLIENT_IDS."
        )


# ── Rozliczenie ─────────────────────────────────────────────────────────────


async def lock_group_for_settlement(
    db: AsyncSession,
    group: ClientOrderGroup,
    *,
    flush_local_changes: bool,
) -> ClientOrderGroup:
    """Serialize group settlement and refresh state after any lock wait.

    A manual budget edit mutates the ORM object before recalculation. Flushing
    only that object first preserves the caller's explicit changes and acquires
    the same row lock; ``populate_existing`` can then safely refresh everything
    else. Read-only callers lock first and refresh without an early flush.
    """
    if flush_local_changes:
        await db.flush([group])
    locked_group = await db.scalar(
        select(ClientOrderGroup)
        .where(ClientOrderGroup.id == group.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_group is None:
        raise RuntimeError(
            f"lock_group_for_settlement: brak grupy po blokadzie (id={group.id})"
        )
    return locked_group


async def invoiced_total(db: AsyncSession, order_id: int) -> Decimal:
    """Suma zafakturowana na linii — pole „Zafakturowano" przy konsultancie.

    Sumuje ``invoice_amount`` (pełną kwotę faktury), a NIE ``settled_amount``:
    „ile wystawiliśmy" to inna liczba niż „ile zmieściło się w budżecie", a
    konsultantowi należy się ta pierwsza.
    """
    total = await db.scalar(
        select(
            func.coalesce(func.sum(ClientOrderInvoiceConsumption.invoice_amount), 0)
        ).where(ClientOrderInvoiceConsumption.order_id == order_id)
    )
    return quantize_money(total or 0)


async def settle_group(db: AsyncSession, group: ClientOrderGroup) -> Decimal:
    """Przelicz całe zamówienie kosztowe od zera i zapisz wynik.

    Jedyny writer ``budget_remaining`` oraz ``settled_amount`` /
    ``unsettled_amount``. Zwraca nową pozostałość.

    Pozostałość NIE schodzi poniżej zera — nadwyżka nad budżetem ląduje jako
    ``unsettled_amount`` na konkretnym wierszu, żeby dało się powiedzieć,
    KTÓREJ osobie zabrakło pieniędzy. Sama informacja „budżet przekroczony
    o X zł" bez wskazania osoby nie daje się rozliczyć z klientem.

    Ustawia też ``status='exhausted'``, gdy pula spadnie do zera — i cofa ten
    status, gdy korekta kwoty znów odsłoni budżet. Bez tego cofnięcia podniesienie
    kwoty zamówienia zostawiałoby je w „Wyczerpanych" z dodatnią resztą, czyli
    w stanie, którego interfejs nie umie wytłumaczyć.

    Wszystkie ścieżki przeliczenia serializują się na wierszu grupy *przed*
    odczytem konsumpcji. W przeciwnym razie importer, który policzył na stanie
    sprzed równoległego usunięcia linii, mógłby po jego commicie nadpisać
    poprawne ``budget_remaining`` starym wynikiem. Wąski flush zachowuje lokalną
    korektę kwoty wykonaną przez endpoint edycji, a ``populate_existing`` po
    ewentualnym oczekiwaniu odświeża wszystkie pozostałe pola.
    """
    group = await lock_group_for_settlement(db, group, flush_local_changes=True)

    if not group.is_cost_based or group.budget_amount is None:
        group.budget_remaining = None
        return ZERO

    rows = (
        await db.scalars(
            select(ClientOrderInvoiceConsumption)
            .join(ClientOrder, ClientOrder.id == ClientOrderInvoiceConsumption.order_id)
            .where(ClientOrder.order_group_id == group.id)
            # Deterministyczne i stabilne — patrz docstring modułu.
            .order_by(
                ClientOrderInvoiceConsumption.period_month.asc(),
                ClientOrderInvoiceConsumption.order_id.asc(),
            )
            .execution_options(populate_existing=True)
        )
    ).all()

    budget = quantize_money(group.budget_amount)
    adjustment = quantize_money(group.budget_manual_adjustment or 0)
    pool = budget + adjustment
    if pool < ZERO:
        pool = ZERO

    for row in rows:
        amount = quantize_money(row.invoice_amount)
        settled = amount if amount <= pool else pool
        if settled < ZERO:
            settled = ZERO
        row.settled_amount = settled
        row.unsettled_amount = quantize_money(amount - settled)
        pool = quantize_money(pool - settled)

    group.budget_remaining = pool

    # `completed` (zakończone ręcznie) NIE jest tu ruszane — decyzja człowieka
    # o zamknięciu zamówienia nie może zostać cofnięta przez import.
    if group.status == GROUP_STATUS_ACTIVE and pool <= ZERO:
        group.status = GROUP_STATUS_EXHAUSTED
    elif group.status == GROUP_STATUS_EXHAUSTED and pool > ZERO:
        group.status = GROUP_STATUS_ACTIVE

    return pool


async def upsert_invoice(
    db: AsyncSession,
    *,
    order: ClientOrder,
    period_month: str,
    invoice_amount: Decimal,
    source: str = CONSUMPTION_SOURCE_IMPORT,
    import_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> ClientOrderInvoiceConsumption:
    """Zapisz zafakturowaną kwotę linii za miesiąc (bez przeliczania grupy).

    ``INSERT … ON CONFLICT DO UPDATE``, a nie „SELECT, potem INSERT albo
    UPDATE": ta druga wersja ma okno wyścigu, w którym dwa równoległe importy
    widzą brak wiersza, oba wstawiają i drugie dostaje ``IntegrityError``.

    Przeliczenie grupy jest CELOWO osobnym krokiem — jeden import dokłada wiele
    wierszy do tej samej puli, a rozliczanie po każdym z osobna dawałoby
    pośrednie stany, w których „brakuje X zł" wskazuje osobę, która po
    domknięciu importu mieści się w budżecie.
    """
    amount = quantize_money(invoice_amount)
    stmt = (
        pg_insert(ClientOrderInvoiceConsumption)
        .values(
            order_id=order.id,
            period_month=period_month,
            invoice_amount=amount,
            settled_amount=ZERO,
            unsettled_amount=ZERO,
            source=source,
            import_id=import_id,
            created_by_user_id=user_id,
        )
        .on_conflict_do_update(
            index_elements=[
                ClientOrderInvoiceConsumption.order_id,
                ClientOrderInvoiceConsumption.period_month,
            ],
            set_={
                "invoice_amount": amount,
                "source": source,
                "import_id": import_id,
                "created_by_user_id": user_id,
                "updated_at": func.now(),
            },
        )
        .returning(ClientOrderInvoiceConsumption.id)
    )
    row_id = await db.scalar(stmt)
    row = await db.get(ClientOrderInvoiceConsumption, row_id)
    if row is None:
        # Nie `assert` — ten znika pod `python -O`, a wtedy `None` wędruje do
        # wywołującego i wybucha AttributeError bez śladu, skąd przyszedł.
        # W praktyce `RETURNING` zawsze oddaje id (także w gałęzi DO UPDATE).
        raise RuntimeError(
            f"upsert_invoice: brak wiersza konsumpcji po zapisie (id={row_id})"
        )
    return row


def describe_invoice_import(
    *, group_number: str, period_month: str, total: Decimal
) -> str:
    """Opis zdarzenia „import faktur" dla historii zamówienia."""
    return (
        f"Import faktur za {period_month}: zamówienie {group_number} "
        f"pomniejszone o {quantize_money(total)} zł."
    )
