# Przeniesienie rekrutacji z Traffita do NEXUSA falami (11.10.2026)

<!-- indeks: próba i wykonanie fali, lista osób per stan jako źródło prawdy, remis czasu wpisów historii, osoby zdjęte w Traffit, bliźniaki, skutki otwarcia -->

Decyzje Artura 11.10.2026: zespół przechodzi z Traffita **falami** (klient po
kliencie), nie przez lustro „na żywo”; „otwarta” rekrutacja to taka bez daty
zamknięcia w Traffit i z ruchem z Traffita w ostatnich 30 dniach; karty osób
zdjętych z rekrutacji w Traffit schodzą z Tablicy ze śladem. Raport:
`docs/traffit-transfer-completion-report.md`.

**Pomiar, od którego wyszła decyzja (produkcja, 11.10.2026):** 323 rekrutacje
otwarte w Traffit, 186 z ruchem w 30 dniach, 6 310 osób na 185 z nich — i
**99,2% stoi w NEXUSIE na tym samym stanie co w Traffit**. Mapowanie etapów na
kolumny działa (`board_stage_badges`), import też. Zespół „nie widzi” swoich
ludzi, bo rekrutacje z Traffita są w NEXUSIE zamknięte jako archiwum (0377).
Nie zaczynaj więc od mappera ani od częstszego syncu — to nie one blokują.

## Narzędzie

`POST /api/admin/traffit/transfer?dry_run=…&client_id=…|job_ids=…` i
`GET /api/admin/traffit/transfer/status` (`api/admin_traffit.py`,
`services/traffit_transfer.py`, czysta logika w `traffit_transfer_plan.py`).
Fala to klient albo lista rekrutacji (id NEXUSA); bez fali trasa odmawia (422),
bo bieg objąłby wszystko naraz.

- **Próba** (`dry_run=true`, domyślnie) niczego nie zmienia. Raport per
  rekrutacja w `app_settings['traffit_transfer_dry_run']`: ile osób zgodnych, co
  zostanie poprawione, kto zejdzie z Tablicy, ile osób stanie w której kolumnie,
  braki z bramki „Otwórz ponownie”, powód pominięcia.
- **Wykonanie** (`dry_run=false`) wymaga próby **tej samej fali z ostatnich
  24 godzin** (stan w Traffit zmienia się z dnia na dzień) i zalogowanego
  administratora — klucz konta serwisowego może zrobić tylko próbę, bo otwarcie
  zapisuje, kto je wykonał. Każda rekrutacja idzie we własnej transakcji;
  paragon (liczby i ID) dopisuje się do `app_settings['traffit_transfer_log']`.
- Bieg idzie w tle pod blokadą syncu Traffita, jak naprawy notatek i dat plików.

## Reguły, które łatwo cofnąć

- **Źródłem prawdy jest lista osób NA STANIE**
  (`/recruitments/{id}/states/{stan}/employees`), nie historia ruchów. Filtr
  `/employees/recruitment_history` po rekrutacji jest przez Traffit ignorowany
  (sprawdzone na żywym API), a historia nie mówi, że kogoś zdjęto z rekrutacji.
- **Niekompletna lista = rekrutacja pominięta.** Suma osób ze stanów musi być
  równa licznikowi składu (`/recruitments/{id}/employees`). Urwana odpowiedź
  jednego stanu wyglądałaby jak masowe zdjęcie ludzi z rekrutacji.
- **Remis czasu to nie brak danych.** Traffit zapisuje dwa wpisy historii z tą
  samą datą („Nowy” i „Screening” w jednej sekundzie), bieżący etap pary liczy
  się po `(moved_at, id)`, a import czyta historię od najnowszych — nowszy wpis
  dostaje niższe `id` i przegrywa. Właściwy wiersz jest w bazie, więc
  przeniesienie wysuwa go o 1 ms zamiast dopisywać zdarzenie (nowy wiersz
  podbiłby statystyki etapów). Nowy wiersz powstaje tylko wtedy, gdy stanu
  z Traffita w historii pary w ogóle nie ma; dostaje
  `external_id = 'transfer:state:<rekrutacja>:<osoba>'`, żeby ponowny bieg trafił
  w ten sam wiersz.
- **Osoba zdjęta w Traffit dostaje wiersz „Wycofany”, niczego nie kasujemy.**
  Powód `legacy_unknown` (ten sam co w imporcie), notatka „Zdjęty z rekrutacji
  w Traffit — przeniesienie do NEXUSA”, `external_id =
  'transfer:removed:<rekrutacja>:c<kandydat>'`. Karta schodzi z ośmiu kolumn do
  „Zamkniętych”, historia pary zostaje. Usunięcie wierszy pary
  (`delete_voided_stage_history`) zabrałoby zdarzenia, z których liczą się KPI
  i Liga DL, i nie ma cofnięcia — to wymagałoby osobnej decyzji.
- **Ruch zrobiony w NEXUSIE wygrywa.** Para, której ostatni wiersz nie pochodzi
  z Traffita, nie jest poprawiana ani zdejmowana. Karty bez żadnego wiersza
  z Traffita (dodane w NEXUSIE, ze scrapera) zostają nietknięte.
- **Rekrutacja z bliźniakiem jest pomijana.** Bliźniak = rekrutacja założona
  w NEXUSIE od 25.09.2026 u tego samego klienta o niemal tym samym tytule
  (`find_twin`, `TWIN_MIN_RATIO`). Z 73 takich rekrutacji 45 ma odpowiednik
  w Traffit i to tam są kandydaci; która z dwóch zostaje, jest otwartą decyzją
  — do tego czasu narzędzie ich nie rusza, żeby nie powstały dwie otwarte
  rekrutacje na jeden request.
- **Otwarcie idzie tymi samymi funkcjami co „Otwórz ponownie”**
  (`job_lifecycle.publish_core` + `reopen_keep_team_core`): „Prowadzona
  w NEXUSIE”, `published`, `is_open`, „Szukamy”, przypisanie prowadzącego.
  Flaga i status zapisują się w jednej transakcji — inaczej archiwum
  (`ARCHIVE_TRAFFIT_JOBS_SQL`) zamknęłoby rekrutację przy najbliższym imporcie.
- **Bramka braków jest tu świadomie pominięta.** „Otwórz ponownie” wymaga m.in.
  hiring managera i terminu, a archiwum z Traffita nie ma ich nigdy; przeniesienie
  dotyczy rekrutacji, które już są w pracy. Braki niesie raport (`blockers`),
  a ekran rekrutacji pokazuje je jak zwykle. To wyjątek tylko dla tej trasy —
  nie przenoś go na `POST /{id}/publish`.
- **Nie zakładamy kandydatów.** Osoba z Traffita, której NEXUS nie zna (np.
  karta-duplikat z kolizją maila), trafia do raportu z numerem osoby.
- **Worek zgłoszeń nie jest rekrutacją.** Powyżej `MAX_PEOPLE` (3000) par
  rekrutacja jest pomijana („projekty wewnętrzne” mają 14,6 tys. zgłoszeń).

## Co wywołuje otwarcie fali

Otwarta rekrutacja wchodzi w zwykłe automaty NEXUSA i tego narzędzie nie
wycisza: dzwonek „Nowy request do pracy” do prowadzącego (i mail z kolejki),
migawka dopasowań, zdarzenie auto-matcha i nocny przegląd bazy, automat
przydziału (aktywny prowadzący zostaje właścicielem), przypomnienia o kartach
stojących 7–30 dni i o „CV wysłane” od 6 godzin do 14 dni. Przed dużą falą
policz te karty — przy jednym kliencie z jednym prowadzącym było ich 146.

## Po fali

Import ruchów przełączonych rekrutacji jest pomijany (`skipped_managed`
w statusie syncu) — ta liczba pokazuje, czy ktoś nadal rusza karty w Traffit.
Cofnięcie: „Wróć do Traffita” na rekrutacji i jej zamknięcie; wiersze dopisane
przy przeniesieniu mają `external_id` z prefiksem `transfer:`.

Znany dług, którego ta zmiana nie rusza: remis czasu w imporcie dotyczy
wszystkich rekrutacji z Traffita, nie tylko przenoszonych.
