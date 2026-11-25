# Rozliczenia: dni na kolejnych zamówieniach kontraktu, gdy pula się kończy

<!-- indeks: _pool_split, podział z pul, kolejne zamówienia, dwie linie w miesiącu, Ponad zamówienie, pula na wyczerpaniu, nowe zamówienie od połowy miesiąca, split_auto, Podział na kolejne zamówienia kontraktu, _closed_for, Zamówienie zakończone w NEXUS-ie, status completed po miesiącu -->

Od 25.11.2026. Próby rozliczeń VI–X 2026 (kopia produkcji): rozliczenie brało jedną linię
zamówienia osoby (`service._order_for`: trwająca w miesiącu, aktywna, najnowsza). Gdy osoba
miała w miesiącu dwie linie, np. starą pulę na wyczerpaniu i nowe zamówienie od połowy
miesiąca albo dwa równoległe, rozliczenie stało na „Ponad zamówienie”, a Finanse dzieliły
fakturę na obie linie.

## Podział z pul (`service._pool_split`)

- Wchodzi tylko wtedy, gdy linia wybrana przez `_order_for` nie mieści dni zwykłych i nie ma
  podziału z maila klienta (ten ma pierwszeństwo, `rozliczenia-podzial-na-zamowienia-z-maila.md`).
- Kolejność: od najwcześniej rozpoczętej linii trwającej w miesiącu. Każda bierze tyle, ile
  zostało w jej puli, a linia bez puli MD bierze resztę.
- Gdy pule wszystkich linii nie mieszczą MD, zostaje jedno zamówienie i „Ponad zamówienie”
  jak dotąd (karta DL `rule_settlement_over_order`).
- Silnik liczy części jak przy mailu: linia, stawka, zejście i faktura na każde zamówienie.
  Uwaga to „Podział na kolejne zamówienia kontraktu” (stan ok). Przy pracy dodatkowej albo
  MD wdrożeniowych podział nie wchodzi i rozliczenie wraca po cichu na jedno zamówienie
  (`Inputs.split_auto`), bez uwagi „Podział z maila klienta nie wszedł”.
- Linia wybrana przez `_order_for`, która mieści MD, zostaje jak była. Zmiana nie rusza
  rozliczeń, które dziś są „Bez uwag”.

## „Zamówienie zakończone” względem miesiąca (`service._closed_for`)

Linia z datą końca jest zakończona dla miesiąca tylko wtedy, gdy skończyła się przed jego
początkiem. Status `completed` ustawiony po miesiącu (zamówienie do 30.10, rozliczenie za
wrzesień przeliczone w listopadzie) nie daje już uwagi „Zamówienie zakończone w NEXUS-ie”.
Bez daty końca rozstrzyga status.
