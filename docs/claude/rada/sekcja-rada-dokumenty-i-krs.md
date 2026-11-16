# Sekcja „Rada”: dokumenty, KRS, pulpit, budżet (R1 0727, R2, R3 0728, 16.11.2026)
<!-- indeks: /rada dom roli board, Rada czyta, admin wgrywa; odpis pełny KRS co noc, wiersze z wzmianek, dzwonek board_krs_entry; F51 odczyt skanu jako propozycja; etapy R2–R5 -->

Członek Rady nadzorczej poprosił 16.11.2026 o moduł „tylko dla RN”: dokumenty
korporacyjne, analiza finansowa i budżet, z historią 2023–2025, żeby nie
składać tego ręcznie. Propozycja z makietami na kopii produkcji:
https://claude.ai/artifact/Fg6SAGKUAri2yEMLvoHStp.

## Decyzje Artura z 16.11.2026 (nie pytać ponownie)

- **Osobna sekcja „Rada” (`/rada`)** jest domem roli `board` (`BOARD_HOME`).
  Insights → Firma przestaje być ekranem startowym; po R2 Rada przejmuje
  z Insights ranking klientów, rok do roku i ruch konsultantów, a Insights
  znika z menu Rady.
- **Rada czyta, admini (Zarząd) wgrywają.** Finanse i „Wyniki firmy” nie
  widzą dokumentów Rady: protokoły Zarządu to nie są podsumowania przychodu.
- **Historia finansowa 2023–2025** przyjdzie z plików XML e-Sprawozdań
  i z ZOiS Symfonii co miesiąc (R4). Repozytorium Dokumentów Finansowych ma
  wyzwanie JS przeciw automatom — nie obchodzimy go.
- **Kolejność R1 → R5:** R1 dokumenty i KRS, R2 pulpit z faktur, R3 budżet
  i prognoza z kontraktów, R4 wskaźniki, zdolność kredytowa i wycena, R5
  gotówka z wyciągów, pakiet na posiedzenie i głosowanie.

## Dostęp

- API `/api/supervisory-board/*` (`app/api/supervisory_board.py`): router za
  bramką sekcji Insights; odczyt `require_roles(UserRole.board)` (admin
  przechodzi z definicji), zapis `AdminUser`. **Nie** `BoardReader` — ten
  wpuszcza też imienne nadanie „Wyniki firmy”. Wzorzec:
  `tests/data/authz_golden/supervisory_board.json` (Rada P na GET, D na
  zapisach; Finanse, HoR, rekruter, pracownik D wszędzie).
- Front: middleware `/rada` = role `admin`, `board` z `enforceRoles`
  (rekruter z Insights nie wchodzi), menu `rada` w grupie „Firma”
  i w `BOARD_NAV_IDS`, okruszek „Rada”.

## Dokumenty (`board_documents`)

- Rodzaje z maila Rady: statut, regulaminy Zarządu i Rady, protokoły i uchwały
  WZA, Rady i Zarządu, sprawozdania finansowe, inne (`CATEGORIES`
  w `board_documents_schema.py`; ten sam słownik w `lib/api/supervisory-board.ts`).
- **Wiersz z KRS** (`source='krs'`, `krs_key` = `financial_statement:2025`,
  `approval:2025`, `audit_opinion:…`, `activity_report:…`, `statute:<nr wpisu>`)
  zakłada automat z wzmianek odpisu pełnego, idempotentnie. Nie da się go
  usunąć (409, wraca co noc); admin dołącza do niego skan i poprawia opis.
- Wiersz z ręki (`source='upload'`): admin dodaje z plikiem albo bez, usuwa
  razem z plikiem. Pliki: `UPLOADS_DIR/board_documents/`, PDF, zdjęcia, Word,
  do 25 MB; pobranie przez API z `Cache-Control: no-store`.
- **Odczyt skanu (F51, `board_document_read`)**: przycisk admina „Odczytaj pola
  z pliku”; model dostaje sam plik, zwraca rodzaj, organ, numer, datę,
  przedmiot i głosy. To **propozycja** w `extraction` — pola zmienia dopiero
  „Przyjmij”. Awaria modelu = komunikat, dokument zostaje. Model nie
  przepisuje nazwisk ani PESEL-i (prompt), a NEXUS ich nie zapisuje.

## Odpis KRS (`board_krs_snapshots`, pętla `board_krs`)

- KRS spółki z `company_party.COMPANY_PL` (jedno miejsce danych spółki).
  Pętla co noc 05:40 (Warszawa) i przy starcie; wyłącznik `BOARD_KRS_ENABLED`.
  Admin może pobrać odpis od razu („Pobierz teraz”).
- Nowy wiersz odpisu tylko przy zmianie treści (skrót bez daty wydruku).
  Ekran liczy z odpisu: liczbę wpisów i ostatni wpis, kapitał i akcje, skład
  Zarządu (funkcje) i Rady (liczba — API maskuje nazwiska), ostatnią zmianę
  statutu, tabelę wzmianek o sprawozdaniach i **brakujące wzmianki**
  (np. opinia biegłego za rok, w którym jest sprawozdanie).
- **Dzwonek `board_krs_entry`** (kategoria „Systemowe”, sekcja Insights) do
  Rady i adminów o każdym nowym wpisie. Pierwszy odpis w bazie nie dzwoni —
  to stan zastany.
- Staging: pętla w `STAGING_BLOCKED_TASKS`; ręczne pobranie wymaga
  `STAGING_EXTRA_ALLOWED_HOSTS=api-krs.ms.gov.pl`.

## Pulpit i Firma (R2)

- Zakładki „Rady”: **Pulpit** (domyślna), **Firma** (ten sam `FirmaView` co
  w Insights; okres zapisuje się w bieżącej ścieżce, nie w `/insights`),
  **Dokumenty**. Insights zniknęło z menu Rady (`BOARD_NAV_IDS`); adresy
  `/insights` zostają dla linków z maila i raportów.
- `GET /summary` (`services/board/summary.py`): sprzedaż i koszty z archiwum
  faktur eBI24 (netto w PLN = netto × brutto PLN / brutto, data wystawienia),
  3 lata + rok bieżący, miesiące roku bieżącego i poprzedniego, pięciu
  największych klientów ostatniego pełnego roku, aktywne kontrakty i te, których
  umowa albo zamówienie kończy się do 31.12 (potencjał = stawka × 160 h po
  kursie NBP), braki w KRS z ostatnich 4 lat, dokumenty bez skanu.
- **„Wynik z faktur” to nie RZiS** (bez płac UoP, ZUS, amortyzacji) — ekran
  mówi to wprost; po K8 zastąpi go księga. **Porównanie rok do roku** bierze
  ten sam zakres miesięcy: sprzedaż do ostatniego miesiąca z co najmniej
  połową mediany 6 poprzednich (ledwo zaczęty miesiąc nie wydłuża okresu),
  wynik tylko do ostatniego miesiąca z pełnymi kosztami (≥ 80% mediany, od
  stycznia bez przerwy) — faktury kosztowe spływają z opóźnieniem i bez tego
  wynik bieżącego roku wychodził 14,5% zamiast 5,8%.
- „Do uwagi Rady” (`attentionItems`): spadek wyniku o ponad 1 p.p. rok do
  roku, co najmniej 30% kontraktów kończących się do 31.12, klient powyżej 30%
  sprzedaży, brakujące wzmianki KRS, dokumenty bez skanu.

## Budżet (R3, 0728)

- `board_budgets` (rok, szkic/przyjęty, uchwała Rady z dokumentów) i
  `board_budget_lines` (miesiąc × sprzedaż/koszty, PLN netto). Plan wpisuje
  admin (`PUT /budget/{rok}`, rok bieżący ±1, uchwała musi być „Uchwałą Rady”);
  Rada czyta (`GET /budget/{rok}`).
- **Prognoza** (`services/board/budget.py`) miesięcy po ostatnim pełnym
  miesiącu sprzedaży: aktywne kontrakty × stawka klienta po kursie NBP × dni
  robocze miesiąca z polskimi świętami (8 h przy stawce godzinowej) ×
  realizacja = średnia faktur do potencjału z ostatnich 3 pełnych miesięcy.
  Dwa scenariusze: bez przedłużeń (kontrakt kończy się w dniu końca umowy albo
  zamówienia) i wszystkie przedłużone; Rada przesuwa realizację suwakiem.
- **Koszty** prognozy i miesięcy, których faktury kosztowe jeszcze spływają =
  sprzedaż × udział kosztów z 12 miesięcy kroczących (krótsze okno łapało
  przesunięcia dat wystawienia: lipiec 2026 dawał 109%).
- Na kopii 16.11: realizacja 79%, koszty 92,7%, rok 2026 ok. 121 mln
  sprzedaży; 2027 bez przedłużeń to ok. 24 mln — miara ryzyka, nie prognoza.

## Pilnują

`tests/test_supervisory_board_unit.py` (parser, wiersze z wzmianek, skrót,
czytnik, treść dzwonka), `tests/test_supervisory_board_api.py` (bramki ról,
jeden odpis przy braku zmian, dzwonek tylko przy nowym wpisie, wiersz KRS bez
usunięcia), `frontend/src/components/rada/__tests__/DocumentsTab.test.tsx`
(Rada bez zapisu, awaria ≠ pusta lista), `board-role.test.ts`,
`middleware.test.ts`.
