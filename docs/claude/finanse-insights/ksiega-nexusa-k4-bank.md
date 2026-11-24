# Księga NEXUSA K4a (14.11.2026): jeden import wyciągu i dokument WB

Etap K4 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar),
część pierwsza. Fundament: `ksiega-nexusa-k1-fundament.md`, źródła:
`ksiega-nexusa-k2-zrodla.md`. Migracja `0705_ledger_bank`
(`ledger_bank_schema.py`, lustro przez `hr_schema_bundle`), kod
`app/services/ledger/bank.py`, zakładka „Bank” (`/accounting/bank`, moduł `bank`).

## Decyzja Artura z 14.11.2026

Wyciąg wgrywa się **raz, w Księgowości**. Plik czytają istniejące ścieżki bez
zmian w ich kodzie, każda w swoim zakresie i idempotentnie po skrócie pliku:

- E3 (`finance_ledger.payments.import_debits`) — obciążenia → zapłaty faktur
  kosztowych,
- R9 (`hr.bank.statements.import_statement`) — obciążenia → wypłaty dla osób
  z zespołu; **tylko gdy wgrywa osoba z Płacami** (D2), od razu z uznaniami
  (E8 w środku R9),
- E8 (`client_invoicing.payments.import_credits`) — uznania → zapłaty faktur do
  klientów, wprost, gdy wgrywa osoba bez Płac.

Księga odczytuje wynik każdej operacji z tabel tych ścieżek (skrót pliku +
`line_ref`) i zapisuje go w `ledger_bank_lines`. Stare ekrany importu (Koszty,
Płace) zostają do przełączenia — ten sam plik wgrany tam i tu nie dubluje
zapłat, bo wszystkie trzy ścieżki pomijają znane `(sha, line_ref)`. Nie
dopisuj czwartej ścieżki dopasowania ani kopii logiki E3/R9/E8 w Księdze.

## Co jest

- **Rachunki firmy** (Ustawienia, admin): NRB z sumą kontrolną
  (`hr.bank.accounts.normalize_nrb`) → konto w planie (130-x) i nazwa. Wyciąg
  z rachunku spoza listy jest odrzucany (422) — inaczej WB poszedłby na
  zgadywane konto. Pełne numery widzi administrator, reszta końcówkę.
- **Konta reguł** (ZUS, PIT, VAT, CIT, opłaty) — każde może być puste; pusta
  reguła = operacja czeka na ręczne konto, zamiast iść na złe.
- **Plik = jeden WB**: jeden rachunek firmy (plik z kilkoma `:25:`/`Stmt`
  → 422, `ParsedStatement.accounts`), jedna waluta = waluta rachunku z
  Ustawień (każda operacja, nie tylko nagłówek; od K4c-1 także EUR i USD),
  operacje z jednego miesiąca (WB ma jeden okres — wyciąg przez
  przełom miesiąca → 422, wgrać miesięczny albo dzienny). Pozycje 0,00
  pomijamy. Bez tego obce waluty i drugi rachunek szły na jedno konto 130-x
  w PLN, a marzec lądował w kwietniu (przegląd 14.11.2026).
- **Saldo musi się zgadzać** (od 18.11.2026): każdy wyciąg w pliku, który ma
  oba salda (MT940 `:60F:`/`:60M:` → `:62F:`/`:62M:`, CAMT.053 `OPBD`/`PRCD`
  → `CLBD`), daje `ParsedStatement.balances`; otwarcie + operacje ≠ saldo
  końcowe banku → 422 (plik ucięty albo uszkodzony). Wyciąg bez salda
  końcowego przechodzi bez tej kontroli. Odrzuca tylko Księga — parser i stare
  ekrany importu (Przelewy, Płace, faktury do klientów) zostają bez zmian.
  Santander przez eBI24 daje plik `.eMT`: MT940 z nagłówkami SWIFT
  `{1:}{2:}{4:` … `-}`, trzy części wyciągu dnia, windows-1250 — pola wyboru
  pliku przyjmują `.emt`. Próbka 06.10.2026: 30/30 operacji, saldo zgodne.
  Fikstury testów z MT940 do Księgi muszą mieć saldo końcowe zgodne
  z operacjami (`_mt940_balance` w `test_ledger_sources_db.py`).
- **Salda i numery wyciągu zostają w bazie** (0742, 19.11.2026): saldo otwarcia
  i zamknięcia pliku w groszach ze znakiem, ich daty, numer wyciągu banku
  pierwszej i ostatniej części (`:28C:`) i `credits_matched` (uznania przeszły
  przez E8). Z nich „po terminie” faktur do klientów liczy ciągłość rachunku
  (`docs/claude/zamowienia/faktury-do-klientow-z-ksef.md`). Plik, który sam nie
  jest ciągły, wchodzi jak dotąd, tylko bez sald. Ten sam plik wgrany drugi raz
  uzupełnia puste salda (wyciągi sprzed 0742) — bez drugiego importu operacji.
- **Rozpoznanie**, po kolei: duplikat (ten sam rachunek, referencja banku,
  data i kwota w innym wyciągu — dzienny i miesięczny) → wypłata dla zespołu
  **tak jak w E3**: każdy wiersz R9 tego pliku (też „unmatched”/„ignored”)
  albo `hr_statements.decide(...).related` (numer KSeF lub faktury, rachunek
  osoby); uznanie z rachunku osoby z zespołu albo z numerem KSeF jej faktury
  w tytule (zwrot, też z zamkniętego rachunku) też — samego numeru faktury
  przy uznaniach nie bierzemy, bo łapałby wpłaty klientów; UoP i zlecenie
  dopasowane w R9 = rozrachunki z tytułu wynagrodzeń, reszta bez konta →
  faktura kosztowa dopasowana w E3 (konto dostawcy `cost_account` z kartoteki)
  → faktura sprzedaży dopasowana w E8 (konto odbiorcy jak FVS w K2) → reguły:
  rachunek ZUS (numer banku 60000002), mikrorachunek podatkowy (10100071 222…)
  z symbolem `/SFP/` w tytule (VAT/PIT/CIT), opłata banku (bez rachunku
  kontrahenta i „opłata/prowizja/abonament” w tytule) → do wyjaśnienia.
- **„Zaksięguj wyciąg”** = WB w buforze, data operacji = ostatni dzień wyciągu,
  każda operacja Wn/Ma konto rachunku i konto przeciwstawne. Źródło
  `bank_statement` / `<id>`, płacowy `<id>-payroll` z wrażliwością `payroll`.
  Odcisk jak w K2: bez zmian = „bez zmian”, zmieniony szkic się przebudowuje,
  zatwierdzony = 409 (storno).
- Lista zamknięcia miesiąca: pozycja „Wyciągi bankowe” (operacje bez konta,
  wyciągi bez WB) przy otwartym module; wyłączony = „etap K4” jak dotąd.

## Zasady, których łatwo nie zauważyć

- **D2**: wypłaty dla osób z zespołu (`payroll = true`) widzi, przypisuje
  i księguje tylko osoba z Płacami albo admin. Osoba bez Płac dostaje tylko
  flagę `payroll_hidden` (bez liczby), sumy i liczby operacji bez nich,
  numery pozycji liczone w swoim zasięgu (luka zdradzałaby liczbę wypłat) i robi
  tylko WB zwykły. Duplikat dziedziczy D2 po oryginale (i po rachunku osoby
  z zespołu) — ta sama wypłata z wyciągu dziennego i miesięcznego nie wychodzi
  z nazwiskiem i kwotą (przegląd bezpieczeństwa 14.11.2026). R9 nie biegnie przy
  imporcie osoby bez Płac — wypłatę rozpoznaje wtedy sam rachunek osoby, a konto
  przypisują Płace.
- **D2 zamyka się po bezpiecznej stronie**: gdy rachunków zespołu nie da się
  odszyfrować (`account_owners` → `unreadable`), import kończy się 503 zamiast
  pokazać wypłaty jako zwykłe przelewy.
- Opis WB nie zawiera nazwy rachunku z Ustawień (tylko końcówkę numeru): opis
  wchodzi do odcisku, a zmiana nazwy po zatwierdzeniu WB blokowała „Zaksięguj”
  także dla WB płacowego.
- **Zmiana konta po księgowaniu przebudowuje szkic WB od razu** (ta sama
  funkcja `_write_wb` co „Zaksięguj”). Bez tego w buforze zostawał WB ze
  starym kontem, który dało się zatwierdzić. Zatwierdzony WB blokuje zmianę
  kont swojej grupy (409) — poprawka to storno dokumentu.
- Przypisanie i księgowanie idą po kolei (blokada wiersza wyciągu `FOR
  UPDATE`). Duplikatu nie da się przypisać — nie wchodzi do WB.
- **„Usuń wyciąg”** (`DELETE /bank/statements/{id}`, tylko administrator, od
  17.11.2026): cofnięcie importu po złym dopasowaniu — znikają linie wyciągu
  i zapłaty E3/E8 z tego pliku (po skrócie), stan zapłaty faktur kosztowych
  liczy się od nowa, plik wczytuje się potem od zera. Odmowa (409), gdy wyciąg
  ma jakikolwiek WB (też po stornie), gdy z pliku są wypłaty R9 albo gdy import
  zostawił skutek, którego nie odtworzymy (zamknięta pozycja paczki, zapłata
  eBI24 zastąpiona zapłatą z wyciągu) — to rozstrzygają Finanse.
  **Odmowa (409) także, gdy inny plik ma operacje tego wyciągu jako duplikaty**
  (decyzja Artura 24.11.2026, audyt): linia `duplicate` w innym wyciągu tego
  rachunku (ta sama referencja banku, dzień i kwota) albo wiersz E3/E8
  z `DUPLICATE_REASON` pod innym skrótem (także z pliku sprzed Księgi). Bez tego
  usunięcie dziennego D przy wgranym miesięcznym M kasowało oryginał zapłaty,
  duplikat z M zostawał `ignored`, faktura kosztowa wracała na „Do zapłaty”
  (ryzyko drugiego przelewu), a ponowne wgranie D było już tylko duplikatem M.
  Droga: najpierw usuń plik z duplikatami (M), potem oryginał (D), wgraj oba.
  Przeniesienia decyzji na duplikat Artur nie wybrał — za dużo stanu do
  przepisania (linia banku, E3, E8, WB drugiego pliku).
- Pełnego rachunku kontrahenta nie trzymamy (tylko cztery ostatnie cyfry, jak
  E3 i R9), a tytuły mają zamaskowane numery rachunków z parsera.
- Rachunki walutowe (EUR, USD) i kurs NBP operacji — K4c-1
  (`ksiega-nexusa-k4c-waluty.md`). Parowanie zapłaty
  WB z fakturą robią rozrachunki K4b (`ksiega-nexusa-k4b-rozrachunki.md`) —
  WB pamięta w `meta.bank_lines`, która jego pozycja jest którą operacją
  wyciągu (poza odciskiem dokumentu).

## Koszt importu (19.11.2026)

18.11.2026 18:42 jeden import trwał 66,6 s przy 1057 zapytaniach, a jedyny
proces web stał (`loop_lag_ms_p99` 1111 ms, `/api/health` 12,8 s). Zasady:

- **Numer faktury w tytule tylko przez `hr.bank.titles.number_in_title`.**
  Wzorzec kompilowany dla każdej pary operacja × faktura (E3 `decide_debit`,
  E8 `decide_credit`) kosztował ok. 0,2 ms, bo przy tysiącach faktur pamięć
  podręczna `re` (512 wzorców) nic nie trzyma: 100 obciążeń × 3000 faktur =
  63,9 s, po zmianie 0,4 s. Helper najpierw sprawdza ciągi cyfr numeru
  w tytule, a wzorce trzyma w `lru_cache`.
- **Na operację nie ma zapytań w E3, E8 ani w Księdze.** Duplikat z innego
  pliku sprawdza jedno zapytanie (`hr.bank.duplicates.seen_elsewhere`), E3
  zamyka pozycje paczek i liczy `refresh` raz po wszystkich operacjach (kolejne
  operacje biorą stan faktury z pamięci), kontrahentów faktur sprzedaży Księga
  czyta jednym zapytaniem. R9 płaci osobno tylko za każde opłacone rozliczenie
  (`mark_paid`: blokada, status, ślad HR, powiadomienie osoby — ok. 17 zapytań,
  jak „Opłacono” na karcie).
- Księga parsuje plik raz, w `asyncio.to_thread`, i podaje E3 i R9 `parsed`
  oraz `team` (rachunki osób i rozliczenia), które ma już z tego żądania.
  Stare ekrany importu wołają te funkcje bez nich i liczą je same.
- Sufit pilnuje `tests/test_ledger_bank_import_query_budget.py` (dwie długości
  wyciągu, osoba z Płacami i bez), a wynik dopasowania numeru
  `tests/test_bank_title_number_match.py`.

## Testy

`tests/test_ledger_bank_rules.py` (reguły bez bazy), sekcja K4a
w `tests/test_ledger_sources_db.py` (import, D2, przebudowa i blokada WB,
lista zamknięcia, duplikat), `tests/test_ledger_closing_rules.py`
(`bank_check`), front: `BankView.test.tsx`, `bank-model.test.ts`.
