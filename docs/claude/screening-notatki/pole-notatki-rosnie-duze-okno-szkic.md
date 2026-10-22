# Pole notatki: rośnie z tekstem, duże okno pisania, szkic (12.10.2026)
<!-- indeks: Enter w dużym oknie = nowa linia, szkic w sessionStorage -->

Zgłoszenie rekruterów: pole notatki na dole panelu osoby miało jedną linię
(230 × 32 px w wąskim doku), nie dało się go powiększyć, a niewysłany tekst
znikał po przejściu do innej osoby. Decyzje Artura 12.10.2026 (makiety:
https://claude.ai/artifact/Fke4apawoCig47Lqqjsww2): pole rośnie samo, „Powiększ”
otwiera duże okno, szkic zostaje. Uchwyt do ręcznej zmiany wysokości odrzucony —
daje to samo ręcznie, a na laptopie 1280 × 720 wysokie pole na stałe zabiera
miejsce sekcjom. Raport: `docs/note-field-completion-report.md`. Tylko front.

- **`MentionTextarea` rośnie z tekstem** od `rows` do `maxRows` linii (domyślnie
  10), dalej przewija się w środku. Wysokość liczy `lib/textarea-autogrow.ts`
  z pomiaru ukrytej kopii pola (`lib/textarea-mirror.ts`), nie przez zwinięcie
  prawdziwego pola do `height: auto` — to skraca stronę na czas pomiaru
  i przestawia przewinięcie, gdy ktoś pisze odpowiedź na samym dole listy.
  Rachunek dolicza ramkę (pole jest `border-box`) i zaokrągla sufit w górę,
  bo na dotyku linia ma 21,33 px. Pole w ukrytym panelu ma szerokość 0, więc
  kopia bierze wtedy ostatnią zmierzoną szerokość, a ramka pochodzi z kroju —
  inaczej pole wracałoby spod przeglądu DL z wysokością sufitu. Nowe pole
  notatki dostaje rośnięcie samo.
- **Czaty mają `autoGrow={false}`** (`JobChatTab`, `CandidateChatTab`): lista
  wiadomości trzyma się dołu tylko przy nowej wiadomości, więc rosnące pole
  wypychałoby ostatnie poza widok. Włączenie tam rośnięcia wymaga najpierw
  poprawki trzymania listy przy dole.
- **Kompozytor w doku ma trzy stany** (`DockNoteComposer`
  w `PipelineCandidateDock.tsx`): zwarty (puste pole bez fokusu — jedna linia
  jak dotąd), otwarty (fokus w kompozytorze albo tekst — pole na całą
  szerokość, z fokusem 3–10 linii, bez fokusu najwyżej 3) i duży („Powiększ”
  — pole wypełnia panel pod paskiem osoby). Limit 3 linii bez fokusu jest
  po to, żeby długi szkic nie zabierał sekcjom doku miejsca: przy 1280 × 650
  zostaje ok. 310 px przewijanego obszaru zamiast ok. 170.
- **Kompozytor zostaje w pliku doku.** Plik jest w `sources` przewodnika
  `jobs.person` (lista ma limit 3 i jest pełna), a inwentarz funkcji szuka
  w nim literału `ariaLabel="Dodaj notatkę"`. Wyniesienie do osobnego pliku
  zdjęłoby z pola przegląd przewodnika przy zmianie klawiszy.
- **Klawisze:** w małym polu Enter dodaje notatkę, Shift+Enter robi nową linię;
  w dużym oknie Enter robi nową linię, a dodaje przycisk albo Ctrl/⌘+Enter
  (działa też w małym). Długa notatka z rozmowy nie może wysłać się w połowie.
  Podpowiedź klawiszy stoi pod polem w obu stanach.
- **Duże okno ukrywa środek doku, nie odmontowuje go** (`hidden` + `inert` na
  `dock-body`): otwarte sekcje, zakładka i podgląd CV zostają, plik CV nie
  pobiera się drugi raz. Strefa podglądu po lewej jest rodzeństwem kolumny,
  więc po „Rozwiń” CV widać podczas pisania — dlatego okno nie jest dialogiem.
- **Esc zamyka najwyższą warstwę, a duże okno jest najwyższą.** Okno zmniejsza
  nasłuch `window` w kompozytorze — także gdy fokus jest poza polem; zamknięcie
  listy „@” przychodzi tam jako `defaultPrevented`. Tablica ma własny nasłuch
  `window`, a kolejność obu nie jest stała (tamten rejestruje się na nowo po
  „Rozwiń” i po odświeżeniu karty) i React przerysowuje między nimi. Dlatego
  są dwa zabezpieczenia i oba muszą zostać: kompozytor woła `preventDefault()`
  (Tablica druga — widzi obsłużone zdarzenie) i ma `data-note-enlarged`
  (Tablica pierwsza — widzi otwarte okno). Bez pierwszego jedno Esc po
  „Powiększ” → „Rozwiń” zamykało i okno, i rozwinięcie; jsdom tego nie pokaże
  (`fireEvent` przerysowuje dopiero po wszystkich nasłuchach), pilnuje e2e.
  Okno w doku ukrytym pod przeglądem DL warstwą nie jest (`closest("[hidden]")`).
- **Lista „@” w polu wyższym niż 3 linie staje przy linii z „@”**
  (`chooseCaretPlacement`, pozycja linii z `caretOffsetTop`), nie przy krawędzi
  pola: nad polem na 10 linii byłaby do 200 px od kursora, a w dużym oknie nie
  ma miejsca ani nad polem, ani pod nim. Pole do 3 linii zachowuje regułę
  z 08.10.2026 i klasy `top-full`/`bottom-full`.
- **Szkic to `sessionStorage`**, klucz `nexus:note-draft:v1:<osoba pisząca>:<rekrutacja>:<kandydat>`
  (`lib/note-drafts.ts`). Świadomie nie `localStorage`: notatka niesie dane
  kandydata, więc żyje najwyżej tyle co karta przeglądarki — jak robocze
  wyszukiwanie Talent Radaru. Przeżywa zmianę osoby, zamknięcie panelu,
  odświeżenie i samoczynne przeładowanie karty po wdrożeniu.
- **Szkic znika z pamięci w chwili wysłania** (`onMutate`), a po błędzie zapisu
  wraca, jeśli nic nowego nie powstało. `onSuccess` działa też po odmontowaniu
  doku, więc szkic trzymany do odpowiedzi serwera wracałby po „wyślij, wyjdź,
  wróć” jako gotowy duplikat.
- **Wylogowanie i martwa sesja kasują szkice** — `clearSessionArtifacts`
  (`lib/session.ts`) woła `clearNoteDrafts`. Tamta lista jest listą dozwolonych:
  nowy klucz z danymi kandydata trzeba do niej dopisać. `lib/note-drafts.ts`
  nie importuje `store/auth` ani `lib/api` (cykl przez `lib/session`).
- **Margines 92 px „na maskotkę Jarvisa” zniknął.** Od 04.10.2026 maskotka chowa
  się, gdy panel osoby jest otwarty (`globals.css`), więc margines zabierał polu
  jedną czwartą szerokości na nic.
- **Poza zakresem:** szkic w polu notatki profilu kandydata i w `DockNotesPanel`
  (Rozmowy → Notatki) — tam pole tylko rośnie.
- Testy: `PipelineCandidateDock.test.tsx` (stany, klawisze, szkic),
  `KanbanBoardV2.test.tsx` (warstwy Esc; „ukryty, nie odmontowany” sprawdza
  tożsamość węzła pola, bo sama wartość wróciłaby też ze szkicu),
  `MentionTextarea.test.tsx`, `note-drafts.test.ts`, `textarea-autogrow.test.ts`,
  e2e „pole notatki rośnie…” w `responsive-preview.spec.ts` (1280 × 650).
