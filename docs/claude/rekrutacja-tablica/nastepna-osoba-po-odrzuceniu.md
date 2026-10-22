# Po odrzuceniu z panelu osoby — od razu następna osoba (13.10.2026)

<!-- indeks: kolejka „‹ ›” = kolumna + „Kto dodał”, pasek „Odrzucono · Pokaż” -->

Prośba rekrutera, decyzje Artura D1–D4 z 13.10.2026 (makiety:
https://claude.ai/artifact/JMfDAZdjFJtGjFxwHNyta6). Do tej daty po „Potwierdź”
panel zostawał na odrzuconej osobie, a „‹ N z M ›” zamieniał się w napis
„Panel osoby”: osoba wypadała z `dockNavigationOrder(visibleCols)`, a dok
szukał jej we wszystkich kolumnach, także zamkniętych. Rekruter w widoku
„Rozwiń” musiał zwinąć panel i szukać następnej karty na Tablicy.

- **Które przyciski przenoszą (D1).** Tylko uruchomione z panelu osoby:
  „Odrzuć z powodem” i „Zrezygnował” w doku (także odrzucenie z akcji
  wymagań w doku i rezygnacja po zmianie stawki — idą przez `onReject` doku)
  oraz „Odrzuć” w stopce formularza screeningu w widoku „Rozwiń”
  (`ScreeningFullForm` ma własny ruch przez `usePipelineMoveCore`; panel
  podaje mu `rejectFollowUp` przez `WorkbenchContext`). Karta, przeciągnięcie,
  pasek zaznaczonych osób, okno „Przesuń dalej” i przegląd Delivery Leada
  zostają bez zmian. „Zapisz i przekaż dalej” nie przenosi — po przekazaniu
  rekruter zwykle pracuje dalej z tą samą osobą (CV, QC).
- **Kto jest następny (D2).** Osoba, która stała za zamykaną w kolejności
  strzałki „›”. Od 14.10.2026 ta kolejność to kolumna otwartej osoby z filtrem
  „Kto dodał”, nie cała Tablica — sekcja niżej; po
  ostatniej osobie kolumny panel się zamyka, nie przechodzi do następnej
  kolumny. Kolejność jest migawką
  z chwili otwarcia okna (`dockFollowUp` w `KanbanBoardV2.tsx`); po ruchu
  bierzemy pierwszą osobę z migawki, która nadal jest na Tablicy. Widok
  zostaje jak po „›” (`showInDock`): w panelu dzielonym osoba z „Nowych”
  albo „Screeningu” dostaje formularz, inna — zwykły dok.
- **Dopiero po odpowiedzi serwera.** `SendMoveOptions.onMoved` w
  `usePipelineMove.tsx` woła się przed `return true` w `sendMove`; ponowienia po
  „Przenieś mimo to” i po debriefie niosą te same `opts`, więc okno ostrzeżenia
  albo debriefu dotyczy jeszcze zamykanej osoby. Odmowa serwera i konflikt
  wersji niczego nie wołają — panel zostaje. Gdy rekruter w trakcie ruchu
  otworzył kogoś innego albo zamknął panel, panel nie skacze.
- **Pasek zamiast ciszy (D3).** Nad nazwiskiem następnej osoby `role="status"`
  „Odrzucono: X · powód” (przy rezygnacji „Rezygnacja: X · powód”) i „Pokaż”,
  które otwiera zamkniętą osobę. Tam w miejscu napisu „Panel osoby” stoi
  „Wróć do kolejki ›” (z powrotem do następnej osoby, jak klik w jej kartę).
  Pasek znika po przejściu do innej osoby i po ruchu tej, przy której stoi.
- **Ostatnia osoba (D4).** Panel się zamyka, komunikat „Odrzucono: X. To była
  ostatnia osoba w kolejce „Nowi”.” z „Pokaż” (do 14.10.2026: „…w kolejności
  Tablicy”).
- **Okno mówi, kogo zamykasz i kto dalej.** `RejectionV2` dostaje `subject`
  (każde zamknięcie jednej osoby: imię i nazwisko, z panelu także kolumna)
  i `nextPerson` (tylko z panelu: „Dalej: Anna Wiśniewska · Nowi” albo „To
  ostatnia osoba w kolejce — panel się zamknie.”). Bez `nextPerson` okno
  niczego nie zapowiada.
- **Czego to nie zmienia.** Szkic notatki zostaje przy zamkniętej osobie
  (szkice są per osoba, `lib/note-drafts.ts`). Niezapisany formularz screeningu
  zamykanej osoby przepada tak samo jak przy „›” — powód i notatka idą przez
  okno odrzucenia. Komunikat „Anuluj wysyłkę” maila do kandydata działa jak
  dotąd.
- Testy: `KanbanBoardV2.test.tsx` (opisy z 13.10.2026), `RejectionV2.test.tsx`,
  `PipelineCandidateDock.test.tsx`, `ScreeningFullForm.test.tsx`.

## Kolejka w kolumnie i filtr „Kto dodał” (D1–D5, 14.10.2026)

Prośba rekrutera przekazana przez Artura: przy screeningu chce widzieć tylko
osoby, które sam dodał, i przechodzić strzałkami tylko po jednym etapie.
W rekrutacji 383089 panel pokazywał „1 z 66”, a w „Nowych” było 43 (23 z nich
dodała jedna osoba). Makiety i decyzje D1–D5:
https://claude.ai/artifact/XdnEDtUXR7PRm7TtJhn4kj. Artur 14.10.2026: „tak na
wszystkie D1–D5, wdrażaj”.

- **Strzałki chodzą po jednej kolumnie (D1).** Kolejka panelu to kolumna
  Tablicy otwartej osoby (z etapami złożonymi w tę kolumnę), zawężona filtrem
  „Kto dodał”, karty od góry. Za licznikiem stoi nazwa kolejki („Nowi”,
  „Nowi · dodani przez Ciebie”); klik otwiera menu filtra, bo w widoku
  „Rozwiń” Tablica jest zasłonięta. Zamknięci nie są kolejką.
- **Kiedy kolejka się zmienia.** Kotwica (`queue` w `KanbanBoardV2.tsx`,
  `queueColumnAfterOpen` w `lib/board-dock-order.ts`) jest liczona w renderze:
  osoba z obecnej kolejki (strzałki, przejście po odrzuceniu, „Wróć do
  kolejki”) — kolejka zostaje; osoba z innej kolumny — kolejką staje się jej
  kolumna; osoba spoza kolumn (zamknięta, „Pokaż”) — kolejka zostaje.
- **Osoba wypadła z kolejki** (przesunięta dalej, zamknięta, schowana
  filtrem): panel zostaje na niej, zamiast licznika „Wróć do kolejki ›” —
  po odrzuceniu do osoby, która przejęła panel, inaczej do pierwszej osoby,
  która stała za nią i nadal jest w kolejce (`returnToQueueTarget`).
- **Przejście po odrzuceniu** (wyżej) bierze tę
  samą kolejkę: następna osoba z tej kolumny i z tym filtrem. Po ostatniej
  panel się zamyka z „To była ostatnia osoba w kolejce „Nowi”.”; okno
  odrzucenia zapowiada „To ostatnia osoba w kolejce — panel się zamknie.”
  „Następna w Screeningu” w karcie CV liczy całą widoczną Tablicę z filtrem.
- **Koniec kolejki (D4).** Na ostatniej osobie „›” jest nieaktywna, a pasek
  „To ostatnia z N osób w kolejce.” ma „Od pierwszej”, „Wszyscy (M)”
  (gdy filtr coś schował) i „Dalej: <kolumna> (K) ›” — do pierwszej kolumny
  na prawo, w której ktoś jest (z filtrem). Jedna osoba bez dalszych kroków —
  bez paska. Pasek stoi na górze `dock-actions`, nie w pasku osoby: w wąskim
  doku pasek osoby się nie przewija, a te dwie linie zabierały sekcjom 61 px
  przy 1280 × 650 (20.10.2026, `duzy-podglad-po-lewej-stronie-panelu-osoby.md`).
- **Filtr „Kto dodał” (D2).** Jeden przycisk w linii faktów nagłówka
  rekrutacji (`JobDetailCompactHeader.factsTrailing`, tylko na Tablicy), nie
  pasek filtrów. Menu: „Wszyscy”, „Ty” (zawsze, z zerem wyszarzone), pozostałe
  osoby od największej liczby, „System” (osoby od silnika „Nowi na 20”,
  `entry_source = "system"`, `?added_by=system`, 23.10.2026), „Brak danych” (karty bez zapisanej osoby
  dodającej, głównie z Traffita). Liczby = osoby w toku na Tablicy
  (`peopleInProgress`: bez zamkniętych, z „Poza szablonem”). Karty innych
  znikają (nie są przygaszane); licznik kolumny „N z M”; kolumna pusta przez
  filtr mówi „Brak osób dodanych przez…” i ma „Pokaż wszystkich (M)”, nie
  zwęża się i nie znika przy „Ukryj puste kolumny”. Kafle „Kandydaci do
  dodania”, „Zamknięci”, „Porównaj (N)” i „Obsada N z M” liczą bez filtra.
- **Tylko w adresie (D3).** `?added_by=<numer>|none` (`lib/board-added-by.ts`),
  zapis przez `useUrlWriter` (bez routera Nexta). Nowe wejście w rekrutację =
  „wszyscy”: kto zapomni o filtrze, nie zobaczy „pustej” rekrutacji.
- **„Moje” = kto dodał (D5).** Osoba z PIERWSZEGO wpisu etapu pary
  kandydat–rekrutacja — `added_to_job_by_id` w odpowiedzi
  `GET /api/pipeline/kanban/{job_id}` (obok `added_to_job_by_name`), ta sama,
  którą karta pokazuje inicjałami. Porównanie po numerze, nie po imieniu
  (imiennicy). Nie rezerwacja „Biorę” i nie `recruiter_id` (właściciel procesu).
- **Osoba na karcie od „Zweryfikowanego” (20.10.2026).** Rekruterka
  zweryfikowała osobę, którą dwa miesiące wcześniej dodał ktoś inny, a karta
  w „CV w Cpro” dalej pokazywała dodającego. Decyzja Artura: w „Nowych”
  i „Screeningu” karta pokazuje, kto dodał. Od „Zweryfikowanego” w prawo
  (i w „Zamkniętych”) pokazuje, kto zweryfikował (`verified_by_*` w kanbanie).
  Dymek pokazuje obie osoby z datami. Wyborem osoby rządzi `cardOwner`
  w `lib/board-card-badges.ts`. Filtr „Kto dodał” i kolejka panelu dalej
  liczą po dodającym (D5).
- **„Kto zweryfikował” = PIERWSZY weryfikujący pary (21.10.2026).** Karta
  Tablicy i przegląd DL biorą `stage_verifier.first_verifier` — tę samą osobę
  co premia rekrutera (`load_verifiers`), KPI i rekruter pary w rozmowach.
  Nie najnowszy wiersz „Zweryfikowany”: DL, który cofa kartę z „QC CV”,
  zapisuje nowszy wiersz „Zweryfikowany”, a karta pokazywała wtedy jego
  zamiast rekruterki (NORD/047/2026). Decyzja Artura 21.10.2026.
- **Przeciąganie i zaznaczanie przy filtrze.** Filtr jest nakładany na kolumny
  do renderu PRZED przeciąganiem, a karta przy upuszczeniu jest szukana po
  `draggableId`, nie po `source.index`. Zaznaczone osoby, które filtr schował,
  są odznaczane.
- **Wyjątek od „Tablicy bez paska filtrów”** (`prostszy-ekran-rekrutacji-…md`):
  jeden przycisk w nagłówku. Kolejny filtr Tablicy = nowa decyzja Artura.
- Testy: `lib/__tests__/board-added-by.test.ts`, `board-dock-order.test.ts`,
  `KanbanBoardV2.test.tsx` (opisy z 14.10.2026), `PipelineCandidateDock.test.tsx`,
  `AddedByFilter.test.tsx`, `JobDetailPage.routing.test.tsx`,
  `backend/tests/test_jobs_list_needs_action.py`. Harness: `/preview/job-detail`
  (przycisk w nagłówku, osoby dodane przez trzy osoby i jedna bez danych).

## Powód odrzucenia w panelu osoby i na karcie (19.10.2026)

Prośba rekrutera przekazana przez Artura: powód odrzucenia było widać tylko
w profilu kandydata (zakładka „Rekrutacje”), a kolumna zamkniętych obiecywała
„powody w doku”, których panel osoby nie pokazywał. Makiety i decyzje D1–D3:
https://claude.ai/artifact/SHKjoNHA1MC2XSAYR4A86r. Artur 19.10.2026: A + B,
z osobą, która odrzuciła; stan maila odrzucenia później.

- **Ramka w panelu osoby (A).** `DockClosedReason` stoi jako pierwsza rzecz
  w `dock-actions` — widać ją bez przewijania i w widoku „Rozwiń”. Treść:
  „Odrzucony: <powód>” albo „Rezygnacja: <powód>”, pod spodem komentarz
  z okna odrzucenia (`notes` etapu), na dole „kto · data”. Oś czasu w „W
  procesie” ma wpis „Odrzucony · <powód>” z datą i osobą zamiast „W etapie
  od N dni”. Osoby w toku ramki nie mają.
- **Linia na karcie (B).** Karta w „Odrzuconych” i „Rezygnacjach” ma pod
  osobą jedną linię z powodem (ucięta), pełny powód, komentarz, kto i kiedy
  w dymku (`title`) i w opisie karty dla czytnika. Linia jest widoczna także
  w przeglądzie na dużym ekranie (nie chowa się jak odznaki). Podpis kolumny
  zamkniętych: „powody na kartach i w panelu”.
- **Dane.** Wyłącznie z karty `GET /api/pipeline/kanban/{job_id}`:
  `rejection_reason_name` (etykieta po polsku z `rejection_reason_labels`,
  z tabeli powodów, więc powód wycofany z szablonu nadal się wyświetla),
  `closed_by_name` (kto przesunął kartę na etap zamknięty), `notes` i
  `moved_at`. Oba nowe pola serwer wypełnia tylko dla kart `rejected`
  i `withdrawn`; reszta kart ma `null`. Wspólna funkcja: `lib/closed-reason.ts`.
- **Tony.** Odrzucenie z powodem — czerwień (jak „Powód odrzucenia”
  w profilu). Rezygnacja, brak powodu i „Powód nieznany (import z Traffita)”
  — szarość. Brak powodu mówimy wprost („powód nie został zapisany”, na
  karcie „Powód nie zapisany”), nic nie zgadujemy.
- **Czego to nie robi.** Nie pokazuje stanu maila odrzucenia (D3 — osobny
  krok, gdy rekruterzy poproszą; Tablica tych danych nie ma). Nie dodaje
  filtra ani grupowania po powodzie (nowy filtr Tablicy = decyzja Artura,
  sekcja „Kolejka w kolumnie” wyżej). Nie pozwala edytować powodu.
- Testy: `lib/__tests__/closed-reason.test.ts`,
  `PipelineCandidateDock.test.tsx` i `KanbanBoardV2.test.tsx` (opisy
  z 19.10.2026), `backend/tests/test_pipeline_integrity.py`
  (`test_kanban_closed_card_carries_reason_and_who_closed_it`). Harness:
  `/preview/job-detail` (odrzucona z powodem i komentarzem, z Traffita,
  rezygnacja).
