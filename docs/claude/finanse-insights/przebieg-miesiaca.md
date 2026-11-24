# Przebieg miesiąca: wszyscy klienci rozliczeń w jednym widoku
<!-- indeks: Finanse → Przychody → „Przebieg miesiąca” (`?view=month-close`), GET /api/finance/settlements/overview, `month_close.overview`, kolejka „Do decyzji wg powodu”, pasek kroków nad tabelą klienta, link „Wystaw” do `?view=sales-invoices&siPeriod=&siView=issue` -->

Decyzja Artura z 23.11.2026 po makietach przed/po na danych z próby IX–X
(prywatny artefakt, link w pamięci sesji). Finanse rozliczały klienta po kliencie
z listy rozwijanej i nie widziały, czy miesiąc da się zamknąć u wszystkich.

## Co jest na ekranie

- **Pozycja w `FinanceAreaNav`** (Przychody, przed „Rozliczeniami klientów”), widoczna
  przy otwartym module rozliczeń. Nie jest osobnym paskiem zakładek
  (`ui/klienci-i-finanse-jedna-lista.md`). Adres: `?view=month-close&mcMonth=RRRR-MM&mcTab=reasons`.
- **Podsumowanie:** osoby z RCP (bez klientów z raportem T4T), bez uwag, do decyzji,
  plik bez MD, brak raportu, kwota bez uwag do faktur (tylko z uprawnieniem do kwot),
  cztery kroki: raporty → RCP → faktury kontraktorów → faktury do klientów.
- **Klienci:** wiersz na klienta, kolejność według pracy, która została. Klient
  z regułą `report.time_for_teams` (Nordea) pokazuje stan raportu klienta i różnice
  T4T, a „Otwórz” prowadzi do jego zakładki T4T.
- **Do decyzji wg powodu:** te same sprawy pogrupowane po kluczu reguły pierwszego
  błędu albo uwagi (kolejność jak `service._row`: najpierw błąd), plus „Brak raportu”
  i „Plik bez MD”. `reason-plan.ts` mówi, kto rozstrzyga i dokąd prowadzi akcja
  (np. `proof.accept_has_hours` → „Reguły klienta”).
- **Ekran jednego klienta** ma nad tabelą pasek tych samych kroków i trzy najczęstsze
  powody (`ClientMonthStrip`).
- **„Wystaw”** prowadzi do „Faktury do klientów” → „Wystaw za miesiąc” dla tego miesiąca
  (`siPeriod`, `siView`; zmiana widoku Finansów czyści te klucze). Z wiersza klienta
  i z paska na ekranie klienta link niesie też `siClient`: panel pokazuje tylko tego
  klienta i zaznacza jego zamówienia do wystawienia (od 24.11.2026). Szkice powstają
  dopiero po „Utwórz szkice”; „Pokaż wszystkich klientów” zdejmuje filtr i zaznaczenie.
  Klient spoza listy do wystawienia (np. zamówienia na innym kliencie z rodziny) nie
  chowa reszty — panel pokazuje wszystkich bez zaznaczenia.

## Dla księgowej (od 24.11.2026)

Zakładka „Dla księgowej” (`mcTab=closing`, `ClosingPanel`) odpowiada na trzy pytania, z którymi
główna księgowa co miesiąc ok. 20. dnia M+1 pisała do rozliczeń (mail „Rozliczenie lipca”, 24.08.2026):
- faktury kontraktorów w KSeF przy nieprzyjętym RCP (`contractor_invoice` ∈ in_ksef / differs / nip_check);
- brakujące faktury kontraktorów → **rezerwa kosztu**: rozliczenia z MD (`ok`, `accepted`, `warnings`)
  bez faktury w KSeF, suma `amount_cost`, lista z pobieraniem CSV (średnik, przecinek dziesiętny);
  osoby bez kosztu (brak stawki albo MD) są policzone osobno i nie wchodzą do sumy;
- przyjęte RCP bez faktury sprzedaży (`client_invoice` ∈ ready / awaiting_signature / awaiting_client).
Kwoty i nazwiska tylko przy `has_financial_access`; bez tego same liczby.

## Przypomnienia i automat w tabeli klientów (od 24.11.2026)

- Pod liczbą brakujących raportów notka z `GET /api/finance/settlements/reminders` (#3805): „bez adresata: N”
  (ważniejsze), „przypomniano DD.MM”, „przypomni automat” albo „bez przypomnienia”. Wysyłka zostaje
  w miesiącu klienta („Przypomnij (n)”), bo tam jest podgląd treści i adresatów.
- Pod paskiem RCP: „N przyjmie automat od DD.MM”, gdy klient ma regułę `order.auto_accept_clean` (#3806).

## Reguły, które łatwo cofnąć

- Wiersz klienta liczy się z `service.month_view`, tym samym co ekran klienta.
  Nie dopisuj osobnego SQL-a ze statusami, bo dwa ekrany zaczną się różnić.
- Widok tylko czyta. Akcje zbiorcze (przypomnienia, automatyczne przyjęcie „bez uwag”)
  są osobnymi zmianami z własnymi regułami; nie dopisuj wysyłki z tego widoku.
- Trasa ma tę samą bramkę co reszta rozliczeń (`FinanceModuleUser` + moduł otwarty),
  kwoty tylko przy `has_financial_access`.
