# Kafelek kontraktora: status zamówienia musi zgadzać się z okresem (29.09.2026)

Zgłoszenie: kafelki z zamówieniem kończącym się jutro mówiły „Brak aktywnego
zamówienia” albo „przyszłe zamówienie … kończy się za 1 dzień” i nie miały
„Zakończ zamówienie”. Dwie niezależne przyczyny, obie łatwo cofnąć:

- **Rozjazd danych: `completed` przy końcu w PRZYSZŁOŚCI.** Każda droga
  zamykająca zamówienie (`close_order`, offboarding, sync terminacji) ucina
  `end_date` do dnia zamknięcia, więc legalnie zamknięte kończy się najpóźniej
  dziś. `completed` z późniejszym końcem to edycja dat sprzed #1638 (21.09) —
  `refresh_periodic_order_status` przelicza status tylko przy zapisie OKRESU,
  a późniejsza zmiana samej stawki go nie ruszała. Na produkcji cztery umowy
  (stare wiersze z importów Excela/Nordea). Naprawia to nocny skaner:
  `dl_portal_expiry_scanner.revive_stale_completed_periodic_orders`, wołany
  z `run_once` PRZED `_promote_statuses` (pętla robi pierwszy bieg przy starcie
  kontenera, więc naprawa wchodzi z deployem). Bezpieczniki (jedna definicja
  `_revivable_clause` dla SELECT i UPDATE): koniec ŚCIŚLE po dziś (zamknięcie
  „dziś” zostaje `completed`), start znany, umowa `active`/`ending`, ten sam
  klient i data końca umowy NIE wcześniejsza niż koniec zamówienia (zamówienie
  nie przeżywa umowy — inaczej nocny reconcile mógłby wskrzesić wypowiedzianą
  umowę), tylko efektywny typ okresowy, nie ożywia duplikatu (umowa ma inne
  aktywne/wstrzymane zamówienie obejmujące dziś) ani zamówienia osoby z żywą
  linią MD/kosztową (jak ścieżki automatyczne, `order_engagement_separation`),
  najwyżej jedno zamówienie na umowę na bieg. Krok jest w savepoincie — jego
  błąd (`logger.exception` → Sentry) nie zatrzymuje przejść statusów ani
  alertów. Kierunek odwrotny do `periodic_due` (koniec < dziś), więc bez
  ping-ponga.
- **UI: „bieżące” zamówienie ≠ pierwszy wiersz.** `splitOrders` wybiera do
  górnego slotu zamówienie, które TRWA (`isCurrentOrder`), a dopiero bez
  takiego ostatnie rozpoczęte. Kontrakt z dwoma wierszami tego samego okresu
  (stary `completed` obok aktywnego) miał w slocie martwy wiersz. Plakietka
  „przyszłe zamówienie … kończy się za N dni” pojawia się tylko dla
  zamówienia z listy „Przyszłe zamówienie” tej karty (`futureOrders`, podział
  po `orderNotStarted` — start po dziś), NIE z porównania id z górnym slotem;
  zamówienie, które trwa (także jedyne, które jeszcze się nie zaczęło i stoi
  w slocie), mówi „kończy się za N dni” bez numeru.
