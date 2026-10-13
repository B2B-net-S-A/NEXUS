# Po odrzuceniu z panelu osoby — od razu następna osoba (13.10.2026)

<!-- indeks: które przyciski przenoszą, kolejność „›”, przejście dopiero po odpowiedzi serwera, pasek „Odrzucono … · Pokaż”, „Wróć do kolejki”, ostatnia osoba, okno mówi kogo zamykasz i kto dalej, czego to nie obejmuje -->

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
  strzałki „›” (kolumny od lewej, karty od góry). Kolejność jest migawką
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
  ostatnia osoba w kolejności Tablicy.” z „Pokaż”.
- **Okno mówi, kogo zamykasz i kto dalej.** `RejectionV2` dostaje `subject`
  (każde zamknięcie jednej osoby: imię i nazwisko, z panelu także kolumna)
  i `nextPerson` (tylko z panelu: „Dalej: Anna Wiśniewska · Nowi” albo „To
  ostatnia osoba na Tablicy — panel się zamknie.”). Bez `nextPerson` okno
  niczego nie zapowiada.
- **Czego to nie zmienia.** Szkic notatki zostaje przy zamkniętej osobie
  (szkice są per osoba, `lib/note-drafts.ts`). Niezapisany formularz screeningu
  zamykanej osoby przepada tak samo jak przy „›” — powód i notatka idą przez
  okno odrzucenia. Komunikat „Anuluj wysyłkę” maila do kandydata działa jak
  dotąd.
- Testy: `KanbanBoardV2.test.tsx` (opisy z 13.10.2026), `RejectionV2.test.tsx`,
  `PipelineCandidateDock.test.tsx`, `ScreeningFullForm.test.tsx`.
