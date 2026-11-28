# Dzwonienie: akcje zbiorcze w Tabeli — decyzja Artura 27.11.2026 (wariant A)
<!-- indeks: zaznaczanie w Tabeli, Zaznacz wszystkie z filtra GET /record-ids BULK_LIMIT 5000, POST /records/bulk assign move remove restore dry_run, removed_at removed_by_user_id migracja 0802, Usuń z listy Cofnij, bramka importu widzi usunięte, Umówione spotkanie nie znika, already_in_campaign przy przeniesieniu, not_on_list, blokada importu LOCK_KEY, calling_bulk.py, CallBulkBar -->

Powód: lista „Nexus - zmiany do wdrożenia”, punkt 3.2. Osoby dzwoniące zmieniały rekordy
pojedynczo, a Tabela osoby ma ok. 2700 rekordów.

Kod: `backend/app/services/sales/calling_bulk.py`, trasy `GET /api/sales/calling/record-ids`
i `POST /api/sales/calling/records/bulk`, front `CallBulkBar.tsx` i pola wyboru w `CallTableView.tsx`.

- **Gdzie:** tylko Tabela (tam są filtry). Kolejka zostaje do dzwonienia po kolei.
  Pole wyboru ma tylko rekord kampanii; pozycja szansy (bez kampanii) idzie za szansą.
  Zaznaczenie przeżywa zmianę strony, filtr je czyści. „Zaznacz wszystkie N z filtra” bierze id
  z serwera tymi samymi filtrami co lista (najwyżej 5000).
- **Kto:** każdy z „Sprzedaż: edycja” (jak zapis wyniku od 13.11.2026). Osoba z „Przypisz osobie”
  też musi mieć „Sprzedaż: edycja”. Przypisanie nie zmienia opiekuna szansy.
- **Najpierw liczby, potem zapis:** okno wysyła `dry_run` i pokazuje, ile się zmieni i co zostaje
  bez zmian z powodem (`not_on_list`, `meeting_booked`, `already_in_campaign`). Zapis to jedna
  transakcja pod blokadą importu list (`LOCK_KEY`), bo przeniesienie i import pytają o to samo.
- **Usuń z listy = miękko** (`removed_at`, 0802): rekord znika z kolejki, Tabeli, Przypomnień,
  „Mojego dnia”, liczników kampanii, Skuteczności („na liście”, „zostało”), listy osób nad kolejką
  i karty firmy; nie przyjmuje wyniku (404). Historia telefonów i karta firmy zostają.
  „Cofnij” w dymku (10 s) przywraca te same rekordy. Bramka importu dalej widzi usunięty rekord,
  więc ta sama firma nie wraca z kolejną listą. Historia („Kto dzwoni?”, powtórki, bramki botów)
  widzi go nadal, bo to był prawdziwy telefon.
- **Umówione spotkanie** nie znika z listy ani nie przechodzi do innej kampanii (ma szansę
  w lejku); przypisać je można.
- **Przeniesienie:** firma, która ma już rekord w kampanii docelowej (także usunięty), zostaje
  na miejscu; z dwóch zaznaczonych rekordów tej samej firmy przechodzi pierwszy. Rekord idzie ze
  statusem, datą powrotu i historią.
