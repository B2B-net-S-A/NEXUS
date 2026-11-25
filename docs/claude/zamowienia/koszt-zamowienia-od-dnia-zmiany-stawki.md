# Koszt zamówienia od dnia zmiany stawki Partnera (0741, 19.11.2026)
<!-- indeks: części kosztu zamówienia z harmonogramu kontraktu, `client_order_cost_steps`, lista Finansów „Do korekty po zmianie stawki”, `client_order_cost_reviews`, `priced_for_month` z kosztem -->

Zgłoszenie Artura z 18.11.2026 (wariant D z makiet stawek z dokumentów).
Zamówienie Nordei 284887 trwało 01.07–15.12.2026 i miało jedną stawkę kosztu.
Aneks podniósł stawkę Partnera ze 120 na 130 zł/h od 01.09 i na 140 od 01.11,
a synchronizacja kontrakt → zamówienie wpisała 140 na cały okres. Zamówienie
niesie jedną liczbę: stawkę na dziś. Zakończone zamówienia PFRON zostały ze
stawką sprzed aneksu.

Makieta proponowała podział na nowe zamówienia. Artur wybrał 19.11 części
w jednym zamówieniu, bo do 284887 były już przypięte faktury sprzedaży za
każdy miesiąc (`client_sales_invoice_links`), a PDF i opis do faktury Nordei
należą do jednego wiersza. Podział ręczny przez API zrobiliśmy tylko raz,
przy 286585, gdzie zmiana wypadła na granicy faktur.

- **Żywe zamówienie ma części kosztu z harmonogramu kontraktu.** Dotyczy
  szkicu, aktywnego i wstrzymanego zamówienia, poza liniami zamówień
  zbiorczych. Robi to `services/order_cost_steps.py`, a woła je
  `contract_order_sync.sync_orders_cost_from_contract`, także w przebiegu
  dobowym. Wiersze `client_order_cost_steps` powstają tylko przy co najmniej
  dwóch różnych stawkach w okresie zamówienia. Pierwsza część zaczyna się
  w dniu startu. Kolumna `rate_candidate` dalej jest stawką na dzień
  odniesienia (`cost_reference_day`), więc czytnik, który nie zna części,
  liczy jak dotąd. Progresja z umowy w przyszłości (np. 110 → 115 od 01.01)
  też daje części.
- **Miesiąc liczy się stawką z jego pierwszego dnia**, tak samo jak kroki
  przychodu. `order_revenue_steps.priced_for_month` i `priced_one` nakładają
  oba rodzaje kroków (`PricedOrder.rate_candidate`). Nowy czytnik kosztu
  „za miesiąc” z zamówienia musi przejść przez nie. Marża w Insights liczy
  się z harmonogramu kontraktu i części nie potrzebuje.
- **Zakończone zamówienie jest zapisem tego, co rozliczono.** Synchronizacja
  go nie rusza. Gdy harmonogram zmienił się wstecz w jego okresie, zamówienie
  trafia do Finansów → „Rozjazdy stawek” → „Do korekty po zmianie stawki”
  (`GET /api/finance/order-cost-corrections`, odczyt `FinanceModuleUser`).
  Lista obejmuje ostatnie 180 dni, bez linii zbiorczych i bez zamówień bez
  stawki. Decyzje wymagają uprawnienia `AmountsEditUser`:
  - „Ustaw koszt z kontraktu” (`…/{id}/apply`) zapisuje części
    (`source='finance'`) i kolumnę;
  - „Zostaw” (`…/{id}/dismiss`) zapisuje podpis harmonogramu
    w `client_order_cost_reviews`.

  Kolejna zmiana stawki w okresie zamówienia zmienia podpis, więc zamówienie
  wraca na listę. Obie decyzje zostawiają Activity na zamówieniu.
- **Linie zamówień zbiorczych MD/kosztowych są poza tym.** Ich stawkę dalej
  prowadzi Delivery Lead. Rozjazd z kontraktem pokazuje nocny raport linii MD
  w tej samej zakładce. Rozliczenie klienta liczy jednak koszt takiej linii ze
  stawki kontraktu, gdy ta obowiązuje cały miesiąc
  (`finanse-insights/rozliczenia-delegacje-i-zmiana-stawki-w-miesiacu.md`).
- **Widok:** zamówienie w API ma `cost_parts` (`[{from, to, rate}]`, redagowane
  razem z `rate_candidate`). Tabela zamówień klienta pokazuje pod kosztem
  „w częściach od zmiany stawki”, a panel osoby pokazuje pełną linię
  „120 PLN/h do 31.08.2026 · 130 PLN/h od 01.09.2026 · …”.
- Pomiar na produkcji 19.11, tylko odczyt: części dostanie 8 żywych zamówień
  (284887 i 7 innych, głównie z progresją z umowy). Lista „Do korekty” ma 1 pozycję,
  po korektach PFRON zrobionych tego dnia ręcznie.
- Testy: `test_order_cost_steps_rules.py` (bez bazy), `test_order_cost_steps_api.py`,
  `OrderCostCorrections.test.tsx`, `contractor-order-row.test.ts`.
