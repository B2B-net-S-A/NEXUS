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
- **Niekompletna albo pusta lista = rekrutacja pominięta.** Suma osób ze stanów
  musi być równa licznikowi składu (`/recruitments/{id}/employees`). Urwana
  odpowiedź jednego stanu wyglądałaby jak masowe zdjęcie ludzi z rekrutacji,
  a brak nagłówka z licznikiem czyta się jako zero.
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
  i Liga DL, i nie ma cofnięcia — to wymagałoby osobnej decyzji. Karta już
  zamknięta (zatrudniony, odrzucony, wycofany) zostaje, jak jest
  (`already_closed`) — „Wycofany” na zatrudnionym byłby fałszem.
- **Zapis wierszy etapów idzie przez `recruitment_process_commands`**
  (`promote_external_stage_row`, `note_external_stage_row`) — surowy `UPDATE`
  tej tabeli poza adapterem Traffita wywraca strażnika
  `test_priority_work_writer_architecture.py`.
- **Ruch zrobiony w NEXUSIE wygrywa.** Para, której ostatni wiersz nie pochodzi
  z Traffita, nie jest poprawiana ani zdejmowana. Karty bez żadnego wiersza
  z Traffita (dodane w NEXUSIE, ze scrapera) zostają nietknięte.
- **Rekrutacja z bliźniakiem jest domyślnie pomijana.** Bliźniak = rekrutacja
  założona w NEXUSIE od 25.09.2026 u tego samego klienta o niemal tym samym
  tytule (`match_twin`, `TWIN_MIN_RATIO`). `include_twins=true` (migracja całego
  zespołu, 12.10.2026) otwiera kopię z Traffita jak każdą inną; rekrutacji
  NEXUSA nie rusza, więc request jest wtedy widoczny dwa razy, dopóki obu nie
  scali osobny krok. `include_twins` wchodzi do klucza fali.
- **Zespół bliźniaka przechodzi tylko przy PEWNYM dopasowaniu** (`Twin.exact`,
  `assign_twins`): ten sam tytuł i ten sam numer requestu w nawiasie, albo ten
  sam tytuł, gdy numeru nie ma jedna ze stron i dopasowanie jest jedyne.
  RÓŻNE numery to różne requesty („Programista Python (ZOB-2904)” to nie
  „…(ZOB-2947)”), a jedna rekrutacja NEXUSA ma najwyżej jednego pewnego
  bliźniaka — 12.10.2026 osiem kopii pasowało tytułem do cudzych requestów.
  Przy pewnym dopasowaniu kopia dostaje aktywnego prowadzącego, DL-a
  i ręcznych współpracowników z rekrutacji NEXUSA (`_adopt_twin_team`).
- **Osoba odpowiedzialna z Traffita to zwykle Delivery Lead, nie rekruter**
  (`_settle_owner`). Import wpisuje ją do `jobs.recruiter_id`, a po otwarciu
  prowadzący jest przy requeście z urzędu jako „Rekruter” — pierwsza fala
  pokazała w „Obłożeniu” Delivery Leadów z 10–18 requestami (103 ze 133
  rekrutacji). Aktywny prowadzący bez roli rekrutera schodzi z tego miejsca
  i — jeśli jest Delivery Leadem — zostaje DL-em rekrutacji, także gdy miejsce
  wypełnił automat (główny DL klienta; u klienta z kilkoma DL-ami to nie ta
  osoba). DL wpisany przez człowieka zostaje. Rekrutacja zostaje bez
  rekrutera: nikogo nowego nie przypisujemy (decyzja Artura 12.10.2026:
  przypisane osoby mają się nie zmieniać). Każde wykonanie zaczyna od naprawy
  rekrutacji przeniesionych wcześniej (`repair_transferred_owners`, zwolnienie
  przypisania przez `_sync_work_assignments_with_owner`).
- **Rekrutacja przełączona ręcznie, ale zamknięta**, wchodzi do fali tylko
  wskazana wprost w `job_ids`. „Przełącz do NEXUSA” nie otwiera rekrutacji,
  a „Otwórz ponownie” ma bramkę braków, której archiwum nie przejdzie —
  12.10.2026 cztery takie zostały w pół drogi.
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
przydziału (aktywny prowadzący zostaje właścicielem).

Przypomnienia o zaległych kartach (`stage_stuck_7d`, `dl_stage_stale_6h`) **nie
budzą etapu z importu Traffita** — także wierszy dopisanych przy przeniesieniu
(`external_source='traffit'`). Zaczynają działać po pierwszym ruchu karty
w NEXUSIE (`notification_triggers._set_in_nexus`, decyzja Artura 11.10.2026).
Bez tego pierwsza fala dałaby jednej osobie 146 przypomnień.

## Po fali

Karty scrapera („Z ogłoszenia”), których w Traffit nie ma, przeniesienie
zostawia nietknięte — po otwarciu stoją w „Nowych”. Do propozycji przenosi je
osobny bieg, już PO otwarciu fali (propozycja nie istnieje na zamkniętej
rekrutacji): `POST /api/admin/proposals/convert-integration-cards?job_ids=…`
— próba, potem zapis z `expected`. U pierwszego klienta: 80 kart z 16–23.09,
79 z notatką automatu z wynikiem.

Import ruchów przełączonych rekrutacji jest pomijany (`skipped_managed`
w statusie syncu) — ta liczba pokazuje, czy ktoś nadal rusza karty w Traffit.
Cofnięcie: „Wróć do Traffita” na rekrutacji i jej zamknięcie; wiersze dopisane
przy przeniesieniu mają `external_id` z prefiksem `transfer:`.

Znany dług, którego ta zmiana nie rusza: remis czasu w imporcie dotyczy
wszystkich rekrutacji z Traffita, nie tylko przenoszonych.
