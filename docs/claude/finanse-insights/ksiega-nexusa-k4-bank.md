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
- Pełnego rachunku kontrahenta nie trzymamy (tylko cztery ostatnie cyfry, jak
  E3 i R9), a tytuły mają zamaskowane numery rachunków z parsera.
- Rachunki walutowe (EUR, USD) i kurs NBP operacji — K4c-1
  (`ksiega-nexusa-k4c-waluty.md`). Parowanie zapłaty
  WB z fakturą robią rozrachunki K4b (`ksiega-nexusa-k4b-rozrachunki.md`) —
  WB pamięta w `meta.bank_lines`, która jego pozycja jest którą operacją
  wyciągu (poza odciskiem dokumentu).

## Testy

`tests/test_ledger_bank_rules.py` (reguły bez bazy), sekcja K4a
w `tests/test_ledger_sources_db.py` (import, D2, przebudowa i blokada WB,
lista zamknięcia, duplikat), `tests/test_ledger_closing_rules.py`
(`bank_check`), front: `BankView.test.tsx`, `bank-model.test.ts`.
