# Przebieg miesiąca: wszyscy klienci rozliczeń w jednym widoku
<!-- indeks: Finanse → Przychody → „Przebieg miesiąca” (`?view=month-close`), GET /api/finance/settlements/overview, `month_close.overview` i `stage_counts`, cztery odpowiedzi (automat, co źle, braki, faktury), tabela pięciu kroków z „Kto teraz”, biuro `GET …/settlements/team` (NIP, bez kwot), „Błędy i uwagi” (błąd blokuje, uwaga nie), link „Wystaw” do `?view=sales-invoices&siPeriod=&siView=issue` -->

Decyzja Artura z 23.11.2026 po makietach przed/po na danych z próby IX–X
(prywatny artefakt, link w pamięci sesji). Finanse rozliczały klienta po kliencie
z listy rozwijanej i nie widziały, czy miesiąc da się zamknąć u wszystkich.

## Cztery odpowiedzi i pięć kroków (od 24.11.2026)

Decyzje Artura z 24.11.2026 po makietach przed/po na powtórce października
(prywatny artefakt, link w pamięci sesji). Artur: „nadal nie jest przejrzyste,
ile automat sam zrobił, ile jest błędów i jakich, czego brakuje i na jakim
etapie jest fakturowanie klienta”, a biuro (nasi ludzie na B2B) ma być na tym
samym ekranie.

- **Na górze cztery karty, każda zaczyna się od pytania:** „Co zrobił automat”
  (lejek: raport z poczty → MD z pliku → reguły bez uwag → samo przyjęcie →
  faktury z KSeF), „Co jest źle” (błędy, uwagi, plik nieodczytany, zamówienie
  bez MD, odesłane), „Czego brakuje” (raporty, adres do przypomnienia, numer
  zamówienia, ewidencja i faktury biura, NIP-y biura) i „Faktury do klientów”
  (klienci według stanu faktury). Liczby z `month_close.stage_counts`: każda
  osoba jest w każdym kroku dokładnie raz. Nie dopisuj osobnych liczników na
  froncie, bo karty i tabela zaczną się różnić (23.11 zakładka mówiła 107,
  podsumowanie 40, „Dla księgowej” 141).
- **Tabela „Gdzie są rozliczenia”:** wiersz na klienta i wiersz biura,
  kolumny = kroki (raport, kontrola, przyjęcie, faktura od osoby, faktura do
  klienta) i „Kto teraz” (Finanse, konsultanci, opiekun, klient, Płace).
  Strzałka rozwija osoby z tymi samymi krokami (osoby klienta z istniejącego
  `GET /api/finance/settlements?client_id=`).
- **Błąd ≠ uwaga.** Wiersz osoby ma `issue_level`: `fail` — reguła klienta
  blokuje przyjęcie (serwer odmawia „Reguła klienta blokuje przyjęcie”),
  `warn` — Finanse przyjmują na karcie osoby. Ekran klienta pokazuje „Błąd”
  i „Uwaga” zamiast jednego „Z uwagami” (`statusLook`). Ta sama reguła bywa
  blokadą u jednego klienta i uwagą u innego, więc powody grupujemy po
  (klucz, rodzaj) — dwa wiersze w „Błędy i uwagi”, nie jedna suma.
- **`no_md` to zamówienie bez MD** (brak linii albo puli, rozstrzyga opiekun),
  a nie nieodczytany plik. Nieodczytany plik to `checking` (Finanse wpisują MD).
- **Uwaga zawsze ma tytuł i stały klucz.** Koszty delegacji w RCP to uwaga
  „Delegacja do sprawdzenia” z kwotą w opisie i kluczem `travel.rcp_costs`
  (`rcp_checks.py`), więc w „Błędy i uwagi” jest jedna grupa, a nie jedna na
  kwotę. Do 24.11 silnik ustawiał uwagę i zapisywał samą informację, więc osoba
  wisiała „z uwagami” bez powodu.
- **Faktura do klienta przed przyjęciem RCP to ostrzeżenie, nie blokada**
  (decyzja Artura 24.11). Licznik `client_invoice.issued_early`; w październiku
  56 osób miało fakturę sprzedaży w KSeF przy nieprzyjętym RCP.
- **Biuro (`GET /api/finance/settlements/team`, `team_month.py`):** aktywne
  osoby z potwierdzoną formą B2B (`employment_type_pending = false`), ewidencja
  czasu za miesiąc, faktura z Płac (`payroll_invoices`, czytnik KSeF Płac bierze
  tylko NIP-y z „Danych do rozliczeń”) i zapłata z Płac albo z Kosztów. Faktury
  łączymy **wyłącznie po NIP-ie** — bez NIP-u osoba ma stan `no_nip`, a „Kto
  teraz” mówi „Płace (NIP)”. Dopasowanie po nazwie sprzedawcy łapało 18 z 30
  osób i Artur je odrzucił. **Bez kwot:** Finanse widzą stany i daty, kwoty
  biura zostają w Płacach. Faktury do klienta biuro nie ma („nie dotyczy —
  klientem jesteśmy my”).
- **Świadomy wyjątek od D2.** Koszty chowają faktury osób zespołu przed
  „Modułem Finanse” bez Płac (`finance_ledger/costs.py`, `_payroll_scope`).
  Trasa biura pokazuje każdemu z „Modułem Finanse” same stany i daty (jest
  ewidencja, jest faktura, zapłacona), bez kwot i bez dokumentów — decyzja
  Artura z 24.11.2026. Kwota albo dokument biura w tej trasie to złamanie D2.
- **Kto jest w biurze w miesiącu:** ewidencja za ten miesiąc decyduje o formie
  (zlecenie w październiku wyklucza, nawet gdy dziś osoba jest na B2B); bez
  ewidencji — faktura za miesiąc albo dzisiejszy aktywny profil B2B. Osoba
  z kontem wyłączonym po odejściu zostaje w swoim ostatnim miesiącu.
  Faktura odrzucona przez Płace (`match_status = ignored`) się nie liczy,
  a dopasowana do rozliczenia wygrywa z pozostałymi.
- **„Co zrobił automat” liczy tylko pracę automatu:** `check.auto_clean` = MD
  odczytane z pliku (`md_source = rcp`) i reguły bez uwag. MD wpisane przez
  Finanse (`md_manual`) i uwagi przyjęte ręcznie (`check.resolved`,
  `accepted_issue`) nie są „przeszło samo”.
- **„Kto teraz” po przyjęciu:** najpierw nasz ruch (faktura do klienta gotowa
  → Finanse), potem konsultant bez faktury (`contractor_invoice.waiting`).
  Wiersz klienta i wiersz osoby liczą to tak samo.
- **Awaria zapytania to nie zero:** przypomnienia albo biuro, które się nie
  pobrały, pokazują „—” albo „nie udało się pobrać”, nigdy 0.

## Co jest na ekranie (23.11.2026, część nadal obowiązuje)

- **Pozycja w `FinanceAreaNav`** (Przychody, przed „Rozliczeniami klientów”), widoczna
  przy otwartym module rozliczeń. Nie jest osobnym paskiem zakładek
  (`ui/klienci-i-finanse-jedna-lista.md`). Adres: `?view=month-close&mcMonth=RRRR-MM&mcTab=reasons`.
- **Podsumowanie:** osoby z RCP (bez klientów z raportem T4T), bez uwag, do decyzji,
  plik bez MD, brak raportu, kwota bez uwag do faktur (tylko z uprawnieniem do kwot),
  cztery kroki: raporty → RCP → faktury kontraktorów → faktury do klientów.
- **Klienci:** wiersz na klienta, kolejność według pracy, która została. Klient
  z regułą `report.time_for_teams` (Nordea) pokazuje stan raportu klienta i różnice
  T4T, a „Otwórz” prowadzi do jego zakładki T4T.
- **Błędy i uwagi** (do 24.11 „Do decyzji wg powodu”): te same sprawy pogrupowane po
  kluczu reguły pierwszego błędu albo uwagi i po rodzaju (kolejność jak `service._row`:
  najpierw błąd). Braki raportu są w karcie „Czego brakuje” i w tabeli kroków, nie
  w tej liście. `reason-plan.ts` mówi, kto rozstrzyga i dokąd prowadzi akcja
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
