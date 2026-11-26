# Karty bez śladu wracają do „Nowych” po 2 dniach roboczych (23.11.2026)
<!-- indeks: `services/screening_stale.py`, pętla `screening_stale`, `SCREENING_STALE_RETURN_ENABLED`, `returns_to_new_on`, `entry_meta.returned_to_pool_at`, grupy „Do telefonu” / „Nie odebrał” / „Po rozmowie” w „Screeningu”, `scripts.screening_stale_return`, `returned_from_screening`, grupa „Wróciły od Ciebie”, „Weź z powrotem” -->

Decyzja Artura z 23.11.2026, rekomendacja 1 z analizy „Dzień rekrutera A–Z”
(https://claude.ai/artifact/Bf7wiygZoxpTPq9G8oHgiL, sekcja „1 · Screening bez
zawieszonych kart”). Artur: „wraca do nowych po 2 dniach roboczych i jest
dostępna znowu dla wszystkich albo cofane jest biorę i też dostępna dla
wszystkich”. Czyli automat, a nie pasek „Zdecyduj” z makiety.

Pomiar na kopii produkcji z 23.11: z 1 500 osób wziętych do Screeningu
26.10–09.11 aż 402 (27%) dalej tam stało po 2–4 tygodniach, 219 z nich bez
jednej notatki. W otwartych rekrutacjach 1 335 par w Screeningu, 750 starszych
niż 7 dni, w 101 rekrutacjach. Podgląd automatu na tej samej kopii (wieczór
23.11): 1 441 kart do oddania (1 285 ze Screeningu, 156 „Biorę” w „Nowych”)
w 137 rekrutacjach, 33 osoby z dzwonkiem.

## Reguła

- **Screening:** karta bez śladu przez 2 pełne dni robocze wraca do „Nowych”,
  bez „Biorę” i bez blokady 12 h, więc bierze ją każdy.
- **„Nowi” z „Biorę”:** karta, którą ktoś wziął („Biorę”, „Dzwonię”, „Przejmij”,
  czyli wpis `candidate_claimed`), bez śladu przez tyle samo traci „Biorę”.
  Ręczne dodanie też zakłada blokadę, ale bez wpisu: taka karta zostaje
  u dodającego (`biore-zmienia-osobe-karty.md`).
- **Ślad** to: ruch karty, „Biorę”, notatka człowieka do osoby przy tej
  rekrutacji albo bez rekrutacji (także „Nie odebrał”, `contact_attempt`,
  i odpowiedź w wątku; notatka z importu liczy się datą źródła), zapis arkusza
  screeningu (`screening_answered`) i umówiony telefon. Zapis terminu to ślad,
  a otwarty termin trzyma kartę do startu + 30 min, jak blokada
  w `umowiony-telefon-na-screening.md`. Notatka z innej rekrutacji i notatka
  bez autora śladem nie są.
- **Dni:** kalendarz firmy (`business_date`, polskie święta). Dzień śladu = 0,
  potem dwa pełne dni robocze ciszy, karta wraca trzeciego dnia roboczego:
  ślad w poniedziałek → czwartek, w czwartek → wtorek, we wtorek przed świętem
  w środę → poniedziałek. To ta sama miara co termin porcji
  (`review_batch.close_window_start`), więc obie reguły mówią o tym samym dniu.
- **Gdzie działa:** opublikowane rekrutacje. Zamknięta i szkic zostają, jak
  były (zamknięcie zostawia osoby tam, gdzie stały).
- **Dzwonek** dostaje osoba z „Biorę”, a w Screeningu bez niej osoba, która
  kartę tam przesunęła. Jeden na osobę i rekrutację, typ
  `candidate_claim_taken` (kategoria przekazań, jak „przejął(a) osobę”), więc
  bez migracji enuma. Dedup dobowy `emit` po rekrutacji: restart nie dzwoni
  drugi raz.
- **„Prowadzi” zostaje.** Przypisanie admina i HoR (`prowadzi-przypisanie-osoby.md`)
  to decyzja przełożonego, automat go nie zdejmuje. Karta z „Prowadzi” wraca
  do „Nowych” jak każda.

## Jak to działa

- **Ruch wstecz idzie przez `transition_process`**, wspólną ścieżkę zapisu
  etapu na serwerze (`require_existing=True`, autor pusty, notatka „NEXUS: 2 dni
  robocze bez śladu…”), a nie przez `/api/pipeline/move`: to automat bez
  człowieka, bez bramek ruchu i bez `usePipelineMoveCore` (ten jest dla ekranów).
  Etap docelowy to pierwszy etap szablonu z kodem `new`, który Tablica pokazuje
  w kolumnie „Nowi” (`_new_column_defs`; „Wysłać do Cpro” też ma kod `new`).
  Ślad w historii: `stage_changed` z `source = screening_stale_return` i
  `stale_card_returned`.
- **Raporty lejka:** „Lejek po etapach” liczy pary, które doszły do etapu
  („Doszło”) i stan dziś („Teraz”), więc powrót nie dokłada nikogo do „Doszło”,
  a z „Teraz” zdejmuje kartę ze Screeningu. Pierwsze wejście (`earliest`),
  „kto dodał”, Liga i premie się nie zmieniają. Ponowne wzięcie do Screeningu
  przez innego rekrutera jest jego ruchem.
- **Pętla `screening_stale`** co 15 minut, tylko w dzień roboczy, najwyżej
  200 kart na przebieg (pierwszy przebieg na produkcji ma ok. 1 400 kart, więc
  rozkłada się na ok. 2 godziny). Karta wraca przy pierwszym przebiegu po
  północy dnia powrotu, przed blokadą porcji o 7:00. Wyłącznik
  `SCREENING_STALE_RETURN_ENABLED` (domyślnie włączony, workflow „Coolify set env”).
- **Staging:** pętla zatrzymana (`STAGING_BLOCKED_TASKS`), bo oddałaby setki
  kart we wspólnej kopii, na której inne sesje robią zrzuty. Ręcznie:
  `python -m scripts.screening_stale_return --job <id>` (podgląd),
  `--apply` (przebieg z dzwonkami), `--as-of <moment>` (liczy, jakby był inny
  dzień, do sprawdzenia ścieżki bez czekania).

## Porcja dnia i termin decyzji

- **Porcja nie daje tej osoby z powrotem jako nowej.** Osoba od systemu
  (`entry_source = system`) po powrocie ma w `entry_meta` znacznik
  `returned_to_pool_at` i traci `review_owner_id`, `decided_*` i `decision`.
  `review_batch.in_batch` zwraca dla niej `False`, więc nie wchodzi do porcji
  nikogo, nie ma „Dla: …” na karcie i nie zajmuje miejsca w planie. Była już
  oceniona jako „Pasuje”, a stoi w „Nowych” dla wszystkich.
- **„Do screeningu” sprzed powrotu przestaje być zaległością.** `_decisions`
  pomija decyzję, gdy znacznik powrotu jest późniejszy niż ruch. Dotąd pomijała
  tylko kartę, która stoi w „Nowych”, więc gdy kartę wziął potem ktoś inny,
  pierwszej osobie wracała blokada wyszukiwania za cudzą kartę.
- **Blokada za „Pasuje” bez wyniku po 2 dniach (Artur, 10.11) zostaje** dla kart
  ze śladem: notatka bez wyniku, telefon, który minął. Kartę bez żadnego śladu
  automat oddaje do puli tego samego dnia, w którym zaczęłaby blokować, więc
  zamiast blokady rekruter traci kartę i dostaje dzwonek. „Nie odebrał”
  przesuwa oba terminy (#3788 w porcji: do 3 prób; tu każda notatka jest śladem).
- **Termin decyzji w „Nowych” liczy się od powrotu**
  (`autofill_decisions.waiting_days`), więc karta nie trafia od razu do
  „Czeka na Ciebie” jako „N dni bez decyzji”.

## Tablica

- **Kolumna „Screening” w grupach** (`lib/screening-column-groups.ts`) z danych,
  które Tablica już ma: „Do telefonu”, „Nie odebrał · do 3 prób” (pod kartą
  „próba N z 3”, po trzeciej „wpisz wynik albo odrzuć”) i „Po rozmowie ·
  dokończ arkusz” (`screening_done` albo odpowiedzi w karcie rekomendacji).
  W grupie najpierw karty, które najszybciej wrócą. Kolejność liczona przed
  filtrem „Kto dodał”, jak w „Nowych”.
- **Napis pod kartą**, gdy został najwyżej 1 dzień roboczy: „Wraca do „Nowych”
  jutro” / „dziś” / „w poniedziałek” (w piątek), a w „Nowych” „„Biorę” wygasa
  jutro”. Dzień daje serwer (`returns_to_new_on` w `/api/pipeline/kanban/{job_id}`,
  ta sama funkcja co automat), front nie liczy dni roboczych. Napis stoi pod
  kartą, nie w niej, bo wygląd karty jest wspólny dla wszystkich kolumn.
- **Chcesz zatrzymać kartę:** notatka, „Nie odebrał” albo „Umów telefon”.

Testy: `backend/tests/test_screening_stale.py` (z bazą: weekend, ślad w ostatniej
godzinie, notatka z innej rekrutacji, umówiony telefon w przyszłości, cudza
karta, zamknięta rekrutacja, „Biorę” w „Nowych”, ręczne dodanie, porcja),
`test_screening_stale_unit.py` (kalendarz, święto, znacznik),
`frontend/src/lib/__tests__/screening-column-groups.test.ts`.

## Ślad po powrocie: „Wróciły od Ciebie” (26.11.2026)

Rekruter zgłosił 26.11, że osoby „zniknęły” ze Screeningu i nie pamięta,
które to były. Pomiar z produkcji tego dnia: od 24.11 wróciło 1 651 kart
u 33 osób, a z pierwszej fali (1 490) ktoś wziął z powrotem tylko 53. Wrócone
karty stały w „Nowych” wśród kilkudziesięciu innych bez żadnego oznaczenia,
a dzwonek wymieniał trzy nazwiska. Decyzja Artura: reguła 2 dni roboczych
zostaje, Tablica pokazuje ślad. Analiza z makietami:
https://claude.ai/artifact/FqzXsyeZdmoVACwzrHibUg

- **Serwer:** `returned_from_screening` na karcie
  (`screening_stale.returned_cards_for_jobs`): `{at, holder_user_id,
  holder_name, screening_since}` dla kart, którym wpis `stale_card_returned`
  rodzaju `screening` wskazuje dzisiejszy ostatni wiersz etapu pary (nikt ich
  nie ruszył), z ostatnich `RETURNED_VISIBLE_WORKDAYS = 5` dni roboczych
  (dziś się liczy). Pięć dni pokazuje też pierwszą falę z 24.11 do 30.11.
  Wygasłe „Biorę” w „Nowych” (rodzaj `claim`) tu nie trafia: ta karta nigdzie
  nie zniknęła.
- **„Nowi”:** osobie z `holder_user_id` karty stoją na samej górze w grupie
  „Wróciły od Ciebie · N” (`orderNewColumn(…, viewerId)`, sekcja
  `returned_mine`), najświeższy powrót pierwszy, poza kolejką „Zadzwoń
  najpierw”. Pod kartą: „Wróciła <dzień>” (w podpowiedzi: od kiedy stała w Screeningu)
  i „Weź z powrotem” = `POST /api/pipeline/claim`, potem ruch strzałką „→”
  (ta sama droga, `deferMove` albo „Przesuń dalej”). Pozostali widzą pod kartą
  „Wróciła ze Screeningu od: <osoba>”. Karta dalej jest dla wszystkich.
  Gdy kartę wziął już ktoś inny („Biorę” innej osoby z terminem), nie stoi
  w grupie i nie ma napisu. Gdy „Biorę” jest już patrzącego (np. po „Cofnij”),
  „Weź z powrotem” robi sam ruch, bo własnej blokady nie da się przedłużyć (409).
- **„Screening”:** pasek nad kolumną liczy karty z napisem „Wraca do „Nowych”
  …” (`screeningWarning`), a pod taką kartą stoi „Nie odebrał”
  (`useNoAnswerNote`, ta sama notatka-próba co w doku), który zatrzymuje kartę.
- **Dzwonki** (gubienie kart przy limicie 200 na przebieg i dziennym dedupie,
  poranne ostrzeżenie dzień wcześniej) robi osobny PR z migracją typów
  powiadomień.

Testy: `test_screening_stale.py` (grupa po powrocie, okno 5 dni, wygasłe
„Biorę”), `test_screening_stale_unit.py` (okno), front:
`lib/__tests__/screening-returned.test.ts`, `new-column-queue.test.ts`.
