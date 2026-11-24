# „Szukamy” po terminie to „Po terminie” — decyzja Delivery Leada (24.11.2026)
<!-- indeks: `request_stage = overdue` dzień po terminie, pasek `JobOverdueBanner` (nowy termin / Klient milczy / Zamknij), dzwonek `overdue` w `job_idle`, zostaje na daily i w przydziale -->

Pytanie Artura z 24.11.2026: „jak rekrutacja ma status Szukamy, jak jest po
terminie? Jak jest po terminie, to nie może mieć statusu Szukamy”. Kopia
produkcji z 24.11: 51 ze 180 rekrutacji „Szukamy” bez championa było po
terminie (od 1 do 405 dni), ale w 22 z nich w ostatnich 14 dniach poszło CV
do klienta, a w 19 CV poszło już po terminie. Termin bywa więc miękki,
tylko nikt nie wpisuje nowego. Artur wybrał wariant B z makiet na stagingu
(https://claude.ai/artifact/LkYoGLn6JG8w67pAKU7Lv7). Odrzucone: A (sama
nazwa, bez decyzji) i C (automat przestawia na „Klient milczy”; 22 rekrutacje
z bieżącą wysyłką wypadłyby z daily).

## Reguła

- **Stan requestu `overdue` („Po terminie”)** liczy serwer w
  `job_similarity.request_stage_expr`: `work_state = searching`, bez championa
  na komplet miejsc, `deadline < business_today()`. Termin dziś to jeszcze
  „Szukamy”. Champion, „Klient milczy”, „Do przejrzenia”, szkic i zamknięte
  zostają tym, czym są. Bez terminu (116 z 180 na kopii) — dalej „Szukamy”.
- **Status requestu (`request_status`) zostaje „searching”**: zależą od niego
  championi („Szukamy · 1 z 2”), filtr „Status” i przydział. Ekran pokazuje
  „Po terminie” z `request_stage` (lista, pigułka nad listą, nagłówek
  rekrutacji — `JobChampionsStatus` z propem `requestStage`, także przy części
  miejsc z championem).
- **Nagłówek mówi to samo co lista** także przy „Klient milczy”, „Do
  przejrzenia” i „Zakończony” (`headerStage` w `JobChampionsStatus`): status
  requestu zna je tylko jako „Szukamy”, więc po kliknięciu „Klient milczy”
  na pasku nagłówek dalej mówił „Szukamy” (przeklikane na stagingu 24.11).
  Champion na komplet miejsc zostaje championem.
- **Kolor:** czerwień `OVERDUE_TONE_CLASS` — ta sama co „po terminie N dni”
  w kolumnie terminu (`data-dodania-i-termin-w-naglowku.md`).
- **Do decyzji nic nie znika:** rekrutacja „Po terminie” zostaje na daily
  i w puli automatu przydziału. Decyzja należy do Delivery Leada.

## Pasek nad Tablicą (`components/v2/jobs/JobOverdueBanner.tsx`)

Widzą go ci, którzy mogą zamknąć rekrutację (`canCloseJob`), przy
`request_stage === "overdue"`:

- **„Klient przedłużył…”** → pole daty (od dziś wzwyż) → `PATCH /api/jobs/{id}`
  z `deadline`; rekrutacja wraca do „Szukamy”.
- **„Klient milczy”** → `PATCH /api/request-work-states` (`client_silent`);
  tylko DL, HoR, admin (`WorkStateEditor`), innym przycisk się nie pokazuje.
- **„Zamknij…”** → dzisiejsze okno zamykania.

## Dzwonek

Pętla `job_idle` (co godzinę, dzień roboczy 8–17, kill-switch
`JOB_IDLE_ENABLED`) dzwoni do Delivery Leada (bez aktywnego DL: Head of
Recruitment) jednym zbiorczym wpisem `request_review_needed` (bez maila):
„Po terminie: N rekrutacji”. Jeden na termin: znacznik `idle_notice`
ze `stage=overdue` i `since` = termin, więc nowy termin, który też minie,
zaczyna nowy cykl. Pierwszy przebieg po wdrożeniu zadzwoni o wszystkie
zaległe (na kopii 24.11: 51 rekrutacji u 5 DL-i, u jednej osoby 31) — jeden
wpis na osobę. Reguła 14/21/28 dni bez ruchu
(`rekrutacje-bez-ruchu-zamykaja-sie-same.md`) działa obok bez zmian.
