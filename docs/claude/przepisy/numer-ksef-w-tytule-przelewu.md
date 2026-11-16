# Strażnik: numer KSeF w tytule przelewu od 1.01.2027 (art. 108g VAT)
<!-- indeks: strażnik, art. 108g, numer KSeF w tytule przelewu, zbiorczy identyfikator KSeF, paczka przelewów, Elixir-O, E3 przelewy kosztów, R9 paczka Płac, ksef_title_problem, KSEF_TITLE_FROM, no_ksef_number, ksef_title_overflow, data płatności -->

Jeden z trzech strażników radaru „Przepisy” (zmiana prawa zamieniona w kontrolę
tam, gdzie powstaje błąd; `radar-przepisow-dwa-boty.md`). Wprowadzony 16.11.2026.

## Przepis

Od płatności wykonanych 1.01.2027 czynny podatnik VAT, który płaci przelewem
innemu czynnemu podatnikowi za fakturę ustrukturyzowaną (KSeF, także offline),
podaje w tytule numer KSeF faktury, a przy kilku fakturach jednego sprzedawcy
kilka numerów KSeF albo zbiorczy identyfikator (MF:
https://ksef.podatki.gov.pl/informacje-ogolne-ksef-20/numer-ksef-i-zbiorczy-identyfikator/,
stan strony 10.11.2026). **Decyduje data płatności**, nie data faktury ani dzień,
w którym ktoś składa paczkę. Wyjątek MF: faktury z trybu awaryjnego. Zbiorczy
identyfikator generuje wystawca, nabywca albo podmiot trzeci przez API KSeF albo
Aplikację Podatnika (do 500 numerów, 35 znaków); rozporządzenie było
16.11.2026 w toku. Strona MF nie mówi, w którym polu komunikatu MPP ma stać
numer KSeF, ani jak płacić fakturę z korektą.

## Gdzie NEXUS buduje tytuły przelewów (inwentarz 16.11.2026)

| Ścieżka | Kod | Tytuł | Strażnik |
|---|---|---|---|
| E3, przelewy faktur kosztowych (Finanse → Przelewy, zastępuje eksport z eBI24) | `services/finance_ledger/payment_rules.title_lines`, `payments.plan` / `create_batch` | numer faktury + numer KSeF w osobnych liniach; MPP: numer KSeF w `/TXT/` | jeden przelew = jedna faktura; faktura z KSeF bez numeru od daty **wykonania paczki** ≥ 1.01.2027 = blokada `no_ksef_number` |
| R9, paczka przelewów Płac (rozliczenia zespołu B2B, opcja) | `services/hr/bank/titles.py`, `batches.plan` / `create_batch` / `batch_file` | numery faktur i KSeF rozliczenia; gdy nie mieszczą się w 4 × 35 znaków, numery faktur ustępują numerom KSeF | od daty wykonania ≥ 1.01.2027: więcej niż 4 numery KSeF = `ksef_title_overflow`, faktura z KSeF bez numeru = `no_ksef_number` (pozycja poza paczką z powodem) |
| R9, „Dla Finansów” (lista i CSV do ręcznego przelewu w eBI24 albo banku) | `services/hr/bank/finance.describe` → `transfer_title` | ten sam `title_lines` co paczka | bez odmowy (przelew robi człowiek), tytuł z pierwszeństwem numerów KSeF |
| K7a, przelewy z listy płac | `services/hr/payroll_lists/transfers.py` | wynagrodzenie, ZUS, `/TI/…` do urzędu | nie dotyczy: to nie zapłata faktury |
| Księga K4 bank, rozrachunki K4b, faktury sprzedaży | `services/ledger/bank.py`, `client_invoicing/payments.py` | — | nie budują przelewów, tylko czytają wyciągi (numer KSeF w tytule = dopasowanie) |

Zbiorczego identyfikatora KSeF NEXUS **nie generuje**: E3 płaci fakturę
pojedynczo, R9 mieści do 4 numerów KSeF (4 linie Elixir-O po 35 znaków).
Rozliczenie z 5 i więcej fakturami KSeF (faktura z wieloma korektami) od
1.01.2027 trzeba zapłacić poza paczką (kilka przelewów albo identyfikator
zbiorczy w eBI24 lub banku).

## Reguły

- Data: `titles.KSEF_TITLE_FROM` (jedno źródło dla E3 i R9). Porównujemy
  z datą wykonania paczki (`execution_date`, bez niej dziś z `business_today()`;
  data wstecz liczy się jak dziś), nigdy z `date.today()` ani z dniem planu.
  Przed 1.01.2027 E3 pokazuje podpowiedź `ksef_from_2027`.
- „Z KSeF” = źródło faktury z KSeF (`finance_cost_entries.from_ksef`,
  `payroll_invoices.source = 'ksef'`). PDF spoza KSeF przechodzi bez numeru
  KSeF. Każde źródło z KSeF ma dziś numer w bazie (CHECK-i w
  `hr_settlement_schema`, `hr_approval_settlement_schema`, NOT NULL
  w `client_contractor_invoices`), więc `no_ksef_number` jest bezpiecznikiem,
  a realna luka była w dacie (E3) i w ucinaniu tytułu powyżej 4 linii (R9).
- Komunikaty odmowy po polsku w `titles.KSEF_TITLE_LABELS`; ekrany paczek
  pokazują je z `block_label` (E3) i `reason_label` (R9) bez zmian w UI.
- Plik R9 powstaje przy pobraniu z bieżących faktur: gdy po utworzeniu paczki
  strażnik odmawia, pobranie to 409 z tym samym kodem („Anuluj paczkę i utwórz
  nową”).
- Testy: `tests/test_hr_payments_formats.py` i `test_finance_payments_rules.py`
  (bez bazy), `test_hr_payments_batches.py` i `test_finance_payments_db.py`
  (paczka 28.12.2026 z wykonaniem 4.01.2027 → odmowa, z wykonaniem 30.12.2026 →
  przechodzi).

## Otwarte

- Pole numeru KSeF w komunikacie MPP (`/TXT/` dziś) i tytuł przy fakturze
  z korektą: MF nie rozstrzyga na stronie; do potwierdzenia z księgową
  i w objaśnieniach MF przed 1.01.2027.
- Układ Elixir-O sprawdzić importem próbnym w bankowości firmy (jak w E3/R9).
