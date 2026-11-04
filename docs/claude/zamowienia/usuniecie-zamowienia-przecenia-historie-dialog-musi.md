# Usunięcie zamówienia przecenia historię — dialog musi to powiedzieć (18.09.2026)

- **`ContractClientRate.source_order_id` ma `ondelete=CASCADE`.** Komentarz przy
  kolumnie zawęża intencję do SZKICU, ale `delete_order` kasuje od #1594
  w KAŻDYM statusie, więc razem z zamówieniem znika krok harmonogramu stawki
  klienta. `Contract._resolve_scheduled_rate` przy braku kroku obowiązującego
  sięga po NAJBLIŻSZY PRZYSZŁY — miesiące historyczne dostają wtedy stawkę,
  której wtedy nie było. Na produkcji: 99 zamówień ma własny krok, 31
  kontraktów ma ich więcej niż jeden, 5 z różnymi kwotami (kontrakt 167:
  usunięcie zamówienia 351 przecenia III–VIII z 185,00 na 178,00 zł/h).
- **Skutki liczy SERWER** (`GET /api/clients/{c}/orders/{o}/delete-preview`,
  wyłącznie odczyt) — front nie zgaduje, bo reguła wyboru stawki zastępczej
  żyje w modelu kontraktu i rozjechałaby się przy pierwszej jej zmianie.
  Kwoty redagowane jak wszędzie w module (`_can_see_finance`): rola bez
  finansów widzi, ŻE okres się przeceni, i od kiedy — bez kwot.
- **Dialog zamiast `window.confirm`** (`components/orders/DeleteOrderDialog.tsx`,
  zdania w `lib/order-delete-consequences.ts`). Stary tekst obiecywał „umowa
  tej osoby nie zmieni się" i był nieprawdą; przy okazji natywny dialog
  ZAMRAŻA automatyzację przeglądarki, więc tej ścieżki nie dało się przeklikać.
  Zdanie „nic się nie zmieni" pada wyłącznie wtedy, gdy lista skutków jest
  pusta. Dopóki podgląd się nie wczytał, przycisk „Usuń" jest wyłączony:
  „nie wiem" nie jest tym samym co „nic się nie stanie".
- Rozliczenia nadal blokują usunięcie (409, `settlement_blockers`) — dialog
  tylko mówi to WCZEŚNIEJ i nazywa, co by przepadło.
