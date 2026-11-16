# Sekcja „Rada”: dokumenty korporacyjne i odpis KRS (R1, 0727, 16.11.2026)
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

## Pilnują

`tests/test_supervisory_board_unit.py` (parser, wiersze z wzmianek, skrót,
czytnik, treść dzwonka), `tests/test_supervisory_board_api.py` (bramki ról,
jeden odpis przy braku zmian, dzwonek tylko przy nowym wpisie, wiersz KRS bez
usunięcia), `frontend/src/components/rada/__tests__/DocumentsTab.test.tsx`
(Rada bez zapisu, awaria ≠ pusta lista), `board-role.test.ts`,
`middleware.test.ts`.
