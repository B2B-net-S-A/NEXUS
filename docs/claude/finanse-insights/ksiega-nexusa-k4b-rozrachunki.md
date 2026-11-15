# Księga NEXUSA K4b (14.11.2026): rozrachunki z rozliczaniem pozycji

Etap K4 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar),
część druga (dawne K2c, przesunięte do K4, bo bez wyciągów w księdze każda faktura
była „otwarta”). Wyciągi: `ksiega-nexusa-k4-bank.md`, fundament:
`ksiega-nexusa-k1-fundament.md`. Migracja `0706_ledger_settlements`
(`ledger_settlement_schema.py`, lustro przez `hr_schema_bundle`), kod
`app/services/ledger/settlements.py` (pozycje, automat, zapis) i
`settlements_view.py` (zestawienie, karta konta), trasy
`app/api/ledger_settlements.py`, zakładka „Rozrachunki” (`/accounting/settlements`)
— część modułu `bank`, więc wyłączona do jego włączenia.

## Co jest

- **Pozycja rozrachunkowa** = zapis zatwierdzonego dokumentu na analityce konta
  ze słownikiem „kontrahent” w planie kont (`200-1234`, `201-2-15`). Konto bez
  takiego słownika nie ma rozrachunków (karta konta → 404). Kwota ujemna zapisu
  (storno czerwone w PK) idzie na stronę przeciwną.
- **Rozliczenie** (`ledger_settlements`) łączy pozycję Wn z pozycją Ma tego
  samego konta na kwotę; zostało = kwota − rozliczenia. Rozliczenie częściowe
  (wpisana kwota) tylko przy jednej parze; zaznaczonych kilka = od najstarszych.
  Cofnięcie zostawia wiersz z `removed_at`/`removed_by` (ślad).
- **Na dzień**: pozycje dokumentów z datą operacji do tego dnia, rozliczenia
  z datą do tego dnia; data rozliczenia = późniejsza z dat obu dokumentów.
  Domyślnie „dziś” z serwera (`config.today`).
- **Termin** mają faktury sprzedaży (KSeF, `due_date`) i kosztowe (kolejka
  kosztów); zapłaty, PK i BO są „bez terminu”. Wiekowanie: w terminie, 1–30,
  31–60, 61–90, 91–180, 181–365, ponad rok, bez terminu — osobno Wn i Ma.
- **Automat** (podgląd w zestawieniu i na liście zamknięcia miesiąca, zapis
  przyciskiem; wszystkie konta albo jedno):
  1. operacja WB z fakturą dopasowaną w E3/E8 ↔ zapis FVZ/FVS tej faktury
     na tym samym koncie (WB pamięta w `meta.bank_lines`, która pozycja jest
     którą operacją wyciągu; poza odciskiem, więc odciski WB sprzed K4b się nie
     zmieniły; pozycja musi się zgadzać z operacją — konto, kwota, strona),
  2. korekta faktury sprzedaży (strona Ma) ↔ faktura pierwotna,
  3. pozycje konta, które razem dają zero — od najstarszych.
  Nic poza tym — nie dopisuj kojarzenia po kwocie albo numerze w tytule bez
  decyzji, bo to zgadywanie (E3/E8 już dopasowały to, co pewne).

## Zasady, których łatwo nie zauważyć

- **Żywe dokumenty**: zatwierdzone, bez storna i niebędące stornem. Storno
  zeruje dokument razem z nim, więc od daty storna oba wypadają, a ich
  rozliczenia przestają się liczyć (także po drugiej stronie) — wpłata wraca
  do rozliczenia z nową fakturą. Na dzień sprzed storna dokument i jego
  rozliczenia zostają, jak w obrotach i saldach (storno z 05.05 nie zmienia
  rozrachunków na 30.04 — przegląd 14.11.2026). Nie kasuj rozliczeń przy
  stornie: odczyt je pomija, ślad zostaje.
- **Sonda deep health**: `ledger_settlements` jest w `core_checks`
  (`app/main.py`) i w `LEDGER_TABLES` strażnika
  `tests/test_health_deep_hot_tables.py` — nowa tabela księgi bez sondy
  zatrzymuje PR w kolejce.
- **Bilans otwarcia** daje pozycje tylko w pierwszym roku księgi NEXUSA (BO
  z Symfonii). BO kolejnego roku powstaje z sald poprzedniego, którego pozycje
  przechodzą same — inaczej faktura z grudnia byłaby otwarta dwa razy.
- **Szkice nie są pozycjami** — rozlicza się zapisy po zatwierdzeniu (pozycje
  są wtedy trwałe, więc rozliczenie nie gubi się przy przebudowie szkicu).
- **D2**: dokumenty płacowe widzi i rozlicza tylko osoba z Płacami albo admin.
  Para musi mieć tę samą wrażliwość (płacowa z płacową). Osobie bez Płac nazwa
  kontrahenta konta idzie tylko z widocznych zapisów — kartoteka po numerze
  konta pokazałaby nazwisko osoby z zespołu na koncie z samymi PK (test
  `test_settlements_keep_payroll_documents_to_payroll`).
- **Kto**: czyta „Moduł Finanse” przy otwartych modułach `ledger` i `bank`;
  rozlicza, cofa i uruchamia automat lista „Księgowi” albo administrator (403).
- Zapis rozliczeń idzie po kolei (blokada `pg_advisory_xact_lock`), a kwota
  jest sprawdzana pod blokadą — dwie osoby nie rozliczą tej samej kwoty dwa razy.
- Rozrachunki ze stanu sprzed K4b: faktury z miesięcy bez wyciągów w księdze są
  otwarte, dopóki nie wczyta się tych wyciągów w „Banku” (jeden plik = jeden
  miesiąc; E3/E8 rozpoznają zapłaty, które już znały, bez dubli).
- Waluty (K4c-1, `ksiega-nexusa-k4c-waluty.md`): para w tej samej walucie
  obcej rozlicza się w walucie (każda strona zdejmuje swój udział PLN), różnica
  udziałów idzie na PK różnicy kursowej; faktura w walucie zapłacona w PLN —
  w PLN, z proporcjonalną częścią waluty.

## Testy

`tests/test_ledger_settlement_rules.py` (konta kontrahentów, wiekowanie, FIFO,
pozycja listy zamknięcia, `meta.bank_lines` w WB), sekcja K4b
w `tests/test_ledger_sources_db.py` (automat: wyciąg, korekta, saldo zerowe; na
dzień, także przed późniejszym stornem; cofnięcie, kwota częściowa, odmowy;
identyfikator ponad BIGINT = 422; storno WB; D2 i nazwa konta; moduł
wyłączony), `tests/test_health_deep_hot_tables.py` (sonda tabeli), front:
`SettlementsView.test.tsx`, `settlements-model.test.ts`.
