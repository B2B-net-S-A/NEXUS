# Sekcja „Rada”: dokumenty, KRS, pulpit, budżet, analiza, posiedzenia, uchwały pisemne (R1 0727, R2, R3 0733, R4 0734, R5 0735, R6 0736, 16–18.11.2026)
<!-- indeks: /rada dom roli board, Rada czyta, admin wgrywa; odpis pełny KRS co noc, wiersze z wzmianek, dzwonek board_krs_entry; F51 odczyt skanu jako propozycja; etapy R2–R5; analiza z e-Sprawozdań (R4), posiedzenia z pakietem i obowiązkami KSH (R5) -->

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

## Budżet (R3, 0733)

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

## Analiza finansowa (R4, 0734, 18.11.2026)

- `board_financial_statements` — rok obrotowy: pola bilansu i RZiS
  (`amounts`, PLN, lista w `services/board/statements.py::FIELDS`), surowe
  pozycje pliku (`raw`) i źródło: `xml` (e-Sprawozdanie z eKRS), `xml_prev`
  (kolumna „rok poprzedni” z pliku za rok następny — tylko gdy roku nie ma
  z innego źródła), `manual` (admin z PDF). Rok z **księgi NEXUSA** (K8a,
  `ledger.statements.statements`) liczy się na bieżąco, gdy roku nie ma
  w tabeli; rok w trakcie ma `partial_months` i nie jest oceniany ani wyceniany.
- **Pozycja = ścieżka z załącznika nr 1 UoR** (`assets:B.III.1.c`,
  `income:B.I`). Parser nie zna całego schematu MF: zbiera każdy element
  z `KwotaA`/`KwotaB` pod `Bilans`, `RZiSPor`, `RZiSKalk`, `PrzeplywyPosr`.
  DOCTYPE i deklaracje encji odrzuca przebieg samym expatem przed
  ElementTree (podgląd bajtów omijał komentarz-dopełnienie i UTF-16);
  XAdES z treścią w base64 rozpakowany. `JednostkaInnaWTysiacach` × 1000;
  jednostki małe i mikro (inny układ, zał. 4 i 5 UoR) odrzucone. Ponowny
  import tego samego roku podmienia plik w tym samym dokumencie. **Parser nie był jeszcze sprawdzony na prawdziwym pliku
  spółki** — przy pierwszym imporcie porównaj „pozycje w pliku” i KPI z PDF.
- Import (`POST /statements/import`, admin, XML/XADES do 10 MB) zapisuje
  plik jako dokument „Sprawozdania finansowe” (przy wzmiance KRS za ten rok,
  gdy ta nie ma jeszcze PDF-u). Wpis ręczny `PUT /statements/{rok}`;
  `GET /analysis` dla Rady i admina.
- **Wskaźniki i założenia** (`services/board/analysis.py`): płynność,
  zadłużenie, dług netto / EBITDA, DSO/DPO, marże, ROE/ROA; zdolność
  kredytowa = 3× EBITDA − dług netto (+ faktoring 85% należności z tytułu
  dostaw); wycena EV/EBITDA: fundusz 6× (4–8), inwestor branżowy 8× (6–11),
  kontrola EV/przychody. Rada zmienia mnożniki suwakami. To nie jest wycena
  biegłego — tak też mówi ekran.
- Należności i gotówki „na dziś” nie liczymy z archiwum eBI24: flaga `paid`
  na fakturach sprzedaży jest niewiarygodna (2025: 121 mln „nieopłaconych”).
  Bieżąca gotówka i wiekowanie przyjdą z księgi (wyciągi K4, rozrachunki),
  gdy będą w niej zapisy.

## Posiedzenia (R5, 0735, 18.11.2026)

- `board_meetings`: data, tryb (posiedzenie / zdalnie / pisemnie), status
  (zaplanowane / odbyte / odwołane), porządek obrad z dokumentami, protokół
  (dokument z „Protokołów Rady”). Admin prowadzi, Rada czyta.
- **Pakiet** (`POST /meetings/{id}/pack`, admin) zamraża na dziś: pulpit,
  budżet roku, ostatnie pełne sprawozdanie z wskaźnikami, dokumenty i wpisy
  KRS od poprzedniego odbytego posiedzenia (bez niego: 90 dni). To
  informacja Zarządu dla Rady (art. 380¹ KSH), której nie zmienia późniejszy
  import faktur. Dzwonek `board_meeting_pack` do Rady i adminów (`fresh`,
  więc ponowne zamrożenie tego samego dnia też dzwoni). Posiedzenia z
  pakietem nie da się usunąć — tylko odwołać.
- Dokumenty w pakiecie liczą się po dacie dokumentu albo wpisu KRS;
  `created_at` tylko dla wgranych bez daty (wiersze z wzmianek KRS powstają
  przy pierwszym odpisie, a dotyczą lat wstecz — wcześniej wpadało ich 57).
- **Obowiązki roku** (`services/board/meetings.py::obligations`) dla S.A.:
  sprawozdanie do 31.03 (art. 52 UoR), ocena Rady i sprawozdanie Rady przed
  ZWZ (art. 382 § 3 i § 3¹ KSH), ZWZ do 30.06 (art. 395 § 1), złożenie do KRS
  15 dni od zatwierdzenia (art. 69 UoR), min. 3 posiedzenia w roku (art. 389
  § 3). Każda pozycja mówi, skąd wie (KRS, Analiza, tytuł uchwały w
  Dokumentach, rejestr posiedzeń). Uchwały rozpoznawane po słowach w tytule
  („ocen”/„sprawozd”, „zatwierdz”).
- Głosowanie pisemne — zakładka „Uchwały” (R6 niżej).

## Uchwały w trybie pisemnym (R6, 0736, 18.11.2026)

- Decyzja Artura 18.11.2026: budować **na projekcie statutu** (akt NWZ
  z 16.09.2025, § 25), choć tekstu przyjętego 24.11.2025 (Rep. A
  8533/2025) nie ma w M365. Po jego wgraniu sprawdzić § 25 i poprawić
  `services/board/votes.py`, jeśli się różni.
- Reguły (`votes.tally`): ważna, gdy projekt dostali **wszyscy** członkowie
  (skład `member_ids` zapisany przy wysyłce, każdy dostaje dzwonek
  `board_vote`) i głosowała **co najmniej połowa** (ust. 4); zwykła większość
  głosów oddanych — więcej „za” niż „przeciw”, wstrzymujący nie przesądzają;
  remis rozstrzyga Przewodniczący, jeśli głosował za albo przeciw (ust. 1).
  Wyłączone (ust. 5): wybór Przewodniczącego / Wiceprzewodniczącego Rady,
  powołanie, odwołanie i zawieszenie członka Zarządu — admin potwierdza
  przy wysyłce (`not_excluded_matter`), NEXUS treści nie ocenia.
- Członek Rady = aktywne konto z rolą `board`; admin bez tej roli nie
  głosuje. Konto dodane po wysyłce nie głosuje w tej uchwale. Głos można
  zmienić do zamknięcia i terminu.
- **Bramka:** Rada ma w Insights tylko odczyt, więc `POST
  /votes/{id}/ballot` stoi na osobnym `ballot_router` z
  `require_section_access_any_read(insights)`; uprawnienie do głosu (członek
  ze składu) sprawdza trasa. Reszta tras uchwał na zwykłym routerze Rady,
  wysyłka i zamknięcie tylko admin.
- Zamknięcie (`/close`, admin) zapisuje wynik i przy podjęciu zakłada wiersz
  w Dokumentach → Uchwały Rady (numer, tytuł, wynik w opisie) — ten wiersz
  zalicza obowiązek „ocena sprawozdań” z R5, jeśli tytuł o tym mówi.

## Pilnują

`tests/test_supervisory_board_unit.py` (parser, wiersze z wzmianek, skrót,
czytnik, treść dzwonka), `tests/test_supervisory_board_api.py` (bramki ról,
jeden odpis przy braku zmian, dzwonek tylko przy nowym wpisie, wiersz KRS bez
usunięcia), `tests/test_supervisory_board_votes.py` (kworum połowy, większość głosów
oddanych, remis i Przewodniczący, głos spoza składu, wyłączenia z ust. 5,
głos konta bez Insights i admina = 403, wiersz uchwały w Dokumentach),
`tests/test_supervisory_board_meetings.py` (obowiązki z KRS, dokumentów i
posiedzeń; pakiet z dzwonkiem; usunięcie zablokowane po pakiecie; bramki),
`tests/test_supervisory_board_statements.py` (parser XML i XAdES, odrzucenie
DTD, ścieżki z księgi, wskaźniki, import z rokiem poprzednim, wpis ręczny
wygrywa z `xml_prev`, bramki), `frontend/src/components/rada/__tests__/DocumentsTab.test.tsx`
(Rada bez zapisu, awaria ≠ pusta lista), `board-role.test.ts`,
`middleware.test.ts`.
