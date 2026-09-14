# Finanse → Zmiany w zamówieniach — raport ukończenia

Ticket: nowa zakładka „Zmiany w zamówieniach" w module Finanse z podzakładkami
Zmiany · Wejścia · Zejścia · Braki, eksportem do Excela, licznikami i
powiadomieniem Delivery Leada o brakach.

## Decyzje (Artur, 14.09.2026)

| Pytanie | Decyzja |
|---|---|
| Miesiąc zmiany stawki / daty końca | miesiąc **wprowadzenia** zmiany |
| Przedłużenie tej samej osoby w Wejściach | pokazywane, oznaczone „Kontynuacja po zam. X" |
| Co NIE jest Brakiem | wypowiedziana umowa, szkic następnego zamówienia, decyzja offboardingu MD / „zostaw jako historię" (dodatkowo: zamiana kontraktora) |
| Powiadomienie DL | alert w sekcji DL (powtórka co 7 dni) + dzwonek |

## Co powstało

**Backend**
- Migracja `0308_finance_order_changes` (+ lustro w `entrypoint.sh`):
  tabele `order_change_events`, `order_gaps` (bez FK), typ alertu DL
  `order_missing_successor`, wartość enuma `notificationtype`.
- `services/order_change_audit.py` — dziennik starej → nowej wartości stawki
  kosztowej, przychodowej i daty końca (jedna zmiana na transakcję).
- `services/order_facts.py` — wspólny odczyt: okres efektywny, reguła
  następcy, świadome zakończenia.
- `services/order_gaps.py` + `tasks/order_gaps.py` — wykrywanie braków
  (00:30 Warszawa + start), zamykanie przy zapisie zamówienia i z maila,
  alert DL + dzwonek, reguła powtórki w `dl_alerts_scanner`.
- `services/finance_order_changes.py` — cztery listy + eksport XLSX (4 arkusze).
- Endpointy: `GET /api/finance/order-changes?year&month`,
  `GET /api/finance/order-changes/export?year&month` (sekcja Finance).
- Env: `ORDER_GAPS_ENABLED`, `ORDER_GAP_TRACKING_START` (2026-08-01),
  `ORDER_GAP_LOOKBACK_DAYS` (45), `ORDER_GAPS_RUN_HOUR_LOCAL`/`MINUTE_LOCAL`.

**Frontend**
- `/finance?view=order-changes` (`&sub=entries|exits|gaps`, `&month=RRRR-MM`).
- `components/finance/OrderChangesTab.tsx`, `OrderChangesPanel.tsx`,
  `lib/finance-order-changes.ts`; harness `/preview/finance-order-changes`.
- `DlAlertsSection` znowu zamontowana na pulpicie Delivery Leada (od #1304
  nie była wyświetlana nigdzie).
- Dzwonek: ikona dla `order_missing_successor`.

**Dokumentacja**: sekcja w `CLAUDE.md`, akapit o Brakach w instrukcji zamówień
dla DL (przestemplowana).

## Weryfikacja
- pytest: `test_finance_order_changes.py` (19 testów: dziennik zmian, filtr
  szumu, stan pośredni po synchronizacji, braki i wyłączenia, MD po dacie
  końca, kontrakt bez osoby, okno wsteczne, zamknięcie przez API, widok
  miesiąca, eksport, bramka sekcji) + zestawy zamówień/kontraktów/alertów DL.
- Migracja: upgrade → downgrade do 0307 → upgrade.
- vitest: formatowanie, panel z licznikami, strona Finansów, pulpit DL,
  middleware; `tsc --noEmit` i ESLint czyste.
- Wizualnie: harness w przeglądarce (desktop i 375 px).
- Przegląd adwersarialny: 2 błędy wysokie i 5 średnich — naprawione
  (linie MD po dacie końca, stan pośredni, zamykanie z maila, savepoint na
  brak, zawężenie w SQL, okno wsteczne, kontrakt bez osoby, kill-switch
  przypomnień, dane widoczne przy nieudanym odświeżeniu w tle).

## Znane ograniczenia
- Historia zmian stawek i dat zaczyna się od wdrożenia (starej wartości nigdy
  nie zapisywano) — widok mówi to wprost.
- „Dodatkowy projekt" rozpoznaje równoległe zamówienie tylko u INNEGO klienta.
- Linia MD kończona wyczerpaniem budżetu po więcej niż 45 dniach od daty końca
  nie tworzy braku (okno wsteczne).
- Pierwszy przebieg tworzy braki za okres od 01.08.2026; alerty w sekcji DL
  powstają dla wszystkich otwartych, dzwonek tylko dla świeżych.
