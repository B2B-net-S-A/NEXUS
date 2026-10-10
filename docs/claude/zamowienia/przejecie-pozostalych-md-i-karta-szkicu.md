# Przejęcie pozostałych MD i karta szkicu (ticket 09.2026, migracja 0357)

Serwis `app/services/order_line_takeover.py`, trasa
`POST /api/clients/{id}/order-groups/{g}/takeover`, front `lib/order-takeover.ts`
(podgląd tą samą regułą), okna `AssignToOrderModal` (CeZ),
`ReplaceWithTakeoverModal`, `TakeoverTermsFields`, `MdTransferChoice`.

- **Sposób przeniesienia zależy od puli osoby odchodzącej** (`md_input_mode`):
  pula w MD → 1:1, bez przelicznika; pula w kwocie → DL wybiera `departing_rate`
  (X MD) albo `incoming_rate` (X × stawka odchodzącego ÷ stawka przychodzącego,
  0,1 MD). Żadnej opcji nie wybieramy domyślnie. Ta sama reguła w „Wejdź za
  konsultanta", decyzji o MD (`md_transfer_method`), „Zastąp kimś innym" i zamianie
  kontraktora. Zamiana/decyzja BEZ `md_transfer_method` zachowuje stare
  przeliczenie (klienci API sprzed 09.2026) — ekrany wysyłają metodę zawsze.
- **Przejęcie = rozstrzygnięta sprawa offboardingu `transfer` na nową linię**
  (istniejąca albo założona przez serwis): budżet odchodzącego zdejmowany o pulę
  (`_reduce_legacy_md_budget`), więc nie pokazuje już „pozostało" (B2), a korekta
  FIN-MD-02 działa bez zmian. `replaced_by_kind = "takeover"` liczy się w sumie
  pozycji jak zamiana (poprzednik wnosi zużycie). `rate_basis` sprawy jest
  WYPROWADZANY z metody (`stored_rate_basis`) — CHECK zna tylko dwie wartości.
- **Zastępstwo za osobę z przyszłą datą zakończenia jest zaplanowane:** nowa linia
  `draft` z `predecessor_order_id`, plan w payloadzie zdarzenia „dodanie
  konsultanta" (`assignment=takeover`, `scheduled`). `activate_due_takeovers`
  w cyklu `contract_alerts` (PO `_promote_statuses`) przenosi pulę z dnia wejścia,
  gdy odchodzący już nie pracuje. Do tego czasu ręczna decyzja o MD odchodzącego
  → 409. Data wejścia musi być po ostatnim dniu odchodzącego.
- **Karta szkicu** (`ContractWithOrdersRead.draft_card`: żywy kontrakt bez zamówień
  poza szkicami) stoi w pigułce Draft, nie w Aktywnych. „Usuń szkic"
  (`POST …/contractors/{id}/dismiss-draft`, każdy klient) kasuje szkice zamówień
  i stempluje `contracts.orders_card_dismissed_at`; kontrakt zostaje, a zamówienie
  założone później przywraca kartę. „Przypisz do zamówienia" tylko CeZ (front).
- **Dołączenie** idzie zwykłym `POST …/lines` z `assignment: "join"` (plakietka
  „Dołączona"); „wolna pula" = MD czekających spraw offboardingu w zamówieniu —
  ostrzeżenie, nie blokada.
