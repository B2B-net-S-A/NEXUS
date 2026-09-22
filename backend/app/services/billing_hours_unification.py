"""Jednorazowe ujednolicenie godzin rozliczeniowych do 168 h/mc (0343, 22.09.2026).

Audyt statystyk (22.09.2026, zmierzone na produkcji): aktywne kontrakty miały
``billing_hours_per_month`` 160 (domyślne — 443 kontrakty) albo 176 (39
kontraktów przeliczonych z MD, ``contract_order_sync``/0309), a normalizacja
budżetu i frontend liczyły 168 h, a stawkę dzienną ``Contract.monthly_rate``,
raporty i analityka — 22 MD. Ta sama stawka godzinowa dawała więc MRR różny
o ~10%. Decyzja Artura: JEDEN miesiąc roboczy — 21 MD × 8 h = 168 h
(``app.core.work_time``).

Korekta (jedno źródło SQL-a dla migracji 0343 i lustra w ``entrypoint.sh``):

1. **znacznik „zamówienia w MD"** — kontrakt godzinowy ze 176 h był
   rozpoznawany jako przeliczony z MD (zamówienia dziedziczące z niego zostają
   w MD, ``order_unit_for_contract``). Po zmianie godzin liczba przestaje go
   odróżniać, więc fakt przechodzi NAJPIERW do ``contracts.orders_in_md``;
2. ``contracts.billing_hours_per_month`` 160 i 176 → 168. Każda inna, jawnie
   wybrana liczba zostaje nietknięta (i jest policzona w paragonie);
3. ``client_orders.billing_hours_per_month`` 160 i 176 → 168. Godziny
   zamówienia są wyłącznie analityczne i domyślne: liczą marżę/mc wiersza
   zamówienia i godzinowy ekwiwalent w profilu klienta, a przy RĘCZNEJ zmianie
   jednostki zamówienia podpowiadają przelicznik. Nie czyta ich odczyt PDF,
   reguły poczty zamówień, import zużycia MD ani rozliczenia — żadna zapisana
   kwota zamówienia nie zmienia się w tej korekcie.

Żadna stawka nie jest przepisywana (zmienia się wyłącznie przelicznik na
miesiąc). Paragon niesie same liczby, w tym ``cross_unit_live_orders``:
zamówienia samodzielne (nie anulowane), których jednostka jest miesięczna przy
kontrakcie godzinowym albo odwrotnie (albo MD ↔ miesiąc). Ich koszt jest
projekcją stawki kontraktu (``sync_orders_cost_from_contract``), więc
najbliższa synchronizacja przeliczy go nowym miesiącem — kwota miesięczna
zostaje zgodna z kontraktem.

Jednorazowe: marker w ``app_settings`` + advisory lock. Bez markera każdy start
przepisywałby na 168 także liczby, które ktoś po korekcie świadomie wpisał.
Czekanie na blokady ograniczone ``lock_timeout`` — po przekroczeniu blok pada
w całości, marker nie powstaje, następny start spróbuje ponownie.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.core.work_time import HOURS_PER_MONTH

BILLING_HOURS_MARKER = "0343_billing_hours_168"
LOCK_TIMEOUT = "15s"
# Liczby godzin, które powstały jako DOMYŚLNE (160) albo jako znacznik
# kontraktu przeliczonego z MD (176). Tylko one są przepisywane.
LEGACY_DEFAULT_HOURS = 160
LEGACY_MD_HOURS = 176
LEGACY_HOURS = (LEGACY_DEFAULT_HOURS, LEGACY_MD_HOURS)

BILLING_HOURS_UNIFICATION_SQL = f"""
DO $$
DECLARE
    v_marker text := '{BILLING_HOURS_MARKER}';
    v_previous_lock_timeout text := current_setting('lock_timeout');
    v_md_marked integer := 0;
    v_contracts_from_160 integer := 0;
    v_contracts_from_176 integer := 0;
    v_contracts_other integer := 0;
    v_orders_from_160 integer := 0;
    v_orders_from_176 integer := 0;
    v_orders_other integer := 0;
    v_cross_unit integer := 0;
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    -- Rolling deploy potrafi uruchomić blok dwa razy równolegle.
    PERFORM pg_advisory_xact_lock(hashtext(v_marker));
    IF EXISTS (SELECT 1 FROM app_settings WHERE key = v_marker) THEN
        PERFORM set_config('lock_timeout', v_previous_lock_timeout, true);
        RETURN;
    END IF;

    -- 1. Znacznik PRZED zmianą godzin — potem 176 przestaje go odróżniać.
    UPDATE contracts
       SET orders_in_md = true
     WHERE rate_unit = 'hourly'
       AND billing_hours_per_month = {LEGACY_MD_HOURS}
       AND orders_in_md IS DISTINCT FROM true;
    GET DIAGNOSTICS v_md_marked = ROW_COUNT;

    SELECT count(*) FILTER (WHERE billing_hours_per_month = {LEGACY_DEFAULT_HOURS}),
           count(*) FILTER (WHERE billing_hours_per_month = {LEGACY_MD_HOURS}),
           count(*) FILTER (
               WHERE billing_hours_per_month NOT IN ({LEGACY_DEFAULT_HOURS}, {LEGACY_MD_HOURS}, {HOURS_PER_MONTH})
           )
      INTO v_contracts_from_160, v_contracts_from_176, v_contracts_other
      FROM contracts;
    SELECT count(*) FILTER (WHERE billing_hours_per_month = {LEGACY_DEFAULT_HOURS}),
           count(*) FILTER (WHERE billing_hours_per_month = {LEGACY_MD_HOURS}),
           count(*) FILTER (
               WHERE billing_hours_per_month NOT IN ({LEGACY_DEFAULT_HOURS}, {LEGACY_MD_HOURS}, {HOURS_PER_MONTH})
           )
      INTO v_orders_from_160, v_orders_from_176, v_orders_other
      FROM client_orders;

    -- Informacyjnie: projekcje kosztu między podstawami czasu, które
    -- synchronizacja przeliczy nowym miesiącem (patrz docstring modułu).
    SELECT count(*)
      INTO v_cross_unit
      FROM client_orders o
      JOIN contracts c ON c.id = o.contract_id
     WHERE o.order_group_id IS NULL
       AND o.status <> 'cancelled'
       AND o.rate_unit <> c.rate_unit
       AND 'monthly' IN (o.rate_unit::text, c.rate_unit::text);

    -- 2 i 3. Wyłącznie wartości domyślne/znacznikowe; reszta nietknięta.
    UPDATE contracts
       SET billing_hours_per_month = {HOURS_PER_MONTH}
     WHERE billing_hours_per_month IN {LEGACY_HOURS};
    UPDATE client_orders
       SET billing_hours_per_month = {HOURS_PER_MONTH}
     WHERE billing_hours_per_month IN {LEGACY_HOURS};

    INSERT INTO app_settings (key, value)
    VALUES (
        v_marker,
        jsonb_build_object(
            'revision', v_marker,
            'completed_at', clock_timestamp(),
            'hours_per_month', {HOURS_PER_MONTH},
            'contracts_marked_orders_in_md', v_md_marked,
            'contracts_from_160', v_contracts_from_160,
            'contracts_from_176', v_contracts_from_176,
            'contracts_other_hours_left', v_contracts_other,
            'orders_from_160', v_orders_from_160,
            'orders_from_176', v_orders_from_176,
            'orders_other_hours_left', v_orders_other,
            'cross_unit_live_orders', v_cross_unit
        )
    )
    ON CONFLICT (key) DO NOTHING;

    PERFORM set_config('lock_timeout', v_previous_lock_timeout, true);
    RAISE NOTICE '0343 billing hours: contracts 160=% 176=%, orders 160=% 176=%',
        v_contracts_from_160, v_contracts_from_176,
        v_orders_from_160, v_orders_from_176;
END
$$;
"""


def summarize_receipt_for_log(receipt: Optional[Mapping[str, Any]]) -> str:
    """Jedna linia do logu kontenera — same liczby."""
    if not receipt:
        return "no receipt"
    keys = (
        "contracts_marked_orders_in_md",
        "contracts_from_160",
        "contracts_from_176",
        "contracts_other_hours_left",
        "orders_from_160",
        "orders_from_176",
        "orders_other_hours_left",
        "cross_unit_live_orders",
    )
    return " ".join(f"{key}={int(receipt.get(key) or 0)}" for key in keys)
