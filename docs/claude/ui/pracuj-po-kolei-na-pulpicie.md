# „Pracuj po kolei” — panel osoby na pulpicie (23.11.2026)

<!-- indeks: „Czeka na Ciebie” → kolejka przez wszystkie rekrutacje, panel nad pulpitem -->

Rekomendacja 3 z analizy dnia rekrutera A–Z (raport
https://claude.ai/artifact/Bf7wiygZoxpTPq9G8oHgiL, sekcja „3 · „Czeka na
Ciebie” jako kolejka”). Artur 23.11.2026: budować wszystkie pięć rekomendacji
naraz. Do tej daty „Otwórz” w „Czeka na Ciebie” prowadził na Tablicę jednej
rekrutacji, a „‹ ›” panelu chodziły tylko po jej kolumnie. Pomiar: u konta
rekrutera na stagingu 31 osób z 13 rekrutacji (najstarsza w Screeningu bez
arkusza od 19.10), na kopii produkcji średnio 11 przeskoków między
rekrutacjami dziennie na 41 ruchów kart.

Kod: `lib/dashboard-person-queue.ts` (kolejność, kto dalej),
`components/v2/dashboard/DashboardPersonQueue.tsx` (stan kolejki, dane
rekrutacji, portal), `KanbanBoardV2` z propem `panelOnly`.

- **Ten sam panel, nie kopia.** Pulpit montuje `KanbanBoardV2` rekrutacji
  bieżącej osoby z `panelOnly` — plansza jest ukryta (`hidden`), panel osoby
  (`PersonPanelShell`, dok, „Rozwiń”, zakładki, arkusz, notatka, okna ruchu)
  działa jak na Tablicy. Ruch karty wyłącznie przez `usePipelineMove`
  Tablicy. Nie pisz drugiego panelu ani własnego `POST /api/pipeline/move`.
  Dane: te same klucze zapytań co strona rekrutacji (`["job", id]`,
  `["kanban", id]`, `["pipeline-scores", id]`), więc pulpit i otwarta
  Tablica odświeżają się nawzajem. Bez nowej trasy API.
- **Portal do `<main id="main">`.** Kafelek „Czeka na Ciebie” stoi w siatce
  z `transform`, a `position: fixed` w przodku z transformacją przestaje być
  przyklejony do okna. `<main>` nie ma transformacji i daje górną krawędź
  panelu (`chromeTop`).
- **Kolejka.** Trzy listy pulpitu w tej kolejności: „Screening bez arkusza”
  (`flow.screening`), „Zweryfikowani czekają na CV” (`flow.verified`), „Od
  systemu czeka na decyzję” (`flow.autofill_decisions`); w każdej najdłużej
  czekający pierwsi (`since`, przy osobach od systemu dni robocze). Para
  kandydat–rekrutacja jest w kolejce raz. Serwer oddaje do 20 osób na listę;
  po odświeżeniu nowe osoby dochodzą NA KONIEC (`mergeQueueOrder`) — kolejność
  nie przestawia się pod ręką rekrutera.
- **Gdzie co stoi.** Przycisk „Pracuj po kolei · N” w nagłówku „Czeka na
  Ciebie” (N = osoby z trzech list, bez przycisku przy zerze). W panelu:
  „‹ N z M ›” z nazwą kolejki „Czeka na Ciebie” w pasku osoby, nad treścią
  pasek kolejki (`person-queue-bar`): lista, rekrutacja · klient · od kiedy
  czeka, „Otwórz Tablicę” (`/jobs/{id}?candidate=`), „Dalej: <osoba> ·
  <rekrutacja> ›” albo „To ostatnia osoba w kolejce.”.
- **Klik w osobę z tych trzech list** (nazwisko, „Otwórz” przy osobie od
  systemu) otwiera panel na pulpicie od tej osoby. Link zostaje linkiem:
  ⌘/Ctrl/Shift-klik i środkowy przycisk otwierają Tablicę w nowej karcie
  (`openOnDashboard`). Pozostałe listy pulpitu (blokady 12 h, Ogłoszenia,
  Zatrudnieni bez zamówienia, „Czeka na klienta”…) prowadzą na Tablicę jak
  dotąd. Żadna reguła pulpitu nie wymagała przejścia na Tablicę.
- **Po decyzji — jak na Tablicy (`rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md`).**
  Sam przeskakuje tylko po „Odrzuć z powodem” i „Zrezygnował” z panelu
  (także „Odrzuć” w formularzu screeningu), dopiero po odpowiedzi serwera,
  i tylko gdy panel nadal pokazuje tę osobę — rekruter, który zdążył przejść
  dalej, nie traci miejsca. Okno odrzucenia zapowiada „Dalej: <osoba> ·
  <rekrutacja>”. Następna osoba dostaje pasek „Odrzucono: X · powód” z
  „Pokaż”. Po ostatniej panel się zamyka z komunikatem „…To była ostatnia
  osoba w kolejce „Czeka na Ciebie”.”. Inne ruchy (np. „Zapisz i przekaż
  dalej”, „Biorę”) nie przeskakują — rekruter zwykle pracuje dalej z tą
  osobą (CV, telefon), a niewysłana notatka zostaje. Osoba, która po
  odświeżeniu list wyszła z kolejki, zostaje w panelu z paskiem „Poza
  kolejką · Ta osoba nie czeka już na liście” i „Wróć do kolejki”.
- **Odświeżenie.** Każde odświeżenie Tablicy bieżącej rekrutacji (po ruchu)
  unieważnia `GET /api/board-tasks`; Tablica następnej osoby z innej
  rekrutacji wczytuje się w tle, żeby „Dalej” nie czekało na sieć.
- **Awaria ≠ pustka.** Panel wisi na `isSuccess` Tablicy i rekrutacji; przy
  wczytywaniu pasek kolejki już stoi z „Wczytuję panel osoby…”, przy awarii —
  „Nie udało się wczytać Tablicy tej rekrutacji.” z ponowieniem. Osoba, której
  nie ma już na Tablicy, dostaje zdanie zamiast poprzedniej osoby.
- **Czego to nie robi.** Bez filtra „Kto dodał” w kolejce (kolejka to listy
  pulpitu, nie kolumna). Zamknięcie rekrutacji i inne zakładki rekrutacji
  zostają na jej stronie (`canCloseJob: false`, `onTabChange` prowadzi na
  `/jobs/{id}?tab=`). Układ „Tryb rozmowy” i rząd przycisków odrzucenia
  w panelu zmieniają osobne PR-y tej samej analizy — tu panel jest taki,
  jak na Tablicy.
- Testy: `lib/__tests__/dashboard-person-queue.test.ts`,
  `dashboard/__tests__/DashboardPersonQueue.test.tsx`,
  `dashboard/__tests__/BoardTasksPanel.personQueue.test.tsx`,
  `pages/__tests__/KanbanBoardV2.test.tsx` (opisy z 23.11.2026). Inwentarz:
  `dashboard.person-queue`.
