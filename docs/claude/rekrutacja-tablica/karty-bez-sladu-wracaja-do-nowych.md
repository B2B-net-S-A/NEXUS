# Karty bez śladu wracają do „Nowych” po 2 dniach roboczych (23.11.2026)
<!-- indeks: `services/screening_stale.py`, pętla `screening_stale`, `SCREENING_STALE_RETURN_ENABLED`, `returns_to_new_on`, `entry_meta.returned_to_pool_at`, grupy „Do telefonu” / „Nie odebrał” / „Po rozmowie” w „Screeningu”, `scripts.screening_stale_return` -->

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
  kartę tam przesunęła. Od 26.11.2026 jeden dzwonek **dziennie na osobę**
  (typ `screening_cards_returned`, kategoria „Wzmianki”, temat „Rekrutacje”,
  encja `("user", id)`), liczony ze wszystkich dzisiejszych wpisów
  `stale_card_returned` tej osoby, z pełną listą nazwisk po rekrutacjach.
  Kolejny przebieg tego dnia aktualizuje treść i oznacza dzwonek jako
  nieprzeczytany (`_upsert_daily`). Dotąd dzwonek szedł typem
  `candidate_claim_taken` po każdym przebiegu (najwyżej 200 kart), a dzienny
  dedup przepuszczał tylko pierwszy: 24.11 na produkcji 593 z 1 632 kart nie
  trafiło do żadnego dzwonka, a „przejął(a) osobę” blokował powrót.
- **Ostrzeżenie dzień wcześniej:** w dzień roboczy od 8:00 do 20:00 raz
  dziennie (`warn_due`, `warn_once_safely` w pętli) osoba dostaje „Jutro wrócą
  do „Nowych”: N osób” (w piątek „W poniedziałek…”) z nazwiskami i zdaniem,
  co zatrzymuje kartę. Typ `screening_cards_return_soon`, kategoria
  „Zaległości i przypomnienia” (do wyciszenia). Na stagingu:
  `python -m scripts.screening_stale_return --warn --as-of <moment> [--apply]`.
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
